"""End-to-end smoke test: real broker, real Postgres, real service process.

The M0 exit criterion that matters here cannot be proven with test doubles: publish the
same `DerivedEvidence` twice at QoS 1 and require that the running service persists one
row, increments a duplicate counter, and keeps serving.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import grpc
import paho.mqtt.client as mqtt
import psycopg
import pytest
from google.protobuf.timestamp_pb2 import Timestamp
from r360.evidence.v1 import evidence_pb2
from r360.service.v1 import services_pb2, services_pb2_grpc
from r360_reasoning import buildinfo

REPO_ROOT = Path(__file__).resolve().parents[2]
BROKER_HOST = os.environ.get("R360_MQTT_HOST", "mqtt")
BROKER_PORT = int(os.environ.get("R360_MQTT_PORT", "1883"))
POSTGRES_DSN = os.environ.get(
    "R360_POSTGRES_DSN", "postgresql://r360:r360-dev-only@postgres:5432/r360"
)
GRPC_PORT = int(os.environ.get("R360_TEST_GRPC_PORT", "50252"))
SESSION_ID = "sess-reasoning-smoke"
EVIDENCE_TOPIC = f"r360/v1/{SESSION_ID}/rf/evidence"


def wait_for_port(host: str, port: int, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"nothing listening on {host}:{port} after {timeout_seconds}s")


def make_evidence(evidence_id: str) -> evidence_pb2.DerivedEvidence:
    evidence = evidence_pb2.DerivedEvidence(
        evidence_id=evidence_id,
        evidence_type=evidence_pb2.PULSE_DETECTION,
        confidence=0.91,
    )
    evidence.observation.observation_id = f"obs-{evidence_id}"
    evidence.observation.sensor_id = "sensor-alpha"
    evidence.observation.session_id = SESSION_ID
    evidence.observation.capture_id = "RF-002-basic-pulse"
    stamp = Timestamp(seconds=1788004803)
    evidence.observation.time.event_time.CopyFrom(stamp)
    evidence.observation.time.ingest_time.CopyFrom(stamp)
    evidence.observation.time.logical_time_ns = 3_500_000_000
    evidence.provenance.processor_name = "r360-rf-evidence"
    evidence.provenance.processor_version = "0.1.0"
    return evidence


@pytest.fixture(scope="module")
def clean_database() -> None:
    wait_for_port(POSTGRES_DSN.split("@")[1].split(":")[0], 5432)
    with psycopg.connect(POSTGRES_DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS derived_evidence")
        connection.commit()


@pytest.fixture(scope="module")
def service_config(tmp_path_factory: pytest.TempPathFactory, clean_database: None) -> Path:
    config = {
        "service_name": "r360-reasoning",
        "session_id": SESSION_ID,
        "mqtt": {
            "host": BROKER_HOST,
            "port": BROKER_PORT,
            "client_id": "reasoning-smoke",
            "keep_alive_seconds": 20,
        },
        "grpc_listen_address": f"0.0.0.0:{GRPC_PORT}",
        "postgres": {"dsn": POSTGRES_DSN},
        "seen_cache_capacity": 1000,
    }
    path = tmp_path_factory.mktemp("config") / "service.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def running_service(service_config: Path) -> Iterator[subprocess.Popen[bytes]]:
    wait_for_port(BROKER_HOST, BROKER_PORT)
    process = subprocess.Popen(
        ["python", "-m", "r360_reasoning.service", "--config", str(service_config)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_for_port("127.0.0.1", GRPC_PORT)
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def publish(payload: bytes, count: int = 1) -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="smoke-publisher")
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=20)
    client.loop_start()
    for _ in range(count):
        info = client.publish(EVIDENCE_TOPIC, payload, qos=1, retain=False)
        info.wait_for_publish(timeout=10)
    client.loop_stop()
    client.disconnect()


def stored_count(evidence_id: str) -> int:
    with psycopg.connect(POSTGRES_DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM derived_evidence WHERE evidence_id = %s", (evidence_id,)
            )
            row = cursor.fetchone()
    return int(row[0]) if row else 0


def wait_for_rows(evidence_id: str, expected: int, timeout_seconds: float = 15.0) -> int:
    deadline = time.monotonic() + timeout_seconds
    count = 0
    while time.monotonic() < deadline:
        count = stored_count(evidence_id)
        if count >= expected:
            return count
        time.sleep(0.1)
    return count


def test_grpc_health_reports_the_pinned_contract_version(
    running_service: subprocess.Popen[bytes],
) -> None:
    """REQ-REA-009: health answers, and the contract version comes from contracts.lock."""
    with grpc.insecure_channel(f"127.0.0.1:{GRPC_PORT}") as channel:
        stub = services_pb2_grpc.ReasoningControlStub(channel)
        health = stub.GetHealth(services_pb2.Empty(), timeout=10)
    assert health.service_name == "r360-reasoning"
    assert health.status == "SERVING"
    assert health.contract_version == buildinfo.contract_version()
    assert health.session_id == SESSION_ID
    assert health.time.HasField("event_time")
    assert health.time.HasField("ingest_time")


def test_evidence_is_persisted(running_service: subprocess.Popen[bytes]) -> None:
    """REQ-REA-003: the structured record is persisted; the raw signal never existed here."""
    evidence = make_evidence("ev-smoke-single")
    publish(evidence.SerializeToString())
    assert wait_for_rows("ev-smoke-single", 1) == 1


def test_duplicate_qos1_delivery_persists_exactly_one_row(
    running_service: subprocess.Popen[bytes],
) -> None:
    """REQ-REA-002 and REQ-INT-003, against a real broker and a real database.

    This is the M0 exit criterion in its most literal form: publish the same evidence
    twice at QoS 1, and require one row.
    """
    evidence = make_evidence("ev-smoke-duplicate")
    payload = evidence.SerializeToString()
    publish(payload, count=2)

    assert wait_for_rows("ev-smoke-duplicate", 1) == 1
    # Give any second insert time to appear before declaring that it did not.
    time.sleep(2.0)
    assert stored_count("ev-smoke-duplicate") == 1


def test_stored_payload_round_trips(running_service: subprocess.Popen[bytes]) -> None:
    """What was stored must decode back into the evidence that was sent."""
    evidence = make_evidence("ev-smoke-roundtrip")
    publish(evidence.SerializeToString())
    assert wait_for_rows("ev-smoke-roundtrip", 1) == 1

    with psycopg.connect(POSTGRES_DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload, sensor_id, logical_time_ns FROM derived_evidence "
                "WHERE evidence_id = %s",
                ("ev-smoke-roundtrip",),
            )
            row = cursor.fetchone()
    assert row is not None
    restored = evidence_pb2.DerivedEvidence()
    restored.ParseFromString(bytes(row[0]))
    assert restored == evidence
    assert row[1] == "sensor-alpha"
    assert row[2] == 3_500_000_000


def test_unusable_evidence_does_not_stop_the_consumer(
    running_service: subprocess.Popen[bytes],
) -> None:
    """A rejected message must not cost the next good one."""
    broken = make_evidence("ev-smoke-broken")
    broken.observation.time.ClearField("ingest_time")
    publish(broken.SerializeToString())
    publish(b"not a protobuf message")

    good = make_evidence("ev-smoke-after-broken")
    publish(good.SerializeToString())

    assert wait_for_rows("ev-smoke-after-broken", 1) == 1
    assert stored_count("ev-smoke-broken") == 0
