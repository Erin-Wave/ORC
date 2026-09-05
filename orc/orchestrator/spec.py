"""ORC | Hypotheses and their parameter grids.

A hypothesis is registered BEFORE its results exist.  The registration carries a
prose claim about who is paying and why, the rule form, and the exhaustive
parameter grid.  It is then hashed.  The runner refuses to execute a hypothesis
whose file no longer matches its own hash, which makes "adjust the grid until
something works" a visible act rather than an invisible one.

Parameters are enumerated exhaustively, never sampled.  The DCA parameter space
is small enough for that, and the whole response surface is worth more than its
maximum: a plateau is evidence, an isolated spike is an artefact.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

from orc import config


# --------------------------------------------------------------------------
# one concrete, runnable configuration
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TrialConfig:
    symbol: str
    contribution: float = 100.0
    stride_days: float = 7.0
    n_contributions: int = 156
    hold_days: float = 0.0
    leverage: float = 1.0
    gate: str = "none"                 # none | dip:<drop>:<lookback_days> | sma:<days>
    take_profit: float | None = None
    stop_loss: float | None = None
    include_funding: bool = True
    clock: str = "1h"
    fee_bps: float = config.TAKER_FEE_BPS
    slippage_bps: float = config.SLIPPAGE_BPS
    cost_multiplier: float = 1.0

    @property
    def uses_analytic(self) -> bool:
        """The closed-form evaluator is exact only for this shape.

        include_funding is part of the shape, not a detail of it.  The closed
        form has no concept of ruin: it keeps subtracting the funding bill from
        a position that a real account would have been liquidated out of, and
        the row it writes carries liquidation_rate 0.0 -- a number nobody
        measured, sitting where a measurement belongs.  H0001's funded ADAUSDT
        cell at 156 weekly deposits reports tm_q05 -0.4988 and tm_worst -0.7317:
        an unlevered long ending owing more than it deposited, which cannot
        happen.  Run on the simulator the same shape liquidates on 0.692 of its
        start dates, and turning funding off takes that to 0.000, which is how
        the cause is isolated.  Unlevered and unfunded still has no ruin to
        express, and that is the shape the two evaluators are cross-checked on.
        """
        return (self.gate == "none" and self.leverage == 1.0
                and self.take_profit is None and self.stop_loss is None
                and not self.include_funding)

    def to_dict(self) -> dict:
        return asdict(self)

    def with_costs(self, mult: float) -> "TrialConfig":
        return replace(self, cost_multiplier=mult)

    @property
    def effective_fee_bps(self) -> float:
        return self.fee_bps * self.cost_multiplier

    @property
    def effective_slippage_bps(self) -> float:
        return self.slippage_bps * self.cost_multiplier


@dataclass(frozen=True)
class SignalTrialConfig:
    """One Track B configuration: a rule, its thresholds, and how it is sized.

    Deliberately a separate type rather than more fields on TrialConfig.  The
    ledger keys a trial on the hash of its config dict, so widening TrialConfig
    would change the hash of every Track A trial ever recorded and re-run the
    lot under new identities, inflating N for a change that touched none of
    them.  The two tracks describe different objects and get different types.
    """
    symbol: str
    rule: str = "carry_funding"
    lookback_days: float = 21.0
    enter_rate: float = 0.00015          # per settlement, not annualised
    exit_rate: float = 0.00005
    # --- the indicator rules -------------------------------------------
    # The candle the indicator is read on, in hours, aggregated from the
    # execution clock rather than from a separate panel.  4.0 with clock "1h"
    # is the 4-hour candle traded on the hourly bar; 1.0 is the base clock
    # itself.  Keeping this a property of the SIGNAL and not of the panel is
    # what lets `execution_realism` re-run the identical 4h signal against
    # minute fills -- a second set of panel files could not, because the
    # signal would change with the clock and the drift would be unattributable.
    timeframe_hours: float = 1.0
    # CCI levels, in the units the literature quotes: +-100 is the band
    # Lambert's 0.015 was chosen to produce, +-200 the extreme.  `enter_level`
    # must exceed `exit_level`, which is the rule's hysteresis and is
    # pre-registered like any other parameter.
    enter_level: float = 100.0
    exit_level: float = 0.0
    # The slower timeframe of a multi-timeframe rule, and the level at which it
    # permits a side.  None means single-timeframe, which is what every rule
    # but cci_mtf is.  `filter_lookback_days` defaults to `lookback_days`, so
    # the two readings cover the same span of TIME at different resolutions
    # unless a hypothesis deliberately says otherwise.
    filter_timeframe_hours: float | None = None
    filter_lookback_days: float | None = None
    filter_level: float = 100.0
    # How far open interest must FALL over the indicator's own window for a bar
    # to be admissible, as a positive fraction. None means the rule does not
    # read positioning; oi_confirmed_reversion refuses without it, because a
    # discriminator that admits every bar is the unconditional rule wearing a
    # different name.
    oi_drop: float | None = None
    capital: float = 10_000.0
    leverage: float = 1.0
    stop_loss: float | None = None       # fraction of margin
    take_profit: float | None = None
    max_hold_days: float | None = None
    clock: str = "1h"
    fee_bps: float = config.TAKER_FEE_BPS
    slippage_bps: float = config.SLIPPAGE_BPS
    cost_multiplier: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)

    def with_costs(self, mult: float) -> "SignalTrialConfig":
        return replace(self, cost_multiplier=mult)

    @property
    def effective_fee_bps(self) -> float:
        return self.fee_bps * self.cost_multiplier

    @property
    def effective_slippage_bps(self) -> float:
        return self.slippage_bps * self.cost_multiplier


def ordinal_axis(values: list) -> bool:
    """Does "one step away" mean a small change along this axis?

    It needs an order and three levels: with two, the shape diagnostic has no
    cell either side of the peak to compare against.  Booleans are switches and
    a None is "off"; neither sorts anywhere, so neither counts toward the three.
    Strings do not either, which is not pedantry -- "sma:20" through "sma:200"
    reads as ordered to a human and is a set of five unrelated labels to the
    diagnostic.  This is the definition surface.py evaluates the grid with, kept
    here so that what the intake refuses and what the diagnostic can see are the
    same rule rather than two copies of it.
    """
    numeric = [v for v in values
               if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return len(numeric) > 2


# --------------------------------------------------------------------------
# a registered hypothesis
# --------------------------------------------------------------------------
@dataclass
class Hypothesis:
    hypothesis_id: str
    family: str
    claim: str                          # who repeatedly pays, and why
    kill_condition: str                 # what result would close this family
    universe: list[str]
    grid: dict[str, list]
    fixed: dict = field(default_factory=dict)
    # "A" accumulation (DCA), "B" signal-driven positions.  See CLAUDE.md.
    track: str = "A"
    registered_utc: str = ""
    prereg_hash: str = ""

    # ------------------------------------------------------------------
    def payload(self) -> dict:
        """Everything that must be fixed before results are seen."""
        p = {
            "hypothesis_id": self.hypothesis_id,
            "family": self.family,
            "claim": self.claim,
            "kill_condition": self.kill_condition,
            "universe": sorted(self.universe),
            "grid": {k: list(v) for k, v in sorted(self.grid.items())},
            "fixed": dict(sorted(self.fixed.items())),
        }
        # Track A predates this field.  Writing it unconditionally would change
        # the pre-registration hash of every hypothesis registered before Track
        # B existed, which is exactly what pre-registration forbids.
        if self.track != "A":
            p["track"] = self.track
        return p

    def compute_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.payload(), sort_keys=True, separators=(",", ":"),
                       default=str).encode()).hexdigest()

    def register(self) -> "Hypothesis":
        self.registered_utc = datetime.now(timezone.utc).isoformat()
        self.prereg_hash = self.compute_hash()
        return self

    def verify(self) -> None:
        if not self.prereg_hash:
            raise ValueError(f"{self.hypothesis_id} was never registered")
        if self.compute_hash() != self.prereg_hash:
            raise ValueError(
                f"{self.hypothesis_id}: the grid or claim changed after registration. "
                "Register a NEW hypothesis id instead of editing this one.")

    # ------------------------------------------------------------------
    def assert_no_axis_clash(self) -> None:
        """A parameter may be an axis or a constant, never both.

        Checked from BOTH size() and expand() because they disagreed: size()
        multiplies the grid without expanding it, so it charged the full
        product against the configuration ceiling, while expand() applied
        `fixed` last and collapsed the axis to one value. Refusing in expand()
        alone would let intake register the hypothesis and fail later; refusing
        in size() alone would let a caller that goes straight to expand()
        through.
        """
        clash = sorted(set(self.grid) & set(self.fixed))
        if clash:
            raise ValueError(
                f"{self.hypothesis_id}: {clash} appear in both `grid` and "
                "`fixed`. The grid axis would be silently collapsed to the "
                "fixed value while still being charged against the "
                "configuration ceiling. Remove it from one of the two and "
                "register under a new id.")

    def size(self) -> int:
        self.assert_no_axis_clash()
        n = len(self.universe)
        for v in self.grid.values():
            n *= max(len(v), 1)
        return n

    def shape_is_measurable(self) -> bool:
        """Can this family ever be shown not to be a spike?

        A grid with no ordinal axis returns no shape at all, and verdict.py
        counts an unmeasured shape as a disqualifier -- correctly, since an
        absent check is not a passed one.  So every cell such a hypothesis
        enumerates enters N and none of them can ever be a finding.  H0006 is
        the worked example: 72 configurations, every axis binary, nine symbols
        reported with shape '?' and a nan neighbour ratio, and the family was
        closed on PBO while the structural check it most needed could not run.
        """
        return any(ordinal_axis(v) for v in self.grid.values())

    @property
    def primary_metric(self) -> str:
        """What this track is judged on.  Section 4 of the constitution.

        Track A is judged on the 5th-percentile terminal multiple.  Track B has
        no start-date ensemble to take a percentile of, so it is judged on
        Calmar: return over the deepest drawdown, which is the left tail of a
        single equity curve.
        """
        return "calmar" if self.track == "B" else "tm_q05"

    def expand(self) -> list:
        """Every (symbol x grid point) combination, in a deterministic order."""
        self.verify()
        cls = SignalTrialConfig if self.track == "B" else TrialConfig
        keys = sorted(self.grid)

        # `fixed` used to be applied with params.update(self.fixed), so a name
        # in BOTH blocks had its whole pre-registered axis silently collapsed
        # to one value -- while size() still charged the full product against
        # the probe ceiling and run_hypothesis still printed the full count as
        # evaluated. A registration that says it tried five levels and tried
        # one is the pre-registration failing in the direction the whole
        # protocol exists to prevent, and it would have been invisible: the
        # cells are valid, the ledger is consistent, and only the config_json
        # of the rows would have shown it.
        #
        # No registered hypothesis has ever had an overlap (checked across all
        # six on 2026-09-05), so nothing on record is affected. It is refused
        # rather than resolved because there is no correct answer to "which of
        # the two did the author mean" -- a new id is cheap and a wrong guess
        # is permanent.
        self.assert_no_axis_clash()

        out: list = []
        for sym in sorted(self.universe):
            for values in product(*(self.grid[k] for k in keys)):
                params = dict(zip(keys, values))
                params.update(self.fixed)
                out.append(cls(symbol=sym, **params))
        return out

    # ------------------------------------------------------------------
    def save(self, path: Path | None = None) -> Path:
        path = path or (config.REGISTRY / f"{self.hypothesis_id}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        # The id is the only handle anything downstream has on a hypothesis:
        # the surface report selects its trials WHERE hypothesis_id=?.  Writing
        # a different claim or grid to an id that already has trials behind it
        # does not replace them, it adopts them -- the next report would carry
        # one hypothesis's claim and kill condition over two hypotheses'
        # numbers, and the prereg hash that was supposed to make an edited grid
        # visible would have been overwritten by the edit.  verify() cannot
        # catch this: it only checks a hypothesis against itself.  Section 3
        # says a changed hypothesis gets a new id; this is the line where that
        # stops being advice.
        if path.exists():
            prior = json.loads(path.read_text(encoding="utf-8"))
            if prior.get("prereg_hash") != self.prereg_hash:
                raise ValueError(
                    f"{self.hypothesis_id} is already registered under a different "
                    f"pre-registration hash (on disk {str(prior.get('prereg_hash'))[:12]}, "
                    f"offered {self.prereg_hash[:12]}). Register a NEW hypothesis id "
                    "instead of reusing this one.")
        path.write_text(json.dumps(asdict(self), indent=2, default=str), encoding="utf-8")
        return path

    @staticmethod
    def load(path: Path) -> "Hypothesis":
        h = Hypothesis(**json.loads(Path(path).read_text(encoding="utf-8")))
        h.verify()
        return h


def probe_ceiling(family: str, tested: set[str] | None = None) -> int:
    """How many configurations this family may enumerate on its first outing.

    A mechanism with no rows in the ledger has survived nothing, so it gets a
    probe.  Depth is earned by a result: once the family has been tested and
    not closed, a second registration under a new id may go as wide as
    MAX_CONFIGURATIONS_PER_HYPOTHESIS.

    `tested` is the set of families the ledger already holds; it is read from
    the ledger when not supplied, so intake enforces this against what has
    actually been run rather than against what happens to be on disk.
    """
    if tested is None:
        try:
            from orc.ledger.trials import Ledger
            with Ledger() as led:
                tested = {f for f, _ in led.families()}
        except Exception:                                          # noqa: BLE001
            tested = set()
    return (config.MAX_CONFIGURATIONS_PER_HYPOTHESIS if family in tested
            else config.MAX_PROBE_CONFIGURATIONS)


def closed_families(directory: Path | None = None) -> dict[str, dict]:
    """Families the reasoning layer has closed against their kill condition.

    The marker is configs/closed/<id>.json and it is permanent.  It used to be
    consumed the moment the post-mortem was written, which made closing a
    family a documentation act and nothing else: the registry file stayed, so
    the worker kept enumerating the grid.  H0002 closed at 17:13 and the 22:28
    cycle re-ran all 972 of its cells, 972 of the 1210 rows that cycle added to
    N -- a multiple-testing charge for asking a question that had already been
    answered.
    """
    d = directory if directory is not None else config.CONFIGS / "closed"
    out: dict[str, dict] = {}
    if not d.exists():
        return out
    for p in sorted(d.glob("H*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            rec = {}
        out[rec.get("hypothesis_id") or p.stem] = rec
    return out


def load_registry(directory: Path | None = None,
                  include_closed: bool = False) -> list[Hypothesis]:
    """Every hypothesis still open to evaluation.

    A closed family keeps its registry file -- that file is the pre-registered
    claim, and section 3 forbids editing or deleting it -- but it is not handed
    back for evaluation.  Its answer is in reports/POSTMORTEM_<id>.md.
    """
    d = directory or config.REGISTRY
    closed = {} if include_closed else closed_families()
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            h = Hypothesis.load(p)
        except (ValueError, TypeError) as exc:
            print(f"  registry: skipping {p.name} -- {exc}")
            continue
        if h.hypothesis_id in closed:
            print(f"  registry: {h.hypothesis_id} is closed "
                  f"({h.family}); not re-run")
            continue
        out.append(h)
    return out


def next_hypothesis_id(directory: Path | None = None) -> str:
    """The next id no proposal has ever used.

    Every directory a hypothesis id can rest in counts, not just the registry.
    An id that was proposed and killed must not come round again: the kill is
    filed as configs/killed/<id>.json, so reissuing the id overwrites the
    record of why the first one was rejected, and the proposer is told to avoid
    ids already tried on the strength of a file that no longer exists.
    """
    roots = [directory] if directory else [
        config.REGISTRY, config.QUEUE, config.CONFIGS / "killed",
        config.CONFIGS / "closed", config.CONFIGS / "proposed",
    ]
    n = 0
    for d in roots:
        if not d or not d.exists():
            continue
        for p in d.glob("H*.json"):
            try:
                n = max(n, int(p.stem.lstrip("H")))
            except ValueError:
                continue
    return f"H{n + 1:04d}"
