"""Idempotent intake of at-least-once evidence.

MQTT delivers evidence at QoS 1, so duplicate delivery is expected rather than
exceptional (ADR-0004 in r360-contracts). The consumer, not the broker, is what makes
processing exactly-once, and it does that by recognising the evidence ID it has already
accepted.

Two properties matter and both are tested:

* a duplicate must not create a second stored record or a second downstream effect;
* a duplicate must be *counted*, because a consumer that silently discards messages looks
  identical to one that is quietly losing them.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from r360.evidence.v1 import evidence_pb2


@dataclass(frozen=True)
class IntakeResult:
    """What intake did with one delivery."""

    accepted: bool
    evidence_id: str
    duplicate: bool = False
    rejected_reason: str = ""


@dataclass
class IntakeMetrics:
    """Counters an operator can use to tell "quiet" from "broken"."""

    received_total: int = 0
    accepted_total: int = 0
    duplicate_total: int = 0
    rejected_total: int = 0
    rejected_by_reason: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, int]:
        counters = {
            "received_total": self.received_total,
            "accepted_total": self.accepted_total,
            "duplicate_total": self.duplicate_total,
            "rejected_total": self.rejected_total,
        }
        counters.update(
            {
                f"rejected_{reason.lower()}": count
                for reason, count in self.rejected_by_reason.items()
            }
        )
        return counters


class SeenCache:
    """Bounded, thread-safe record of recently accepted IDs.

    The cache is an optimisation in front of the store, not the source of truth: it is
    bounded, so after enough traffic an old ID is evicted and a very late duplicate falls
    through to the store, which is durable. Getting that order wrong -- trusting an
    unbounded in-memory set -- is how a long-running consumer runs out of memory, and
    trusting a bounded one *instead of* the store is how a late duplicate slips through.
    """

    def __init__(self, capacity: int = 100_000) -> None:
        if capacity <= 0:
            raise ValueError("SeenCache capacity must be positive; it is a bounded cache")
        self._capacity = capacity
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def __contains__(self, evidence_id: str) -> bool:
        with self._lock:
            if evidence_id not in self._seen:
                return False
            self._seen.move_to_end(evidence_id)
            return True

    def add(self, evidence_id: str) -> None:
        with self._lock:
            self._seen[evidence_id] = None
            self._seen.move_to_end(evidence_id)
            while len(self._seen) > self._capacity:
                self._seen.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen)


def validate_evidence(evidence: evidence_pb2.DerivedEvidence) -> str:
    """Return a rejection reason, or the empty string when the evidence is acceptable.

    Reasoning is not the place to repair evidence. Anything that cannot be correlated --
    no ID, no dual time, no observation -- is rejected with a reason rather than stored in
    a shape that later stages would have to guess about.
    """
    if not evidence.evidence_id:
        return "MISSING_EVIDENCE_ID"
    if evidence.evidence_type == evidence_pb2.EVIDENCE_TYPE_UNSPECIFIED:
        return "UNSPECIFIED_EVIDENCE_TYPE"
    if not evidence.HasField("observation"):
        return "MISSING_OBSERVATION"
    time = evidence.observation.time
    if not time.HasField("event_time") or not time.HasField("ingest_time"):
        return "MISSING_DUAL_TIME"
    if not 0.0 <= evidence.confidence <= 1.0:
        return "CONFIDENCE_OUT_OF_RANGE"
    return ""
