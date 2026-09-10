# r360-reasoning Software Design Description

## Planned flow

```text
MQTT DerivedEvidence + World-State events
 -> deduplicate and validate            (M0)
 -> persist references                  (M0)
 -> deterministic temporal and rule layer (M8)
 -> confidence aggregation              (M8)
 -> context retrieval                   (M8)
 -> optional bounded LLM hypothesis     (M8)
 -> MissionEvent                        (M9)
 -> minimal MissionEpisode              (M9)
 -> ReasoningOutcome                    (M9)
 -> evidence-linked AAR                 (M9)
```

The first two stages exist. Everything downstream of them depends on their correctness in
a way that would be invisible if they were wrong: correlation over duplicated evidence
does not look like a bug, it looks like corroboration.

## What exists in M0

| Component | File | Responsibility |
|---|---|---|
| intake | `intake/consumer.py` | parse, validate, deduplicate, store, count |
| idempotency | `intake/idempotency.py` | bounded seen-cache, validation vocabulary, metrics |
| storage | `storage/evidence_store.py` | in-memory and Postgres stores behind one port |
| LLM boundary | `llm/boundary.py` | the constraint an adapter must satisfy |
| service | `service.py` | MQTT subscription, gRPC health, retained health, shutdown |
| configuration | `config.py` | validation that fails with reasons rather than defaults |

## Idempotency, in order of authority

1. **The database.** `evidence_id` is the primary key and inserts use
   `ON CONFLICT DO NOTHING`, so a duplicate is a no-op regardless of what any process
   believed, and regardless of the order two workers ran in.
2. **The bounded cache.** An optimisation in front of the database, not a substitute for
   it. It is bounded, so it forgets; a consumer that trusted only its cache would accept
   a duplicate after a restart or after enough traffic to evict the ID.
3. **The downstream effect.** Side effects run only on the path where the database
   actually inserted a row, so deduplicating the record and deduplicating the consequence
   are the same act rather than two hopeful ones.

The unit tests exercise all three, including the eviction case that a naive cache hides.

## Configuration

A dataclass rather than a Protobuf schema. `r360-rf-evidence` uses Protobuf for its
configuration because two languages read it and must agree (ADR-0003 there); here there is
one implementation in one language, and the schema machinery would buy nothing. What is
kept is the behaviour that matters: unknown keys are rejected, every problem is reported
at once, and the configuration is hashed so a run can be tied to what configured it.

## Storage

Postgres holds evidence references, and from M9 events, episodes, hypotheses and outcomes.
It never holds raw RF. The serialized evidence message is stored alongside the extracted
columns so that a later schema change can re-read the original bytes rather than trusting
columns extracted by an older build.

## Error behaviour

| Situation | Response |
|---|---|
| unparseable payload | reject, count, keep consuming |
| evidence missing ID, type, dual time, or with confidence out of range | reject with a typed reason, do not store |
| duplicate delivery | count as duplicate, no second row, no second effect |
| invalid configuration | fail before serving, listing every problem |
| LLM adapter that edits or invents evidence | raise `LlmBoundaryViolation` |
