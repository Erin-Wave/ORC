You are scouting for MECHANISMS on Binance USD-margined perpetual futures.

Not strategies. Not indicators. Not backtest ideas. A mechanism here means one
specific thing:

  a party who is structurally paying, and a durable reason they keep doing it.

The project you are scouting for has a problem you are being asked to fix. Six
of its first eight hypothesis families rested on the funding rate. A tree that
re-arranges one idea is narrower than its hypothesis count suggests, and if
that idea is dead the whole tree is. Its proposing step can only read its own
repository, so it keeps re-deriving the same family under new names. You can
read the outside world. That is the entire point of this step.

## Mechanisms already tested, and closed

{closed}

Do not bring these back. A variation on one of them - a different threshold, a
different lookback, the same payment collected on the other side - is the same
mechanism and will be rejected. If your candidate's payer is the leveraged long
paying funding, or the liquidated long selling into a cascade, it is already on
that list.

## Already in the notebook

{known}

Skip anything whose payer is one of these. A second entry for the same payer
is noise in the one file that is supposed to widen the search.

## What makes a candidate worth writing down

- The payer is IDENTIFIABLE. "The market" is not a payer. "A perpetual holder
  who must roll at a fixed time because their mandate forbids overnight
  exposure" is.
- The reason they keep paying is STRUCTURAL, not a mistake. A mistake gets
  arbitraged away; a constraint does not. Mandates, margin rules, tax years,
  index rebalances, redemption windows, exchange listing mechanics, oracle
  update schedules, settlement calendars, and market-maker inventory limits are
  constraints. "Retail is irrational" is not.
- The payment is MEASURABLE from public market data on this venue. The project
  holds 1-minute OHLCV bars for roughly 480 Binance USDs-M perpetual symbols
  from 2019 to 2024, plus the funding rate history and a listing/delisting
  table. If measuring your mechanism needs the order book, trade prints, open
  interest, or anything else that is not in that list, say so in
  `needs_data_we_lack` rather than pretending it is measurable.
- It is SOURCED. Give real URLs you actually read. Exchange documentation,
  regulatory filings, market-microstructure papers, and post-mortems of specific
  events are worth more than commentary. If your only source is your own prior
  knowledge, say so in `sources` as "no source read" and lower the confidence.

Search the web where you can. Prefer primary documents.

## What NOT to include

Say nothing about whether any of this would be profitable, and do not propose a
rule, a threshold, a parameter or a grid. A later step does that, and it is
deliberately kept from seeing performance numbers when it chooses what to ask
next -- so if you put a return, a Sharpe or a drawdown in this file you will
have contaminated the one input to that step that cannot be biased by the
project's own results.

## Reply format

Reply with one JSON array and nothing else. Zero to four objects. An empty
array is a good answer when you found nothing that clears the bar; a padded one
is worse than nothing, because every entry here is read by the step that
chooses what to ask next.

Each object has exactly these keys:

  payer                  who pays, one phrase, specific
  why_they_keep_paying   the constraint that makes it durable, two sentences max
  what_would_end_it      the change that would stop the payment
  observable             what would be visible in 1-minute bars or funding
                         history if this mechanism is real
  needs_data_we_lack     data required that the project does not hold, or ""
  confidence             high, medium or low
  sources                list of URLs actually read, or ["no source read"]
  distinct_from          why this payer is not one of the closed mechanisms
                         above, in one sentence
