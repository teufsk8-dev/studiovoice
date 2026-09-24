"""Decision engines behind one interface.

- JevEngine: the fast "reflex" (TypeSafe AI's Jev). The wire format below is
  UNVERIFIED — typesafe.ai docs were not reachable from the build environment.
  Confirm endpoint, auth header and payload against console.typesafe.ai before
  enabling, and keep the contract test (tests/test_engines.py) in sync.
- StubEngine: deterministic heuristic used for tests and paper trading
  without any API key. It is NOT a strategy; it exists to exercise the pipeline.

Any engine failure (timeout, HTTP error, schema error) => the caller HOLDs.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Protocol

from .schema import DecisionSchema, Judgment, parse_decision
from .state_engine import Snapshot


class DecisionEngine(Protocol):
    def decide(self, schema: DecisionSchema, snap: Snapshot) -> dict[str, Judgment]: ...


class EngineError(RuntimeError):
    pass


class JevEngine:
    def __init__(self, api_key: str | None = None, url: str | None = None, timeout_s: float = 0.5):
        self.api_key = api_key or os.environ.get("JEV_API_KEY", "")
        # UNVERIFIED default endpoint: override with JEV_URL once confirmed.
        self.url = url or os.environ.get("JEV_URL", "")
        self.timeout_s = timeout_s
        self.last_latency_ms: float | None = None

    def decide(self, schema: DecisionSchema, snap: Snapshot) -> dict[str, Judgment]:
        if not self.api_key or not self.url:
            raise EngineError("JEV_API_KEY and JEV_URL must be set")
        body = {
            "state": snap.to_prompt(),
            "judgments": {
                name: {"type": spec["type"], "question": spec["question"],
                       **({"options": spec["options"]} if spec["type"] == "choice" else {}),
                       **({"min": spec["min"], "max": spec["max"]} if spec["type"] == "score" else {})}
                for name, spec in schema.fields.items()
            },
        }
        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = json.loads(resp.read())
        except Exception as e:  # network, timeout, bad JSON
            raise EngineError(f"jev call failed: {e}") from e
        finally:
            self.last_latency_ms = (time.perf_counter() - t0) * 1e3
        return parse_decision(schema, raw.get("judgments", raw))


class StubEngine:
    """Deterministic, transparent mapping from snapshot to probabilities."""

    def decide(self, schema: DecisionSchema, snap: Snapshot) -> dict[str, Judgment]:
        f = snap.fields
        rv, rN, imb, flow, dd = f["rv"], f["rN"], f["imb5"], f["flow60s"], f["dd"]
        if dd > 0.10 or rv > 0.03:
            regime = {"crisis": 0.7, "high_vol": 0.2, "trending": 0.05, "mean_reverting": 0.05}
        elif abs(rN) > 3 * rv * max(f["n"], 1) ** 0.5 * 0.5:
            regime = {"trending": 0.7, "mean_reverting": 0.1, "high_vol": 0.15, "crisis": 0.05}
        else:
            regime = {"mean_reverting": 0.6, "trending": 0.2, "high_vol": 0.15, "crisis": 0.05}
        tilt = max(-1.0, min(1.0, 0.5 * imb + 0.5 * flow))
        p_long = 0.1 + 0.8 * max(tilt, 0)
        p_short = 0.1 + 0.8 * max(-tilt, 0)
        p_neu = max(0.0, 1 - p_long - p_short)
        s = p_long + p_short + p_neu
        direction = {"long": p_long / s, "short": p_short / s, "neutral": p_neu / s}
        toxic = 0.8 if f["spr_bps"] > 20 else 0.2
        q = min(3, int(abs(tilt) * 4))
        quality = {k: (0.85 if k == q else 0.05) for k in range(4)}
        risk = ({"reduce": 0.8, "near_limit": 0.15, "safe": 0.05} if dd > 0.08
                else {"safe": 0.85, "near_limit": 0.1, "reduce": 0.05})
        raw = {
            "regime": {"probs": regime}, "direction": {"probs": direction},
            "toxic_flow": {"probs": {"true": toxic, "false": 1 - toxic}},
            "setup_quality": {"probs": {str(k): v for k, v in quality.items()}},
            "risk_state": {"probs": risk},
        }
        return parse_decision(schema, raw)
