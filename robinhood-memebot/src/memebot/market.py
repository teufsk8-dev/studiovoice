"""Builds a priced snapshot of a new pool and the state dict sent to the decision engine."""

from __future__ import annotations

import time
from dataclasses import dataclass

from web3 import Web3

from .chain import ChainReader, PoolCreated, TokenInfo
from .pricing import from_raw, quote_per_token


@dataclass
class PoolSnapshot:
    pool: str
    fee: int
    token: TokenInfo
    quote: str
    quote_decimals: int
    initialized: bool
    price_quote: float  # quote units per token, from slot0
    quote_usd: float | None
    quote_reserve: float  # quote tokens held by the pool
    token_reserve: float  # memecoins held by the pool

    @property
    def price_usd(self) -> float | None:
        return self.price_quote * self.quote_usd if self.quote_usd is not None else None

    @property
    def liquidity_usd(self) -> float | None:
        """USD value of the quote side only: what you can actually sell into.

        The token side is deliberately excluded. Its value is the pool's own
        price times a supply the deployer controls, so a single-sided position
        can make a pool look deep while holding almost no quote token.
        """
        return self.quote_reserve * self.quote_usd if self.quote_usd is not None else None

    @property
    def tvl_usd(self) -> float | None:
        if self.quote_usd is None:
            return None
        return (self.quote_reserve + self.token_reserve * self.price_quote) * self.quote_usd


def pair_side(event: PoolCreated, quote: str) -> str | None:
    """The memecoin address of the pair, or None if the pool isn't paired with `quote`."""
    q = Web3.to_checksum_address(quote)
    if event.token0 == q:
        return event.token1
    if event.token1 == q:
        return event.token0
    return None


class QuotePricer:
    """USD price of the quote token: fixed value, or read from a quote/stable pool."""

    def __init__(self, reader: ChainReader, quote: str, fixed: float | None, pool: str | None, ttl: float = 30):
        self.reader, self.quote, self.fixed, self.pool, self.ttl = reader, quote, fixed, pool, ttl
        self._cache: tuple[float, float] | None = None

    def usd(self) -> float | None:
        if not self.pool:
            return self.fixed
        now = time.monotonic()
        if self._cache and now - self._cache[0] < self.ttl:
            return self._cache[1]
        t0, t1, _ = self.reader.pool_tokens(self.pool)
        stable = t1 if Web3.to_checksum_address(t0) == Web3.to_checksum_address(self.quote) else t0
        # Assumes the other side of QUOTE_USD_POOL is a USD stablecoin.
        price = self.reader.pool_price(self.pool, self.quote, stable)
        self._cache = (now, price)
        return price or None


def snapshot(reader: ChainReader, event: PoolCreated, token_info: TokenInfo, quote: str, quote_usd: float | None) -> PoolSnapshot:
    quote = Web3.to_checksum_address(quote)
    q_dec = reader.decimals(quote) or 18
    t_dec = token_info.decimals
    s0 = reader.slot0(event.pool)
    price = 0.0
    if s0.initialized and t_dec is not None:
        price = quote_per_token(s0.sqrt_price_x96, event.token0 == token_info.address, t_dec, q_dec)
    quote_bal = reader.balance_of(quote, event.pool) or 0
    token_bal = (reader.balance_of(token_info.address, event.pool) or 0) if token_info.has_code else 0
    return PoolSnapshot(
        pool=event.pool,
        fee=event.fee,
        token=token_info,
        quote=quote,
        quote_decimals=q_dec,
        initialized=s0.initialized,
        price_quote=price,
        quote_usd=quote_usd,
        quote_reserve=from_raw(quote_bal, q_dec),
        token_reserve=from_raw(token_bal, t_dec) if t_dec is not None else 0.0,
    )


def build_state(snap: PoolSnapshot, pool_age_sec: float) -> dict:
    """The dict passed to decide(). JSON-serialisable; big ints sent as strings."""
    t = snap.token
    return {
        "token_address": t.address,
        "token_name": t.name,
        "token_symbol": t.symbol,
        "total_supply": t.total_supply,
        "total_supply_raw": str(t.total_supply_raw) if t.total_supply_raw is not None else None,
        "owner_renounced": t.owner_renounced,
        "owner_status": t.owner_status,
        "contract_has_code": t.has_code,
        "pool_address": snap.pool,
        "fee_tier": snap.fee,
        "pool_price": snap.price_quote,
        "pool_price_usd": snap.price_usd,
        "liquidity_usd": snap.liquidity_usd,
        "tvl_usd": snap.tvl_usd,
        "pool_age_sec": round(pool_age_sec, 1),
    }

