import pytest

from memebot.pricing import Q96, price_impact, quote_per_token, token1_per_token0


def test_unit_price_same_decimals():
    assert token1_per_token0(Q96, 18, 18) == pytest.approx(1.0)


def test_decimal_adjustment():
    # raw price 1 with token0 18 decimals, token1 6 decimals -> 1e12 token1 per token0
    assert token1_per_token0(Q96, 18, 6) == pytest.approx(1e12)


def test_quote_per_token_both_orientations():
    sqrt = 2 * Q96  # raw price 4: 4 token1 per token0
    assert quote_per_token(sqrt, True, 18, 18) == pytest.approx(4.0)
    # token is token1, quote is token0: 4 tokens per quote -> 0.25 quote per token
    assert quote_per_token(sqrt, False, 18, 18) == pytest.approx(0.25)


def test_uninitialised_pool_has_zero_price():
    assert quote_per_token(0, True, 18, 18) == 0.0
    assert quote_per_token(0, False, 18, 18) == 0.0


def test_price_impact_excludes_fee():
    # mid 0.001 quote/token, 1 quote in, 1% fee -> ideal 990 tokens
    assert price_impact(1.0, 990.0, 0.001, 10_000) == pytest.approx(0.0)
    assert price_impact(1.0, 960.3, 0.001, 10_000) == pytest.approx(0.03)
    assert price_impact(1.0, 0.0, 0.001, 3000) == 1.0
