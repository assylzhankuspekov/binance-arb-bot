"""
Клиент биржи (ccxt) и хелперы по рынкам: точность, квантование, парсинг.
"""

import warnings
from decimal import Decimal, ROUND_DOWN

import ccxt

import config

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

ex = ccxt.binance({
    "apiKey": config.API_KEY,
    "secret": config.API_SECRET,
    "enableRateLimit": True,
    "options": {"defaultType": "spot"},
})
if not config.VERIFY_SSL:
    ex.verify = False


def d(x) -> Decimal:
    return Decimal(str(x))


def parse_base_quote(symbol: str) -> tuple[str, str]:
    base, quote = symbol.split("/")
    return base, quote


def quantize_amount(symbol: str, amount: Decimal) -> Decimal:
    m = ex.market(symbol)
    prec = m.get("precision", {}).get("amount")
    if prec is None:
        return amount
    q = Decimal("1e-" + str(prec))
    return amount.quantize(q, rounding=ROUND_DOWN)


def quantize_price(symbol: str, price: Decimal) -> Decimal:
    m = ex.market(symbol)
    prec = m.get("precision", {}).get("price")
    if prec is None:
        return price
    q = Decimal("1e-" + str(prec))
    return price.quantize(q, rounding=ROUND_DOWN)


def tick_size(symbol: str) -> Decimal:
    prec = ex.market(symbol).get("precision", {}).get("price")
    if prec is None:
        return Decimal("0")
    return Decimal("1e-" + str(prec))


def binance_to_sym(s: str) -> str:
    """Binance stream symbol id -> ccxt symbol (e.g. BTCUSDT -> BTC/USDT)."""
    m = ex.markets_by_id.get(s)
    if not m:
        return ""
    if isinstance(m, list):
        m = m[0] if m else None
    if not m:
        return ""
    return m["symbol"]
