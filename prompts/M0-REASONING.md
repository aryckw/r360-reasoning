# Autonomous Assignment — M0 (r360-reasoning)

Implement **M0 only**: the service skeleton, idempotent evidence intake, persistence, and
the authoritative gate. No reasoning.

## Required outcomes

- MQTT subscriber at QoS 1 with idempotency by evidence ID, backed by a bounded cache and
  a durable store;
- rejection of evidence that cannot be correlated, with typed reasons and counters;
- Postgres persistence of the structured record;
- gRPC health and version reporting service version, contract version and git SHA;
- the LLM boundary, with a deterministic fake behind it;
- contracts vendored at a pinned tree hash and verified by the gate;
- one authoritative containerized gate: `docker compose run --rm gate`;
- requirement trace and dependency/licence inventory.

## Prohibitions

- no rules engine, temporal correlation, confidence aggregation, mission events, episodes,
  outcomes, or AAR generation;
- no real LLM adapter;
- no raw IQ, no DSP, and no array or signal-processing dependency;
- no edits to `contracts/proto/`: it is vendored, and the gate hashes it;
- no uncommitted generated bindings.

## Definition of done

`docker compose run --rm gate` exits zero with a real broker and database in the loop,
every exit criterion in `ROADMAP.md` is individually demonstrated, and the completion
report records the git SHA, the tests run, and the known limitations.
