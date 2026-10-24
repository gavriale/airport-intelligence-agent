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
- **Error classes:** only timeouts, connection problems, rate limits (429) and 5xx are retried. A rejected key (401/403), an unknown model (404) or any other 4xx raises `LLMFatalError`: no retry, the user gets a specific message ("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env." or "Model <name> is not available for this API key. Set MODEL in .env."), and the real error is logged. A missing `ANTHROPIC_API_KEY` is treated like a blank one (`/chat` returns 503, `/ranking` still works). Checked against the real API: a bad key and an unknown model each fail in about 0.3 s with these messages.
- **Tradeoff / when I'd change it:** Only Anthropic is supported; another provider needs a new adapter that classifies its own errors the same way. Which statuses count as retryable is a judgment (408, 409, 429 and 5xx here).

## Model choice: `claude-sonnet-5-5`, configurable
- **Chosen:** A mid-size model by default, set with `MODEL` in `.env`.
- **Why:** Reliable tool calling and instruction following at moderate latency and cost.
- **Alternatives considered:** A smaller model (faster, cheaper, may be weaker at multi-step tool use); a larger model (stronger, slower, costlier).
- **Tradeoff / when I'd change it:** The final choice should come from the eval results, including whether a smaller model passes the same cases. That comparison has not been run.

## Sessions in Postgres behind `SessionStore`
- **Chosen:** `PostgresSessionStore` keeps one row per session in a `sessions` table (`session_id` primary key, `messages` JSONB, `created_at`, `updated_at`), written with an upsert and read with parameterized queries, on the same connection pool as the airport data. `Message`, `ToolCall` and `ToolResult` convert to JSON through two small functions in the adapter (`messages_to_json`, `messages_from_json`); a test checks a conversation with text, parallel tool calls and an error result comes back equal. The table lives in `schema.sql` but is not part of the airport snapshot, and the snapshot loader never truncates it (a test reloads a different snapshot and checks the session survives). `MemorySessionStore` stays for unit tests, the CLI and evals (`DATA_BACKEND=memory`). An unknown id is an empty session, saved on the first `save`. `core/` did not change.
- **Why:** With the in-memory store a restart or deploy wiped every conversation and a second replica could not see them. Postgres is already running, so this adds no service. Checked by hand: chat in one session, `docker compose restart api`, then "Check live FAA status for both airports" with the same session id: the agent still knew the airports (the stored history went from 4 to 8 messages).
- **Alternatives considered:** Redis (right for live session state, but a new service for this assignment); keeping the dictionary (loses conversations); a normalized messages table (queryable per message, more code, nothing here queries it).
- **Tradeoff / when I'd change it:** Not built, in order of importance:
  - **Production split:** Redis with a TTL for live session state, Postgres for permanent transcripts and the audit log.
  - **Concurrent requests on one session:** the last write wins (the second turn can overwrite the first). The fix is a per-session lock or a version column checked on save.
  - **History growth:** every tool result is stored in full and the whole row is rewritten each turn, so long chats grow in size, tokens and latency. Cap the last N turns or summarize older ones.
  - **Cleanup:** old sessions are never deleted. Needs a job that removes rows past an age limit (an index on `updated_at`).
  - Data survives `docker compose down` because the Postgres data directory is the named volume `pgdata` (only `down -v` deletes it, and the sessions with it).

## The chat page keeps its session id in `sessionStorage`
- **Chosen:** The page stores `session_id` in `sessionStorage` and, on load, fetches `GET /sessions/{id}/messages` to redraw the conversation. That endpoint returns only the visible turns (user messages and final answers; tool requests, tool results and text that came with a tool request stay hidden). An unknown id is an empty list. The "New conversation" button clears the stored id and the screen.
- **Why:** Without this a refresh dropped the id, so the next message started a new session and the screen was blank although the server had the history. `sessionStorage` survives a refresh but is cleared when the tab closes and is not shared between tabs, so the next person on a shared computer does not see the previous chat (`localStorage` would keep it).
- **Tradeoff / when I'd change it:** **The session id is the only secret.** Anyone who holds it can read and continue that conversation; there is no login and sessions have no owner. Ids are random UUIDs, so they cannot be guessed, but production needs real authentication and per-user ownership of sessions (the id bound to a signed-in user, and a check on every read and write). The endpoint returns the whole visible history with no paging. On the in-memory store, a GET with an unknown id registers an empty session in the dictionary (Postgres writes nothing).

## Provider-neutral messages with tool blocks
- **Chosen:** `Message` carries `tool_calls` and `tool_results`; only `adapters/anthropic_llm.py` knows the provider's block format.
- **Why:** The loop and the sessions stay provider-independent, and the fake model can script tool calls.
- **Tradeoff / when I'd change it:** A small conversion layer to maintain.

## Numbers come from code, words from the model
- **Chosen:** Every figure the agent shows comes from a tool result computed by deterministic code (`domain/scoring.py`). The model chooses tools and explains; it does not calculate, rank or recall data. The system prompt says so, and evals check that answers are supported by tool output.
- **Why:** The assignment requires deterministic ranking logic, and an analyst must be able to reproduce any number. It also removes the largest hallucination risk.
- **Alternatives considered:** Letting the model rank from raw tables (not reproducible, error-prone).
- **Tradeoff / when I'd change it:** The model can still misquote a tool result or do small arithmetic of its own (in the demo run it computed ratios such as "3.3 times"), so groundedness is evaluated rather than assumed. The fix is to return such ratios from the tool.

## Expansion Pressure Score: national percentiles, configurable weights
- **Chosen:** Six components over the last 12 months compared with the 12 before: passenger growth, load factor, passengers per runway, demand gap (passenger growth minus seat growth), scale and peak-month ratio. Each becomes a mid-rank percentile against all scored peer airports nationally. The score is the weighted sum of the percentiles (weights 0.25, 0.25, 0.20, 0.15, 0.10, 0.05 in `domain/config.yaml`). A regional ranking orders airports by the national score and does not recompute percentiles inside the region. Callers can override weights; they are rescaled to sum to 1.
- **Why:** Percentiles put unlike units on one scale without choosing arbitrary bounds. Reusing national percentiles keeps an airport's score the same whatever region it is asked in (a test checks this). Keeping percentiles separate from weights means re-weighting never recomputes anything.
- **Alternatives considered:** Min-max scaling (one outlier squeezes everyone else); z-scores (assume a bell shape); percentiles inside the region (a small region would make every airport look extreme).
- **Tradeoff / when I'd change it:** The weights are judgment, not a fitted model, and the answer says so. The score measures demand pressure, not physical terminal capacity, because no terminal or gate data exists in the public sources.

## Missing data means "not scored", never a partial score
- **Chosen:** An airport is scored only when all six components can be computed from complete data: no missing month in either window, runway data present, seats present. Otherwise it is listed under `not_scored` with the reasons. A month with zero seats leaves load factor undefined for that month; it is not counted as zero.
- **Why:** Scoring on partial data would put a number in front of an analyst that looks as solid as the others. With the current snapshot all 228 peers are scorable, so the exclusion rules are covered by unit tests on hand-made data, not by real airports.
- **Tradeoff / when I'd change it:** A seasonal airport with one missing month drops out entirely. A later version could score on the available components and flag it, but that needs a documented rule for rescaling the weights.

## Peak-month ratio counts as positive (weight 0.05)
- **Chosen:** A higher peak-month ratio (busiest month divided by the average month) raises the score. The weight is the smallest of the six, 0.05.
- **Why:** Terminals and gates are sized for peak demand, not average demand. An airport that is badly overloaded for a few months is the one that feels the capacity limit and has a case for expansion, even if the rest of the year looks fine.
- **Counter-argument:** Strong seasonality can hurt the investment case. A terminal sized for a short peak sits underused for most of the year, so revenue per square foot is lower and returns are weaker. Read that way, a high peak ratio should lower the score, or at least not raise it.
- **How much it matters (checked on the snapshot):** If the sign were reversed, the national top 20 changes in 4 airports (16 of 20 stay) and the national top five changes noticeably. In New England the top two (Bangor, Portland) stay the same, and third place moves from Burlington to Boston. So the choice is not decisive for the region, but it can matter nationally.
- **Tradeoff / when I'd change it:** The weight is low on purpose because the sign is arguable. The weights are configurable, so an analyst who disagrees can set it to zero (`{"peak": 0}`). A better version would separate short peaks from year-round pressure instead of using one ratio.

## Per-runway metrics count commercial runways only
- **Chosen:** A runway counts if it is open, paved and at least 5,000 ft long. Profiles and comparisons report both the total and the commercial count. The rule is one small function (`domain/runways.py`); the repositories compute the count from the surface and length in the snapshot.
- **Why:** Short strips and unpaved or water runways do not carry airline traffic. Counting them made airports with a small general-aviation strip look less busy per runway. Santa Ana (SNA) has two runways but one is a 2,886 ft strip, so it now counts as one commercial runway, and its passengers per runway doubled. Boston counts 5 of 6.
- **Alternatives considered:** Counting all runways (as before, penalises airports with small side strips); weighting runways by length (more precise, harder to explain).
- **Tradeoff / when I'd change it:** The 5,000 ft threshold is a simple rule of thumb, not a certification. A regional jet can use less, a wide-body needs more. Surface codes in OurAirports vary, so paved is detected by their first letters (asphalt, concrete, permanent). Changing the rule reloads the Postgres data automatically because the rule is part of the snapshot hash.

## Weight overrides are exact, and the code does the arithmetic
- **Chosen:** In `rank_airports`, a component named in `weights` gets exactly that weight (`{"growth": 0.6}` means 0.6) and the others share the rest in proportion to their default weights. The weights actually used come back in `weights_used`. Setting every weight is allowed only if they add up to 1; unknown names, negatives or a total above 1 are errors.
- **Why:** In the first demo the model rescaled the weights itself, which broke the rule that numbers come from code. This way the model passes only what the user asked for and quotes what the code reports.
- **Tradeoff / when I'd change it:** Percentiles are not recomputed, only the weighting, so the effect of a re-weighting is easy to explain.

## Passengers added shown next to growth, outside the score
- **Chosen:** Rankings, comparisons and profiles show the absolute change in passengers (last 12 months minus the 12 before) next to the growth percentage. It is display only.
- **Why:** A small airport can show a large percentage on a few thousand passengers, and a large airport a small percentage on millions. Seeing both stops an analyst from misreading either. It is not in the score because scale and growth are already scored, and adding it would count the same effect twice.

## FAA closure notices are not delay programs
- **Chosen:** `get_live_status` reports `delay_programs`, `closure_notices_only` or `no_reported_programs`.
- **Why:** The first real call to the feed returned only closure entries, including a LAX notice that restricts non-scheduled general-aviation traffic. Calling that "active programs" would suggest airline delays at LAX. The dates in these entries also leave out the year.
- **Tradeoff / when I'd change it:** The label does not decode the NOTAM text, so the reason is passed through for the reader. Decoding NOTAMs reliably is a larger job.

## Output token limit raised, and truncation is logged
- **Chosen:** The model call allows 2,048 output tokens (was 1,024), and a reply that stops because of the limit logs an `llm_truncated` warning. Every model call also logs its stop reason.
- **Why:** A long answer cut off in the middle would look like a finished one. The earlier follow-up answer used 1,003 output tokens in total across its two model calls, so it was under the old limit and was not cut off; but it was close enough to justify more room and a visible warning.

## One analytics layer behind the tools and the API
- **Chosen:** `domain/analytics.py` holds every analysis and returns plain dictionaries with `as_of`, the data window and caveats. The tools are thin wrappers that validate arguments. `GET /ranking` calls the same code with no model. The national KPI table is computed once and cached.
- **Why:** The same numbers appear whether they come from the chat or the endpoint, and a reviewer without an API key can still see the deterministic ranking. Caveat texts live in one config file instead of being scattered through code.
- **Tradeoff / when I'd change it:** The cache assumes the snapshot does not change while the process runs; a refresh needs a restart.

## In-memory repository next to Postgres
- **Chosen:** `MemoryRepository` serves the same snapshot files from memory for unit tests, the CLI and the evals without Docker. Postgres stays the default in docker compose. One contract test file runs against both and checks that they return identical data.
- **Why:** Tests and demos should not need a database, and the contract test stops the two implementations from drifting apart.

## Live status from the FAA feed
- **Chosen:** `get_live_status` reads the FAA NAS status XML through a small adapter (standard library, run in a thread). An airport that is not in the feed is reported as "no reported delay programs" with a caveat that this is not missing data. Closure entries carry a caveat that they may apply only to some aircraft.
- **Why:** The feed lists only airports with an active program, so reading "no entry" as "no data" would mislead. One real closure entry seen during the spike was a general-aviation restriction at LAX, not a delay.
- **Tradeoff / when I'd change it:** A live snapshot only, no history. A failing feed becomes a clean `live_status_unavailable` error.

## Searching by the names people use
- **Chosen:** `search_airports` matches IATA codes, a small alias list (for example "LA" gives LAX), cities and airport names, and prefers airports that have traffic data. The model is told to use a clearly main airport and say which one it used, and to ask when several are plausible.
- **Tradeoff / when I'd change it:** "LA" also returns Las Vegas and other cities that start with those letters. The alias puts LAX first, and the model chose correctly in the demo run.

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

## Postgres is published to the host (tried not publishing it, reverted)
- **Chosen:** `docker-compose.yml` publishes Postgres on the host (`${POSTGRES_PORT:-5432}`) so a database client and the Postgres tests can reach it. The API port is `${API_PORT:-8000}`.
- **History:** Before submission I removed the mapping (and added an opt-in `docker-compose.dev.yml`) because a reviewer's first `docker compose up` failed with "port is already allocated" whenever something else used 5432. After submission I reverted it: it made the usual local workflow (plain `docker compose up --build`, then connect a client) stop working.
- **Tradeoff / when I'd change it:** A reviewer whose 5432 is busy has to set `POSTGRES_PORT` (the README says so). The API does not need the published port; it reaches Postgres over the compose network. If conflicts matter more than convenience, do not publish it by default.

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
- **Tradeoff / when I'd change it:** Debugging message content needs a debugger or a controlled transcript store. In production this becomes OpenTelemetry traces (see section 10 of `DESIGN.md`).

## Development cache and prompt caching
- **Chosen:** `LLM_CACHE=1` replays identical model calls from `.llm_cache/` (development only, off by default, never used by evals). Separately, the Anthropic adapter asks for prompt caching on every request; measured on real calls, a repeated 1,959-token prefix was served from cache on the second call.
- **Why:** The first stops me paying again for the same debugging message. The second cuts cost and time for the part of the prompt that does not change (tool definitions and system prompt).
- **Tradeoff / when I'd change it:** A replay hides real latency and variance, so timings and eval results from a replay mean nothing. The cache key includes the whole conversation, so a repeated message in a longer conversation is a new call.

## Removed from the placeholder skeleton
- **Chosen:** Identity verification, write actions with confirmation and idempotency, escalation and handoff, the advice guardrail, and the BM25 index were removed.
- **Why:** The assignment is read-only analysis for analysts, with no customers, no writes and no regulated advice. Unused safety machinery would be dead code I would have to explain. The generic parts (loop, registry, sessions, logging) stayed.
- **Tradeoff / when I'd change it:** If the agent later triggered actions, the confirmation and idempotency design in the `placeholder-domain` tag is the starting point.

## Eval approach
- **Chosen:** 20 cases (11 of them safety and honesty cases that run three times and must pass every time) plus unit tests of the scoring math and of the checks themselves. Deterministic checks first: tools and arguments, required and forbidden text, the order of the New England top five against `GET /ranking`, and a hard-failing **number audit** (every number must come from a tool result). Then a model judge for groundedness, asked three times with the majority deciding and any disagreement reported. Details, the case list and the three runs are in `docs/EVALS.md`.
- **Why:** Most requirements can be checked without a judge, which keeps results reproducible, and the number audit makes "numbers come from code" testable. The judge covers what rules cannot (a false statement in prose) and did catch real errors, for example a wrong "highest load factor".
- **Rule for changing a check:** each change must fix a real false positive, and must come with tests of answers that should still fail. A check is never loosened just to pass. Three rounds of this took the pass rate from 67% to 60% (stricter checks exposed more false positives) to 85%.
- **Tradeoff / when I'd change it:** Regex checks on free text are brittle. The judge is the same model as the agent, and a single judge call was noisy (the same sentence passed in one run and failed in the next), hence three calls. A different model as judge would be better. Non-safety cases run once.
