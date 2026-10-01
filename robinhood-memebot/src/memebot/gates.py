"""Hard gates, applied in code after the decision engine. They can only veto."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .config import Config
from .decision import Decision


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    value: object
    threshold: object


def evaluate_gates(state: dict, decision: Decision, cfg: Config) -> list[GateResult]:
    liq = state.get("liquidity_usd")
    risk = decision.risk_score
    gates = [
        GateResult("contract_has_code", bool(state.get("contract_has_code")), state.get("contract_has_code"), True),
        GateResult("liquidity_usd", liq is not None and liq >= cfg.min_liquidity_usd, liq, cfg.min_liquidity_usd),
        GateResult("confidence", decision.confidence >= cfg.min_confidence, decision.confidence, cfg.min_confidence),
        # An unknown risk score fails: no score, no trade.
        GateResult("risk_score", risk is not None and risk <= cfg.max_risk_score, risk, cfg.max_risk_score),
    ]
    if cfg.require_owner_renounced:
        gates.append(
            GateResult("owner_renounced", state.get("owner_renounced") is True, state.get("owner_renounced"), True)
        )
    return gates


def final_action(decision: Decision, gates: list[GateResult]) -> tuple[str, list[str]]:
    """Returns (action, reasons). A failed gate always turns the action into skip."""
    failed = [g for g in gates if not g.passed]
    reasons = [f"{g.name}={g.value} (need {g.threshold})" for g in failed]
    if decision.error:
        reasons.insert(0, f"engine error: {decision.error}")
        return "skip", reasons
    if failed:
        return "skip", reasons
    return decision.action, reasons


def gates_as_dicts(gates: list[GateResult]) -> list[dict]:
    return [asdict(g) for g in gates]
