PYTHON ?= python
NPM ?= npm
SIDECAR_HOST ?= 127.0.0.1
SIDECAR_PORT ?= 8765

.PHONY: dev-sidecar build-plugin test contracts contract-test python-test plugin-test plugin-typecheck

dev-sidecar:
	cd services/scheduler && PYTHONPATH=src $(PYTHON) -m agent_scheduler.main --host $(SIDECAR_HOST) --port $(SIDECAR_PORT)

build-plugin: plugin-typecheck
	cd packages/openclaw-plugin && $(NPM) run build

test: contract-test python-test plugin-test

plugin-test:
	cd packages/openclaw-plugin && $(NPM) test

plugin-typecheck:
	cd packages/openclaw-plugin && $(NPM) run typecheck

contracts:
	$(PYTHON) tools/validate_contracts.py

contract-test: contracts

python-test:
	cd services/scheduler && $(PYTHON) -m pytest --basetemp ../../.pytest-tmp
