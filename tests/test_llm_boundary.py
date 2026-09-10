"""REQ-REA-006 and D-017: an LLM may explain; it may not overwrite or invent evidence.

Reasoning proper begins at M8. The boundary is built and tested now so that the adapter
arrives into a constraint that already holds, rather than the constraint being retrofitted
around whatever the adapter turned out to do.
"""

from __future__ import annotations

import pytest
from google.protobuf.timestamp_pb2 import Timestamp
from r360.evidence.v1 import evidence_pb2
from r360_reasoning.llm.boundary import (
    DeterministicFakeLlm,
    Explanation,
    LlmBoundaryViolation,
    request_explanation,
)


def make_evidence(evidence_id: str) -> evidence_pb2.DerivedEvidence:
    evidence = evidence_pb2.DerivedEvidence(
        evidence_id=evidence_id,
        evidence_type=evidence_pb2.PULSE_DETECTION,
        confidence=0.8,
    )
    stamp = Timestamp(seconds=1788004803)
    evidence.observation.time.event_time.CopyFrom(stamp)
    evidence.observation.time.ingest_time.CopyFrom(stamp)
    return evidence


EVIDENCE = (make_evidence("ev-1"), make_evidence("ev-2"))


class MutatingLlm:
    """An adapter that edits its input. Helpfully, even. It still may not."""

    def explain(self, evidence: tuple[evidence_pb2.DerivedEvidence, ...]) -> Explanation:
        evidence[0].confidence = 0.99
        return Explanation(text="raised the confidence a little")


class InventingLlm:
    """An adapter that cites evidence nobody gave it."""

    def explain(self, evidence: tuple[evidence_pb2.DerivedEvidence, ...]) -> Explanation:
        return Explanation(text="also considered", supporting_evidence_ids=("ev-does-not-exist",))


class ContradictingItselfLlm:
    def explain(self, evidence: tuple[evidence_pb2.DerivedEvidence, ...]) -> Explanation:
        return Explanation(
            text="both at once",
            supporting_evidence_ids=("ev-1",),
            contradicting_evidence_ids=("ev-1",),
        )


def test_a_well_behaved_adapter_passes() -> None:
    explanation = request_explanation(DeterministicFakeLlm(), EVIDENCE)
    assert explanation.text == "2 evidence item(s) considered"
    assert explanation.supporting_evidence_ids == ("ev-1", "ev-2")


def test_the_fake_is_deterministic() -> None:
    """A boundary test must fail because the boundary broke, not because a model varied."""
    first = request_explanation(DeterministicFakeLlm(), EVIDENCE)
    second = request_explanation(DeterministicFakeLlm(), EVIDENCE)
    assert first == second


def test_an_adapter_may_not_modify_evidence() -> None:
    with pytest.raises(LlmBoundaryViolation, match="modified the evidence"):
        request_explanation(MutatingLlm(), (make_evidence("ev-1"),))


def test_an_adapter_may_not_cite_evidence_it_was_not_given() -> None:
    with pytest.raises(LlmBoundaryViolation, match="never supplied"):
        request_explanation(InventingLlm(), EVIDENCE)


def test_an_adapter_may_not_cite_evidence_both_ways() -> None:
    with pytest.raises(LlmBoundaryViolation, match="both supporting and contradicting"):
        request_explanation(ContradictingItselfLlm(), EVIDENCE)


def test_the_port_offers_no_way_to_return_evidence() -> None:
    """The strongest guard is structural: `Explanation` carries text and references only.

    A model cannot hand back a DerivedEvidence because there is no field to put one in.
    """
    assert set(Explanation.__dataclass_fields__) == {
        "text",
        "supporting_evidence_ids",
        "contradicting_evidence_ids",
    }
    assert all(
        field.type in {"str", "tuple[str, ...]"}
        for field in Explanation.__dataclass_fields__.values()
    )
