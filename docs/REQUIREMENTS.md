# r360-reasoning Requirements

Each requirement carries the milestone at which it becomes active. `tools/trace.py` fails
the gate if an active requirement has no test referencing its ID.

## Boundary and intake

- REQ-REA-001 [M0]: The Reasoning Service shall not accept raw IQ through the canonical
  R360 evidence contract, and shall contain no signal-processing implementation.
- REQ-REA-002 [M0]: MQTT evidence intake shall be idempotent by evidence ID: a duplicate
  delivery shall create no second persisted record and no second downstream effect, and
  shall be counted.
- REQ-REA-003 [M0]: Structured mission and event history shall be persisted; raw RF shall
  not.
- REQ-REA-009 [M0]: The service shall expose gRPC health reporting service name, status,
  service version, contract version, producer git SHA and dual time.
- REQ-REA-010 [M0]: Evidence that cannot be correlated -- missing ID, evidence type, dual
  time, or with a confidence outside [0,1] -- shall be rejected with a typed reason rather
  than stored or repaired.
- REQ-REA-011 [M0]: The deduplication cache shall be bounded, and durable storage shall be
  the authority on whether an evidence ID has been seen.

## Reasoning (M8 and later)

- REQ-REA-004 [M8]: Deterministic rules and state machines shall remain distinct from
  LLM-generated explanations and hypotheses.
- REQ-REA-005 [M9]: Supporting and contradicting evidence shall both be representable on
  outcomes.
- REQ-REA-006 [M0]: An LLM result shall not mutate or replace source or derived evidence.
  The boundary is built and tested in M0 even though reasoning begins at M8, so that the
  adapter arrives into a constraint that already holds.
- REQ-REA-007 [M9]: MissionEpisode shall be a minimal grouping abstraction, not a full
  workflow ontology.
- REQ-REA-008 [M9]: Human-readable AAR text shall reference the structured outcome and
  evidence chain from which it was generated.

## Cross-repository requirements verified here

- REQ-INT-003 [M0]: Duplicate MQTT delivery shall not create duplicate persisted evidence.
  Proven here against a real broker and a real database, and again by `r360-integration`
  across the composed stack.
