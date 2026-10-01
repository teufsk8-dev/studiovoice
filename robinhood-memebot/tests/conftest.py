import dataclasses

import pytest

from memebot.config import load_config

QUOTE = "0x4200000000000000000000000000000000000006"
TOKEN = "0x1111111111111111111111111111111111111111"  # < QUOTE, so token is token0
POOL = "0x2222222222222222222222222222222222222222"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    for key in ("LIVE_MODE", "PRIVATE_KEY", "QUOTER_V2_ADDRESS", "SWAP_ROUTER02_ADDRESS", "QUOTE_USD_POOL"):
        monkeypatch.delenv(key, raising=False)
    base = load_config(env_file=None)
    return dataclasses.replace(
        base,
        quote_token=QUOTE,
        quote_usd_price=2000.0,
        decisions_log=tmp_path / "decisions.jsonl",
        ledger_log=tmp_path / "ledger.jsonl",
    )
