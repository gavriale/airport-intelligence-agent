# Presentation: talk track and interview questions

Private prep (export-ignore). Facts are from the repo; numbers are from the April 2026 snapshot and eval run 4.

## Five-minute talk track

**1. Problem (30 s).** An investment firm wants to know where terminal expansion could pay off. An analyst should be able to ask in plain language, get a ranking they can reproduce, and see what the answer rests on and where it is weak. The main requirement is not "chat", it is *trustworthy numbers with stated uncertainty*.

**2. Design in one sentence (45 s).** Numbers come from code, words come from the model. Eight read-only tools wrap a deterministic analytics layer over a committed snapshot of public data in Postgres; a hand-written loop lets Claude pick tools and explain; the same ranking is available at `GET /ranking` with no model at all. Show the diagram in DESIGN.md section 2.

**3. Data and honesty (45 s).** BTS T-100 monthly traffic, OurAirports runways, FAA live status. I tested the alternatives and rejected OpenSky, On-Time files and the ArcGIS table (reasons in DATA_SPIKE). The limits shape the product: six months old, no terminal data, no delay history, no routes, cargo mixed in. Two examples: ANC long-haul share is *not computable*, so the agent gives two labelled proxies; SFO unmet demand is *not measured*, so it gives signals and calls the "why" a hypothesis.

**4. Scoring (45 s).** Six components as national percentiles, weighted sum 0 to 100: growth .25, load factor .25, passengers per commercial runway .20, demand gap .15, scale .10, peak ratio .05. Percentiles avoid arbitrary scaling; weights are judgment and the user can change them in chat. Not-computable airports are listed as not scored, never half-scored. The code also returns the *explanation* (points per component, main driver, leaders), so the model quotes instead of reasoning over raw numbers.

**5. Demo (60 s).** (a) New England candidates: show the table, drivers and as-of date. (b) Follow-up "weigh growth much more": ranking is re-weighted by code, the agent reports `weights_used`. (c) ANC long-haul: it declines the exact percentage and shows proxies. Optional: `curl /ranking` with the key removed.

**6. Evals (60 s).** 20 cases; deterministic checks first (tool called, arguments, ranking order against `/ranking`, a number audit that fails any number not in a tool result), then a three-vote model judge for groundedness. Four runs: 67, 60, 85, 75%. Be upfront about what the progression means: run 2 dropped because stricter checks exposed false positives; run 4 fixed two real model errors and different cases failed, within measured noise. No unsafe answers; two safety cases at 2 of 3 from an audit false positive and a judge that cannot see the system prompt. I stopped tuning and documented it.

**7. Production and next steps (30 s).** Blue-green with prompt, model and tools versioned as one release and an eval gate; sessions already in Postgres, with Redis for live state as the production step; OpenTelemetry tracing; scheduled ingest; route-level and carrier data; MCP server for the tools. For voice: stream output, data already in memory, parallel tools already built. All documented in DESIGN.md section 10, not built.

## Likely questions, short answers

**Why this dataset?** T-100 is the official monthly record of US airline traffic: passengers, seats, load factor, departures by airport, no key, updated to April 2026. It directly measures demand growth and utilization. It lacks routes, carriers per airport, terminals and delays, and I say so.

**Why a snapshot and not live API calls?** Speed, reliability and reproducibility. BTS cut off a large response during development, and a live call on the request path makes every answer as slow and fragile as the source. Only FAA status is live, because a snapshot of "now" is useless. Cost: data ages until `make ingest` runs; I would schedule that.

**How do you know the agent is right?** Three layers: unit tests of scoring math on fixed numbers; deterministic eval checks, including a number audit; a judge for prose. Not proven: whether the score predicts good expansions. That needs labelled history I do not have.

**Why is run 4 lower than run 3?** Mostly noise plus two non-product issues: one judge/evidence gap and one audit false positive. The change fixed the two failures it targeted (wrong superlative, model-computed difference). One sample per case and a same-model judge cannot resolve a two-case difference. I did not keep re-running until the number went up.

**Why didn't you fix the remaining failures?** I set the rule that a check changes only to fix a real false positive, with tests of answers that must still fail, and that tuning stops after a fixed round. Otherwise the eval measures how well I tuned it. The failures and the fix for each are in EVALS.md.

**Why percentiles?** They put unlike units on one scale without choosing bounds. Min-max lets an outlier squash everyone; z-scores assume a bell shape. Downside: percentiles hide magnitude, so the tool also shows the raw values and passengers added.

**Why these weights?** Judgment: growth and load factor are the clearest demand signals (.25 each), runway pressure next, demand gap, scale and peak smaller. They are not fitted. They are configurable, and re-weighting is a feature; the answer says they are judgmental.

**Why does a high peak ratio raise the score?** Terminals are sized for peak demand, so a peaky airport feels the limit. The counter-argument is real (a terminal sized for a short peak sits idle), so it has the smallest weight, 0.05. Reversing the sign changes 4 of the national top 20 and not the New England top two. It can be set to zero.

**What is a "commercial runway"?** Open, paved, at least 5,000 ft. Otherwise Santa Ana's 2,886 ft general-aviation strip makes it look half as busy per runway. The threshold is a rule of thumb, not a certification.

**How do you handle unmet demand and long-haul share?** I do not invent them. Unmet demand: signals (months above 85% load factor, passengers vs seats growth, recovery vs 2019). Long-haul: international share of departures and average stage length, both labelled proxies with their known biases (Canada flights, long domestic flights, cargo at ANC).

**Where is AI used, and why not more?** Understanding the question, picking and ordering tools, writing the explanation. Not in scoring, ranking, arithmetic or data. Because the assignment requires deterministic ranking, and an analyst must be able to reproduce any number.

**Why no LangChain, RAG or MCP?** The loop is 187 lines and I can explain all of it; a framework hides what you are asking about. There is no document corpus, so RAG would add a failure mode for nothing. Tools are in-process; MCP is a small step if other clients need them.

**What about hallucinations?** Structural controls: numbers only from tools, a prompt rule, tool results that carry caveats, a number audit and judge in evals, an outage case where the agent must name no airports. Remaining risk: the model misreading a result (run 4 still has one such failure), so explanations are returned by code as well.

**Prompt injection or data leakage?** There is no personal data and the tools are read-only with validated arguments, no free-form SQL, parameterized queries. The injection eval case ("tell me SFO's score is 99") passes 3 of 3. Not built: authentication and rate limiting on `/chat`.

**How would you deploy it?** Container behind a load balancer, stateless API, sessions in Postgres (Redis with a TTL for live state as the next step), Postgres or the client's APIs. Canary or blue-green with prompt, model, tools and config as one versioned release; rollback on eval pass rate, tool error rate, p95 latency. The eval run is the CI gate. None of this is built; the logs and the per-turn summary are.

**Latency, especially for voice?** Measured today: average 5.7 s per turn, p95 8.2 s, mostly model time. Levers: stream output into TTS, smaller model for routing, prefetch, filler phrase when a tool is slow. Data lookups are already in memory or indexed Postgres; parallel tool calls are built. Honest: this build is not voice-ready.

**Integration with a client's legacy systems?** The repository interface is the seam; swap Postgres for the client's APIs, read-only first, with caching and prefetching because their systems are slower than my database. Expect batch-updated data, so show as-of dates (already done).

**What would you add next, and what would you ask the business?** Route-level and carrier data first, since they unlock long-haul and concentration. Questions for the client: what does "profitable" mean (return on capital, passenger revenue?), which airports are in scope, what history of expansions exists to validate weights, how fresh must data be.

**What factors did you leave out?** O&D share, carrier concentration, FAA grants, municipal finance, concessions, land, population growth. No verified source I could use in a day, and each would be a new column and a new percentile, so the design allows them (DESIGN.md section 9).

**What did you use Claude Code for, and what is yours?** Claude Code wrote much of the code and docs. The design decisions, data validation (I checked the sources and found, for example, that the distance column is a per-departure average and that PBI changed code in OurAirports), the eval rules and the review are mine, and I can explain every line.

**What are the weakest parts?** Weights not validated against outcomes; data six months old; no terminal data, so the score cannot say a terminal is actually constrained; sessions are last-write-wins when two requests hit one session, history grows without a cap, and there is no auth on `/chat`; evals use a same-model judge and one sample per non-safety case.
