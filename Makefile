# The project virtualenv on Windows or Linux/macOS, else `python` from the PATH.
PY ?= $(or $(wildcard .venv/Scripts/python.exe),$(wildcard .venv/bin/python),python)

run:
	docker compose up --build

chat:
	DATA_BACKEND=memory $(PY) cli.py

test:
	$(PY) -m pytest -q

eval:
	DATA_BACKEND=memory $(PY) -m evals.runner

ingest:
	$(PY) -m scripts.ingest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
