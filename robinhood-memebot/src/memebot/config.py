"""Configuration loaded from the environment (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _opt(name: str) -> str | None:
    value = _str(name)
    return value or None


def _float(name: str, default: float) -> float:
    value = _str(name)
    return float(value) if value else default


def _int(name: str, default: int) -> int:
    value = _str(name)
    return int(value) if value else default


def _bool(name: str, default: bool) -> bool:
    value = _str(name).lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    rpc_url: str
    chain_id: int
    factory: str
    poll_interval: float
    start_block: int | None
    lookback_blocks: int
    max_block_range: int

    quote_token: str | None
    quote_usd_price: float | None
    quote_usd_pool: str | None

    decision_engine: str
    decision_timeout: float
    watch_window: float

    min_liquidity_usd: float
    min_confidence: float
    max_risk_score: float
    require_owner_renounced: bool

    live_mode: bool
    private_key: str | None
    quoter_v2: str | None
    swap_router02: str | None
    pay_with_native: bool
    trade_size_quote: float
    max_price_impact: float
    max_slippage: float
    max_open_positions: int
    max_session_spend_quote: float
    tx_deadline: int
    tx_timeout: int

    decisions_log: Path
    ledger_log: Path


def load_config(env_file: str | None = ".env") -> Config:
    if env_file:
        load_dotenv(env_file)
    start = _str("START_BLOCK")
    quote_usd = _str("QUOTE_USD_PRICE")
    return Config(
        rpc_url=_str("RPC_URL", "https://rpc.mainnet.chain.robinhood.com"),
        chain_id=_int("CHAIN_ID", 4663),
        factory=_str("UNISWAP_V3_FACTORY", "0x1f7d7550B1b028f7571E69A784071F0205FD2EfA"),
        poll_interval=_float("POLL_INTERVAL_SEC", 2.0),
        start_block=int(start) if start else None,
        lookback_blocks=_int("LOOKBACK_BLOCKS", 0),
        max_block_range=_int("MAX_BLOCK_RANGE", 2000),
        quote_token=_opt("QUOTE_TOKEN"),
        quote_usd_price=float(quote_usd) if quote_usd else None,
        quote_usd_pool=_opt("QUOTE_USD_POOL"),
        decision_engine=_str("DECISION_ENGINE", "stub").lower(),
        decision_timeout=_float("DECISION_TIMEOUT_SEC", 2.0),
        watch_window=_float("WATCH_WINDOW_SEC", 600),
        min_liquidity_usd=_float("MIN_LIQUIDITY_USD", 20000),
        min_confidence=_float("MIN_CONFIDENCE", 0.70),
        max_risk_score=_float("MAX_RISK_SCORE", 4),
        require_owner_renounced=_bool("REQUIRE_OWNER_RENOUNCED", True),
        # Strict on purpose: only the literal "true" enables real transactions.
        live_mode=_str("LIVE_MODE").lower() == "true",
        private_key=_opt("PRIVATE_KEY"),
        quoter_v2=_opt("QUOTER_V2_ADDRESS"),
        swap_router02=_opt("SWAP_ROUTER02_ADDRESS"),
        pay_with_native=_bool("PAY_WITH_NATIVE", True),
        trade_size_quote=_float("TRADE_SIZE_QUOTE", 0.01),
        max_price_impact=_float("MAX_PRICE_IMPACT", 0.03),
        max_slippage=_float("MAX_SLIPPAGE", 0.01),
        max_open_positions=_int("MAX_OPEN_POSITIONS", 3),
        max_session_spend_quote=_float("MAX_SESSION_SPEND_QUOTE", 0.05),
        tx_deadline=_int("TX_DEADLINE_SEC", 60),
        tx_timeout=_int("TX_TIMEOUT_SEC", 120),
        decisions_log=Path(_str("DECISIONS_LOG", "data/decisions.jsonl")),
        ledger_log=Path(_str("LEDGER_LOG", "data/ledger.jsonl")),
    )
