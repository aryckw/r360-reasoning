"""r360-reasoning service entry point.

M0 scope: subscribe to RF evidence, accept it idempotently, persist what is accepted,
answer gRPC health, and publish retained health. There is no reasoning in this build --
correlation, rules, episodes, outcomes and AAR generation arrive at M8 and M9 -- and the
service says so rather than implying otherwise.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from concurrent import futures
from pathlib import Path
from types import FrameType

import grpc
import paho.mqtt.client as mqtt
from google.protobuf.timestamp_pb2 import Timestamp
from r360.service.v1 import services_pb2, services_pb2_grpc

from r360_reasoning import buildinfo
from r360_reasoning.config import ServiceConfig, load_from_file
from r360_reasoning.intake.consumer import EvidenceIntake
from r360_reasoning.intake.idempotency import SeenCache
from r360_reasoning.storage.evidence_store import (
    EvidenceStore,
    InMemoryEvidenceStore,
    PostgresEvidenceStore,
)

LOGGER = logging.getLogger("r360-reasoning")


def now_timestamp() -> Timestamp:
    """Wall clock, used only for health and ingest time.

    Deterministic semantics never read this: replay determinism belongs to the RF side,
    and correlation keys on event and logical time carried in the evidence itself.
    """
    timestamp = Timestamp()
    timestamp.GetCurrentTime()
    return timestamp


def make_health(config: ServiceConfig, status: str) -> services_pb2.HealthResponse:
    health = services_pb2.HealthResponse(
        service_name=config.service_name,
        status=status,
        service_version=buildinfo.SERVICE_VERSION,
        contract_version=buildinfo.contract_version(),
        producer_git_sha=buildinfo.git_sha(),
        session_id=config.session_id,
    )
    health.time.event_time.CopyFrom(now_timestamp())
    health.time.ingest_time.CopyFrom(now_timestamp())
    return health


# The generated servicer base class is untyped, so mypy sees Any here. Subclassing it
# is still the supported way to implement the service, and the gRPC smoke test proves
# the wiring works end to end.
class ReasoningControlServicer(services_pb2_grpc.ReasoningControlServicer):  # type: ignore[misc]
    def __init__(self, config: ServiceConfig, status_provider: ServiceStatus) -> None:
        self._config = config
        self._status = status_provider

    def GetHealth(  # noqa: N802 - the name is fixed by the generated stub
        self, request: services_pb2.Empty, context: grpc.ServicerContext
    ) -> services_pb2.HealthResponse:
        return make_health(self._config, self._status.status)


class ServiceStatus:
    """Live status, so health tells the truth rather than a constant."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = "NOT_SERVING"

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @status.setter
    def status(self, value: str) -> None:
        with self._lock:
            self._status = value


def build_store(config: ServiceConfig) -> EvidenceStore:
    """Postgres when a DSN is configured, in-memory when one is deliberately absent."""
    if not config.postgres.dsn:
        LOGGER.warning(
            "no postgres dsn configured; evidence will be held in memory and lost on "
            "restart. This is acceptable for tests only."
        )
        return InMemoryEvidenceStore()

    import psycopg  # imported here so the in-memory path needs no driver

    connection = psycopg.connect(config.postgres.dsn)
    store = PostgresEvidenceStore(connection)
    store.initialize()
    return store


def run(config: ServiceConfig) -> int:
    status = ServiceStatus()
    store = build_store(config)
    intake = EvidenceIntake(store, SeenCache(config.seen_cache_capacity))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config.mqtt.client_id)

    def on_connect(
        client: mqtt.Client, _userdata: object, _flags: object, reason_code: object, _props: object
    ) -> None:
        LOGGER.info(
            "connected to broker (%s); subscribing to %s", reason_code, config.evidence_topic
        )
        # QoS 1 on the subscribe side too: asking for at-most-once delivery here would
        # discard the guarantee the publisher paid for.
        client.subscribe(config.evidence_topic, qos=1)

    def on_message(_client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
        result = intake.handle_payload(message.payload)
        if result.rejected_reason:
            LOGGER.warning("rejected %s: %s", result.evidence_id, result.rejected_reason)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(config.mqtt.host, config.mqtt.port, keepalive=config.mqtt.keep_alive_seconds)
    client.loop_start()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    services_pb2_grpc.add_ReasoningControlServicer_to_server(
        ReasoningControlServicer(config, status), server
    )
    server.add_insecure_port(config.grpc_listen_address)
    server.start()
    status.status = "SERVING"

    # Retained, so a subscriber that connects later still learns the current state.
    client.publish(
        config.health_topic,
        make_health(config, "SERVING").SerializeToString(),
        qos=1,
        retain=True,
    )

    LOGGER.info(
        "serving control plane on %s, consuming %s, contract %s, build %s (%s)",
        config.grpc_listen_address,
        config.evidence_topic,
        buildinfo.contract_version(),
        buildinfo.SERVICE_VERSION,
        buildinfo.git_sha(),
    )
    LOGGER.info("configuration sha256 %s", config.configuration_sha256)

    stopping = threading.Event()

    def handle_signal(_signum: int, _frame: FrameType | None) -> None:
        stopping.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    while not stopping.is_set():
        time.sleep(0.1)

    status.status = "NOT_SERVING"
    client.publish(
        config.health_topic,
        make_health(config, "NOT_SERVING").SerializeToString(),
        qos=1,
        retain=True,
    )
    time.sleep(0.2)
    client.loop_stop()
    client.disconnect()
    server.stop(grace=5).wait()
    LOGGER.info(
        "stopped; received=%d accepted=%d duplicate=%d rejected=%d",
        intake.metrics.received_total,
        intake.metrics.accepted_total,
        intake.metrics.duplicate_total,
        intake.metrics.rejected_total,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/service.dev.json"))
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    return run(load_from_file(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
