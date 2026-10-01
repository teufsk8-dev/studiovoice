"""Minimal ABIs for the contracts the bot talks to."""


def _fn(name, inputs=(), outputs=(), mutability="view"):
    return {
        "type": "function",
        "name": name,
        "stateMutability": mutability,
        "inputs": [{"name": n, "type": t} for n, t in inputs],
        "outputs": [{"name": n, "type": t} for n, t in outputs],
    }


ERC20 = [
    _fn("name", outputs=[("", "string")]),
    _fn("symbol", outputs=[("", "string")]),
    _fn("decimals", outputs=[("", "uint8")]),
    _fn("totalSupply", outputs=[("", "uint256")]),
    _fn("balanceOf", [("account", "address")], [("", "uint256")]),
    _fn("allowance", [("owner", "address"), ("spender", "address")], [("", "uint256")]),
    _fn("approve", [("spender", "address"), ("amount", "uint256")], [("", "bool")], "nonpayable"),
]

OWNABLE = [_fn("owner", outputs=[("", "address")])]

POOL_V3 = [
    _fn("token0", outputs=[("", "address")]),
    _fn("token1", outputs=[("", "address")]),
    _fn("fee", outputs=[("", "uint24")]),
    _fn("liquidity", outputs=[("", "uint128")]),
    _fn(
        "slot0",
        outputs=[
            ("sqrtPriceX96", "uint160"),
            ("tick", "int24"),
            ("observationIndex", "uint16"),
            ("observationCardinality", "uint16"),
            ("observationCardinalityNext", "uint16"),
            ("feeProtocol", "uint8"),
            ("unlocked", "bool"),
        ],
    ),
]

QUOTER_V2 = [
    {
        "type": "function",
        "name": "quoteExactInputSingle",
        "stateMutability": "nonpayable",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
            }
        ],
        "outputs": [
            {"name": "amountOut", "type": "uint256"},
            {"name": "sqrtPriceX96After", "type": "uint160"},
            {"name": "initializedTicksCrossed", "type": "uint32"},
            {"name": "gasEstimate", "type": "uint256"},
        ],
    }
]

SWAP_ROUTER02 = [
    _fn("WETH9", outputs=[("", "address")]),
    {
        "type": "function",
        "name": "exactInputSingle",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
            }
        ],
        "outputs": [{"name": "amountOut", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "multicall",
        "stateMutability": "payable",
        "inputs": [
            {"name": "deadline", "type": "uint256"},
            {"name": "data", "type": "bytes[]"},
        ],
        "outputs": [{"name": "results", "type": "bytes[]"}],
    },
]

POOL_CREATED_SIGNATURE = "PoolCreated(address,address,uint24,int24,address)"
TRANSFER_SIGNATURE = "Transfer(address,address,uint256)"
