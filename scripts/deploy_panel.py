"""ORC | Build the worker bundle.

The cloud worker never receives the full archive.  It receives a bundle that
has been truncated at the holdout seal, so the sealed period is not merely
off-limits to the remote search -- it is not present on the machine.  A bug in
the worker cannot leak what was never shipped.

The bundle is one compressed file, small enough to attach to a GitHub Release
(free, 2 GB per asset) or drop in an R2 bucket (free under 10 GB, no egress
charge).  Hourly bars for a few hundred symbols compress to a few hundred MB.

Run:
    python scripts/deploy_panel.py                 # all built symbols
    python scripts/deploy_panel.py BTCUSDT ETHUSDT # a subset
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orc import config, holdout
from orc.facts import panel as panel_mod

BUNDLE = config.ORC_ROOT / "dist" / "orc-panel.tar.gz"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_bundle(symbols: list[str] | None = None, out: Path = BUNDLE) -> dict:
    symbols = symbols or panel_mod.available_symbols("1h")
    if not symbols:
        raise SystemExit("no 1h panels built; run  python -m orc.facts.build_panel")

    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="orc-bundle-"))
    (staging / "panel_1h").mkdir(parents=True)
    (staging / "funding").mkdir(parents=True)

    manifest = {
        "built_utc": datetime.now(timezone.utc).isoformat(),
        "holdout_start": str(config.HOLDOUT_START),
        "contains_sealed_data": False,
        "clock": "1h",
        "symbols": {},
    }

    kept = 0
    for sym in symbols:
        src = panel_mod.panel_path(sym, "1h")
        if not src.exists():
            continue
        df = holdout.development_slice(pl.read_parquet(src))
        if df.height == 0:
            continue
        holdout.assert_development_only(df)          # belt and braces
        dst = staging / "panel_1h" / f"{sym}.parquet"
        df.write_parquet(dst, compression="zstd", compression_level=9)

        fsrc = panel_mod.funding_path(sym)
        n_fund = 0
        if fsrc.exists():
            fdf = holdout.development_slice(pl.read_parquet(fsrc))
            fdf.write_parquet(staging / "funding" / f"{sym}.parquet",
                              compression="zstd", compression_level=9)
            n_fund = fdf.height

        manifest["symbols"][sym] = {
            "bars": df.height,
            "first_ts": str(df["ts"][0]),
            "last_ts": str(df["ts"][-1]),
            "funding_settlements": n_fund,
        }
        kept += 1

    (staging / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    if out.exists():
        out.unlink()
    with tarfile.open(out, "w:gz") as tar:
        tar.add(staging, arcname="facts")
    shutil.rmtree(staging, ignore_errors=True)

    size_mb = out.stat().st_size / 1e6
    digest = _sha256(out)
    (out.parent / "orc-panel.sha256").write_text(f"{digest}  {out.name}\n", encoding="utf-8")

    print(f"bundle : {out}")
    print(f"symbols: {kept}")
    print(f"size   : {size_mb:.1f} MB")
    print(f"sha256 : {digest}")
    print(f"sealed : nothing on or after {config.HOLDOUT_START} is inside")
    print()
    print("publish it as a free GitHub Release asset:")
    print(f'  gh release create panel-latest "{out}" '
          f'--title "ORC panel" --notes "dev data only, sealed from '
          f'{config.HOLDOUT_START}" --repo <owner>/<repo>')
    print("or replace an existing one:")
    print(f'  gh release upload panel-latest "{out}" --clobber --repo <owner>/<repo>')
    return {"path": str(out), "symbols": kept, "size_mb": size_mb, "sha256": digest}


if __name__ == "__main__":
    build_bundle([a for a in sys.argv[1:] if not a.startswith("-")] or None)
