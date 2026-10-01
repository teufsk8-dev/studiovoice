import dataclasses
import json

from memebot.decision import DecisionRunner
from memebot.executor import Executor
from memebot.journal import Journal
from memebot.pipeline import Pipeline, UiState

from fakes import FakeReader


def build(cfg, engine, reader=None, **overrides):
    cfg = dataclasses.replace(cfg, start_block=100, **overrides)
    reader = reader or FakeReader()
    calls = []

    def spy(state):
        calls.append(state)
        return engine(state)

    ui = UiState()
    ex = Executor(cfg, reader, Journal(cfg.ledger_log))
    p = Pipeline(cfg, reader, DecisionRunner(spy, 1), ex, Journal(cfg.decisions_log), ui)
    p.start()
    return p, reader, calls, ui, ex, cfg


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def buy_engine(state):
    return {"action": "buy", "confidence": 0.9, "risk_score": 2, "raw": {"jev": "raw"}}


def test_waits_for_liquidity_then_buys(cfg):
    p, reader, calls, ui, ex, cfg = build(cfg, buy_engine)
    p.tick()  # pool detected, empty: engine not called yet
    assert calls == [] and ui.launches[0].status == "watching"

    reader.fund(5)  # 5 WETH * 2000 = 10k < 20k
    p.tick()
    assert calls == []

    reader.fund(20)  # 40k
    p.tick()
    assert len(calls) == 1
    state = calls[0]
    assert state["liquidity_usd"] == 40_000
    assert {"token_address", "total_supply", "owner_renounced", "contract_has_code", "pool_price"} <= state.keys()

    assert ui.launches[0].status == "buy"
    (decision,) = lines(cfg.decisions_log)
    assert decision["final_action"] == "buy"
    assert decision["jev_raw"] == {"jev": "raw"}
    assert decision["state"]["liquidity_usd"] == 40_000
    assert lines(cfg.ledger_log)[0]["status"] == "paper"
    assert len(ex.positions) == 1


def test_gate_veto_is_logged_with_raw_answer(cfg):
    p, reader, calls, ui, ex, cfg = build(cfg, buy_engine, reader=FakeReader(owner_status="active"))
    reader.fund(20)
    p.tick()
    (decision,) = lines(cfg.decisions_log)
    assert decision["final_action"] == "skip"
    assert decision["jev_raw"] == {"jev": "raw"}
    assert any(r.startswith("owner_renounced") for r in decision["reasons"])
    assert lines(cfg.ledger_log) == [] and ex.positions == []


def test_watch_window_expiry_logs_skip_without_calling_engine(cfg):
    p, reader, calls, ui, ex, cfg = build(cfg, buy_engine, watch_window=0)
    p.tick()
    assert calls == []
    (decision,) = lines(cfg.decisions_log)
    assert decision["final_action"] == "skip" and decision["jev_raw"] is None
    assert p.watching == {}


def test_hold_is_logged(cfg):
    engine = lambda s: {"action": "hold", "confidence": 0.9, "risk_score": 1, "raw": {}}
    p, reader, calls, ui, ex, cfg = build(cfg, engine)
    reader.fund(20)
    p.tick()
    assert lines(cfg.decisions_log)[0]["final_action"] == "hold"
    assert ex.positions == []
