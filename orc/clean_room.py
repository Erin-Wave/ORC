"""ORC | Clean-room guard.

ORC is built from scratch.  No prior lab on this machine may be read, imported
or copied.  This module names those labs so a test can prove the boundary held.
"""
from __future__ import annotations

from pathlib import Path

# Prior research trees on this machine.  ORC must not reference any of them.
FORBIDDEN_LAB_NAMES = (
    "SPM", "SPM2", "SPM3", "BTLAB1", "BTLAB2", "BTLAB3", "BTLAB4",
    "BTLAB5", "BTLAB6", "FINAL1", "FWD1", "MECH1", "SER1", "KREV1",
    "KRSPOT1", "WTA", "NNL",
)

# Substrings that would indicate an artifact of a prior lab leaked in.
FORBIDDEN_TOKENS = (
    r"D:/Project/SPM", r"D:\Project\SPM",
    r"D:/Project/BTLAB", r"D:\Project\BTLAB",
    r"D:/Project/FINAL", r"D:\Project\FINAL",
    "MECHANISM CARD", "ADMISSION_GATE", "PAYOFF_CLASS",
    "NO_FINAL_TEST_CANDIDATE", "LINEAGE_SEALED",
)

SOURCE_SUFFIXES = {".py", ".yml", ".yaml", ".json", ".md", ".toml"}


def scan(root: Path) -> list[tuple[Path, str]]:
    """Return (file, offending token) for every clean-room violation under root."""
    hits: list[tuple[Path, str]] = []
    for p in root.rglob("*"):
        if p.suffix.lower() not in SOURCE_SUFFIXES or not p.is_file():
            continue
        if p.name == "clean_room.py":          # this file legitimately names them
            continue
        if any(part in {".git", "facts", "reports", "__pycache__"} for part in p.parts):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for tok in FORBIDDEN_TOKENS:
            if tok in text:
                hits.append((p, tok))
    return hits
