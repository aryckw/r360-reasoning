# r360-reasoning

Turns structured evidence and world context into defensible semantic events, minimal
mission episodes, outcomes, and evidence-linked AAR text. Python only. Raw IQ is out of
scope, and the canonical contract cannot deliver it here even if something tried.

```bash
docker compose run --rm gate      # the authoritative gate; on Windows: .\gate.ps1
docker compose run --rm shell     # same image, interactive
docker compose up service         # run against the local dev broker and database
```

## Current state (M0)

Reasoning begins at M8. What exists now is the intake layer everything later will stand
on, plus the boundary an LLM will have to live inside:

| Working | Not yet |
|---|---|
| MQTT evidence intake at QoS 1 | temporal correlation (M8) |
| idempotency by evidence ID, cache plus durable store | deterministic rules and state machines (M8) |
| rejection of uncorrelatable evidence, with typed reasons | mission events and episodes (M9) |
| Postgres persistence of the structured record | outcomes and evidence-linked AAR (M9) |
| gRPC health and version | world-state correlation (M10) |
| the LLM boundary, with a deterministic fake behind it | a real LLM adapter (M8) |

Building correlation on an intake layer whose idempotency had not been proven would be
building on sand, which is why M0 stops here and proves that instead.

## The rule the LLM lives under

`src/r360_reasoning/llm/boundary.py` enforces what D-017 requires: an LLM may explain or
hypothesise, and may not overwrite evidence or suppress what contradicts it. The port has
no field in which a model could return evidence, the caller verifies the evidence it
handed over is byte-identical afterwards, and a model that cites an ID nobody supplied is
rejected rather than believed.

## Contracts

The `.proto` tree under `contracts/` is vendored from `r360-contracts` at the version in
`contracts.lock`, and the gate re-verifies its hash on every run.
