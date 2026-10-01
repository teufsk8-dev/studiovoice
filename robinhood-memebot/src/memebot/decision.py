"""Decision engine plumbing: engine selection, timeout, output validation.

Any engine is a function `decide(state: dict) -> dict` returning at least
{"action": "buy"|"hold"|"skip", "confidence": float} and optionally
"risk_score" and "raw" (the engine's unprocessed answer).
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, Callable

ACTIONS = ("buy", "hold", "skip")

DecideFn = Callable[[dict], dict]


def stub_decide(state: dict) -> dict:
    """Placeholder engine: never buys. risk_score None makes the risk gate fail."""
    return {"action": "hold", "confidence": 0.0, "risk_score": None, "raw": {"engine": "stub"}}


def load_engine(name: str) -> DecideFn:
    if name == "stub":
        return stub_decide
    if name == "jev":
        # Imported lazily so TYPESAFE_API_KEY is read after .env is loaded.
        from .decision_engine import decide

        return decide
    raise ValueError(f"Unknown DECISION_ENGINE {name!r} (expected 'jev' or 'stub')")


@dataclass
class Decision:
    action: str
    confidence: float
    risk_score: float | None
    raw: Any = None
    latency_ms: float = 0.0
    error: str | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "confidence": self.confidence,
            "risk_score": self.risk_score,
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
        }


def _normalize(result: dict) -> Decision:
    result = dict(result)
    raw = result.pop("raw", None)
    action = str(result.get("action", "")).lower()
    if action not in ACTIONS:
        raise ValueError(f"invalid action {result.get('action')!r}")
    confidence = float(result["confidence"])
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence out of range: {confidence}")
    risk = result.get("risk_score")
    return Decision(
        action=action,
        confidence=confidence,
        risk_score=float(risk) if risk is not None else None,
        raw=raw,
        extra={k: v for k, v in result.items() if k not in ("action", "confidence", "risk_score")},
    )


class DecisionRunner:
    """Calls the engine in a worker thread so a slow engine can't stall the loop."""

    def __init__(self, engine: DecideFn, timeout: float):
        self.engine = engine
        self.timeout = timeout
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="decide")

    def run(self, state: dict) -> Decision:
        start = time.perf_counter()
        future = self._pool.submit(self.engine, state)
        try:
            decision = _normalize(future.result(timeout=self.timeout))
        except FutureTimeout:
            decision = Decision("skip", 0.0, None, error=f"timeout after {self.timeout}s")
        except Exception as exc:  # engine errors must never crash the bot
            decision = Decision("skip", 0.0, None, error=f"{type(exc).__name__}: {exc}")
        decision.latency_ms = (time.perf_counter() - start) * 1000
        return decision

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
