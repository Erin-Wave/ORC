You are casting one vote on a single factual question about the ORC research
project. The question is NOT whether this family is interesting, promising, or
worth continuing. It is only this:

**Does the family's own pre-registered kill condition, as written, apply to the
numbers below?**

The kill condition was written before any of these numbers existed, precisely so
that this decision could not be argued about afterwards. Your job is to read it
literally, check each clause against the surface, and say whether any clause is
met. You may not soften a clause because the result looks good, and you may not
tighten one because it looks bad. If a clause says "a majority of the symbols
for which it is computed", that means a majority of the symbols for which it was
computed -- not a majority of all nine.

A clause that CANNOT be evaluated is not a clause that passed. If the grid made
a diagnostic unrunnable -- a two-level axis leaves the shape diagnostic nothing
to compute, so every symbol reports '?' -- then say so and treat that clause as
unevaluated, neither met nor survived. H0006 closed with its shape clause in
exactly that state, and recording it is how the project learns that a kill
condition can be disarmed by the grid registered beside it.

Family: {hypothesis_id} — {family}

Its pre-registered kill condition, verbatim:

{kill_condition}

Its surface, every symbol, from the ledger. Read the `scales` block FIRST:

{surface}

**Evaluate the clause against the metric it names, and nothing else.** The
surface is ranked on one metric and judged on another, and they are on different
scales -- a terminal multiple breaks even at 1.0, a return at 0.0. The metric
the clause was pre-registered against is `primary_metric_best`, labelled in the
`scales` block.

If that number is absent for the symbols the clause needs, the clause is
UNEVALUABLE. Say so and list it. Do NOT substitute the ranking metric and do
NOT convert a threshold from one scale to the other, even when the arithmetic
looks obvious. The first time this vote ran, two providers split on exactly
that: the payload lacked the metric the sentence asked for, one read the ranking
value as a return and one as a multiple, and they returned opposite verdicts on
a family whose clause was not in fact met -- its true tm_q05 was 3.61 against a
threshold of 1.0. A vote that guesses the scale is worse than a vote that
refuses, because it looks like a verdict.

Answer with one JSON object and nothing else:

```json
{
  "verdict": "CLOSE" or "CONTINUE",
  "clause": "the clause you are deciding on, quoted from the kill condition",
  "clause_met": true or false,
  "unevaluable_clauses": ["any clause that could not be checked, and why"],
  "numbers": ["the specific figures that decide it, with their symbols"],
  "reason": "why the clause does or does not apply, in a few sentences, quoting the numbers rather than describing them"
}
```

Rules for the verdict:

- `CLOSE` if any clause of the kill condition is met. Name that clause.
- `CONTINUE` only if no clause is met. Saying CONTINUE while listing a met
  clause is a contradiction and will be treated as a broken vote.
- Do not invent a clause. If you think the family should close for a reason the
  kill condition does not contain, that is `CONTINUE` plus your reason in
  `reason` -- the condition is what was pre-registered, and a family closed on a
  ground nobody wrote down in advance is a family closed by hindsight.
- A family can produce positive numbers on every symbol and still close. H0006
  did: nine positive Calmars, seven of nine best cells agreeing on the same
  corner, and PBO at or above 0.5 on two of the three symbols where it was
  computable. A surface can agree across nine symbols and still carry no
  selectable information.
