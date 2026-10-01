import time

from memebot.decision import Decision, DecisionRunner, stub_decide
from memebot.gates import evaluate_gates, final_action

GOOD_STATE = {"liquidity_usd": 50_000, "owner_renounced": True, "contract_has_code": True}


def jev(action="buy", confidence=0.9, risk=2):
    return lambda state: {"action": action, "confidence": confidence, "risk_score": risk, "raw": {"x": 1}}


def test_runner_normalises_and_keeps_raw():
    d = DecisionRunner(jev(), 1.0).run({})
    assert (d.action, d.confidence, d.risk_score, d.raw) == ("buy", 0.9, 2.0, {"x": 1})


def test_runner_timeout_becomes_skip():
    def slow(state):
        time.sleep(0.5)
        return {"action": "buy", "confidence": 1.0}

    d = DecisionRunner(slow, 0.05).run({})
    assert d.action == "skip" and "timeout" in d.error


def test_runner_invalid_output_becomes_skip():
    assert DecisionRunner(jev(action="moon"), 1).run({}).action == "skip"
    assert DecisionRunner(jev(confidence=7), 1).run({}).action == "skip"

    def boom(state):
        raise RuntimeError("api down")

    d = DecisionRunner(boom, 1).run({})
    assert d.action == "skip" and "api down" in d.error


def test_all_gates_pass_buy(cfg):
    d = Decision("buy", 0.9, 2)
    assert final_action(d, evaluate_gates(GOOD_STATE, d, cfg)) == ("buy", [])


def test_hold_stays_hold_when_gates_pass(cfg):
    d = Decision("hold", 0.9, 2)
    assert final_action(d, evaluate_gates(GOOD_STATE, d, cfg))[0] == "hold"


def test_each_gate_vetoes_buy(cfg):
    cases = [
        ({**GOOD_STATE, "liquidity_usd": 19_999}, Decision("buy", 0.9, 2), "liquidity_usd"),
        (GOOD_STATE, Decision("buy", 0.69, 2), "confidence"),
        (GOOD_STATE, Decision("buy", 0.9, 5), "risk_score"),
        (GOOD_STATE, Decision("buy", 0.9, None), "risk_score"),
        ({**GOOD_STATE, "owner_renounced": False}, Decision("buy", 0.9, 2), "owner_renounced"),
        ({**GOOD_STATE, "contract_has_code": False}, Decision("buy", 0.9, 2), "contract_has_code"),
    ]
    for state, d, gate in cases:
        action, reasons = final_action(d, evaluate_gates(state, d, cfg))
        assert action == "skip", gate
        assert any(r.startswith(gate) for r in reasons), (gate, reasons)


def test_thresholds_are_inclusive(cfg):
    d = Decision("buy", 0.70, 4)
    state = {**GOOD_STATE, "liquidity_usd": 20_000}
    assert final_action(d, evaluate_gates(state, d, cfg))[0] == "buy"


def test_stub_never_buys(cfg):
    d = DecisionRunner(stub_decide, 1).run(GOOD_STATE)
    assert final_action(d, evaluate_gates(GOOD_STATE, d, cfg))[0] == "skip"


def test_live_mode_requires_literal_true(monkeypatch):
    from memebot.config import load_config

    for value, expected in [("true", True), ("TRUE", True), ("1", False), ("yes", False), ("", False)]:
        monkeypatch.setenv("LIVE_MODE", value)
        assert load_config(env_file=None).live_mode is expected, value
