"""The boundary an LLM may not cross.

D-017 and REQ-REA-006: the LLM may explain or hypothesise; it may not overwrite evidence
or suppress contradictory evidence. That is a property of the *integration*, not a
property of the model, so it is enforced here rather than requested in a prompt.

Reasoning proper begins at M8. What exists now is the boundary itself, with a
deterministic fake model behind it, so that when the real adapter arrives it plugs into a
constraint that is already tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from r360.evidence.v1 import evidence_pb2


class LlmBoundaryViolation(Exception):
    """Raised when a model response tries to do something a model may not do."""


@dataclass(frozen=True)
class Explanation:
    """What an LLM is allowed to return: words, and references to evidence it was given."""

    text: str
    supporting_evidence_ids: tuple[str, ...] = ()
    contradicting_evidence_ids: tuple[str, ...] = ()


class LlmPort(Protocol):
    """The only shape an adapter may have.

    Note what is absent: there is no way to return evidence, amend evidence, or ask for
    evidence to be dropped. The type system removes the possibility before the checks
    below have to catch it.
    """

    def explain(self, evidence: tuple[evidence_pb2.DerivedEvidence, ...]) -> Explanation: ...


class DeterministicFakeLlm:
    """A stand-in that always answers the same way for the same input.

    Deterministic on purpose: a test that exercises the boundary must fail because the
    boundary is broken, never because a model felt different this morning.
    """

    def __init__(self, template: str = "{count} evidence item(s) considered") -> None:
        self._template = template

    def explain(self, evidence: tuple[evidence_pb2.DerivedEvidence, ...]) -> Explanation:
        return Explanation(
            text=self._template.format(count=len(evidence)),
            supporting_evidence_ids=tuple(item.evidence_id for item in evidence),
        )


def request_explanation(
    port: LlmPort, evidence: tuple[evidence_pb2.DerivedEvidence, ...]
) -> Explanation:
    """Call an LLM adapter and verify it stayed inside the boundary.

    Three checks, each corresponding to a way the rule is usually broken in practice:

    1. the evidence handed in is unchanged afterwards -- an adapter may not edit its
       input, even in place, even helpfully;
    2. every ID the model cites was in the input -- a model may not invent evidence, and
       a citation to an ID nobody supplied is exactly what invented evidence looks like;
    3. an ID may not be cited as both supporting and contradicting -- that is not a
       nuanced answer, it is an unusable one.
    """
    before = [item.SerializeToString(deterministic=True) for item in evidence]
    explanation = port.explain(evidence)
    after = [item.SerializeToString(deterministic=True) for item in evidence]

    if before != after:
        raise LlmBoundaryViolation(
            "the LLM adapter modified the evidence it was given; derived evidence is "
            "immutable to the explanation layer"
        )

    supplied = {item.evidence_id for item in evidence}
    cited = set(explanation.supporting_evidence_ids) | set(explanation.contradicting_evidence_ids)
    invented = sorted(cited - supplied)
    if invented:
        raise LlmBoundaryViolation(f"the LLM cited evidence that was never supplied: {invented}")

    both = sorted(
        set(explanation.supporting_evidence_ids) & set(explanation.contradicting_evidence_ids)
    )
    if both:
        raise LlmBoundaryViolation(f"evidence cited as both supporting and contradicting: {both}")

    return explanation
