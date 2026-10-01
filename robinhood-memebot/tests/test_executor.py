import dataclasses
import json

import pytest

from memebot.decision import Decision
from memebot.executor import Executor, LiveModeRefused
from memebot.journal import Journal
from memebot.market import snapshot

from fakes import FakeReader


def make(cfg, sim=None, **overrides):
    cfg = dataclasses.replace(cfg, **overrides)
    reader = FakeReader()
    reader.fund(20)
    ex = Executor(cfg, reader, Journal(cfg.ledger_log))
    if sim is not None:
        ex.simulate = lambda snap: sim
    info = reader.token_info(reader.events[0].token0)
    snap = snapshot(reader, reader.events[0], info, cfg.quote_token, 2000.0)
    return ex, snap, cfg


def ledger(cfg):
    return [json.loads(line) for line in cfg.ledger_log.read_text().splitlines()]


def test_paper_buy_opens_position_and_logs_prices(cfg):
    sim = {"amount_out_raw": 9_800 * 10**18, "tokens_out": 9_800.0, "price": 0.01 / 9_800,
           "price_impact": 0.01, "ticks_crossed": 1, "gas_estimate": 1}
    ex, snap, cfg = make(cfg, sim)
    rec = ex.buy(snap, Decision("buy", 0.9, 2))
    assert rec["status"] == "paper"
    assert rec["fill_price"] == rec["sim_price"]
    assert rec["decision_price"] == pytest.approx(1e-6)
    assert rec["jev"]["confidence"] == 0.9
    assert len(ex.positions) == 1
    assert ledger(cfg)[0]["status"] == "paper"


def test_high_price_impact_is_rejected(cfg):
    sim = {"amount_out_raw": 1, "tokens_out": 1.0, "price": 0.01, "price_impact": 0.03,
           "ticks_crossed": 9, "gas_estimate": 1}
    ex, snap, cfg = make(cfg, sim)
    assert ex.buy(snap, Decision("buy", 0.9, 2))["status"] == "rejected_impact"
    assert ex.positions == []


def test_session_and_position_limits(cfg):
    ex, snap, cfg = make(cfg, max_open_positions=2, max_session_spend_quote=1.0)
    statuses = [ex.buy(snap, Decision("buy", 0.9, 2))["status"] for _ in range(3)]
    assert statuses == ["paper", "paper", "refused_limits"]
    ex, snap, cfg = make(cfg, max_open_positions=10, max_session_spend_quote=0.015)
    statuses = [ex.buy(snap, Decision("buy", 0.9, 2))["status"] for _ in range(2)]
    assert statuses == ["paper", "refused_limits"]


def test_paper_mode_can_never_send(cfg):
    ex, snap, cfg = make(cfg)
    with pytest.raises(LiveModeRefused):
        ex._send(fn=None)


def test_live_mode_refused_without_setup(cfg):
    ex, snap, cfg = make(cfg, live_mode=True)
    with pytest.raises(LiveModeRefused) as err:
        ex.preflight()
    assert "PRIVATE_KEY" in str(err.value) and "QUOTER_V2_ADDRESS" in str(err.value)


def test_live_mode_without_simulation_refuses_swap(cfg):
    ex, snap, cfg = make(cfg, live_mode=True)
    ex.simulate = lambda snap: None
    ex._swap = lambda *a: pytest.fail("swap must not be attempted without simulation")
    assert ex.buy(snap, Decision("buy", 0.9, 2))["status"] == "refused"


def test_received_parses_transfer_logs(cfg):
    from web3 import Web3

    key = "0x" + "11" * 32
    ex, snap, cfg = make(cfg, private_key=key)
    me = ex.account.address
    token = snap.token.address
    topic = bytes(Web3.keccak(text="Transfer(address,address,uint256)"))
    pad = lambda a: bytes.fromhex(a[2:].rjust(64, "0"))
    logs = [
        {"address": token, "topics": [topic, pad("0x" + "22" * 20), pad(me)], "data": (500).to_bytes(32, "big")},
        {"address": token, "topics": [topic, pad(me), pad("0x" + "33" * 20)], "data": (7).to_bytes(32, "big")},
        {"address": "0x" + "44" * 20, "topics": [topic, pad("0x" + "22" * 20), pad(me)], "data": (9).to_bytes(32, "big")},
    ]
    assert ex._received({"logs": logs}, token) == 500


def test_swap_calldata_encodes(cfg):
    """encode_abi works offline with web3 v7 for the router multicall payload."""
    from web3 import Web3

    from memebot import abis

    router = Web3().eth.contract(address="0x" + "55" * 20, abi=abis.SWAP_ROUTER02)
    params = ("0x" + "66" * 20, "0x" + "77" * 20, 10000, "0x" + "88" * 20, 10**16, 1, 0)
    data = router.encode_abi("exactInputSingle", args=[params])
    assert data.startswith("0x04e45aaf")  # SwapRouter02 exactInputSingle selector
