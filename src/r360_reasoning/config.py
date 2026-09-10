"""Service configuration.

Unlike r360-rf-evidence, this service has one implementation in one language, so a
Protobuf config schema would buy nothing here (see ADR-0003 in that repository for why it
buys something there). What it still has to do is the same: reject a configuration that is
wrong, before the service claims to be serving, with a reason rather than a default.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Raised with every problem found, not just the first one."""


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    client_id: str
    keep_alive_seconds: int


@dataclass(frozen=True)
class PostgresConfig:
    # Empty means "run without durable storage", which is only valid for tests and is
    # stated explicitly rather than inferred from a missing key.
    dsn: str


@dataclass(frozen=True)
class ServiceConfig:
    service_name: str
    session_id: str
    mqtt: MqttConfig
    grpc_listen_address: str
    postgres: PostgresConfig
    seen_cache_capacity: int
    configuration_sha256: str

    @property
    def evidence_topic(self) -> str:
        return f"r360/v1/{self.session_id}/rf/evidence"

    @property
    def health_topic(self) -> str:
        return f"r360/v1/{self.session_id}/health/{self.service_name}"


def _require(condition: bool, message: str, problems: list[str]) -> None:
    if not condition:
        problems.append(message)


def load_from_dict(raw: dict[str, Any], *, raw_text: str = "") -> ServiceConfig:
    problems: list[str] = []

    known_keys = {
        "service_name",
        "session_id",
        "mqtt",
        "grpc_listen_address",
        "postgres",
        "seen_cache_capacity",
    }
    unknown = sorted(set(raw) - known_keys)
    # A misspelled key is a mistake, not a no-op.
    _require(not unknown, f"unknown configuration keys: {unknown}", problems)

    service_name = str(raw.get("service_name", ""))
    session_id = str(raw.get("session_id", ""))
    _require(bool(service_name.strip()), "service_name must not be empty", problems)
    _require(bool(session_id.strip()), "session_id must not be empty", problems)

    mqtt_raw = raw.get("mqtt", {})
    host = str(mqtt_raw.get("host", ""))
    port = int(mqtt_raw.get("port", 0))
    client_id = str(mqtt_raw.get("client_id", ""))
    keep_alive = int(mqtt_raw.get("keep_alive_seconds", 0))
    _require(bool(host.strip()), "mqtt.host must not be empty", problems)
    _require(0 < port < 65536, "mqtt.port must be a valid TCP port", problems)
    _require(bool(client_id.strip()), "mqtt.client_id must not be empty", problems)
    _require(keep_alive > 0, "mqtt.keep_alive_seconds must be greater than zero", problems)

    grpc_listen_address = str(raw.get("grpc_listen_address", ""))
    _require(bool(grpc_listen_address.strip()), "grpc_listen_address must not be empty", problems)

    postgres_raw = raw.get("postgres", {})
    dsn = str(postgres_raw.get("dsn", ""))

    capacity = int(raw.get("seen_cache_capacity", 0))
    # The cache is bounded by construction; zero would mean unbounded, which is how a
    # long-running consumer runs out of memory.
    _require(capacity > 0, "seen_cache_capacity must be greater than zero", problems)

    if problems:
        raise ConfigError(
            f"{len(problems)} configuration problem(s):\n"
            + "\n".join(f"  - {problem}" for problem in problems)
        )

    text = raw_text if raw_text else json.dumps(raw, sort_keys=True)
    return ServiceConfig(
        service_name=service_name,
        session_id=session_id,
        mqtt=MqttConfig(host=host, port=port, client_id=client_id, keep_alive_seconds=keep_alive),
        grpc_listen_address=grpc_listen_address,
        postgres=PostgresConfig(dsn=dsn),
        seen_cache_capacity=capacity,
        configuration_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def load_from_file(path: Path) -> ServiceConfig:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"cannot read configuration file {path}") from error
    try:
        raw: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as error:
        raise ConfigError(f"configuration is not valid JSON: {error}") from error
    return load_from_dict(raw, raw_text=text)
