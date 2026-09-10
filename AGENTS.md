# AGENTS.md — r360-reasoning

This repository follows the R360 common operating contract. It may add stricter rules; it
may not weaken these.

## Prime directive

Build one milestone at a time in `ROADMAP.md` order. A milestone is complete only when
`docker compose run --rm gate` exits zero **and** every milestone exit criterion is
individually satisfied.

## Read order

1. `AGENTS.md`
2. `ROADMAP.md`
3. the active milestone prompt under `prompts/`
4. `docs/REQUIREMENTS.md`
5. `docs/SDD.md`
6. the ADRs under `docs/adr/`

Do not jump to later milestones because the reasoning is more interesting. Correlation
built on an intake layer whose idempotency has not been proven is correlation over
duplicated evidence, and it will look like corroboration.

## Autonomous authority

Within the active milestone you may design internal components, implement, refactor, add
tests, profile and benchmark, replace an internal algorithm with a conformant alternative,
and adopt an approved third-party dependency after recording the ADR and licence entry.

## External-contract freeze

The Protobuf contracts are vendored at a pinned hash (ADR-0008 in `r360-contracts`) and
are frozen for the milestone. If a contract genuinely blocks the milestone, write
`docs/BLOCKED.md` with the exact conflict and stop honestly. Do not edit
`contracts/proto/` locally: the gate recomputes its hash and will fail.

Internal refactoring stays free while the gate is green.

## Evidence rules

- Source observations are immutable; derived evidence never overwrites them.
- Confidence is not truth. `UNKNOWN` is a valid, first-class result.
- **Derived evidence is immutable here.** This service correlates and concludes; it never
  edits what RF Evidence observed.
- **Contradicting evidence is retained.** An outcome that disagrees with some of its
  inputs must say so. Dropping the inconvenient half is the failure mode this whole
  architecture exists to prevent.
- **The LLM may explain, never overwrite.** Enforced in `llm/boundary.py`, not requested
  in a prompt.
- Evidence that cannot be correlated is rejected with a typed reason, never repaired into
  a shape later stages would have to guess about.

## Determinism rules

- Correlation keys on event and logical time carried in the evidence, never on arrival
  order or wall-clock time.
- Every stochastic test carries a committed seed. The LLM stand-in is deterministic, so a
  boundary test fails because the boundary broke and not because a model varied.
- No unordered traversal where it affects output ordering.

## Repository boundary

Raw IQ and signal processing do not belong here and cannot arrive here: the canonical
contract has no field for bulk samples, this repository depends on no array or DSP
library, and `tests/test_repository_boundaries.py` fails if either changes.

## Gate tampering prohibited

Do not weaken thresholds, skip or xfail a failing test without requirement authority,
delete a negative test, narrow corpus coverage to hide a regression, or globally suppress
compiler or type errors. If the gate is wrong, write an ADR and leave reality visible.

## Data restrictions

Public, synthetic, or unclassified data only. No classified, CUI, or ITAR-derived material,
no real operational threat libraries, no secrets or private endpoints in fixtures, configs,
comments, or commits.

## Definition of done

Requirement IDs identified; tests cover normal, boundary and adversarial cases;
external contracts unchanged during the milestone; deterministic tests green; performance
results produced where applicable; docs and ADRs updated; `gate` green; every exit
criterion independently checked; completion report records git SHA, tests, metrics, and
known limitations.

## Stop condition

Stop when the active milestone is green, or when a documented external contradiction
prevents honest continuation. A transparent blocked state beats a false green.
