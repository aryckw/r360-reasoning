"""The boundaries this repository is not allowed to cross.

M0 exit criterion: "No raw IQ or DSP implementation is present in Reasoning." The rule is
checked three ways, from strongest to weakest: the contract cannot carry IQ, the
dependencies cannot process it, and the sources do not implement it.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

from google.protobuf.descriptor import FieldDescriptor
from r360.evidence.v1 import evidence_pb2

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src" / "r360_reasoning"

# Array and signal-processing libraries. Their absence is what makes "no DSP here"
# structural rather than aspirational: this service could not process IQ if it wanted to.
FORBIDDEN_MODULES = {"numpy", "scipy", "torch", "cupy", "sigmf", "soapysdr", "pyfftw"}

# Names that would mean somebody started implementing signal processing here.
DSP_VOCABULARY = ("fft", "cfar", "iq_samples", "spectrogram", "matched_filter", "resample")


def python_sources() -> list[Path]:
    return sorted(SOURCE_ROOT.rglob("*.py"))


def code_without_comments(path: Path) -> str:
    """Comments and docstrings removed; string literals kept.

    A comment explaining that DSP does not belong here is not DSP. A string literal is
    kept because that is where a topic name or a smuggled label would live.
    """
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)#.*$", "", text)
    return re.sub(r'"""(?:.|\n)*?"""', "", text)


def test_no_dsp_or_array_dependency_is_imported() -> None:
    """REQ-REA-001: Reasoning consumes structured evidence, not signals."""
    offenders: list[str] = []
    for path in python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0].lower() for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {(node.module or "").split(".")[0].lower()}
            else:
                continue
            for name in names & FORBIDDEN_MODULES:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {name}")
    assert offenders == [], f"signal-processing dependencies in Reasoning: {offenders}"


def test_no_dsp_vocabulary_in_the_sources() -> None:
    offenders: list[str] = []
    for path in python_sources():
        text = code_without_comments(path).lower()
        for term in DSP_VOCABULARY:
            if term in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {term}")
    assert offenders == [], f"signal processing in Reasoning: {offenders}"


def test_the_contract_cannot_deliver_raw_iq() -> None:
    """REQ-REA-001, structurally: there is no field on the evidence path to put IQ in.

    This is the check that does not depend on anyone here behaving. Even a Reasoning
    service that wanted raw samples could not be sent them through the canonical contract.
    """
    offenders: list[str] = []
    hints = ("sample", "iq", "waveform", "spectrogram", "raw")
    for descriptor in (
        evidence_pb2.DerivedEvidence.DESCRIPTOR,
        evidence_pb2.Feature.DESCRIPTOR,
        evidence_pb2.Classification.DESCRIPTOR,
        evidence_pb2.NoveltyAssessment.DESCRIPTOR,
    ):
        for field in descriptor.fields:
            bulk_numeric = field.label == FieldDescriptor.LABEL_REPEATED and field.type in (
                FieldDescriptor.TYPE_FLOAT,
                FieldDescriptor.TYPE_DOUBLE,
            )
            if (bulk_numeric or field.type == FieldDescriptor.TYPE_BYTES) and any(
                hint in field.name.lower() for hint in hints
            ):
                offenders.append(f"{descriptor.full_name}.{field.name}")
    assert offenders == [], f"the evidence contract could carry raw samples: {offenders}"


def test_no_mission_reasoning_is_implemented_yet() -> None:
    """M0 prohibits reasoning. Rules, correlation and episodes arrive at M8 and M9.

    Building them on an intake layer whose idempotency has not been proven would be
    building on sand, so the prohibition is checked rather than trusted.
    """
    premature = ("class Rule", "def correlate", "class MissionEpisode", "def generate_aar")
    offenders: list[str] = []
    for path in python_sources():
        text = code_without_comments(path)
        for term in premature:
            if term in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {term}")
    assert offenders == [], f"M0 must not implement reasoning: {offenders}"


def test_vendored_contracts_match_the_lock() -> None:
    """ADR-0008: a hand-edited local copy of a contract must fail, not change the wire."""
    result = subprocess.run(
        [sys.executable, "tools/contracts_vendor.py", "verify"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
