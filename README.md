# Airport Investment Intelligence Agent

A chat agent that helps analysts of an investment firm find US airports where terminal or capacity expansion looks most promising. It uses public aviation data (BTS T-100, OurAirports, FAA live status), ranks airports with a **deterministic score computed in code**, explains its reasoning, and states assumptions and uncertainty. The task is in [ASSIGNMENT.md](ASSIGNMENT.md).

The agent loop is written by hand (no agent framework). The model chooses tools and explains results; every number comes from a tool result.

- **[DESIGN.md](DESIGN.md)**: scoring methodology, architecture, tradeoffs, where AI is used, excluded factors, next steps.
- **[docs/EVALS.md](docs/EVALS.md)**: how the agent is evaluated, results of four runs, known failures.
- [docs/DECISIONS.md](docs/DECISIONS.md): every decision with alternatives and tradeoffs. [docs/DATA_SPIKE.md](docs/DATA_SPIKE.md): checks of the data sources.

## Run it

**With a key (full chat).**

```bash
cp .env.example .env        # then put your ANTHROPIC_API_KEY in .env
docker compose up --build   # Postgres + API; loads the committed snapshot at startup
```

Open `http://localhost:8000` for the chat page. If port 5432 is taken: `POSTGRES_PORT=5433 docker compose up --build`.

Without Docker (uses the in-memory repository, same data): `pip install -e ".[dev]"`, then `DATA_BACKEND=memory python cli.py` (or `make chat`) for a terminal chat.

Try: *Which airports in New England are strong candidates for terminal expansion?* then *What if we weigh passenger growth much more heavily?*, or *Compare LA and Santa Ana airport congestion.*

**Without a key.** No model is needed for:

- `make test`: unit and API tests with a fake model, no network (Postgres tests are skipped if it is not running).
- `GET /ranking`: the deterministic ranking, for example `curl "localhost:8000/ranking?region=New%20England"`. Also `GET /health`. (Start the API with `docker compose up`, or `DATA_BACKEND=memory uvicorn api.main:app_factory --factory`.)
- `/chat` needs a key; without one it returns a server error.

`make lint`, `make eval` (calls the live model, about $1 and 90 seconds), `make ingest` (rebuilds `domain/data/` from the public APIs, needs internet, about a minute).

## Results summary

20 eval cases, four runs: 67%, 60%, 85%, 75% (run 4 passes 15 of 20). No unsafe answers; two safety cases are at 2 of 3 because of an eval-measurement issue, not agent behavior. Differences of a couple of cases are within noise (one sample per case, same-model judge). Details in [docs/EVALS.md](docs/EVALS.md).

## What it cannot tell you

Data is monthly and about six months old (latest April 2026). There is no terminal or gate data, no delay history, no route-level or carrier-by-airport data, and unmet demand and profitability are not measured. For example, the exact long-haul share at Anchorage is not computable; the agent gives two proxies and says so.

## Layout

`core/` generic engine (loop, tool registry, sessions, logging) · `adapters/` model, data, cache and session adapters · `app/` settings and wiring · `api/` FastAPI and chat page · `domain/` everything airport-specific (config, prompt, scoring, tools, data snapshot, eval cases) · `scripts/ingest.py` builds the snapshot · `evals/` runner and judge · `tests/`.

Learning material (`docs/PYTHON_GUIDE.html`, `docs/FDE_MENTAL_MODEL.html`, `docs/FLOW.html`) explains general concepts; its code examples come from the earlier placeholder version (git tag `placeholder-domain`).
