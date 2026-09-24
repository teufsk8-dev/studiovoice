"""Overnight review: grade every decision against what actually happened.

Outputs a report and a *proposal* for the next schema/policy version into
proposals/. Nothing here edits the live schema: promotion is an operator gate
(phase 5 review -> phase 6 ship). A self-modifying live system with no human
gate is how small calibration errors compound into large losses.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

DIRS = ("long", "short", "neutral")


def realized_direction(ret: float, cost: float) -> str:
    if ret > cost:
        return "long"
    if ret < -cost:
        return "short"
    return "neutral"


def brier_multiclass(probs: dict, outcome: str) -> float:
    return sum((float(probs.get(k, 0.0)) - (1.0 if k == outcome else 0.0)) ** 2 for k in DIRS)


@dataclass
class ReviewResult:
    n: int
    brier: float
    brier_baseline: float  # always predicting the empirical class frequencies
    reliability: list      # (bin_lo, bin_hi, n, mean_conf, hit_rate)
    trades: int
    equity_start: float
    equity_end: float
    recommendations: list


def load(path: str | Path) -> list[dict]:
    rows = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def review(rows: list[dict], cost_bps: float = 12.0, horizon: int = 1,
           bins=(0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)) -> ReviewResult:
    graded = []
    for i, r in enumerate(rows[:-horizon] if horizon else rows):
        j = r.get("judgments")
        if not j:
            continue
        m0, m1 = r["snap"]["mid"], rows[i + horizon]["snap"]["mid"]
        out = realized_direction(math.log(m1 / m0), cost_bps / 1e4)
        probs = j["direction"]["probs"]
        graded.append((probs, j["direction"]["value"], out))

    n = len(graded)
    if n == 0:
        return ReviewResult(0, float("nan"), float("nan"), [], 0, 0, 0, ["no graded decisions"])
    brier = sum(brier_multiclass(p, o) for p, _, o in graded) / n
    freq = {k: sum(1 for *_, o in graded if o == k) / n for k in DIRS}
    base = sum(brier_multiclass(freq, o) for *_, o in graded) / n

    rel = []
    for lo, hi in zip(bins, bins[1:]):
        sel = [(p[v], v == o) for p, v, o in graded if lo <= p[v] < hi or (hi == 1.0 and p[v] == 1.0)]
        if sel:
            rel.append((lo, hi, len(sel), sum(c for c, _ in sel) / len(sel),
                        sum(h for _, h in sel) / len(sel)))

    trades = sum(1 for r in rows if r.get("fill", {}).get("qty", 0) > 0)
    recs = []
    if brier >= base:
        recs.append("Direction Brier is no better than the base-rate forecast: no demonstrated "
                    "skill. Recommend halting live sizing until this changes.")
    for lo, hi, cnt, conf, hit in rel:
        if lo >= 0.8 and cnt >= 30 and hit < conf - 0.05:
            recs.append(f"Overconfident in [{lo},{hi}): claimed {conf:.2f}, realized {hit:.2f} "
                        f"(n={cnt}). Raise min_direction_conf or recalibrate before Kelly sizing.")
    if n < 200:
        recs.append(f"Only {n} graded decisions: calibration estimates are noisy; do not "
                    "promote schema changes on this sample alone.")
    return ReviewResult(n, brier, base, rel, trades, rows[0].get("equity", 0),
                        rows[-1].get("equity", 0), recs)


def write_proposal(res: ReviewResult, schema_path: Path, out_dir: Path) -> Path:
    """Writes report + next-version schema candidate. Operator must promote it."""
    schema = json.loads(schema_path.read_text())
    nxt = dict(schema, version=schema["version"] + 1)
    nxt["review"] = {"brier": res.brier, "baseline": res.brier_baseline, "n": res.n,
                     "recommendations": res.recommendations, "status": "PROPOSED - needs operator approval"}
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"decision_v{nxt['version']}.json"
    p.write_text(json.dumps(nxt, indent=2))
    lines = [f"# Nightly review (schema v{schema['version']})", "",
             f"- graded decisions: {res.n}", f"- direction Brier: {res.brier:.4f} "
             f"(base rate {res.brier_baseline:.4f}; lower is better)",
             f"- fills: {res.trades}", f"- equity: {res.equity_start:.2f} -> {res.equity_end:.2f}", "",
             "## Reliability (direction)", "| bin | n | mean conf | hit rate |", "|---|---|---|---|"]
    lines += [f"| {lo:.1f}-{hi:.1f} | {c} | {mc:.3f} | {hr:.3f} |" for lo, hi, c, mc, hr in res.reliability]
    lines += ["", "## Recommendations"] + [f"- {r}" for r in res.recommendations or ["none"]]
    (out_dir / f"review_v{schema['version']}.md").write_text("\n".join(lines) + "\n")
    return p


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="logs/decisions.jsonl")
    ap.add_argument("--schema", default="schemas/decision_v1.json")
    ap.add_argument("--out", default="proposals")
    ap.add_argument("--cost-bps", type=float, default=12.0)
    a = ap.parse_args()
    r = review(load(a.log), cost_bps=a.cost_bps)
    print(write_proposal(r, Path(a.schema), Path(a.out)))
