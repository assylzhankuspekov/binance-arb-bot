"""
WebSocket-подписка на bookTicker Binance, обновление TOB и jitter.
"""

import asyncio
import json
import ssl
import time
import websockets

from decimal import Decimal

import config
import state
import exchange


def sym_to_binance(symbol: str) -> str:
    return symbol.replace("/", "")


async def ws_book_ticker(symbols: list) -> None:
    streams = "/".join([f"{sym_to_binance(s).lower()}@bookTicker" for s in symbols])
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"

    ssl_ctx = None
    if not config.VERIFY_SSL:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    while True:
        try:
            async with websockets.connect(
                url, ping_interval=20, ping_timeout=20, ssl=ssl_ctx
            ) as ws:
                async for msg in ws:
                    data = json.loads(msg)
                    payload = data.get("data", {})
                    if not isinstance(payload, dict):
                        continue
                    s_id = payload.get("s")
                    sym = exchange.binance_to_sym(s_id)
                    if not sym:
                        continue
                    bid = exchange.d(payload.get("b", "0"))
                    ask = exchange.d(payload.get("a", "0"))
                    state.TOB[sym] = {"bid": bid, "ask": ask, "ts": time.time()}
                    state.update_jitter(sym, bid, ask)
        except Exception as e:
            print(f"[WS] Ошибка подключения к Binance: {e}")
            await asyncio.sleep(5.0)
