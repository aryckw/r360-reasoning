"""Build and contract identity.

A service must not be able to claim a contract version it was not built against. The C++
service compiles the value in; this one reads it from the same `contracts.lock` that the
gate hashes the vendored proto tree against, so the two are one fact rather than two.
"""

from __future__ import annotations

import functools
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_NAME = "r360-reasoning"
SERVICE_VERSION = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()


@functools.lru_cache(maxsize=1)
def contract_version() -> str:
    lock = tomllib.loads((REPO_ROOT / "contracts.lock").read_text(encoding="utf-8"))
    version: str = lock["contract_version"]
    return version


@functools.lru_cache(maxsize=1)
def contract_tag() -> str:
    lock = tomllib.loads((REPO_ROOT / "contracts.lock").read_text(encoding="utf-8"))
    tag: str = lock["contract_tag"]
    return tag


@functools.lru_cache(maxsize=1)
def git_sha() -> str:
    """The revision this build came from, or `unknown` when git cannot say.

    `unknown` is honest. Fabricating a value here would put a lie into evidence
    provenance, which is the one place it would be most costly.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "unknown"
