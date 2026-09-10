"""Where accepted evidence references are kept.

REQ-REA-003: structured mission and event history is persisted; raw RF is not. What is
stored here is a *reference* to an observation plus the structured evidence record --
never IQ, which the canonical contract cannot carry in the first place (REQ-REA-001).

Two implementations behind one port:

* `InMemoryEvidenceStore` -- used by unit tests and by a single-process run;
* `PostgresEvidenceStore` -- the durable one, where the evidence ID is the primary key so
  that idempotency survives a restart and does not depend on a process-local cache.

The port exists because M8 will add real reasoning on top of this, and it should not have
to care which store it is talking to.
"""

from __future__ import annotations

import json
from typing import Protocol

from google.protobuf import json_format
from r360.evidence.v1 import evidence_pb2

# Storing the serialized message alongside the extracted columns keeps the record exact:
# a later schema change can re-read the original bytes instead of trusting columns that
# were extracted by an older build.
SCHEMA = """
CREATE TABLE IF NOT EXISTS derived_evidence (
    evidence_id      TEXT PRIMARY KEY,
    evidence_type    TEXT        NOT NULL,
    session_id       TEXT,
    sensor_id        TEXT,
    capture_id       TEXT,
    event_time       TIMESTAMPTZ NOT NULL,
    ingest_time      TIMESTAMPTZ NOT NULL,
    logical_time_ns  BIGINT,
    confidence       DOUBLE PRECISION NOT NULL,
    processor_name   TEXT,
    processor_version TEXT,
    payload          BYTEA       NOT NULL,
    stored_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class EvidenceStore(Protocol):
    """Storage port for accepted evidence."""

    def store(self, evidence: evidence_pb2.DerivedEvidence) -> bool:
        """Store the evidence. Returns False when this ID is already present.

        The return value is what makes the store the durable half of idempotency: the
        caller learns that a delivery was a duplicate even when its in-memory cache has
        long since evicted the ID.
        """

    def get(self, evidence_id: str) -> evidence_pb2.DerivedEvidence | None: ...

    def count(self) -> int: ...


class InMemoryEvidenceStore:
    """Non-durable store for tests and single-process runs."""

    def __init__(self) -> None:
        self._records: dict[str, bytes] = {}

    def store(self, evidence: evidence_pb2.DerivedEvidence) -> bool:
        if evidence.evidence_id in self._records:
            return False
        self._records[evidence.evidence_id] = evidence.SerializeToString(deterministic=True)
        return True

    def get(self, evidence_id: str) -> evidence_pb2.DerivedEvidence | None:
        payload = self._records.get(evidence_id)
        if payload is None:
            return None
        record = evidence_pb2.DerivedEvidence()
        record.ParseFromString(payload)
        return record

    def count(self) -> int:
        return len(self._records)


class PostgresEvidenceStore:
    """Durable store. The evidence ID is the primary key, which is the point.

    Idempotency is enforced by the database rather than by application logic: an insert of
    an ID that is already present is a no-op, whatever the application believed about its
    cache, and whatever order two workers happened to run in.
    """

    def __init__(self, connection: object) -> None:
        # Typed as object so this module does not import psycopg at definition time; the
        # caller supplies a live connection.
        self._connection = connection

    def initialize(self) -> None:
        with self._connection.cursor() as cursor:  # type: ignore[attr-defined]
            cursor.execute(SCHEMA)
        self._connection.commit()  # type: ignore[attr-defined]

    def store(self, evidence: evidence_pb2.DerivedEvidence) -> bool:
        time = evidence.observation.time
        with self._connection.cursor() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                """
                INSERT INTO derived_evidence (
                    evidence_id, evidence_type, session_id, sensor_id, capture_id,
                    event_time, ingest_time, logical_time_ns, confidence,
                    processor_name, processor_version, payload
                )
                VALUES (%s, %s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s), %s, %s, %s, %s, %s)
                ON CONFLICT (evidence_id) DO NOTHING
                """,
                (
                    evidence.evidence_id,
                    evidence_pb2.EvidenceType.Name(evidence.evidence_type),
                    evidence.observation.session_id,
                    evidence.observation.sensor_id,
                    evidence.observation.capture_id,
                    time.event_time.seconds + time.event_time.nanos / 1e9,
                    time.ingest_time.seconds + time.ingest_time.nanos / 1e9,
                    time.logical_time_ns if time.HasField("logical_time_ns") else None,
                    evidence.confidence,
                    evidence.provenance.processor_name,
                    evidence.provenance.processor_version,
                    evidence.SerializeToString(deterministic=True),
                ),
            )
            inserted: bool = cursor.rowcount == 1
        self._connection.commit()  # type: ignore[attr-defined]
        return inserted

    def get(self, evidence_id: str) -> evidence_pb2.DerivedEvidence | None:
        with self._connection.cursor() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                "SELECT payload FROM derived_evidence WHERE evidence_id = %s", (evidence_id,)
            )
            row = cursor.fetchone()
        if row is None:
            return None
        record = evidence_pb2.DerivedEvidence()
        record.ParseFromString(bytes(row[0]))
        return record

    def count(self) -> int:
        with self._connection.cursor() as cursor:  # type: ignore[attr-defined]
            cursor.execute("SELECT count(*) FROM derived_evidence")
            row = cursor.fetchone()
        return int(row[0]) if row else 0


def evidence_to_json(evidence: evidence_pb2.DerivedEvidence) -> str:
    """Readable form for diagnostics and fixtures. Never the storage format."""
    return json.dumps(
        json_format.MessageToDict(evidence, preserving_proto_field_name=True),
        indent=2,
        sort_keys=True,
    )
