.PHONY: dev-sidecar build-plugin test contracts contract-test python-test

dev-sidecar:
	cd services/scheduler && python -m agent_scheduler.main --host 127.0.0.1 --port 8765

build-plugin:
	cd packages/openclaw-plugin && npm.cmd run build

test: contract-test python-test
	cd packages/openclaw-plugin && npm.cmd test

contracts:
	python tools/validate_contracts.py

contract-test: contracts

python-test:
	cd services/scheduler && python -m pytest --basetemp ../../.pytest-tmp
