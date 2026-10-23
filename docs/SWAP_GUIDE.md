# Swap guide: moving to a new domain

> **Stale:** this document describes the placeholder investment-house version of the project (git tag `placeholder-domain`). It is being rewritten for the airport assignment.

The engine (`core/`) should not change. Everything below is a file you edit or replace.

| Step | File | What to do |
|---|---|---|
| 1. Policies | `domain/config.yaml` | Agent name, `max_failed_verifications`, advice/forbidden-output regexes, refusal and escalation messages. The keys map to `core/guardrails.py: GuardrailConfig`; add a field there only if you need a genuinely new generic rule. |
| 2. Prompt | `domain/system_prompt.md` | Role, capabilities, rules. Keep the structure: what you can do, then numbered rules (never invent data, verification, confirmation, escalation, scope). |
| 3. Data model | `domain/data/schema.sql`, `domain/data/seed.json` | New tables, indexes on lookup keys, seed rows. Keep inserts `ON CONFLICT DO NOTHING`. |
| 4. Backend access | `adapters/postgres_repository.py`, `adapters/fake_repository.py`, and the `AccountRepository` protocol in `domain/tools.py` | Same method names on all three. The seed loader in the Postgres adapter maps seed keys to tables, so it changes with the schema. If the client exposes APIs instead of a database, write an HTTP adapter implementing the same protocol. |
| 5. Tools | `domain/tools.py` | One input model + one handler + one `Tool(...)` per capability. `requires_verification=False` only for tools that must work before login. Writes use `access="write"` and get confirmation and an idempotency key for free. Tools read the customer from `ctx.customer_id`, never from arguments. |
| 6. Knowledge | `domain/knowledge/*.md` | One short file per topic, first line `# Title`. Nothing else to change (BM25 loads the folder). |
| 7. Wiring | `app/container.py` | Only if you add a new repository or index; the rest is already generic. |
| 8. Evals | `domain/eval_cases.yaml` | 15-20 cases in the same categories. Use distinctive values so regexes can detect leaks. Add a pre-verified customer in `verified_as`. |
| 9. Docs | `docs/DESIGN.md`, `docs/DECISIONS.md`, `docs/EVALS.md`, README | Problem statement, new decisions, real eval results. |

## Identity
If the new domain verifies differently (OTP, account number + DOB), change `verify_identity` in `domain/tools.py` and `DataRepository.verify_identity` (the credential is one opaque string; for several factors, widen the argument model and the repository method). The gate in `core/tools.py` and the session fields stay the same.

## Things that do require touching `core/`
- A second write flow with a different confirmation rule.
- Non-text channels (voice, files): the loop is text-only.
- A different notion of "verified" than a single customer ID (e.g. a household with several accounts): `Session.verified_customer_id` would need to become a set or a principal object.

## Checklist before trusting the swap
1. `make test` passes (update `tests/` for renamed tools).
2. `make eval` runs end to end and every safety category passes.
3. `docker compose up` works from a clean checkout and twice in a row.
