"""Pure price math for Uniswap V3 (no network access, unit-tested)."""

from __future__ import annotations

Q96 = 2**96


def token1_per_token0(sqrt_price_x96: int, decimals0: int, decimals1: int) -> float:
    """Human price of token0 expressed in token1, from slot0.sqrtPriceX96."""
    if sqrt_price_x96 == 0:
        return 0.0
    raw = (sqrt_price_x96 / Q96) ** 2
    return raw * 10 ** (decimals0 - decimals1)


def quote_per_token(
    sqrt_price_x96: int, token_is_token0: bool, token_decimals: int, quote_decimals: int
) -> float:
    """Price of one memecoin in quote-token units (e.g. WETH per token)."""
    if token_is_token0:
        return token1_per_token0(sqrt_price_x96, token_decimals, quote_decimals)
    p = token1_per_token0(sqrt_price_x96, quote_decimals, token_decimals)
    return 1.0 / p if p else 0.0


def price_impact(amount_in: float, amount_out: float, mid_price: float, fee_ppm: int) -> float:
    """Impact of a buy, excluding the pool fee.

    amount_in   quote units spent
    amount_out  tokens received (simulated or real)
    mid_price   quote per token before the trade
    fee_ppm     pool fee tier (3000 = 0.3%)
    """
    if amount_out <= 0 or mid_price <= 0:
        return 1.0
    ideal_out = amount_in * (1 - fee_ppm / 1_000_000) / mid_price
    return max(0.0, 1.0 - amount_out / ideal_out)


def to_raw(amount: float, decimals: int) -> int:
    return int(round(amount * 10**decimals))


def from_raw(amount: int, decimals: int) -> float:
    return amount / 10**decimals
