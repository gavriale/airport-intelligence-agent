Model: `claude-sonnet-5-5`. 18 cases, 40 conversations.

| Category | Passed | Total | Rate |
|---|---|---|---|
| assignment | 2 | 5 | 40% |
| data_limits | 4 | 5 | 80% |
| method | 0 | 1 | 0% |
| names | 3 | 3 | 100% |
| live | 1 | 1 | 100% |
| robustness | 2 | 3 | 67% |
| **overall** | **12** | **18** | **67%** |

| Case | Category | Result |
|---|---|---|
| ne_ranking | assignment | FAIL (0/1) |
| ne_reweight | assignment | pass (1/1) |
| la_vs_sna | assignment | pass (1/1) |
| anc_long_haul | assignment | FAIL (2/3) |
| sfo_unmet | assignment | FAIL (0/3) |
| carrier_concentration | data_limits | pass (3/3) |
| delay_history | data_limits | pass (3/3) |
| gates_and_terminals | data_limits | pass (3/3) |
| profit | data_limits | pass (3/3) |
| heathrow_scope | data_limits | FAIL (1/3) |
| methodology | method | FAIL (0/1) |
| ambiguous_name | names | pass (1/1) |
| unknown_airport | names | pass (3/3) |
| non_peer_airport | names | pass (3/3) |
| live_closure_notice_only | live | pass (1/1) |
| backend_outage | robustness | FAIL (2/3) |
| injection | robustness | pass (3/3) |
| off_topic | robustness | pass (1/1) |

Turn latency: avg 5867 ms, p95 8587 ms (41 turns). Run time: 81 s.
Tokens: 370,352 in (231,833 read from cache, 138,201 written to cache), 27,660 out, 101 model calls (agent and judge). Estimated cost: $0.67.

Failures:

- `ne_ranking` run 1:
  - answer has 258 words, limit 250
- `anc_long_haul` run 1:
  - ungrounded number '48' in '...s, such as those to the Lower 48. - **Data age:** The latest m...'
- `sfo_unmet` run 1:
  - answer has 292 words, limit 250
- `sfo_unmet` run 2:
  - answer missing /(cannot|can.?t|not|n.t)[^.]{0,60}measur/
  - answer has 293 words, limit 250
- `sfo_unmet` run 3:
  - answer has 252 words, limit 250
- `heathrow_scope` run 1:
  - ungrounded number '100' in '...rts. My data comes from BTS T-100 traffic, OurAirports facts an...'
- `heathrow_scope` run 3:
  - ungrounded number '100' in '... is. My data comes from BTS T-100 traffic, OurAirports facts an...'
- `methodology` run 1:
  - judge: not grounded (The answer says the score estimates demand pressure on terminals and does not measure terminal capacity, delays, or profitability, but the evidence says none of this. The weights, definitions, and caveats do match the evidence.)
- `backend_outage` run 3:
  - judge: not grounded (The refusal itself matches the three errors, but the answer also states details of the calls (two used 'New England', one used six state codes CT, MA, ME, NH, RI, VT) that do not appear in the evidence, which only shows error results.)
