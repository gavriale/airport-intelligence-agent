# Production plan

> **Stale:** this document describes the placeholder investment-house version of the project (git tag `placeholder-domain`). It is being rewritten for the airport assignment.

Everything here is **documented, not built**, unless it says "already implemented".

## Integration with the client's systems
- Replace `AccountRepository` (the interface in `domain/tools.py`) with clients for the real systems: REST/SOAP services, a database view, or an MCP server wrapping them. Tools and prompts don't change.
- **Read-only first.** Ship balance/status/knowledge, add the withdrawal write after the read path is trusted. Writes go through the client's own approval workflow; the agent only creates a request.
- Credentials: a service account per environment with least privilege (per-tool scopes), in a secrets manager. Network: private connectivity (VPN / private link / on-prem agent) to legacy systems, allow-listed egress to the LLM provider only.
- Legacy constraints to expect: slow or batch-updated systems (show "as of" timestamps), rate limits, SOAP/XML, no idempotency support (keep our own idempotency table), data in more than one system of record.
- The agent usually doesn't own the database, so caching and prefetching matter more than query tuning (see Latency).

## Deployment
- Container per release, stateless API behind a load balancer. **Version prompt + model + tools + config as one release**; the git SHA is the version, logged on every turn.
- **Blue-green or canary:** run the new version beside the old, send 1-5% of traffic (or internal users first), compare, then shift. Sessions are in Redis so a conversation survives a version switch; pin a session to one version to avoid mid-conversation prompt changes.
- **Rollback criteria** (automatic where possible): eval pass rate below the baseline in CI; online escalation rate, tool error rate or fallback rate up by a set margin; p95 latency over budget; any confirmed cross-customer data exposure (immediate).
- Config (guardrail patterns, limits) is in `domain/config.yaml`, so policy tweaks ship through the same pipeline.

## Evaluation in production
- **CI gate:** `make eval` on every prompt/model/tool change; block the release if the pass rate drops or any safety category (identity, injection, advice, write) fails.
- **Online metrics:** containment/resolution rate, escalation rate and reasons, CSAT, fallback rate, tool error rate, "hallucination flags" (LLM judge sampling live answers against tool results), advice-guardrail triggers.
- **Transcript review:** sample conversations weekly plus all escalations, fraud and low-CSAT ones, with PII masked.
- **Regression set:** every real failure becomes a case in `eval_cases.yaml`.
- Run each case several times and track flakiness; use a different model as judge.

## Latency (especially voice)
Already implemented: parallel tool calls (`asyncio.gather`), async end to end, DB indexes on lookup keys, connection pool, timeouts with a fallback reply, per-turn timing logs (LLM vs. tools).
Not built:
- **Streaming** the LLM output into TTS, starting speech at the first sentence.
- **Prefetch** the customer's data at session start (right after verification), so most questions need no tool round-trip.
- **Cache static knowledge** in memory; **read-through cache** (Redis) for hot customer data with short TTLs and invalidation on writes.
- **Smaller/faster model** for routing and simple intents; the larger model only for complex turns. Prompt caching for the system prompt and tool schemas.
- Read replicas for heavy read traffic. Against client APIs: connection reuse, regional placement, and a budget per turn (e.g. 1.5 s to first audio) that triggers a filler phrase ("let me check that") when exceeded.
- Measure first: the turn log already splits `llm_ms` and `tools_ms`; set budgets per segment.

## Scaling
- Stateless async API, horizontally scaled behind a load balancer; **Redis `SessionStore`** with a TTL and a per-session lock (today two concurrent requests on one session can interleave).
- Vector DB / hybrid search when knowledge outgrows BM25 over a handful of files.
- Queues for long-running workflows (e.g. a withdrawal that needs back-office approval, callbacks).
- Rate limiting per user/IP and per customer ID (including failed verification attempts across sessions); model fallback (secondary model or provider when the primary errors or is slow); provider quota monitoring.

## Observability
- **Already implemented:** structured logs (JSON, or readable `console` format locally) with correlation ID, session ID and file/line/function on every line; a `turn` summary (tools, latencies split LLM vs. tools, tokens, flags), a `tool_call` event per tool (name, ms, error code), `llm_usage` with cache read/write tokens, and full tracebacks for retries and failures. Message text is deliberately not logged.
- **In production I would use OpenTelemetry tracing:** one trace per conversation turn with a span per LLM call and per tool call (attributes: model, token counts, cache hits, tool name, error code), exported to an LLM observability tool so I can inspect a bad turn step by step. The correlation and session IDs here map directly to trace and span attributes.
- Not built: distributed tracing across API, LLM and each client call (OpenTelemetry), dashboards (latency percentiles, escalation reasons, tool error rate, cost per conversation), alerting on the rollback criteria, cost tracking from token counts per model.

## Security and compliance
- **PII:** minimise what goes to the LLM (only the fields a tool returns), mask in logs and transcript review, retention limits, encryption in transit and at rest. Check the provider's data-processing terms and zero-retention options.
- **Authentication:** replace "customer ID + last 4 phone digits" with the client's real auth (OTP/app login); bind session IDs to an authenticated token (today any caller who knows a session ID can continue it).
- **Least privilege:** read tools separate from write tools, scoped credentials. **Audit log** of every write action (who, what, when, idempotency key, outcome), append-only.
- **Prompt injection:** already handled structurally (no customer ID in tool inputs, identity gate in code). Also treat retrieved documents and tool output as untrusted data.
- **Data residency:** run in the region the client requires; confirm where the LLM provider processes data.
- **Licensing:** the advice refusal is both a prompt rule and an output check; legal should review the wording and the human-advisor handoff. Keep a record of what the agent said.
- **Known gaps in this build:** weak identity factor; per-session (not per-customer) lockout; regex advice backstop only; if the LLM fails after a write executed, a retry may propose a second, separately keyed request.

## Rollout
1. **Shadow / internal:** staff use it, compare answers with agents'.
2. **Pilot:** a small share of traffic, read-only intents, easy human escape hatch.
3. Compare against the human baseline (handle time, resolution, CSAT, error rate).
4. Expand by intent and traffic share; enable the write action last, with a daily cap per customer.
5. Keep a kill switch that routes everything to humans.
