Model: `claude-sonnet-5-5`. 20 cases, 42 conversations.

| Category | Passed | Total | Rate |
|---|---|---|---|
| assignment | 4 | 5 | 80% |
| data_limits | 4 | 5 | 80% |
| method | 0 | 1 | 0% |
| names | 3 | 3 | 100% |
| live | 1 | 1 | 100% |
| robustness | 2 | 3 | 67% |
| style | 1 | 2 | 50% |
| **overall** | **15** | **20** | **75%** |

| Case | Category | Result |
|---|---|---|
| ne_ranking | assignment | pass (1/1) |
| ne_reweight | assignment | pass (1/1) |
| la_vs_sna | assignment | pass (1/1) |
| anc_long_haul | assignment | pass (3/3) |
| sfo_unmet | assignment | FAIL (2/3) |
| carrier_concentration | data_limits | pass (3/3) |
| delay_history | data_limits | pass (3/3) |
| gates_and_terminals | data_limits | pass (3/3) |
| profit | data_limits | pass (3/3) |
| heathrow_scope | data_limits | FAIL (2/3) |
| methodology | method | FAIL (0/1) |
| ambiguous_name | names | pass (1/1) |
| unknown_airport | names | pass (3/3) |
| non_peer_airport | names | pass (3/3) |
| live_closure_notice_only | live | pass (1/1) |
| backend_outage | robustness | pass (3/3) |
| injection | robustness | pass (3/3) |
| off_topic | robustness | FAIL (0/1) |
| length_plain | style | pass (1/1) |
| length_why | style | FAIL (0/1) |

Turn latency: avg 5714 ms, p95 8154 ms (43 turns). Run time: 90 s.
Tokens: 551,644 in (265,330 read from cache, 285,826 written to cache), 42,931 out, 144 model calls (agent and judge). Estimated cost: $1.20.

Failures:

- `sfo_unmet` run 1:
  - judge (majority): not grounded (Every figure matches the evidence, but the answer says the data has no delay history or route-level data. The evidence only states that terminal, gate and construction data are unavailable.)
- `heathrow_scope` run 2:
  - ungrounded number '2' in '...by-side comparison:** compare 2–5 airports.  Tell me which US...'
  - ungrounded number '5' in '...-side comparison:** compare 2–5 airports.  Tell me which US a...'
- `methodology` run 1:
  - judge (majority): not grounded (Almost everything matches the methodology, but the opening claim that the score 'estimates demand pressure on terminals' is not in the evidence. The evidence says there is no terminal data and only describes an 'Expansion Pressure Score'.)
- `off_topic` run 1:
  - ungrounded number '2' in '... or for a region. - **Compare 2 to 5 airports** on passengers...'
  - ungrounded number '5' in '...or a region. - **Compare 2 to 5 airports** on passengers, gro...'
- `length_why` run 1:
  - judge (majority): not grounded (The answer says all three higher-ranked airports beat BOS on load factor points, but BGR has 17.3 and BOS has 20.3, so this contradicts the evidence.)

Judge: 3 calls per judged answer, the majority decides. The calls disagreed on 3 of 19 judged answers.

- `sfo_unmet` run 1: judge disagreed: 1 of 3 said grounded, majority not grounded; dissent: All figures (load factor, months at or above 85%, growth rates, 2019 recovery, per-runway traffic, score, percentiles, main driver) match the evidence, and the caveats are reflected accurately. The note that the data lacks delay and route-level information is not stated outright in the evidence, but neither tool returned any such data.
- `methodology` run 1: judge disagreed: 1 of 3 said grounded, majority not grounded; dissent: The range, method, weights, data windows, as-of date, exclusions and not-scored rules all match the methodology output. The only addition is the loose phrase "demand pressure on terminals", which is a general description and not a stated figure or policy.
- `length_why` run 1: judge disagreed: 1 of 3 said grounded, majority not grounded; dissent: All scores, ranks, component points, growth figure, data periods and caveats match the tool output, and the tied 0.25 weight on growth is a minor wording issue.

Warnings (style, not counted as failures):

- `ne_ranking` run 1: answer has 209 words, aim for 200
- `la_vs_sna` run 1: answer has 211 words, aim for 200
- `sfo_unmet` run 1: answer has 260 words, aim for 250
- `sfo_unmet` run 2: answer has 270 words, aim for 250
