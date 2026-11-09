"""Check that numbers written in prose match a real run.

In README.md and docs/*.md, a number followed by a marker is checked against results/metrics.json:

    accuracy **91.3%**<!-- m:variants.full.accuracy.rate -->      (percent, one decimal)
    8 domains<!-- p:totals.domains -->                          (p: = results/packs.json)
    temperature 1.85<!-- m:calibration.temperature -->            (same decimals as written)

The test count between <!-- tests -->N<!-- /tests --> must equal what scripts/count_tests.py prints.
Run: python scripts/check_numbers.py   (CI runs it on every push)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK = re.compile(r"(-?[\d,]*\.?\d+)(%?)\**<!-- ([mp]):([\w.\-]+) -->")
TESTS = re.compile(r"<!-- tests -->(\d+)<!-- /tests -->")


def lookup(m: dict, path: str):
    cur = m
    for part in path.split("."):
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    return cur


def check_text(text: str, metrics: dict, packs: dict | None = None) -> list[str]:
    bad = []
    for num, pct, src, path in MARK.findall(text):
        val = float(lookup(metrics if src == "m" else packs, path))
        written = float(num.replace(",", ""))
        if pct:
            val *= 100
        decimals = len(num.split(".")[1]) if "." in num else 0
        if round(val, decimals) != round(written, decimals):
            bad.append(f"{path}: README says {num}{pct}, run says {round(val, decimals)}")
    return bad


def test_count() -> int:
    out = subprocess.run([sys.executable, str(ROOT / "scripts/count_tests.py")], capture_output=True, text=True,
                         cwd=ROOT, check=True).stdout
    return int(re.search(r"(\d+) tests collected", out).group(1))


def main() -> int:
    metrics = json.loads((ROOT / "results/metrics.json").read_text())
    packs = json.loads((ROOT / "results/packs.json").read_text())
    files = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    problems, n_marks = [], 0
    n = test_count()
    for f in files:
        text = f.read_text()
        n_marks += len(MARK.findall(text))
        problems += [f"{f.name}: {p}" for p in check_text(text, metrics, packs)]
        problems += [f"{f.name}: test count {c} != {n}" for c in TESTS.findall(text) if int(c) != n]
    if problems:
        print("\n".join(problems))
        return 1
    print(f"{n_marks} documented numbers and the test count ({n}) match a real run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
