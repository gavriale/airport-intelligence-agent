PY ?= .venv/Scripts/python

run:
	docker compose up --build

chat:
	$(PY) cli.py

test:
	$(PY) -m pytest -q

eval:
	$(PY) -m evals.runner

ingest:
	$(PY) -m scripts.ingest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
