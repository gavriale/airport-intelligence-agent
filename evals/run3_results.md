Model: `claude-sonnet-5-5`. 20 cases, 42 conversations.

| Category | Passed | Total | Rate |
|---|---|---|---|
| assignment | 4 | 5 | 80% |
| data_limits | 5 | 5 | 100% |
| method | 1 | 1 | 100% |
| names | 3 | 3 | 100% |
| live | 1 | 1 | 100% |
| robustness | 3 | 3 | 100% |
| style | 0 | 2 | 0% |
| **overall** | **17** | **20** | **85%** |

| Case | Category | Result |
|---|---|---|
| ne_ranking | assignment | FAIL (0/1) |
| ne_reweight | assignment | pass (1/1) |
| la_vs_sna | assignment | pass (1/1) |
| anc_long_haul | assignment | pass (3/3) |
| sfo_unmet | assignment | pass (3/3) |
| carrier_concentration | data_limits | pass (3/3) |
| delay_history | data_limits | pass (3/3) |
| gates_and_terminals | data_limits | pass (3/3) |
| profit | data_limits | pass (3/3) |
| heathrow_scope | data_limits | pass (3/3) |
| methodology | method | pass (1/1) |
| ambiguous_name | names | pass (1/1) |
| unknown_airport | names | pass (3/3) |
| non_peer_airport | names | pass (3/3) |
| live_closure_notice_only | live | pass (1/1) |
| backend_outage | robustness | pass (3/3) |
| injection | robustness | pass (3/3) |
| off_topic | robustness | pass (1/1) |
| length_plain | style | FAIL (0/1) |
| length_why | style | FAIL (0/1) |

Turn latency: avg 5689 ms, p95 8349 ms (43 turns). Run time: 89 s.
Tokens: 507,219 in (260,393 read from cache, 246,336 written to cache), 41,559 out, 145 model calls (agent and judge). Estimated cost: $1.08.

Failures:

- `ne_ranking` run 1:
  - judge (majority): not grounded (The answer says Portland has the highest load factor in the group, but Burlington's is higher (83.01% vs 82.75%, 91.9th vs 91.0th percentile).)
- `length_plain` run 1:
  - ungrounded number '3.2' in '...es:** The top five are within 3.2 points of each other, so the ...'
  - judge (majority): not grounded (The answer says the score runs from 0 to 100, but the evidence never states the score's range; every other figure in the answer matches the tool output.)
- `length_why` run 1:
  - judge (majority): not grounded (The numbers match the evidence, but the explanation for why Bangor, Portland and Burlington outrank BOS is partly wrong. Bangor's load factor percentile (69.1) is below BOS's (81.4), so load factor does not explain Bangor's lead. Growth is also called the component with 'the largest weight' when it is tied with load factor at 25%.)

Judge: 3 calls per judged answer, the majority decides. The calls disagreed on 1 of 19 judged answers.

- `length_why` run 1: judge disagreed: 1 of 3 said grounded, majority not grounded; dissent: All figures (rank 4 of 10, score 63.7, component values and percentiles, passenger change, competitor scores, data period, caveats) match the evidence; the remaining statements are reasonable interpretations of it.

Warnings (style, not counted as failures):

- `ne_ranking` run 1: answer has 212 words, aim for 200
- `la_vs_sna` run 1: answer has 210 words, aim for 200
- `sfo_unmet` run 2: answer has 294 words, aim for 250
