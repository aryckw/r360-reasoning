# r360-reasoning gate. This Makefile runs INSIDE the container image.
# From the Windows host, do not invoke it directly:
#     docker compose run --rm gate      (or: .\gate.ps1)
#     docker compose run --rm shell     then `make <target>`

.PHONY: help gate gen gen-check contracts-verify contracts-update fmt fmt-write lint \
        types test test-integration boundaries trace deps deps-write clean

PROTO_DIR   := contracts/proto
PY_OUT      := generated/python
PROTOS      := $(shell find $(PROTO_DIR) -name '*.proto' | sort)
SERVICE_VERSION := $(shell cat VERSION)

export PYTHONPATH := $(PY_OUT):$(CURDIR)/src:$(CURDIR)

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ── THE GATE ─────────────────────────────────────────────────────────────────
# This target is the contract. It is the only thing that decides whether a milestone is
# done for this repository. Do not weaken it to make a milestone pass; see AGENTS.md.
gate: contracts-verify fmt lint types gen-check test test-integration trace deps
	@echo ""
	@echo "  r360-reasoning GATE PASSED  (service $(SERVICE_VERSION))"
	@echo ""

# ── contracts ────────────────────────────────────────────────────────────────
contracts-verify:  ## ADR-0008: vendored proto tree matches contracts.lock
	python tools/contracts_vendor.py verify

contracts-update:  ## re-vendor from a sibling r360-contracts checkout
	python tools/contracts_vendor.py update --source ../r360-contracts --tag $(TAG)

gen:  ## regenerate Python bindings from the vendored contracts
	@rm -rf $(PY_OUT)
	@mkdir -p $(PY_OUT)
	python -m grpc_tools.protoc -I$(PROTO_DIR) \
	       --python_out=$(PY_OUT) --pyi_out=$(PY_OUT) --grpc_python_out=$(PY_OUT) $(PROTOS)
	@echo "generated $(words $(PROTOS)) proto files"

gen-check: gen  ## regeneration must leave a clean git diff
	@git diff --exit-code -- $(PY_OUT) \
	  || (echo "FAIL: generated bindings are stale; commit the result of 'make gen'" && exit 1)
	@test -z "$$(git ls-files --others --exclude-standard -- $(PY_OUT))" || ( \
	    echo "FAIL: generation produced untracked bindings; commit them:"; \
	    git ls-files --others --exclude-standard -- $(PY_OUT); \
	    exit 1)
	@echo "generation is deterministic and committed"

# ── static checks ────────────────────────────────────────────────────────────
fmt:  ## formatting
	ruff format --check src tests tools

fmt-write:  ## apply formatting
	ruff format src tests tools

lint:  ## lint
	ruff check src tests tools

types:  ## strict type check
	mypy --strict src tools

# ── tests ────────────────────────────────────────────────────────────────────
test:  ## unit tests: idempotency, LLM boundary, repository boundaries
	pytest -q tests --ignore=tests/integration

test-integration:  ## real broker, real Postgres, real service process
	pytest -q tests/integration

boundaries:  ## repository boundary rules only
	pytest -q tests/test_repository_boundaries.py

# ── inventory ────────────────────────────────────────────────────────────────
trace:  ## every active requirement has at least one referencing test
	python tools/trace.py --tests tests

deps:  ## dependency and license inventory is current
	python tools/license_inventory.py --check

deps-write:  ## rewrite docs/DEPENDENCIES.md from docs/dependencies.toml
	python tools/license_inventory.py

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
