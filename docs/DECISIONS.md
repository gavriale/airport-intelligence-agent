# Decision log

Decisions for the airport assignment. Entries marked **planned** are decided but not built yet. The earlier placeholder version (git tag `placeholder-domain`) had its own log; only the entries that still apply were kept.

## No agent framework
- **Chosen:** Hand-written agent loop on top of the thin Anthropic SDK.
- **Why:** The loop is the core of the product. Owning it means I can explain every line, place timeouts and logging exactly where I want them, and test it with a scripted fake model.
- **Alternatives considered:** LangChain, LlamaIndex, CrewAI. They hide the loop behind abstractions and add dependency churn.
- **Tradeoff / when I'd change it:** I re-implement small things (retries, tool dispatch). In a team that already uses a framework I would adapt to it and keep the same boundaries.

## Ports and adapters
- **Chosen:** `core/` depends only on interfaces (`LLMProvider`, `SessionStore`). The airport data interface (`AirportRepository`) lives in `domain/repository.py`. Concrete classes live in `adapters/` and are wired in `app/container.py`.
- **Why:** The loop is tested without network, and a backend can be swapped without touching the engine. Core knows nothing about airports.
- **Alternatives considered:** Calling the SDK or the database directly from the agent (less code, untestable offline).
- **Tradeoff / when I'd change it:** A little indirection. With a real client I would add an adapter that calls their APIs behind the same interface.

## Async end to end
- **Chosen:** `async`/`await` from the HTTP endpoint through the agent to the model, the tools and the database (`AsyncAnthropic`, `asyncpg`). Independent tool calls in one model turn run with `asyncio.gather`.
- **Why:** Model and tool calls are I/O-bound. One process can serve many conversations, and a comparison such as "LAX vs SNA" can fetch both airports at once. A test proves two 150 ms tools take about 150 ms.
- **Alternatives considered:** Sync code with a thread pool.
- **Tradeoff / when I'd change it:** Harder to debug; blocking calls must stay out of the event loop.

## Reliability lives in the agent, not the SDK
- **Chosen:** The adapter turns SDK errors into `LLMError` and disables the SDK's own retries. The agent applies a timeout per attempt, one retry with backoff, then a fallback reply. The tool registry applies a timeout and one retry to unexpected errors and returns every failure as a structured error result. A failed turn is not saved.
- **Why:** One place owns the timeout and retry policy, so total latency is predictable. Tools are read-only, so a retry is always safe.
- **Alternatives considered:** SDK built-in retries (hidden, they stack with ours).
- **Tradeoff / when I'd change it:** Every `LLMError` is retried, including permanent ones such as a bad API key. Production should retry only transient errors (5xx, 429, timeouts).

## Model choice: `claude-sonnet-5-5`, configurable
- **Chosen:** A mid-size model by default, set with `MODEL` in `.env`.
- **Why:** Reliable tool calling and instruction following at moderate latency and cost.
- **Alternatives considered:** A smaller model (faster, cheaper, may be weaker at multi-step tool use); a larger model (stronger, slower, costlier).
- **Tradeoff / when I'd change it:** The final choice should come from the eval results, including whether a smaller model passes the same cases. That comparison has not been run.

## In-memory sessions behind `SessionStore`
- **Chosen:** A per-process dictionary implementing `SessionStore`. A session holds only the message history.
- **Why:** The simplest thing that works, with the API stateless by design.
- **Alternatives considered:** Redis from day one (more moving parts for a one-day assignment).
- **Tradeoff / when I'd change it:** Sessions are lost on restart and are not shared between replicas. With more than one replica I would use Redis with an expiry and a per-session lock; nothing in `core/` would change.

## Provider-neutral messages with tool blocks
- **Chosen:** `Message` carries `tool_calls` and `tool_results`; only `adapters/anthropic_llm.py` knows the provider's block format.
- **Why:** The loop and the sessions stay provider-independent, and the fake model can script tool calls.
- **Tradeoff / when I'd change it:** A small conversion layer to maintain.

## Numbers come from code, words from the model (planned for the scoring stage)
- **Chosen:** Every figure the agent shows comes from a tool result computed by deterministic code (`domain/scoring.py`). The model chooses tools and explains; it does not calculate, rank or recall data. The system prompt says so, and evals check that answers are supported by tool output.
- **Why:** The assignment requires deterministic ranking logic, and an analyst must be able to reproduce any number. It also removes the largest hallucination risk.
- **Alternatives considered:** Letting the model rank from raw tables (not reproducible, error-prone).
- **Tradeoff / when I'd change it:** The model can still misquote a tool result, so groundedness is evaluated rather than assumed.

## Data sources
- **Chosen:** BTS T-100 summary by origin airport (Socrata, monthly, no key), OurAirports (airports and runways), and the FAA NAS status feed (live delays, planned tool). Details and the checks behind this are in `docs/DATA_SPIKE.md`.
- **Why:** They are public, need no key, and cover traffic, seats, load factor and airport facts, which is what the expansion question needs.
- **Alternatives considered and rejected:** OpenSky (anonymous access is the last six hours only and destinations are 5% filled); BTS On-Time files (bulk downloads, domestic passenger carriers only); the ArcGIS T-100 table (one row per airport per year, no routes).
- **Tradeoff / when I'd change it:** The data is monthly and about six months old, has no terminal capacity, no delay history, no routes and no carrier-by-airport data. The agent must say so; these limits are part of the design, not hidden.

## Committed snapshot loaded into Postgres at startup
- **Chosen:** `make ingest` builds CSV files in `domain/data/` from the public sources. At startup the API creates the schema and replaces the tables from those files in one transaction, skipping the load when the files' hash is unchanged. Traffic is kept for peer airports only; airports and runways cover every US airport with an IATA code. The committed files are about 1.5 MB.
- **Why:** No external API is on the request path, so answers are fast and do not fail when a source is slow or down. Startup works offline, and the data is versioned with the code, so every number is reproducible from the repository.
- **Alternatives considered:** Calling the APIs live from each tool (always fresh, slow and fragile; the BTS server cut off a large response during development); loading only on first run (cannot pick up a refreshed snapshot).
- **Tradeoff / when I'd change it:** The snapshot ages until someone runs `make ingest`. In production I would schedule the refresh and show the as-of month in every answer, which the agent already does.

## Peer airports: at least 100,000 passengers in the last 12 months
- **Chosen:** 228 airports qualify (April 2026 data). Only they have traffic rows and only they enter the percentile ranking.
- **Why:** Tiny airports have noisy growth rates (a few hundred passengers can double) and would distort percentiles. A fixed threshold is easy to explain and the value is stored in the snapshot.
- **Alternatives considered:** No threshold (noise); top N airports (the cutoff moves with the data).
- **Tradeoff / when I'd change it:** An airport just below the line cannot be analysed. The agent says "not in the peer set" instead of guessing.

## Matching BTS and OurAirports codes
- **Chosen:** Airports are joined on IATA code. For a BTS code that OurAirports no longer uses (PBI is now DJT there), the ingest matches by ICAO code (K + code) and keeps the BTS code. Territories (BQN, GUM, SJU, SPN, STT, STX) are dropped because OurAirports does not list them as US airports.
- **Why:** The dropped code was a real data-quality problem found during ingest: West Palm Beach would otherwise have silently disappeared. Users and BTS both say PBI.
- **Tradeoff / when I'd change it:** A general crosswalk would be cleaner. This handles the one case that exists and reports any other mismatch in `snapshot_meta.json`.

## All-cargo flights are in the data, and each metric says how it treats them
- **Chosen:** Keep cargo flights in the snapshot and document the effect per metric (table in `docs/DATA_SPIKE.md`). Passenger, seat and load-factor metrics are unaffected. Departure counts include cargo, which is right for runway pressure. Average flight distance and the international share describe all departures.
- **Why:** The source mixes cargo and passenger flights and cannot separate them per flight. ANC shows it clearly: its international departures average about 4 seats each.
- **Alternatives considered:** Removing cargo (not possible without flight-level data).
- **Tradeoff / when I'd change it:** Cargo-heavy airports (ANC, MEM, SDF) look different on distance and departure metrics. The agent states this when it matters.

## Long-haul share is not computed; two proxies are reported
- **Chosen:** The exact share of long-haul flights is not computable from public API data because route-level distances are not available. The agent reports the international share of departures and the average stage length as proxies, and says the international share is an approximation: it overcounts short international flights (Canada) and undercounts long domestic ones.
- **Why:** A confident number would be invented precision. The assignment asks for clearly stated assumptions and uncertainty.
- **Alternatives considered:** The BTS On-Time files (domestic passenger carriers only, bulk download, and ANC's long-haul traffic is mostly international cargo).
- **Tradeoff / when I'd change it:** With a route-level source (the full T-100 segment files or a paid feed) I would compute the share directly.

## "Congestion" means utilization, not delay
- **Chosen:** Congestion is measured as passengers and departures per runway, load factor and peak-month ratio, plus a live FAA snapshot of current delay programs. There is no delay history.
- **Why:** Delay data is not available through the public APIs used here. Calling utilization "congestion" is a common proxy, but it must be labelled as one.
- **Tradeoff / when I'd change it:** With BTS on-time data or a flight-tracking feed I would add measured delay minutes.

## Logging: two formats, caller location, tracebacks, per-tool events
- **Chosen:** `LOG_FORMAT=json|console`. Every line carries file, line and function of the caller, a correlation id and a session id (context variables). Each tool call logs a `tool_call` event. Places that turn an exception into an error result or a fallback also log it with the traceback. Message text is never logged.
- **Why:** JSON for log systems, a readable line for local debugging. Converting errors into results is right for the loop but would otherwise hide the cause.
- **Tradeoff / when I'd change it:** Debugging message content needs a debugger or a controlled transcript store. In production this becomes OpenTelemetry traces (see `docs/PRODUCTION.md` when rewritten).

## Development cache and prompt caching
- **Chosen:** `LLM_CACHE=1` replays identical model calls from `.llm_cache/` (development only, off by default, never used by evals). Separately, the Anthropic adapter asks for prompt caching on every request; measured on real calls, a repeated 1,959-token prefix was served from cache on the second call.
- **Why:** The first stops me paying again for the same debugging message. The second cuts cost and time for the part of the prompt that does not change (tool definitions and system prompt).
- **Tradeoff / when I'd change it:** A replay hides real latency and variance, so timings and eval results from a replay mean nothing. The cache key includes the whole conversation, so a repeated message in a longer conversation is a new call.

## Removed from the placeholder skeleton
- **Chosen:** Identity verification, write actions with confirmation and idempotency, escalation and handoff, the advice guardrail, and the BM25 index were removed.
- **Why:** The assignment is read-only analysis for analysts, with no customers, no writes and no regulated advice. Unused safety machinery would be dead code I would have to explain. The generic parts (loop, registry, sessions, logging) stayed.
- **Tradeoff / when I'd change it:** If the agent later triggered actions, the confirmation and idempotency design in the `placeholder-domain` tag is the starting point.

## Eval approach (planned for the evals stage)
- **Chosen:** About 16 cases plus unit tests of the scoring math. Deterministic checks first (tool called or not, required text, caveats present); one groundedness judge with a fixed rubric. The runner and the judge exist; the airport cases are not written yet and no live run has happened.
- **Why:** Most requirements can be checked without a model judge, which keeps results reproducible.
- **Tradeoff / when I'd change it:** Regex checks on free text are brittle, and a judge from the same model is likely lenient. Results will be reported with these limits, and each case should be run more than once.
