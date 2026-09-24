"""Deterministic state engine: market data -> one compact numeric snapshot.

Everything here is plain arithmetic. The snapshot is the ONLY input the fast
decision model sees. Causality is enforced: any datum stamped after `as_of_ms`
raises, so no field can leak from the future (the classic backtest bug).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Sequence

from .types import Candle, OrderBook, Portfolio, Side, Trade

MAX_SNAPSHOT_TOKENS = 400
# Conservative token estimate for compact numeric JSON: ~3 chars per token.
CHARS_PER_TOKEN = 3


class LookaheadError(ValueError):
    """Raised when an input is timestamped after the decision time."""


@dataclass(frozen=True)
class Snapshot:
    as_of_ms: int
    fields: dict

    def to_prompt(self) -> str:
        return json.dumps(self.fields, separators=(",", ":"), sort_keys=True)

    def est_tokens(self) -> int:
        return math.ceil(len(self.to_prompt()) / CHARS_PER_TOKEN)


def _r(x: float, nd: int = 6) -> float:
    return float(round(x, nd))


def _check_causal(as_of_ms: int, *stamps: int) -> None:
    for ts in stamps:
        if ts > as_of_ms:
            raise LookaheadError(f"input ts {ts} > as_of {as_of_ms}")


def realized_vol(closes: Sequence[float]) -> float:
    """Std-dev of log returns over the window (per-candle, not annualized)."""
    if len(closes) < 3:
        return 0.0
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    if len(rets) < 2:
        return 0.0
    mu = sum(rets) / len(rets)
    return math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))


def book_imbalance(book: OrderBook, depth: int = 5) -> float:
    """(bid_vol - ask_vol) / (bid_vol + ask_vol) over top `depth` levels, in [-1, 1]."""
    b = sum(l.size for l in book.bids[:depth])
    a = sum(l.size for l in book.asks[:depth])
    return 0.0 if b + a == 0 else (b - a) / (b + a)


def build_snapshot(
    as_of_ms: int,
    book: OrderBook,
    candles: Sequence[Candle],
    trades: Sequence[Trade],
    portfolio: Portfolio,
    vol_window: int = 30,
    trade_window_ms: int = 60_000,
    max_book_age_ms: int = 5_000,
) -> Snapshot:
    if not book.bids or not book.asks:
        raise ValueError("empty book side")
    _check_causal(as_of_ms, book.ts_ms, *(c.ts_ms for c in candles), *(t.ts_ms for t in trades))

    best_bid, best_ask = book.bids[0].price, book.asks[0].price
    if best_bid >= best_ask:
        raise ValueError(f"crossed book {best_bid} >= {best_ask}")
    mid = (best_bid + best_ask) / 2
    spread_bps = (best_ask - best_bid) / mid * 1e4

    closes = [c.close for c in candles[-vol_window:]]
    rv = realized_vol(closes)
    ret_1 = math.log(closes[-1] / closes[-2]) if len(closes) >= 2 else 0.0
    ret_n = math.log(closes[-1] / closes[0]) if len(closes) >= 2 else 0.0

    recent = [t for t in trades if as_of_ms - t.ts_ms <= trade_window_ms]
    buy_v = sum(t.size for t in recent if t.aggressor is Side.BUY)
    sell_v = sum(t.size for t in recent if t.aggressor is Side.SELL)
    flow = 0.0 if buy_v + sell_v == 0 else (buy_v - sell_v) / (buy_v + sell_v)

    eq = portfolio.equity
    inventory_pct = portfolio.position_qty * mid / eq if eq > 0 else 0.0
    drawdown = 1 - eq / portfolio.peak_equity if portfolio.peak_equity > 0 else 0.0
    day_pnl = eq / portfolio.day_start_equity - 1 if portfolio.day_start_equity > 0 else 0.0

    fields = {
        "sym": book.symbol,
        "mid": _r(mid, 8),
        "spr_bps": _r(spread_bps, 3),
        "imb5": _r(book_imbalance(book), 4),
        "flow60s": _r(flow, 4),
        "rv": _r(rv, 6),
        "r1": _r(ret_1, 6),
        "rN": _r(ret_n, 6),
        "n": len(closes),
        "inv_pct": _r(inventory_pct, 4),
        "dd": _r(drawdown, 4),
        "day_pnl": _r(day_pnl, 4),
        "book_age_ms": as_of_ms - book.ts_ms,
        "stale": int(as_of_ms - book.ts_ms > max_book_age_ms),
    }
    snap = Snapshot(as_of_ms=as_of_ms, fields=fields)
    if snap.est_tokens() > MAX_SNAPSHOT_TOKENS:
        raise ValueError(f"snapshot too large: ~{snap.est_tokens()} tokens")
    return snap
