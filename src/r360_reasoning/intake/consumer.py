"""MQTT evidence intake.

The consumer subscribes to the RF evidence topic, validates each payload against the
canonical contract, deduplicates by evidence ID, and stores what it accepts. It does no
reasoning: correlation, rules, episodes and outcomes arrive at M8, and building them on an
intake layer that has not been proven idempotent would be building on sand.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from r360.evidence.v1 import evidence_pb2

from r360_reasoning.intake.idempotency import (
    IntakeMetrics,
    IntakeResult,
    SeenCache,
    validate_evidence,
)
from r360_reasoning.storage.evidence_store import EvidenceStore

LOGGER = logging.getLogger(__name__)

# One message type per topic (ADR-0007): the payload can be decoded without an envelope.
EVIDENCE_TOPIC_TEMPLATE = "r360/v1/{session_id}/rf/evidence"
LIFECYCLE_TOPIC_TEMPLATE = "r360/v1/{session_id}/rf/lifecycle"
DIAGNOSTICS_TOPIC_TEMPLATE = "r360/v1/{session_id}/rf/diagnostics"


class EvidenceIntake:
    """Validates, deduplicates and stores incoming evidence.

    Deduplication asks the cache first and the store second. The cache is bounded, so it
    can forget; the store cannot, which is why the store is what decides. A consumer that
    trusted only its cache would accept a duplicate that arrived after a restart or after
    enough traffic to evict the ID.
    """

    def __init__(
        self,
        store: EvidenceStore,
        seen: SeenCache | None = None,
        on_accepted: Callable[[evidence_pb2.DerivedEvidence], None] | None = None,
    ) -> None:
        self._store = store
        self._seen = seen if seen is not None else SeenCache()
        self._on_accepted = on_accepted
        self.metrics = IntakeMetrics()

    def handle_payload(self, payload: bytes) -> IntakeResult:
        self.metrics.received_total += 1

        evidence = evidence_pb2.DerivedEvidence()
        try:
            evidence.ParseFromString(payload)
        except Exception:  # noqa: BLE001 - any parse failure is the same decision
            return self._reject("", "UNPARSEABLE_PAYLOAD")

        reason = validate_evidence(evidence)
        if reason:
            return self._reject(evidence.evidence_id, reason)

        if evidence.evidence_id in self._seen:
            return self._duplicate(evidence.evidence_id)

        stored = self._store.store(evidence)
        self._seen.add(evidence.evidence_id)
        if not stored:
            # The cache had forgotten it; the store had not. Durable state wins.
            return self._duplicate(evidence.evidence_id)

        self.metrics.accepted_total += 1
        if self._on_accepted is not None:
            # Downstream effects run exactly once per evidence ID, because they run only
            # on the path where the store actually inserted a row.
            self._on_accepted(evidence)
        return IntakeResult(accepted=True, evidence_id=evidence.evidence_id)

    def _duplicate(self, evidence_id: str) -> IntakeResult:
        self.metrics.duplicate_total += 1
        LOGGER.debug("duplicate delivery of %s", evidence_id)
        return IntakeResult(accepted=False, evidence_id=evidence_id, duplicate=True)

    def _reject(self, evidence_id: str, reason: str) -> IntakeResult:
        self.metrics.rejected_total += 1
        self.metrics.rejected_by_reason[reason] = self.metrics.rejected_by_reason.get(reason, 0) + 1
        LOGGER.warning("rejected evidence %s: %s", evidence_id or "<no id>", reason)
        return IntakeResult(accepted=False, evidence_id=evidence_id, rejected_reason=reason)
