"""
Binance Spot Triangular Arbitrage Bot — v3.1
Adds:
1) PAPER TRADING mode (no real orders) + realistic fill simulation
2) Dynamic MIN_PROFIT threshold based on:
   - recent volatility proxy (bid/ask jitter)
   - recent fill-rate (paper or live)
3) Inventory-aware safety (soft exposure caps) so you don’t get stuck in BTC/ETH/BNB
4) Live WS top-of-book (bookTicker) + CSV logs

Install:
  pip install ccxt websockets

Run:
  python bot_v3_1.py

⚠️ Start in PAPER_TRADING=True for 1–3 days.
"""

import asyncio
import json
import os
import time
import csv
import ssl
import warnings
from datetime import datetime
from collections import deque, defaultdict
from decimal import Decimal, ROUND_DOWN
import ccxt
import websockets

# Убрать предупреждения SSL в консоли (InsecureRequestWarning от urllib3)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# ===================== CONFIG =====================
API_KEY = "PUT_YOUR_KEY"
API_SECRET = "PUT_YOUR_SECRET"

PAPER_TRADING = True  # <-- start here; set False for live trading

QUOTE = "USDT"
START_BALANCE_USDT = Decimal("200")   # ~100k ₸ equivalent (adjust to your actual USDT)
CYCLE_USDT = Decimal("20")            # 15–25 USDT recommended

BASE_MIN_PROFIT = Decimal("0.0001")   # 0.01% — занижено для теста, чтобы видеть попытки сделок в CSV (обычно 0.0025 = 0.25%)
MAKER_FEE = Decimal("0.00075")        # ~0.075% if paying fees with BNB
TAKER_FEE = Decimal("0.0010")         # emergency flatten estimate
SLIP_RESERVE = Decimal("0.00025")     # extra cushion
ORDER_TIMEOUT_SEC = Decimal("2.0")
COOLDOWN_AFTER_TRADE_SEC = 1.5

# Top-of-book freshness
MAX_TOB_AGE_SEC = 0.8

# Risk caps (inventory-aware)
MAX_EXPOSURE_USDT_EQ = Decimal("60")  # max allowed exposure in non-USDT before forcing flatten (paper/live)
FORCE_FLATTEN_ON_EXPOSURE = True

# SSL: отключить проверку сертификата, если ошибка из-за корпоративного прокси
VERIFY_SSL = False

# Paper fill simulation
# If maker price is too far from mid, assume it won't fill. Keep it conservative.
PAPER_MAX_MID_DISTANCE_TICKS = 2
PAPER_FILL_PROB_BASE = 0.85  # base probability of fill when within distance

# Dynamic threshold tuning windows
JITTER_WINDOW = 120          # ~ last N updates per symbol
FILL_WINDOW = 50             # last N trade legs for fill-rate

# CSV logs
LOG_DIR = "./logs"
SIGNALS_CSV = os.path.join(LOG_DIR, "arb_signals_v3_1.csv")
TRADES_CSV  = os.path.join(LOG_DIR, "arb_trades_v3_1.csv")
STATE_CSV   = os.path.join(LOG_DIR, "arb_state_v3_1.csv")

TRIANGLES = [
    {"name": "USDT-BTC-ETH-USDT",
     "legs": [("BTC/USDT", "buy"), ("ETH/BTC", "buy"), ("ETH/USDT", "sell")]},
    {"name": "USDT-BTC-BNB-USDT",
     "legs": [("BTC/USDT", "buy"), ("BNB/BTC", "buy"), ("BNB/USDT", "sell")]},
    {"name": "USDT-ETH-BNB-USDT",
     "legs": [("ETH/USDT", "buy"), ("BNB/ETH", "buy"), ("BNB/USDT", "sell")]},
]

# ===================== EXCHANGE =====================
ex = ccxt.binance({
    "apiKey": API_KEY,
    "secret": API_SECRET,
    "enableRateLimit": True,
    "options": {"defaultType": "spot"},
})
if not VERIFY_SSL:
    ex.verify = False

# ===================== STATE =====================
TOB = {}  # {"BTC/USDT": {"bid": Decimal, "ask": Decimal, "ts": float}}
JITTER = defaultdict(lambda: deque(maxlen=JITTER_WINDOW))  # price jitter proxy (mid changes)
FILL_HISTORY = deque(maxlen=FILL_WINDOW)  # booleans for legs filled

# Paper portfolio
paper_bal = defaultdict(Decimal)
paper_bal["USDT"] = START_BALANCE_USDT

# ===================== HELPERS =====================
def d(x) -> Decimal:
    return Decimal(str(x))

def ensure_logs():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(SIGNALS_CSV):
        with open(SIGNALS_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts", "triangle", "usdt_in", "usdt_out_est", "profit_est",
                        "dyn_min_profit", "jitter_score", "fill_rate", "snapshot"])
    if not os.path.exists(TRADES_CSV):
        with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts", "triangle", "mode", "status", "usdt_in", "usdt_out_est", "profit_est",
                        "dyn_min_profit", "notes"])
    if not os.path.exists(STATE_CSV):
        with open(STATE_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts", "mode", "USDT", "BTC", "ETH", "BNB", "exposure_usdt_eq"])

def log_signal(tri_name, usdt_in, usdt_out, profit, dyn_min_profit, jitter_score, fill_rate, snapshot):
    with open(SIGNALS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([time.time(), tri_name, str(usdt_in), str(usdt_out), str(profit),
                    str(dyn_min_profit), str(jitter_score), str(fill_rate), snapshot[:500]])

def log_trade(tri_name, status, usdt_in, usdt_out, profit, dyn_min_profit, notes=""):
    with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([time.time(), tri_name, "PAPER" if PAPER_TRADING else "LIVE",
                    status, str(usdt_in), str(usdt_out), str(profit), str(dyn_min_profit), notes[:300]])

def log_state():
    # approximate exposure in USDT: sum(non-USDT balances * mid USDT price if available)
    exposure = Decimal("0")
    for asset in ("BTC", "ETH", "BNB"):
        amt = paper_bal.get(asset, Decimal("0"))
        sym = f"{asset}/USDT"
        if sym in TOB and TOB[sym]["bid"] > 0:
            mid = (TOB[sym]["bid"] + TOB[sym]["ask"]) / Decimal("2")
            exposure += amt * mid
    with open(STATE_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([time.time(), "PAPER" if PAPER_TRADING else "LIVE",
                    str(paper_bal.get("USDT", 0)),
                    str(paper_bal.get("BTC", 0)),
                    str(paper_bal.get("ETH", 0)),
                    str(paper_bal.get("BNB", 0)),
                    str(exposure)])

def parse_base_quote(symbol: str):
    base, quote = symbol.split("/")
    return base, quote

def quantize_amount(symbol, amount: Decimal) -> Decimal:
    m = ex.market(symbol)
    prec = m.get("precision", {}).get("amount")
    if prec is None:
        return amount
    q = Decimal("1e-" + str(prec))
    return amount.quantize(q, rounding=ROUND_DOWN)

def quantize_price(symbol, price: Decimal) -> Decimal:
    m = ex.market(symbol)
    prec = m.get("precision", {}).get("price")
    if prec is None:
        return price
    q = Decimal("1e-" + str(prec))
    return price.quantize(q, rounding=ROUND_DOWN)

def tick_size(symbol) -> Decimal:
    prec = ex.market(symbol).get("precision", {}).get("price")
    if prec is None:
        return Decimal("0")
    return Decimal("1e-" + str(prec))

def tob_ready(symbols):
    now = time.time()
    for s in symbols:
        if s not in TOB:
            return False
        if now - TOB[s]["ts"] > MAX_TOB_AGE_SEC:
            return False
        if TOB[s]["bid"] <= 0 or TOB[s]["ask"] <= 0:
            return False
    return True

def update_jitter(symbol: str, bid: Decimal, ask: Decimal):
    mid = (bid + ask) / Decimal("2")
    JITTER[symbol].append(mid)

def jitter_score(symbols) -> Decimal:
    """
    Simple volatility proxy:
    average(abs(Δmid)/mid) across symbols, last window.
    """
    scores = []
    for s in symbols:
        mids = JITTER[s]
        if len(mids) < 3:
            continue
        diffs = [abs(mids[i] - mids[i-1]) / mids[i-1] for i in range(1, len(mids)) if mids[i-1] != 0]
        if diffs:
            scores.append(sum(diffs) / Decimal(len(diffs)))
    if not scores:
        return Decimal("0")
    return sum(scores) / Decimal(len(scores))

def fill_rate() -> Decimal:
    if not FILL_HISTORY:
        return Decimal("1")
    return Decimal(sum(1 for x in FILL_HISTORY if x)) / Decimal(len(FILL_HISTORY))

def dynamic_min_profit(base: Decimal, j_score: Decimal, f_rate: Decimal) -> Decimal:
    """
    Raise threshold when:
    - volatility/jitter is higher
    - fill-rate is poor (you'll waste time/fees)
    """
    # jitter add-on: up to +0.20% if jitter high
    # (scale factor tuned for typical crypto bookTicker noise)
    jitter_add = min(Decimal("0.0020"), j_score * Decimal("40"))  # tweak if needed

    # fill penalty: if fill-rate < 0.8 add up to +0.25%
    fill_pen = Decimal("0")
    if f_rate < Decimal("0.8"):
        fill_pen = (Decimal("0.8") - f_rate) * Decimal("0.0125")  # 0.1 drop => +0.125%
        fill_pen = min(fill_pen, Decimal("0.0025"))

    return base + jitter_add + fill_pen

def estimate_triangle(usdt_in: Decimal, legs):
    amount = usdt_in
    snap_parts = []
    for sym, side in legs:
        bid = TOB[sym]["bid"]
        ask = TOB[sym]["ask"]
        snap_parts.append(f"{sym}:b={bid},a={ask}")
        if side == "buy":
            amount = (amount / ask) * (Decimal("1") - MAKER_FEE)
        else:
            amount = (amount * bid) * (Decimal("1") - MAKER_FEE)
    amount *= (Decimal("1") - SLIP_RESERVE)
    profit = (amount / usdt_in) - Decimal("1")
    return amount, profit, "; ".join(snap_parts)

def maker_price(symbol, side, bid: Decimal, ask: Decimal) -> Decimal:
    """
    Maker quoting improved:
    BUY: bid + tick (but < ask)
    SELL: ask - tick (but > bid)
    """
    t = tick_size(symbol)
    if t <= 0:
        return quantize_price(symbol, bid if side == "buy" else ask)

    if side == "buy":
        p = bid + t
        if p >= ask:
            p = bid
        return quantize_price(symbol, p)
    else:
        p = ask - t
        if p <= bid:
            p = ask
        return quantize_price(symbol, p)

# ===================== PAPER SIM =====================
def paper_can_fill(symbol, side, price: Decimal) -> bool:
    """
    Conservative fill simulation:
    - Compare to mid; if too far => no fill
    - Otherwise probabilistic fill
    """
    bid = TOB[symbol]["bid"]; ask = TOB[symbol]["ask"]
    mid = (bid + ask) / Decimal("2")
    t = tick_size(symbol)
    if t <= 0:
        t = (ask - bid) / Decimal("10") if ask > bid else Decimal("0.00000001")
    max_dist = t * Decimal(PAPER_MAX_MID_DISTANCE_TICKS)

    dist = abs(price - mid)
    if dist > max_dist:
        return False

    # slightly lower probability if spread is tiny (harder to get filled as maker)
    spread = ask - bid
    spread_factor = Decimal("1")
    if mid > 0 and (spread / mid) < Decimal("0.00010"):
        spread_factor = Decimal("0.85")

    # use time as pseudo randomness (no external RNG needed)
    p = Decimal(str(PAPER_FILL_PROB_BASE)) * spread_factor
    # deterministic-ish:
    r = Decimal(str((time.time_ns() % 1000) / 1000))
    return r < p

def paper_exec_leg(symbol, side, amount_base: Decimal, price: Decimal) -> (bool, str, Decimal):
    """
    Apply paper trade balances.
    Returns: (filled, note, filled_amount_base)
    """
    base, quote = parse_base_quote(symbol)
    bid = TOB[symbol]["bid"]; ask = TOB[symbol]["ask"]

    if not paper_can_fill(symbol, side, price):
        FILL_HISTORY.append(False)
        return False, "not_filled_sim", Decimal("0")

    if side == "buy":
        # spend quote to buy base at price
        cost_quote = amount_base * price
        if paper_bal[quote] < cost_quote:
            FILL_HISTORY.append(False)
            return False, "insufficient_quote", Decimal("0")
        paper_bal[quote] -= cost_quote
        recv_base = amount_base * (Decimal("1") - MAKER_FEE)
        paper_bal[base] += recv_base
        FILL_HISTORY.append(True)
        return True, "filled", recv_base
    else:
        # sell base for quote at price
        if paper_bal[base] < amount_base:
            FILL_HISTORY.append(False)
            return False, "insufficient_base", Decimal("0")
        paper_bal[base] -= amount_base
        recv_quote = (amount_base * price) * (Decimal("1") - MAKER_FEE)
        paper_bal[quote] += recv_quote
        FILL_HISTORY.append(True)
        return True, "filled", amount_base

def paper_flatten(asset: str, amount_asset: Decimal) -> str:
    if asset == "USDT":
        return "Already USDT"
    sym = f"{asset}/USDT"
    if sym not in TOB:
        return f"No TOB for {sym}"
    bid = TOB[sym]["bid"]
    if amount_asset <= 0:
        return "Nothing to flatten"
    # taker-ish flatten at bid with taker fee
    if paper_bal[asset] < amount_asset:
        amount_asset = paper_bal[asset]
    paper_bal[asset] -= amount_asset
    recv = (amount_asset * bid) * (Decimal("1") - TAKER_FEE)
    paper_bal["USDT"] += recv
    return f"Flattened {amount_asset} {asset} -> {recv} USDT (sim taker)"

def paper_exposure_usdt() -> Decimal:
    exp = Decimal("0")
    for asset in ("BTC", "ETH", "BNB"):
        amt = paper_bal.get(asset, Decimal("0"))
        sym = f"{asset}/USDT"
        if sym in TOB and TOB[sym]["bid"] > 0:
            mid = (TOB[sym]["bid"] + TOB[sym]["ask"]) / Decimal("2")
            exp += amt * mid
    return exp

# ===================== EXECUTE TRIANGLE (PAPER or LIVE) =====================
def execute_triangle(tri, dyn_min_profit: Decimal):
    legs = tri["legs"]
    tri_name = tri["name"]
    usdt_in = CYCLE_USDT

    usdt_out_est, profit_est, snapshot = estimate_triangle(usdt_in, legs)

    # signal log always
    log_signal(tri_name, usdt_in, usdt_out_est, profit_est,
               dyn_min_profit, jitter_score(sorted(TOB.keys())), fill_rate(), snapshot)

    if profit_est <= dyn_min_profit:
        return False

    # inventory safety (paper)
    if PAPER_TRADING and FORCE_FLATTEN_ON_EXPOSURE:
        exp = paper_exposure_usdt()
        if exp > MAX_EXPOSURE_USDT_EQ:
            # flatten all
            notes = []
            for a in ("BTC", "ETH", "BNB"):
                if paper_bal[a] > 0:
                    notes.append(paper_flatten(a, paper_bal[a]))
            log_trade(tri_name, "FORCE_FLATTEN", usdt_in, usdt_out_est, profit_est, dyn_min_profit, " | ".join(notes))
            return False

    # ----- PAPER TRADING -----
    if PAPER_TRADING:
        if paper_bal["USDT"] < usdt_in:
            log_trade(tri_name, "SKIP", usdt_in, usdt_out_est, profit_est, dyn_min_profit, "paper: insufficient USDT")
            return False

        # Leg1
        sym1, side1 = legs[0]
        bid1 = TOB[sym1]["bid"]; ask1 = TOB[sym1]["ask"]
        p1 = maker_price(sym1, side1, bid1, ask1)
        amt1 = quantize_amount(sym1, usdt_in / p1)
        ok1, n1, filled1 = paper_exec_leg(sym1, side1, amt1, p1)
        if not ok1:
            log_trade(tri_name, "ABORT", usdt_in, usdt_out_est, profit_est, dyn_min_profit, f"paper leg1 {n1}")
            return False

        base1, _ = parse_base_quote(sym1)

        # Leg2
        sym2, side2 = legs[1]
        bid2 = TOB[sym2]["bid"]; ask2 = TOB[sym2]["ask"]
        p2 = maker_price(sym2, side2, bid2, ask2)
        amt2 = quantize_amount(sym2, filled1 / p2)
        ok2, n2, filled2 = paper_exec_leg(sym2, side2, amt2, p2)
        if not ok2:
            # emergency flatten what we likely hold (base1)
            fl = paper_flatten(base1, paper_bal[base1])
            log_trade(tri_name, "FLATTEN", usdt_in, usdt_out_est, profit_est, dyn_min_profit, f"paper leg2 {n2} | {fl}")
            return False

        base2, _ = parse_base_quote(sym2)

        # Leg3
        sym3, side3 = legs[2]
        bid3 = TOB[sym3]["bid"]; ask3 = TOB[sym3]["ask"]
        p3 = maker_price(sym3, side3, bid3, ask3)
        amt3 = quantize_amount(sym3, filled2)
        ok3, n3, _ = paper_exec_leg(sym3, side3, amt3, p3)
        if not ok3:
            fl = paper_flatten(base2, paper_bal[base2])
            log_trade(tri_name, "FLATTEN", usdt_in, usdt_out_est, profit_est, dyn_min_profit, f"paper leg3 {n3} | {fl}")
            return False

        log_trade(tri_name, "DONE", usdt_in, usdt_out_est, profit_est, dyn_min_profit, "paper cycle done")
        log_state()
        return True

    # ----- LIVE TRADING (optional) -----
    # Keep simple: same flow as v3.0 but gated by dyn_min_profit
    # (If you want, I can paste the full live-maker execution here too.)
    log_trade(tri_name, "SKIP", usdt_in, usdt_out_est, profit_est, dyn_min_profit,
              "LIVE mode not implemented in this v3.1 snippet — keep PAPER_TRADING=True")
    return False

# ===================== WEBSOCKET FEED =====================
def sym_to_binance(symbol: str) -> str:
    return symbol.replace("/", "")

def binance_to_sym(s: str) -> str:
    m = ex.markets_by_id.get(s)
    if not m:
        return ""
    # У Binance в ccxt один id может соответствовать списку рынков (spot/margin) — берём первый
    if isinstance(m, list):
        m = m[0] if m else None
    if not m:
        return ""
    return m["symbol"]

async def ws_book_ticker(symbols):
    streams = "/".join([f"{sym_to_binance(s).lower()}@bookTicker" for s in symbols])
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"

    # Для работы за прокси: отключить проверку SSL (как для ccxt)
    ssl_ctx = None
    if not VERIFY_SSL:
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
                    sym = binance_to_sym(s_id)
                    if not sym:
                        continue
                    bid = d(payload.get("b", "0"))
                    ask = d(payload.get("a", "0"))
                    TOB[sym] = {"bid": bid, "ask": ask, "ts": time.time()}
                    update_jitter(sym, bid, ask)
        except Exception as e:
            print(f"[WS] Ошибка подключения к Binance: {e}")
            await asyncio.sleep(5.0)

async def trader_loop(symbols):
    last_trade_ts = 0.0
    last_status_ts = 0.0
    last_wait_ts = 0.0  # когда последний раз печатали "ожидание котировок"

    while True:
        await asyncio.sleep(0.05)
        now = time.time()

        if not tob_ready(symbols):
            # Котировок ещё нет — раз в 15 сек выводим статус, чтобы было видно, что бот жив
            if now - last_wait_ts >= 15.0:
                last_wait_ts = now
                parts = []
                for s in symbols:
                    if s in TOB and TOB[s].get("ts"):
                        age = now - TOB[s]["ts"]
                        parts.append(f"{s}: {age:.1f}с")
                    else:
                        parts.append(f"{s}: нет")
                print(f"[...] Ожидание котировок с Binance… {', '.join(parts)}")
            continue

        # Раз в 30 сек — статус в консоль и запись в CSV (чтобы файлы не были пустыми)
        if now - last_status_ts >= 30.0:
            last_status_ts = now
            tob_age = max((now - TOB[s]["ts"]) for s in symbols) if symbols else 0
            best = None
            for tri in TRIANGLES:
                out_est, prof_est, snap = estimate_triangle(CYCLE_USDT, tri["legs"])
                if best is None or prof_est > best["profit"]:
                    best = {"tri": tri, "profit": prof_est, "out": out_est, "snapshot": snap}
            if best:
                j = jitter_score(symbols)
                fr = fill_rate()
                dyn = dynamic_min_profit(BASE_MIN_PROFIT, j, fr)
                t = datetime.now().strftime("%H:%M:%S")
                print(f"[OK] {t} | котировки {tob_age:.2f} сек назад | лучший {best['tri']['name']} ~{best['profit']*100:.3f}% | порог {dyn*100:.3f}% | fill {fr:.2f}")
                # Периодическая запись в arb_signals — в CSV появятся данные даже без сделок
                log_signal(best["tri"]["name"], CYCLE_USDT, best["out"], best["profit"], dyn, j, fr, best["snapshot"])

        j = jitter_score(symbols)
        fr = fill_rate()
        dyn = dynamic_min_profit(BASE_MIN_PROFIT, j, fr)

        # pick best triangle
        best = None
        for tri in TRIANGLES:
            out_est, prof_est, _ = estimate_triangle(CYCLE_USDT, tri["legs"])
            if best is None or prof_est > best["profit"]:
                best = {"tri": tri, "out": out_est, "profit": prof_est}

        if not best or best["profit"] <= dyn:
            continue

        now = time.time()
        if now - last_trade_ts < COOLDOWN_AFTER_TRADE_SEC:
            continue

        tri = best["tri"]
        print(f"[SIGNAL] {tri['name']} est {best['profit']*100:.3f}% | dynMin {dyn*100:.3f}% | fill {fr:.2f} | jitter {j:.6f}")

        executed = await asyncio.to_thread(execute_triangle, tri, dyn)
        if executed:
            last_trade_ts = time.time()

async def main():
    ensure_logs()

    # В бумажном режиме с заглушкой API ключа загружаем только публичные рынки (без /sapi/...)
    if PAPER_TRADING and API_KEY in ("PUT_YOUR_KEY", "PUT_YOUR_KEY_HERE", ""):
        try:
            ex.options["fetchMargins"] = False  # не вызывать /sapi/margin/... (требует ключ)
            markets = ex.fetch_markets()
            ex.set_markets(markets)
        except Exception as e:
            print(f"Ошибка загрузки рынков: {e}")
            raise
    else:
        ex.load_markets()

    symbols = sorted({sym for tri in TRIANGLES for (sym, _) in tri["legs"]})
    for s in symbols:
        TOB[s] = {"bid": Decimal("0"), "ask": Decimal("0"), "ts": 0.0}

    print("[OK] Бот запущен. Ожидание котировок с Binance… Раз в 30 сек — статус в консоль.")
    await asyncio.gather(
        ws_book_ticker(symbols),
        trader_loop(symbols),
    )

if __name__ == "__main__":
    asyncio.run(main())