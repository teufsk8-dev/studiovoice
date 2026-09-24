"""Gate + size. Pure functions of (judgments, code-computed state, config)."""
from __future__ import annotations

from dataclasses import dataclass

from .schema import Judgment


@dataclass(frozen=True)
class PolicyConfig:
    min_setup_quality: int = 2
    min_direction_conf: float = 0.80   # strict: fire only if > this
    escalate_below_conf: float = 0.60
    kelly_fraction: float = 0.25       # hard cap: never above quarter Kelly
    reward_risk: float = 1.5           # take-profit distance / stop distance, set by code
    round_trip_cost_bps: float = 12.0  # fees + expected slippage, both legs (ESTIMATE: measure live)
    stop_bps: float = 80.0


@dataclass(frozen=True)
class PolicyResult:
    action: str          # "long" | "short" | "hold"
    size_frac: float     # fraction of equity at risk budget, before risk layer
    escalate: bool
    reasons: tuple


def kelly_fraction(p_win: float, reward_risk: float, cost_frac_of_stop: float = 0.0) -> float:
    """Kelly for a binary bet: win +b, lose -1 (in stop units), costs paid either way."""
    b = reward_risk - cost_frac_of_stop
    loss = 1 + cost_frac_of_stop
    if b <= 0:
        return 0.0
    f = (p_win * b - (1 - p_win) * loss) / (b * loss)
    return max(0.0, f)


def decide(j: dict[str, Judgment], code_risk_state: str, cfg: PolicyConfig) -> PolicyResult:
    reasons = []
    d = j["direction"]
    escalate = d.confidence < cfg.escalate_below_conf or j["regime"].value == "crisis"
    if escalate:
        reasons.append("escalate: low confidence or crisis regime")

    # The stricter of model and code risk state wins; code can only tighten.
    order = {"safe": 0, "near_limit": 1, "reduce": 2}
    risk_state = max(j["risk_state"].value, code_risk_state, key=order.__getitem__)

    gates = [
        (not escalate, "escalated"),
        (d.value in ("long", "short"), "direction neutral"),
        (d.confidence > cfg.min_direction_conf, f"dir conf {d.confidence:.2f} <= {cfg.min_direction_conf}"),
        (int(j["setup_quality"].value) >= cfg.min_setup_quality, "setup_quality < min"),
        (risk_state == "safe", f"risk_state {risk_state}"),
        (j["toxic_flow"].value is False, "toxic flow"),
    ]
    failed = [msg for ok, msg in gates if not ok]
    if failed:
        return PolicyResult("hold", 0.0, escalate, tuple(reasons + failed))

    cost_units = cfg.round_trip_cost_bps / cfg.stop_bps
    f_star = kelly_fraction(d.confidence, cfg.reward_risk, cost_units)
    frac = min(cfg.kelly_fraction, 0.25) * f_star
    if frac <= 0:
        return PolicyResult("hold", 0.0, escalate, tuple(reasons + ["no edge after costs"]))
    return PolicyResult(d.value, frac, escalate, tuple(reasons))


def code_risk_state(dd: float, day_pnl: float, inv_pct: float, max_dd: float, max_daily: float,
                    max_pos: float) -> str:
    """Deterministic risk state from code-computed numbers only."""
    if dd >= 0.66 * max_dd or day_pnl <= -0.66 * max_daily or abs(inv_pct) >= max_pos:
        return "reduce"
    if dd >= 0.33 * max_dd or day_pnl <= -0.33 * max_daily or abs(inv_pct) >= 0.75 * max_pos:
        return "near_limit"
    return "safe"
