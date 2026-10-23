PY ?= .venv/Scripts/python

run:
	docker compose up --build

chat:
	DATA_BACKEND=fake $(PY) cli.py

test:
	$(PY) -m pytest -q

eval:
	DATA_BACKEND=fake $(PY) -m evals.runner

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
