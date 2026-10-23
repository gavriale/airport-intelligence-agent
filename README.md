# Customer-service agent skeleton

A small tool-calling agent for a regulated customer-service domain, with the agent loop written by hand (no agent framework). The placeholder domain is a fictional Israeli investment house, "Example Investments". Everything domain-specific lives in `domain/`; `core/` is generic.

It verifies identity in code before showing personal data, answers account questions through read tools, opens a withdrawal request only after explicit confirmation (with an idempotency key), answers general questions from a BM25 knowledge base, refuses personalised investment advice, and escalates to a human with a structured handoff.

## Run it

```bash
cp .env.example .env        # then put your ANTHROPIC_API_KEY in .env
docker compose up --build   # Postgres + API; seeds on startup (safe to restart)
```

Port 5432 already taken on your machine? `POSTGRES_PORT=5433 docker compose up --build`.

```bash
open http://localhost:8000   # chat UI
curl localhost:8000/health
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message": "Hi, I am C001, last 4 digits 4412. What is my balance?"}'
# reuse the returned session_id in the next request to continue the conversation
```

Without Docker (in-memory seed data), using the project virtualenv:

```bash
pip install -e ".[dev]"
DATA_BACKEND=fake python cli.py     # interactive demo
make test                            # unit + API tests (Postgres tests skip if it isn't running)
make eval                            # live-model evals, needs the API key
make lint
```

Save money while debugging: set `LLM_CACHE=1` in `.env` to replay identical LLM calls from `.llm_cache/` (dev only; look for `llm_cache_hit` / `llm_cache_miss` in the logs; delete the folder to start fresh; evals ignore it).

Postgres integration tests: `docker compose up -d postgres`, then `make test` (set `DATABASE_URL` if you changed the port).

## Sample conversation

```
you>   What's my balance?
agent> I can help with that. First I need to verify you: please send your customer ID and the last 4 digits of your phone number.
you>   C001, 4412
agent> Thanks, you're verified. Your total balance is 125,400 NIS: 45,400 in the Money Market Fund and 80,000 in the Tel Aviv 35 Index Fund.
you>   Withdraw 5,000
agent> To confirm: withdraw 5,000 NIS from your account. Shall I go ahead?
you>   Yes
agent> Done: withdrawal request W-2000 for 5,000 NIS is pending.
```
This is an illustration of the intended behaviour, not a captured transcript: the live model has not been run in the environment this was built in.

## Status

| Area | State |
|---|---|
| Unit and API tests (fake LLM) | 58 passing, including Postgres integration tests against a real container |
| `docker compose up` | Verified from a clean state and on restart (seed is idempotent); `/health` checked |
| Live-model evals (20 cases) | **Not run yet** (no API key available while building). See `docs/EVALS.md` |
| `/chat` against the real Anthropic API | Not exercised yet, for the same reason |

## Docs
- [DESIGN](docs/DESIGN.md): problem, architecture, one turn
- [DECISIONS](docs/DECISIONS.md): what/why/alternatives/tradeoffs, including what is enforced in code vs. the prompt
- [EVALS](docs/EVALS.md): methodology, rubric, results (pending), known limits
- [PRODUCTION](docs/PRODUCTION.md): integration, deployment, latency, scaling, security (documented, not built)
- [SWAP_GUIDE](docs/SWAP_GUIDE.md): which files change for a new domain
