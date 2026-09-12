# r360-reasoning Roadmap

Milestones execute in program order. A milestone is `DONE` only when
`docker compose run --rm gate` exits zero **and** every exit criterion is individually
demonstrated.

| # | Milestone | Status |
|---|---|---|
| M0 | service skeleton, idempotent intake, persistence, gate | DONE |
| M1 | no work in this repository; the program's M1 lives in rf-evidence and integration | — |
| M2 | no work in this repository; the native dataplane lives in rf-evidence, its stack proof in integration | — |
| M8 | reasoning foundation: lifecycle and diagnostic intake, rules, temporal correlation, confidence, bounded LLM | TODO |
| M9 | event fusion, minimal mission episodes, evidence-linked AAR | TODO |
| M10 | World-State Adapter correlation | TODO |

## M0 exit criteria for this repository

1. `gate` exits zero, with a real broker and a real database in the loop.
2. Duplicate QoS 1 delivery of the same evidence persists exactly one row and creates no
   second downstream effect (REQ-REA-002).
3. Duplicates are counted, not silently dropped.
4. The deduplication cache is bounded, and the durable store is the authority on whether
   an ID has been seen (REQ-REA-011).
5. Evidence that cannot be correlated is rejected with a typed reason and is not stored
   (REQ-REA-010).
6. A malformed payload does not stop the consumer.
7. gRPC health reports service name, status, service version, contract version, git SHA
   and dual time (REQ-REA-009).
8. The service cannot report a contract version other than the one in `contracts.lock`.
9. No raw IQ or DSP is present: no array or signal-processing dependency, no DSP
   vocabulary in the sources, and no contract field that could carry samples
   (REQ-REA-001).
10. An LLM adapter cannot modify evidence, invent evidence, or cite the same evidence both
    ways (REQ-REA-006).
11. Requirement trace and dependency/licence inventory are complete and current.

## Explicitly not in M0

No rules engine, no temporal correlation, no confidence aggregation, no mission events, no
episodes, no outcomes, no AAR generation, no real LLM adapter. Those arrive at M8 and M9,
on top of an intake layer that has been proven idempotent first.
