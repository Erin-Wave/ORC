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
        """The closed-form evaluator is exact only for this shape."""
        return (self.gate == "none" and self.leverage == 1.0
                and self.take_profit is None and self.stop_loss is None)

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
    registered_utc: str = ""
    prereg_hash: str = ""

    # ------------------------------------------------------------------
    def payload(self) -> dict:
        """Everything that must be fixed before results are seen."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "family": self.family,
            "claim": self.claim,
            "kill_condition": self.kill_condition,
            "universe": sorted(self.universe),
            "grid": {k: list(v) for k, v in sorted(self.grid.items())},
            "fixed": dict(sorted(self.fixed.items())),
        }

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
    def size(self) -> int:
        n = len(self.universe)
        for v in self.grid.values():
            n *= max(len(v), 1)
        return n

    def expand(self) -> list[TrialConfig]:
        """Every (symbol x grid point) combination, in a deterministic order."""
        self.verify()
        keys = sorted(self.grid)
        out: list[TrialConfig] = []
        for sym in sorted(self.universe):
            for values in product(*(self.grid[k] for k in keys)):
                params = dict(zip(keys, values))
                params.update(self.fixed)
                out.append(TrialConfig(symbol=sym, **params))
        return out

    # ------------------------------------------------------------------
    def save(self, path: Path | None = None) -> Path:
        path = path or (config.REGISTRY / f"{self.hypothesis_id}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, default=str), encoding="utf-8")
        return path

    @staticmethod
    def load(path: Path) -> "Hypothesis":
        h = Hypothesis(**json.loads(Path(path).read_text(encoding="utf-8")))
        h.verify()
        return h


def load_registry(directory: Path | None = None) -> list[Hypothesis]:
    d = directory or config.REGISTRY
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(Hypothesis.load(p))
        except (ValueError, TypeError) as exc:
            print(f"  registry: skipping {p.name} -- {exc}")
    return out


def next_hypothesis_id(directory: Path | None = None) -> str:
    d = directory or config.REGISTRY
    existing = sorted(p.stem for p in d.glob("H*.json")) if d.exists() else []
    n = 0
    for name in existing:
        try:
            n = max(n, int(name.lstrip("H")))
        except ValueError:
            continue
    return f"H{n + 1:04d}"
