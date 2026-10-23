# CLAUDE.md: Airport Investment Intelligence Agent

## Why this repo exists

I am interviewing for a **Forward Deployed Engineer (FDE)** role at Wonderful, a company that deploys production-grade AI agents (voice, chat, email) for regulated enterprises. I received a home assignment with a **one-day** budget and I present it in a technical interview. The interview probes:

- **Why** each choice was made (data sources, scoring, tools).
- **Evaluation:** how I know the agent works. A past candidate was rejected for gaps in evaluation and deployment.
- **Production thinking:** deployment, latency, observability, integration.
- **Business framing:** the FDE role is part engineer, part product owner, part business analyst.

**The most important constraint: I must be able to explain every line.** A smaller project I fully own beats a bigger one I partly understand. When in doubt, build less and document the rest.

## The assignment (see ASSIGNMENT.md)

An investment firm wants an agent that helps analysts find US airports where renovation or terminal expansion would be most profitable, based on growth in flights and passenger capacity.

- Answer questions such as: strong **New England** candidates for terminal expansion; compare **LAX vs SNA** congestion; **% of long-haul flights out of ANC**; **unmet flight demand at SFO and why**.
- Use public APIs for airport and aviation data.
- Rank or compare airports with **deterministic scoring logic** (not LLM output).
- Explain reasoning, support conversational follow-ups, and **state assumptions, uncertainty and scope clearly**.
- A chat interface is required (voice is a bonus; not planned).
- Deliverables: source code and a short design document (scoring methodology, key tradeoffs, where and how AI is used).

## Guiding principles

1. **Minimal but complete.** Every layer exists end to end (agent loop, tools, data, scoring, API, UI, evals, docs), each as simple as it can be.
2. **Numbers come from code, words from the model.** Every figure shown to the user comes from a tool result computed by deterministic code. The model chooses tools and explains; it does not calculate or recall data.
3. **Honest about data.** Say what a metric is, what it is not, and how old the data is. Never present a proxy as the real thing (see "Known data limits").
4. **Domain is configuration, the engine is generic.** Domain-specific code lives in `domain/`; `core/` knows nothing about airports.
5. **Every decision is documented** with reason and tradeoff in `docs/DECISIONS.md`.
6. **No frameworks that hide the agent loop.** No LangChain, LlamaIndex, CrewAI or similar. A thin provider SDK is fine.
7. **Honest docs.** Do not claim anything that is not implemented and verified. Label future work as future work.
8. **Ask before adding** anything not listed here.

## Tech stack

- **Python 3.11+, async end to end.** `AsyncAnthropic`, `asyncpg`, `asyncio.gather` for parallel tool calls.
- **LLM:** `LLMProvider` interface, Anthropic adapter (default), `FakeLLMProvider` for tests, dev-only record/replay cache (`LLM_CACHE=1`, never used by evals), prompt caching in the adapter.
- **API and UI:** FastAPI (`POST /chat`, `GET /health`) plus a static chat page; CLI for demos.
- **Data:** PostgreSQL via `asyncpg` behind a repository interface (`domain/repository.py`). A committed **snapshot** (CSV files in `domain/data/`) is loaded at startup in one transaction and skipped when its hash is unchanged. Traffic is kept for peer airports only (at least 100,000 passengers in the last 12 months); airports and runways cover every US airport with an IATA code. `make ingest` rebuilds the snapshot from the public APIs. Parameterized queries only.
- **No retrieval index.** The knowledge base and BM25 were removed; methodology comes from `get_methodology` (config).
- **Config:** `pydantic-settings` (`.env`), scoring weights and definitions in `domain/config.yaml`.
- **Tests:** pytest (+ pytest-asyncio). Lint and format with `ruff`.
- **Run:** `docker compose up` starts Postgres and the API.

## Target structure

```
.
├── CLAUDE.md, ASSIGNMENT.md, README.md
├── Dockerfile, docker-compose.yml, Makefile      # run, chat, test, eval, lint, ingest
├── core/                  # generic engine
│   ├── interfaces.py      # LLMProvider, SessionStore, message and tool models
│   ├── agent.py           # the tool-calling loop
│   ├── tools.py           # registry, validation, timeouts, structured errors
│   ├── session.py         # conversation history
│   ├── errors.py, logging.py
├── adapters/              # anthropic_llm, fake_llm, llm_cache, memory_session_store,
│                          # postgres_repository, memory_repository, snapshot_files, faa_status
├── app/                   # settings.py, container.py (composition root)
├── api/                   # main.py, static/index.html
├── domain/                # everything airport-specific
│   ├── config.yaml        # scoring weights, definitions, region map, thresholds
│   ├── system_prompt.md
│   ├── tools.py           # airport tools
│   ├── scoring.py         # deterministic KPIs and score (pure functions)
│   ├── metrics.py, search.py, config.py, live_status.py
│   ├── analytics.py       # the analyses behind the tools and /ranking
│   ├── repository.py      # AirportRepository interface and record models
│   ├── data/              # schema.sql, airports.csv, runways.csv, airport_month.csv, snapshot_meta.json
│   └── eval_cases.yaml
├── scripts/ingest.py      # builds the snapshot from public APIs
├── evals/                 # runner.py, judges.py
├── tests/
└── docs/                  # DESIGN, DECISIONS, EVALS, PRODUCTION, DATA_SPIKE, PRESENTATION
```

## Data sources (verified in docs/DATA_SPIKE.md)

- **BTS T-100 summary by origin airport** (Socrata `r495-tyji`, no key): monthly, latest **April 2026**. Traffic, seats, load factor, average flight distance, domestic vs international departures, freight.
- **OurAirports** `airports.csv` and `runways.csv`: state, coordinates, IATA, runways (columns to be confirmed at ingest).
- **FAA NAS status** (`nasstatus.faa.gov/api/airport-status-information`, XML, live): lists only airports with an active delay program or closure; absence means no reported delay.
- **Not used:** OpenSky (anonymous access is the last ~6 hours only, destinations 5% filled), BTS On-Time files (bulk, domestic passenger carriers only), ArcGIS T-100 (one row per airport per year, no routes).

## Known data limits (must be stated by the agent when relevant)

- Data is **monthly, and about six months old** (as of April 2026). Always report the as-of month.
- **No terminal or gate capacity data.** The score measures demand pressure, not physical terminal constraint. Runway count is a weak capacity proxy.
- **No delay history.** "Congestion" means utilization of runways and seats, plus a live FAA snapshot. Never claim measured delays.
- **No route-level data.** The exact share of long-haul flights is **not computable from public API data**, because route-level distances are not available. The agent presents two proxies and says so: the **international share of departures** and the **average stage length**. The international share is an approximation, not a bound: it overcounts short international flights (for example to Canada) and undercounts long domestic flights (for example Alaska to the East Coast).
- **No carrier-by-airport data.** Carrier concentration is not answerable.
- **Cargo is included** in the T-100 summary (confirmed: ANC international departures average about 4 seats). Passenger, seat and load-factor metrics are unaffected; departure counts include cargo flights; average flight distance and the international share describe all departures at cargo hubs such as ANC. The per-metric table is in `docs/DATA_SPIKE.md`.
- **"Unmet demand" is not measured.** Report proxies (load factor, demand gap, recovery vs 2019) and label any explanation of "why" as a hypothesis, not a finding.

## Scoring (deterministic, in `domain/scoring.py`, weights in `domain/config.yaml`)

Expansion Pressure Score, 0 to 100: weighted sum of percentile ranks computed **against national peers** (airports above a minimum annual passenger threshold). Regional queries rank within the region using the national percentiles.

| Metric | Definition | Weight |
|---|---|---|
| Growth | passengers, last 12 months vs the 12 months before | 0.25 |
| Load factor | passengers / seats, last 12 months | 0.25 |
| Passengers per runway | last 12 months passengers / runway count | 0.20 |
| Demand gap | passenger growth minus seat growth | 0.15 |
| Scale | log of last 12 months passengers | 0.10 |
| Peak ratio | peak month passengers / average month | 0.05 |

Assumptions to state with every ranking: data as-of month; origin passengers approximate boardings; runway count is a capacity proxy; weights are judgmental and configurable; "profitable" is not measured.

## Tools (read-only)

`search_airports`, `get_airport_profile`, `rank_airports`, `compare_airports`, `get_distance_profile`, `demand_pressure`, `get_live_status`, `get_methodology`. No tool takes free-form SQL. Each tool returns small, explicit results including `as_of` and a `caveats` list; the caveat texts live in `domain/config.yaml`. `GET /ranking` returns the same deterministic ranking with no model, for reviewers without an API key.

## Core requirements

- **Agent loop** (`core/agent.py`): explicit loop, max-iterations cap, parallel tool calls, tool errors returned as structured results, per-turn log of tools, latency (total, LLM, tools) and tokens.
- **Reliability:** timeouts on LLM and tool calls, one retry with backoff, graceful fallback message. Exceptions that are converted to error results are logged with tracebacks.
- **Logging:** structured logs (`LOG_FORMAT=console|json`), correlation and session ids on every line, a `tool_call` event per tool, no message text in logs.
- **Ports and adapters:** `core/` depends only on interfaces; concrete classes live in `adapters/` and are wired in `app/container.py`.
- **Clean code:** small single-purpose functions, type hints, pydantic models, typed errors, no magic values, no dead code.
- **Scalable by design:** stateless API; state goes through `SessionStore`.

## Removed from the placeholder skeleton

Identity verification, write actions with confirmation and idempotency, escalation and handoff, the investment-advice guardrail, the BM25 knowledge index and the old investment-house domain. The previous version is tagged `placeholder-domain`.

## Evals (first-class deliverable)

- About 16 cases in `domain/eval_cases.yaml` plus unit tests of the scoring math with fixed numbers.
- Deterministic checks first (tool called or not, required values, caveat present); one LLM-judge groundedness check with a fixed rubric.
- Cases include: the four assignment questions; the ANC answer must not invent an exact percentage; a carrier-concentration question must say it is unavailable; unknown airport code; follow-up keeps context; re-weighting changes the ranking; as-of date is stated; backend outage invents no numbers; injection attempt; off-topic request; correct wording of "no reported delay" for live status.
- `make eval` prints per-category and overall pass rate, average and p95 latency. It is the only code that calls the live model besides the app.

## Documentation

`DESIGN.md` (scoring methodology, tradeoffs, where AI is used, flow of one turn), `DECISIONS.md` (what, why, alternatives, tradeoff), `EVALS.md` (method, rubric, real results, known failures), `PRODUCTION.md` (documented, not built), `DATA_SPIKE.md` (source checks), `PRESENTATION.md` (5-minute talk track and likely questions). Docs are written from what was actually built.

## Working agreements

- Work in stages; after each stage run tests and lint, summarize, update `docs/DECISIONS.md`, and **stop for review** where I ask.
- Commit at the end of a stage with a clear message. Do not push.
- Do not spend live-model tokens or download large files without asking. Say clearly what is not verified.
- Build order: (1) strip old domain and rewrite instructions [done], (2) data layer: schema, ingest, snapshot, repository [done], (3) scoring and tools [done], (4) prompt, API and UI, (5) evals, (6) docs and presentation.
- At the docs stage every document with a "Stale" banner is rewritten or deleted. `docs/SWAP_GUIDE.md` is deleted.
- The learning guides and this file are marked `export-ignore` in `.gitattributes`, so `git archive` leaves them out of the submission.
