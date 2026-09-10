"""REQ-REA-002: evidence intake is idempotent by evidence ID.

MQTT QoS 1 means duplicate delivery is normal traffic. The M0 exit criterion is that a
redelivered message creates no second stored record and no second downstream effect, and
that the duplicate is counted rather than silently dropped.
"""

from __future__ import annotations

import pytest
from google.protobuf.timestamp_pb2 import Timestamp
from r360.evidence.v1 import evidence_pb2
from r360_reasoning.intake.consumer import EvidenceIntake
from r360_reasoning.intake.idempotency import SeenCache
from r360_reasoning.storage.evidence_store import InMemoryEvidenceStore


def make_evidence(evidence_id: str = "ev-0001") -> evidence_pb2.DerivedEvidence:
    evidence = evidence_pb2.DerivedEvidence(
        evidence_id=evidence_id,
        evidence_type=evidence_pb2.PULSE_DETECTION,
        confidence=0.9,
    )
    evidence.observation.observation_id = "obs-0001"
    evidence.observation.sensor_id = "sensor-alpha"
    evidence.observation.session_id = "sess-test"
    stamp = Timestamp(seconds=1788004803)
    evidence.observation.time.event_time.CopyFrom(stamp)
    evidence.observation.time.ingest_time.CopyFrom(stamp)
    evidence.observation.time.logical_time_ns = 3_500_000_000
    evidence.provenance.processor_name = "r360-rf-evidence"
    evidence.provenance.processor_version = "0.1.0"
    return evidence


def test_first_delivery_is_accepted_and_stored() -> None:
    store = InMemoryEvidenceStore()
    intake = EvidenceIntake(store)
    result = intake.handle_payload(make_evidence().SerializeToString())
    assert result.accepted
    assert store.count() == 1
    assert intake.metrics.accepted_total == 1


def test_duplicate_delivery_creates_no_second_record() -> None:
    """The core of the M0 exit criterion, stated as plainly as it can be."""
    store = InMemoryEvidenceStore()
    intake = EvidenceIntake(store)
    payload = make_evidence().SerializeToString()

    first = intake.handle_payload(payload)
    second = intake.handle_payload(payload)

    assert first.accepted
    assert not second.accepted
    assert second.duplicate
    assert store.count() == 1
    assert intake.metrics.accepted_total == 1
    assert intake.metrics.duplicate_total == 1


def test_downstream_effects_run_once_per_evidence_id() -> None:
    """Deduplicating the record is not enough if the side effect still fires twice."""
    effects: list[str] = []
    intake = EvidenceIntake(
        InMemoryEvidenceStore(), on_accepted=lambda e: effects.append(e.evidence_id)
    )
    payload = make_evidence().SerializeToString()
    for _ in range(5):
        intake.handle_payload(payload)
    assert effects == ["ev-0001"]


def test_duplicates_are_counted_not_silently_dropped() -> None:
    """A consumer that discards messages silently looks identical to one losing them."""
    intake = EvidenceIntake(InMemoryEvidenceStore())
    payload = make_evidence().SerializeToString()
    for _ in range(4):
        intake.handle_payload(payload)
    counters = intake.metrics.as_dict()
    assert counters["received_total"] == 4
    assert counters["accepted_total"] == 1
    assert counters["duplicate_total"] == 3


def test_distinct_evidence_ids_are_all_accepted() -> None:
    store = InMemoryEvidenceStore()
    intake = EvidenceIntake(store)
    for index in range(10):
        intake.handle_payload(make_evidence(f"ev-{index:04d}").SerializeToString())
    assert store.count() == 10


def test_a_late_duplicate_is_caught_by_the_store_after_cache_eviction() -> None:
    """REQ-REA-011: the cache is bounded, so the durable store is what actually decides.

    This is the failure mode a process-local cache hides: after enough traffic the ID is
    evicted, and a consumer that trusted only its cache would accept the duplicate.
    """
    store = InMemoryEvidenceStore()
    intake = EvidenceIntake(store, SeenCache(capacity=4))
    original = make_evidence("ev-original").SerializeToString()

    assert intake.handle_payload(original).accepted
    for index in range(8):
        intake.handle_payload(make_evidence(f"ev-filler-{index}").SerializeToString())
    assert "ev-original" not in intake._seen  # noqa: SLF001 - asserting the eviction happened

    late = intake.handle_payload(original)
    assert not late.accepted
    assert late.duplicate
    assert store.count() == 9


def test_seen_cache_stays_bounded() -> None:
    cache = SeenCache(capacity=16)
    for index in range(1000):
        cache.add(f"ev-{index}")
    assert len(cache) == 16


def test_unbounded_seen_cache_cannot_be_configured() -> None:
    with pytest.raises(ValueError):
        SeenCache(capacity=0)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda e: e.ClearField("evidence_id"), "MISSING_EVIDENCE_ID"),
        (lambda e: e.ClearField("evidence_type"), "UNSPECIFIED_EVIDENCE_TYPE"),
        (lambda e: e.observation.time.ClearField("ingest_time"), "MISSING_DUAL_TIME"),
        (lambda e: e.observation.time.ClearField("event_time"), "MISSING_DUAL_TIME"),
        (lambda e: setattr(e, "confidence", 1.5), "CONFIDENCE_OUT_OF_RANGE"),
    ],
)
def test_unusable_evidence_is_rejected_with_a_reason(mutate, reason: str) -> None:  # type: ignore[no-untyped-def]
    """REQ-REA-010: Reasoning does not repair evidence. It refuses it, and says why."""
    store = InMemoryEvidenceStore()
    intake = EvidenceIntake(store)
    evidence = make_evidence()
    mutate(evidence)

    result = intake.handle_payload(evidence.SerializeToString())
    assert not result.accepted
    assert result.rejected_reason == reason
    assert store.count() == 0
    assert intake.metrics.rejected_by_reason[reason] == 1


def test_garbage_payload_is_rejected_without_raising() -> None:
    """A malformed payload must not take the consumer down; the next message still matters."""
    intake = EvidenceIntake(InMemoryEvidenceStore())
    result = intake.handle_payload(b"this is not a protobuf message at all")
    assert not result.accepted
    assert result.rejected_reason in {"UNPARSEABLE_PAYLOAD", "MISSING_EVIDENCE_ID"}
    assert intake.handle_payload(make_evidence().SerializeToString()).accepted
