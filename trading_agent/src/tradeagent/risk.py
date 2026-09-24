"""Hard deterministic risk layer. No model output is an input here.

check() runs before EVERY order. The kill switch latches: once tripped it
stays tripped until an operator calls reset() with a reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .types import Order, Portfolio, RiskVerdict, Side


@dataclass(frozen=True)
class RiskLimits:
    max_drawdown: float = 0.15          # from peak equity -> trip kill switch
    max_daily_loss: float = 0.03        # from day-start equity -> halt new risk for the day
    max_position_pct: float = 0.20      # |position notional| / equity
    max_order_pct: float = 0.05         # single order notional / equity
    max_spread_bps: float = 25.0        # refuse to trade into a wide book
    max_book_age_ms: int = 5_000        # refuse to trade on stale data
    max_price_deviation_bps: float = 50  # limit price vs mid sanity band


@dataclass
class KillSwitch:
    armed: bool = True
    tripped: bool = False
    reason: str = ""
    log: list = field(default_factory=list)

    def trip(self, reason: str) -> None:
        if not self.tripped:
            self.tripped, self.reason = True, reason
            self.log.append(("trip", reason))

    def reset(self, operator_reason: str) -> None:
        if not operator_reason:
            raise ValueError("reset needs an operator reason")
        self.tripped, self.reason = False, ""
        self.log.append(("reset", operator_reason))


class RiskManager:
    def __init__(self, limits: RiskLimits, kill_switch: KillSwitch | None = None):
        self.limits = limits
        self.kill = kill_switch or KillSwitch()

    def update_equity(self, pf: Portfolio) -> None:
        pf.peak_equity = max(pf.peak_equity, pf.equity)
        dd = 1 - pf.equity / pf.peak_equity if pf.peak_equity > 0 else 1.0
        if dd >= self.limits.max_drawdown:
            self.kill.trip(f"drawdown {dd:.2%} >= {self.limits.max_drawdown:.0%}")

    def daily_halted(self, pf: Portfolio) -> bool:
        return pf.equity / pf.day_start_equity - 1 <= -self.limits.max_daily_loss

    def check(self, order: Order, pf: Portfolio, mid: float, spread_bps: float, book_age_ms: int) -> RiskVerdict:
        L, reasons = self.limits, []
        self.update_equity(pf)

        if not self.kill.armed:
            return RiskVerdict(False, None, ["kill switch disarmed: refusing all orders"])
        cur = pf.position_qty
        signed = order.qty if order.side is Side.BUY else -order.qty
        reduces = abs(cur + signed) < abs(cur) and cur * signed < 0
        if self.kill.tripped and not reduces:
            return RiskVerdict(False, None, [f"kill switch tripped: {self.kill.reason}"])
        if self.daily_halted(pf) and not reduces:
            return RiskVerdict(False, None, ["daily loss limit hit"])
        if order.qty <= 0 or mid <= 0 or pf.equity <= 0:
            return RiskVerdict(False, None, ["invalid qty/price/equity"])
        if book_age_ms > L.max_book_age_ms:
            return RiskVerdict(False, None, [f"stale book {book_age_ms}ms"])
        if spread_bps > L.max_spread_bps and not reduces:
            return RiskVerdict(False, None, [f"spread {spread_bps:.1f}bps too wide"])
        if abs(order.limit_price / mid - 1) * 1e4 > L.max_price_deviation_bps:
            return RiskVerdict(False, None, ["limit price outside sanity band"])

        qty = order.qty
        max_order_qty = L.max_order_pct * pf.equity / mid
        if qty > max_order_qty:
            qty = max_order_qty
            reasons.append("clipped to max_order_pct")
        if not reduces:
            room = L.max_position_pct * pf.equity / mid - abs(cur) if cur * signed >= 0 else \
                L.max_position_pct * pf.equity / mid + abs(cur)
            if room <= 0:
                return RiskVerdict(False, None, ["max position reached"])
            if qty > room:
                qty = room
                reasons.append("clipped to max_position_pct")
        return RiskVerdict(True, replace(order, qty=qty), reasons)
