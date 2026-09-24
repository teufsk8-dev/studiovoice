"""Per-candle loop: snapshot -> judge -> gate -> size -> risk check -> execute -> log.

Paper trading only. There is intentionally no live exchange adapter in this
package: going live is an operator gate (see README, phase 6).
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Protocol, Sequence

from .engines import DecisionEngine, EngineError
from .escalation import EscalationVerdict
from .policy import PolicyConfig, code_risk_state, decide
from .risk import RiskManager
from .schema import DecisionSchema, SchemaError
from .state_engine import build_snapshot
from .types import Candle, Order, OrderBook, Portfolio, Side, Trade


class Exchange(Protocol):
    def submit(self, order: Order, book: OrderBook) -> tuple[float, float]:
        """Returns (filled_qty, avg_price)."""


class PaperExchange:
    """Marketable-limit fills against the visible book, plus a taker fee."""

    def __init__(self, fee_bps: float = 5.0):
        self.fee_bps = fee_bps
        self.fees_paid = 0.0

    def submit(self, order: Order, book: OrderBook) -> tuple[float, float]:
        levels = book.asks if order.side is Side.BUY else book.bids
        left, cost = order.qty, 0.0
        for lvl in levels:
            if (order.side is Side.BUY and lvl.price > order.limit_price) or \
               (order.side is Side.SELL and lvl.price < order.limit_price):
                break
            take = min(left, lvl.size)
            cost += take * lvl.price
            left -= take
            if left <= 1e-12:
                break
        filled = order.qty - left
        if filled <= 0:
            return 0.0, 0.0
        px = cost / filled
        self.fees_paid += cost * self.fee_bps / 1e4
        return filled, px


class Agent:
    def __init__(self, schema: DecisionSchema, engine: DecisionEngine, risk: RiskManager,
                 exchange: Exchange, portfolio: Portfolio, cfg: PolicyConfig | None = None,
                 escalator=None, log_path: str | Path = "logs/decisions.jsonl"):
        self.schema, self.engine, self.risk = schema, engine, risk
        self.exchange, self.pf = exchange, portfolio
        self.cfg = cfg or PolicyConfig()
        self.escalator = escalator
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    # --- accounting -----------------------------------------------------
    def _apply_fill(self, side: Side, qty: float, px: float, fee_bps: float) -> None:
        signed = qty if side is Side.BUY else -qty
        cur = self.pf.position_qty
        if cur == 0 or cur * signed > 0:
            new = cur + signed
            self.pf.avg_entry = (abs(cur) * self.pf.avg_entry + qty * px) / abs(new)
            self.pf.position_qty = new
        else:
            closed = min(abs(cur), qty)
            pnl = closed * (px - self.pf.avg_entry) * (1 if cur > 0 else -1)
            self.pf.equity += pnl
            self.pf.position_qty = cur + signed
            if abs(self.pf.position_qty) < 1e-12:
                self.pf.position_qty, self.pf.avg_entry = 0.0, 0.0
            elif self.pf.position_qty * cur < 0:  # flipped through zero
                self.pf.avg_entry = px
        self.pf.equity -= qty * px * fee_bps / 1e4

    def mark(self, mid: float) -> float:
        """Mark-to-market equity used for drawdown checks."""
        return self.pf.equity + self.pf.position_qty * (mid - self.pf.avg_entry)

    # --- one candle -----------------------------------------------------
    def step(self, as_of_ms: int, book: OrderBook, candles: Sequence[Candle],
             trades: Sequence[Trade]) -> dict:
        rec: dict = {"ts": as_of_ms, "schema_v": self.schema.version}
        mid = (book.bids[0].price + book.asks[0].price) / 2
        marked = Portfolio(equity=self.mark(mid), peak_equity=self.pf.peak_equity,
                           day_start_equity=self.pf.day_start_equity,
                           position_qty=self.pf.position_qty, avg_entry=self.pf.avg_entry)
        self.risk.update_equity(marked)
        self.pf.peak_equity = marked.peak_equity

        snap = build_snapshot(as_of_ms, book, candles, trades, marked)
        rec["snap"] = snap.fields

        self._apply_escalations(book, snap.fields, rec)

        t0 = time.perf_counter()
        try:
            j = self.engine.decide(self.schema, snap)
        except (EngineError, SchemaError) as e:
            rec.update(action="hold", reasons=[f"engine: {e}"])
            return self._log(rec)
        rec["latency_ms"] = round((time.perf_counter() - t0) * 1e3, 2)
        rec["judgments"] = {k: {"value": v.value, "probs": {str(o): p for o, p in v.probs.items()}}
                            for k, v in j.items()}

        L = self.risk.limits
        crs = code_risk_state(snap.fields["dd"], snap.fields["day_pnl"], snap.fields["inv_pct"],
                              L.max_drawdown, L.max_daily_loss, L.max_position_pct)
        res = decide(j, crs, self.cfg)
        rec.update(action=res.action, size_frac=res.size_frac, reasons=list(res.reasons),
                   code_risk_state=crs)

        if res.escalate and self.escalator is not None:
            self.escalator.submit({"snapshot": snap.fields, "judgments": rec["judgments"],
                                   "position": asdict(self.pf)})
        if res.action in ("long", "short"):
            self._execute(res.action, res.size_frac, book, mid, snap.fields, marked, rec)
        return self._log(rec)

    def _execute(self, action, size_frac, book, mid, f, marked, rec) -> None:
        side = Side.BUY if action == "long" else Side.SELL
        stop_frac = self.cfg.stop_bps / 1e4
        qty = size_frac * marked.equity / stop_frac / mid  # risk size_frac of equity at the stop
        band = 10 / 1e4  # marketable limit, 10bps through mid
        limit = mid * (1 + band) if side is Side.BUY else mid * (1 - band)
        order = Order(book.symbol, side, qty, limit, reason="policy")
        verdict = self.risk.check(order, marked, mid, f["spr_bps"], f["book_age_ms"])
        rec["risk"] = {"approved": verdict.approved, "reasons": verdict.reasons}
        if not verdict.approved:
            rec["action"] = "hold"
            return
        filled, px = self.exchange.submit(verdict.order, book)
        rec["fill"] = {"side": side.value, "qty": filled, "px": px}
        if filled > 0:
            self._apply_fill(side, filled, px, getattr(self.exchange, "fee_bps", 0.0))

    def _apply_escalations(self, book, f, rec) -> None:
        if self.escalator is None:
            return
        while not self.escalator.results.empty():
            v: EscalationVerdict = self.escalator.results.get_nowait()
            rec.setdefault("escalations", []).append({"action": v.action, "why": v.rationale})
            cur = self.pf.position_qty
            if v.action == "hold" or cur == 0:
                continue
            qty = abs(cur) if v.action == "flatten" else abs(cur) / 2
            side = Side.SELL if cur > 0 else Side.BUY
            mid = f["mid"]
            limit = mid * (0.996 if side is Side.SELL else 1.004)  # inside the risk sanity band
            order = Order(book.symbol, side, qty, limit, reason=f"escalation:{v.action}")
            ver = self.risk.check(order, self.pf, mid, f["spr_bps"], f["book_age_ms"])
            if ver.approved:
                filled, px = self.exchange.submit(ver.order, book)
                if filled > 0:
                    self._apply_fill(side, filled, px, getattr(self.exchange, "fee_bps", 0.0))

    def _log(self, rec: dict) -> dict:
        rec["equity"] = self.pf.equity
        rec["pos"] = self.pf.position_qty
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
        return rec
