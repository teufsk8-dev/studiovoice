from memebot.chain import decode_pool_created

from conftest import POOL, QUOTE, TOKEN


def _word(hexaddr):
    return bytes.fromhex(hexaddr[2:].rjust(64, "0"))


def test_decode_pool_created():
    tick_spacing = (-60) % (1 << 256)  # negative int24, ABI-encoded as int256
    log = {
        "blockNumber": 123,
        "transactionHash": b"\x01" * 32,
        "topics": [b"\x00" * 32, _word(TOKEN), _word(QUOTE), (10000).to_bytes(32, "big")],
        "data": tick_spacing.to_bytes(32, "big") + _word(POOL),
    }
    ev = decode_pool_created(log)
    assert ev.block == 123
    assert ev.token0.lower() == TOKEN
    assert ev.token1.lower() == QUOTE
    assert ev.fee == 10000
    assert ev.tick_spacing == -60
    assert ev.pool.lower() == POOL
