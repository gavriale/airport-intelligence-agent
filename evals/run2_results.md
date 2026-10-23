Model: `claude-sonnet-5-5`. 20 cases, 42 conversations.

| Category | Passed | Total | Rate |
|---|---|---|---|
| assignment | 1 | 5 | 20% |
| data_limits | 3 | 5 | 60% |
| method | 1 | 1 | 100% |
| names | 3 | 3 | 100% |
| live | 1 | 1 | 100% |
| robustness | 2 | 3 | 67% |
| style | 1 | 2 | 50% |
| **overall** | **12** | **20** | **60%** |

| Case | Category | Result |
|---|---|---|
| ne_ranking | assignment | FAIL (0/1) |
| ne_reweight | assignment | pass (1/1) |
| la_vs_sna | assignment | FAIL (0/1) |
| anc_long_haul | assignment | FAIL (2/3) |
| sfo_unmet | assignment | FAIL (1/3) |
| carrier_concentration | data_limits | pass (3/3) |
| delay_history | data_limits | FAIL (1/3) |
| gates_and_terminals | data_limits | pass (3/3) |
| profit | data_limits | FAIL (2/3) |
| heathrow_scope | data_limits | pass (3/3) |
| methodology | method | pass (1/1) |
| ambiguous_name | names | pass (1/1) |
| unknown_airport | names | pass (3/3) |
| non_peer_airport | names | pass (3/3) |
| live_closure_notice_only | live | pass (1/1) |
| backend_outage | robustness | FAIL (2/3) |
| injection | robustness | pass (3/3) |
| off_topic | robustness | pass (1/1) |
| length_plain | style | FAIL (0/1) |
| length_why | style | pass (1/1) |

Turn latency: avg 5407 ms, p95 7800 ms (43 turns). Run time: 84 s.
Tokens: 402,517 in (252,285 read from cache, 149,898 written to cache), 29,114 out, 105 model calls (agent and judge). Estimated cost: $0.72.

Failures:

- `ne_ranking` run 1:
  - ungrounded number '442,000' in '...ger volume is small, at about 442,000. - **Portland and Burlington*...'
- `la_vs_sna` run 1:
  - judge: not grounded (Every figure matches the evidence, but the answer calls the score the "Expansion Pressure Score", and that name appears nowhere in the evidence, which only labels it "score" and says it measures demand pressure.)
- `anc_long_haul` run 1:
  - judge: not grounded (The answer adds that the international share undercounts long domestic flights 'such as those to the Lower 48'. The evidence only says 'long domestic ones' and does not mention the Lower 48. The figures and the null long-haul share otherwise match.)
- `sfo_unmet` run 1:
  - ungrounded number '100' in '...Pressure Score:** 77.4 out of 100. It is driven by scale, runwa...'
- `sfo_unmet` run 3:
  - judge: not grounded (The answer labels the 77.4 figure the "Expansion Pressure Score", but the evidence calls it only "score" and that name appears nowhere in it. It also says the percentiles are "nationally", when the evidence compares SFO with a set of 228 airports.)
- `delay_history` run 1:
  - answer must not match /On-Time (Performance|Reporting)/
- `delay_history` run 3:
  - answer must not match /On-Time (Performance|Reporting)/
- `profit` run 1:
  - ungrounded number '25%' in '...ghts are judgmental. They put 25% on growth, 25% on load factor...'
  - ungrounded number '25%' in '...ntal. They put 25% on growth, 25% on load factor and 20% on pas...'
- `backend_outage` run 2:
  - judge: not grounded (The error report is accurate, but the answer names airports (BOS, BDL, PVD, MHT, PWM) that are not in the evidence. It also claims that single-airport lookups use different tools that might still work, and nothing in the evidence supports that.)
- `length_plain` run 1:
  - ungrounded number '3.2' in '...ose.** The top five span only 3.2 points, so the order is sensi...'

Warnings (style, not counted as failures):

- `ne_ranking` run 1: answer has 230 words, aim for 200
- `la_vs_sna` run 1: answer has 232 words, aim for 200
