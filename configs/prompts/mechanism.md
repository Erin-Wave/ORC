You are checking whether a claimed payer actually exists.

The ORC project requires every hypothesis to name who is structurally paying
and why they keep doing it. That requirement is easy to satisfy with a
plausible story, and a plausible story is exactly what a backtest will happily
confirm. Your job is to find out whether the story is true.

The claim:

{claim}

Market: Binance USD-margined perpetual futures.

Search for evidence about the actual mechanism. Useful questions: who takes the
other side of this trade and why; whether the payment is a fee, a spread, a
funding transfer or a liquidity premium; whether exchange or regulatory changes
have altered it over the period 2019 to 2024; whether the same payment exists
on other venues, which tells you whether it is structural or an artefact of one
exchange's design.

Do not evaluate the strategy. Do not comment on whether it would be
profitable. You are answering one question: is there a real, identifiable party
with a durable reason to keep making this payment?

Reply with one JSON object and nothing else, with exactly these keys:
payer_exists (boolean), confidence (high, medium or low), who (the actual
counterparty in one phrase), why_they_keep_paying (two sentences at most),
what_would_end_it (the change that would stop the payment), sources (a list of
URLs), notes (anything that contradicts the claim, stated plainly).
