# Airport Investment Intelligence Agent

A chat agent that helps analysts of an investment firm find US airports where terminal or capacity expansion looks most promising. It uses public aviation data, ranks airports with a deterministic score (not model output), explains its reasoning, and states assumptions and uncertainty. The task is in [ASSIGNMENT.md](ASSIGNMENT.md); project rules are in [CLAUDE.md](CLAUDE.md).

The agent loop is written by hand (no agent framework). The model chooses tools and explains results; all numbers come from tool results computed by code.

## Status

Work is staged. **Stages 1 and 2 are done: the placeholder domain was removed, and the airport data layer (snapshot, schema, repository) is in place. There are no airport tools yet, so the agent cannot answer data questions.**

| Stage | State |
|---|---|
| 1. Strip the old domain, rewrite instructions | done |
| 2. Data layer: schema, ingest, committed snapshot, repository | done |
| 3. Scoring and airport tools | next |
| 4. Prompt, API and chat UI polish | partly in place (chat UI and API run, but there are no airport tools yet) |
| 5. Evals (no cases yet) | not started |
| 6. Docs and presentation | not started |

Data sources and their limits were checked first: see [docs/DATA_SPIKE.md](docs/DATA_SPIKE.md).

## Run

```bash
cp .env.example .env        # then put your ANTHROPIC_API_KEY in .env
docker compose up --build   # Postgres + API; loads the committed snapshot at startup (port 5432 taken? POSTGRES_PORT=5433 docker compose up --build)
```

Then open `http://localhost:8000` for the chat page, or `GET /health`.

Without Docker, with the project virtualenv:

```bash
pip install -e ".[dev]"
python cli.py        # interactive demo (needs Postgres: docker compose up -d postgres)
make test            # unit and API tests (fake model, no network); Postgres tests skip if it is not running
make lint
make ingest          # rebuild domain/data/ from the public APIs (needs internet, about a minute)
```

Development helpers: `LOG_FORMAT=console` for readable logs; `LLM_CACHE=1` replays identical model calls from `.llm_cache/` (development only; evals ignore it).

## Layout

`core/` generic engine (loop, tool registry, sessions, logging) · `adapters/` model, cache and session adapters · `app/` settings and wiring · `api/` FastAPI and chat page · `domain/` airport-specific files (prompt, data snapshot, repository interface; tools and scoring come next) · `scripts/ingest.py` builds the snapshot · `evals/` runner and judge · `tests/`.

## Docs

- [DATA_SPIKE](docs/DATA_SPIKE.md): checks of the public data sources and ingest findings (current).
- [DECISIONS](docs/DECISIONS.md): decisions with reasons and tradeoffs (current).
- DESIGN, EVALS, PRODUCTION, SWAP_GUIDE: carry a "Stale" banner. They describe the earlier placeholder version (git tag `placeholder-domain`) and will be rewritten.
- Learning material (`docs/PYTHON_GUIDE.html`, `docs/FDE_MENTAL_MODEL.html`, `docs/FLOW.html`): general explanations whose code examples come from the `placeholder-domain` version.
