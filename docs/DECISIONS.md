# Decision log

## No agent framework
- **Chosen:** Hand-written agent loop on top of the thin Anthropic SDK.
- **Why:** The loop is the core of the product. Owning it means I can explain every line, put timeouts, retries and guardrails exactly where I want them, and test it with a scripted fake LLM.
- **Alternatives considered:** LangChain, LlamaIndex, CrewAI. They hide the loop behind abstractions and add dependency churn.
- **Tradeoff / when I'd change it:** I re-implement small things (retry, tool dispatch). If a client already standardised on a framework, I'd adapt to it, but keep `core/` behind the same ports.

## Ports and adapters (`core/interfaces.py`)
- **Chosen:** `core/` depends only on `Protocol` interfaces (`LLMProvider`, `SessionStore`, `DataRepository`, `KnowledgeIndex`). Adapters live in `adapters/` and are wired in `app/container.py`.
- **Why:** Core never imports the Anthropic SDK, FastAPI or file I/O, so the loop is tested without network and any backend can be swapped without touching core.
- **Alternatives considered:** Calling the SDK directly from the agent (less code, but untestable offline and tied to one vendor).
- **Tradeoff / when I'd change it:** A bit more indirection. `DataRepository` in core is deliberately tiny (just `verify_identity`); the domain-specific queries live in `AccountRepository` in `domain/tools.py`, so a new domain doesn't touch `core/`.

## Async end to end
- **Chosen:** `async`/`await` from the HTTP endpoint through the agent to the LLM, the tools and the database (`AsyncAnthropic`, `asyncpg`). Independent tool calls from one model turn run with `asyncio.gather`.
- **Why:** LLM and tool calls are I/O-bound and slow; async lets one process serve many conversations, and parallel tool calls cut turn latency (a test asserts this). For a voice agent, every saved 100 ms is audible.
- **Alternatives considered:** Sync code with a thread pool.
- **Tradeoff / when I'd change it:** Async is slightly harder to debug; blocking calls in the event loop must be avoided (the CLI reads input via `asyncio.to_thread`). Parallel calls that depend on each other are not possible: the model can call `verify_identity` and `get_portfolio` in the same turn, and the portfolio call is then blocked by the identity gate (safe; the model retries on the next iteration).

## Reliability lives in the agent, not the SDK
- **Chosen:** The adapter sets `max_retries=0` and wraps SDK errors in `LLMError`. The agent applies `asyncio.timeout` per attempt, one retry with exponential backoff, then returns a fallback reply. Tools get the same timeout-and-one-retry treatment in the registry.
- **Why:** One place owns timeout and retry policy, so total latency is predictable (important for voice) and behaviour is identical for any provider.
- **Alternatives considered:** SDK built-in retries (hidden, stacks with ours).
- **Tradeoff / when I'd change it:** Retries every `LLMError`, including non-retryable ones like a bad API key. Production should distinguish 4xx from 5xx/429.

## Model choice: `claude-sonnet-5-5` (configurable)
- **Chosen:** Sonnet-class model by default, set via `MODEL` in `.env`.
- **Why:** Good tool-calling accuracy at moderate latency and cost, a sensible default for a customer-service agent.
- **Alternatives considered:** Haiku (faster/cheaper, may be weaker on multi-step tool use and policy-following); a larger model (better reasoning, slower and pricier).
- **Tradeoff / when I'd change it:** Decide with eval results. If Haiku passes the same cases, switch for latency and cost; for voice, consider a small model for routing and a larger one only where needed. No comparison has been run yet.

## In-memory sessions behind `SessionStore`
- **Chosen:** A per-process dict implementing `SessionStore`.
- **Why:** Simplest thing that works for demos and tests, while the interface keeps the API stateless in design.
- **Alternatives considered:** Redis from day one (more moving parts for the home assignment).
- **Tradeoff / when I'd change it:** Sessions are lost on restart and not shared between replicas. For more than one replica, swap in Redis with a TTL, with no change to `core/`. Two concurrent requests on the same session are not serialised (needs a per-session lock in Redis).

## Provider-neutral messages with tool blocks
- **Chosen:** `Message` carries `tool_calls` (assistant) and `tool_results` (user); only `adapters/anthropic_llm.py` knows the Anthropic block format.
- **Why:** The loop and sessions stay provider-independent and the fake LLM can script tool calls.
- **Alternatives considered:** Storing raw Anthropic content blocks in the session (simpler adapter, but leaks the SDK into core and session storage).
- **Tradeoff / when I'd change it:** A small conversion layer to maintain. Adding another provider means one new adapter.

## Postgres behind a repository, with mock data (and what a real deployment looks like)
- **Chosen:** PostgreSQL via an `asyncpg` pool; schema in `domain/data/schema.sql`, seed in `domain/data/seed.json`, idempotent seed on startup (`CREATE ... IF NOT EXISTS`, `INSERT ... ON CONFLICT DO NOTHING`, plus an advisory lock so replicas booting together don't race). Indexes on `transactions(customer_id, booked_on)` and `withdrawal_requests(customer_id)`; all queries parameterised. `FakeRepository` loads the same seed for tests and evals.
- **Why:** Customer/account/transaction data is relational, and this mirrors a real enterprise backend including a real network hop whose latency I can reason about. Amounts are stored as `NUMERIC`, not floats.
- **Alternatives considered:** SQLite (no network hop, hides pool/latency issues), JSON files (no constraints, no idempotency via a unique key), NoSQL (no benefit for this shape).
- **Tradeoff / when I'd change it:** In a real deployment the agent usually does **not** own the database: it calls the client's APIs. `AccountRepository` is exactly where those REST/SOAP clients would go, and caching/prefetching would matter more than query tuning. Mock data is 10 customers with distinctive balances so eval assertions (and cross-customer leaks) are easy to detect. Amounts are converted to float on output for JSON: fine for display, not for arithmetic.

## BM25 over local documents, not embeddings
- **Chosen:** `rank_bm25` over six short markdown files, one document per file, exposed as the `search_knowledge` tool.
- **Why:** The corpus is tiny and keyword-heavy (fees, rules); BM25 is deterministic, needs no embedding model or index service, adds no latency, and I can explain why a document ranked first.
- **Alternatives considered:** Embeddings plus a vector DB (better for paraphrases and large corpora, but more infrastructure and harder to inspect); stuffing all docs in the prompt (works at this size, but costs tokens every turn and doesn't scale).
- **Tradeoff / when I'd change it:** BM25 misses synonyms ("charge" vs "fee") and has no chunking. When knowledge grows past a few dozen documents, add chunking and hybrid BM25 + embeddings.

## Identity enforced in code
- **Chosen:** Tools declare `requires_verification`; the registry refuses to run them unless the session is verified, whatever the model says. Tool inputs never contain a customer ID: handlers read it from the session (`ctx.customer_id`). A verified session cannot switch to another customer. Two failed verifications escalate and lock the session.
- **Why:** A prompt can be talked around (injection, "I'm the admin"); a code gate cannot. Because tools don't accept a customer ID, cross-customer access is impossible even if the model is fully compromised.
- **Alternatives considered:** Prompt-only instruction (cheapest, weakest); passing the customer ID as a tool argument and validating it (more ways to get it wrong).
- **Tradeoff / when I'd change it:** Customer ID + last 4 phone digits is a weak factor with a 10,000-value search space, and the failure counter is per session, so someone could start new sessions. A real system would use the client's authentication (OTP, app login) and rate-limit per customer across sessions.

## Confirmation and idempotency for writes
- **Chosen:** A write tool's first call only records a `PendingAction` (with a server-generated idempotency key) and returns `confirmation_required`. It executes only when called again with identical arguments on a **later user turn**. The key lives in the pending action (the model never sees or controls it) and is a UNIQUE column in Postgres, so a retry returns the original row.
- **Why:** The code guarantees a human turn happened between proposal and execution, and that a retry or a timeout-then-retry cannot create a duplicate request.
- **Alternatives considered:** Prompt-only confirmation (the model can skip it); a separate `confirm` tool or a UI button (stronger, but needs a UI).
- **Tradeoff / when I'd change it:** Code cannot verify that the user's next message actually says "yes", only that a turn passed; the prompt requires a clear confirmation and an eval checks the flow. For real money I'd confirm out of band (button or OTP). If the LLM fails after a write executed, that turn's history is dropped, so the user may be asked again and a new proposal gets a new key, so a duplicate is possible in that rare case (see PRODUCTION.md).

## What is enforced in code vs. in the prompt
| Rule | Prompt | Code |
|---|---|---|
| Verify before personal data | asked to | `requires_verification` gate in the registry |
| Only own data | told | tools get the customer from the session |
| Confirm before write | told | pending action + later-turn check + idempotency key |
| No investment advice | told, with the reason | regex backstop on the reply (coarse) |
| Escalate when asked / out of scope | told | `escalate_to_human` sets a handoff; afterwards the agent stops calling the LLM |
| Escalate after 2 failed verifications | not needed | code, limit from `domain/config.yaml` |
| No invented data | told | tool errors are explicit; groundedness is measured in evals |
| Stay on topic | told | not enforced (eval only) |

Both exist because the prompt handles fuzzy judgment (is this advice? is this out of scope?) and code handles what must never fail. The advice regex is deliberately coarse: it catches "you should buy X" style leaks but not subtle advice; the evals measure the rest.

## Dev-only LLM record/replay cache (not a production feature)
- **Chosen:** `CachingLLMProvider` (`adapters/llm_cache.py`) wraps the real LLM when `LLM_CACHE=1`. Key = hash of model + system prompt + full messages + tool schemas; entries live in `.llm_cache/` (gitignored, dockerignored). Wired only in `app/container.py`; off by default; the eval runner never uses it and warns if the flag is set. Hits and misses are logged as `llm_cache_hit` / `llm_cache_miss` (same correlation ID as the turn log); replayed responses report 0 tokens.
- **Why:** Repeating the same message while debugging should not cost money.
- **Alternatives considered:** Caching whole answers in production (rejected: replies depend on live customer data and session state, so stale or cross-customer replay is a real risk); a semantic cache (only safe for generic FAQ text).
- **Tradeoff / when I'd change it:** A replay hides real model variance and real latency, so never trust timings or eval results from it. Delete `.llm_cache/` to force fresh calls. Production cost control is prompt caching instead (next entry).

## Prompt caching in the Anthropic adapter
- **Chosen:** Top-level `cache_control: {"type": "ephemeral"}` on every request, so the API caches the stable prefix (tool schemas, system prompt, earlier conversation). Usage is logged per call as `llm_usage` (`uncached_input_tokens`, `cache_write_tokens`, `cache_read_tokens`).
- **Why:** Roughly 2k input tokens per call are identical across calls (tools + system prompt) and each tool-loop iteration resends the growing history; cache reads cost a fraction of normal input and speed up the first token. Default 5-minute lifetime fits chat traffic.
- **Alternatives considered:** Manual breakpoints on the system block (more control, more code); the 1-hour TTL (costs more to write, only worth it with sparse traffic).
- **Tradeoff / when I'd change it:** Any change to the tool list or system prompt invalidates the cache (expected). A prefix below the model's minimum cacheable size silently isn't cached; check `cache_read_tokens` in the logs, not just that the flag is set.

## Logging: two formats, caller location, tracebacks, per-tool events
- **Chosen:** `LOG_FORMAT=json|console` (default json). Every line carries file, line and function of the caller (`stacklevel=2` in `log_event`), a correlation ID (per request) and a session ID (set by the agent), both in context variables so no function has to pass them around. Each tool call logs a `tool_call` event (name, ms, is_error, error code). Every place that catches an exception and turns it into an error result or a fallback logs it with `exc_info=True` (`tool_exception`, `tool_retry`, `llm_retry`, `llm_failed`), so the stack trace is in the logs even though the model and the user only see a generic message.
- **Why:** JSON is what log pipelines need; a one-line console format is what I need while stepping through behaviour. Converting errors into results is right for the loop but would otherwise hide the real cause. Context variables keep IDs attached across `await`s and are isolated per request/task.
- **Alternatives considered:** A logging library such as structlog (nicer API, one more dependency to explain); passing IDs as arguments (noisy).
- **Tradeoff / when I'd change it:** Message text is never logged (PII), so debugging content needs the transcript store or a debugger. Business errors like `insufficient_balance` are logged as normal `tool_call` events, not tracebacks. In production this is replaced by OpenTelemetry traces (see PRODUCTION.md).

## Eval approach
- **Chosen:** 20 cases in `domain/eval_cases.yaml` across 10 categories. Deterministic checks first (tools called/not called, regexes, escalation flag, side effects on the backend), plus one LLM-judge groundedness check on cases that state data. The runner uses the live model with the in-memory repository, so it needs only an API key.
- **Why:** Most requirements are checkable without a judge, which keeps results reproducible. Groundedness is the one thing regexes cannot check.
- **Alternatives considered:** Judging every answer with an LLM (noisy and costly); human review only (doesn't gate releases).
- **Tradeoff / when I'd change it:** Regex checks on free text are brittle to phrasing. The judge is the same model, which biases it toward leniency; in production use a different model for the judge. Evals use the fake repository, so database behaviour is covered by the Postgres integration tests instead.

## Tool failures and retries
- **Chosen:** Handlers raising `ToolExecutionError` return an error with a code (no retry). Any other exception or timeout is retried once, then returned as `internal_error` with no details, so internals aren't leaked and the model is told not to guess.
- **Why:** The loop never crashes and the model can't fabricate data from an exception message.
- **Alternatives considered:** Surfacing the exception text to the model (useful for debugging, leaks internals).
- **Tradeoff / when I'd change it:** Retrying every unexpected exception also retries programming bugs. Production should retry only known transient errors.

## Session state saved on LLM failure
- **Chosen:** If the LLM fails mid-turn, state changes (verification, pending action, escalation) are saved but the half-finished messages are dropped.
- **Why:** A tool call without its result is an invalid history for the provider, while losing a verification would make the user start over.
- **Tradeoff / when I'd change it:** See the duplicate-write edge case above.
