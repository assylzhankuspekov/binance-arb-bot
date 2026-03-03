"""
Исполнение треугольного арбитража: оценка профита, maker-цены, paper/live логика.
"""

import time
from decimal import Decimal

import config
import state
import exchange
import logs


def dynamic_min_profit(base: Decimal, j_score: Decimal, f_rate: Decimal) -> Decimal:
    """
    Повышать порог при высокой волатильности (jitter) и низком fill-rate.
    """
    jitter_add = min(Decimal("0.0020"), j_score * Decimal("40"))
    fill_pen = Decimal("0")
    if f_rate < Decimal("0.8"):
        fill_pen = (Decimal("0.8") - f_rate) * Decimal("0.0125")
        fill_pen = min(fill_pen, Decimal("0.0025"))
    return base + jitter_add + fill_pen


def estimate_triangle(usdt_in: Decimal, legs: list) -> tuple[Decimal, Decimal, str]:
    amount = usdt_in
    snap_parts = []
    for sym, side in legs:
        bid = state.TOB[sym]["bid"]
        ask = state.TOB[sym]["ask"]
        snap_parts.append(f"{sym}:b={bid},a={ask}")
        if side == "buy":
            amount = (amount / ask) * (Decimal("1") - config.MAKER_FEE)
        else:
            amount = (amount * bid) * (Decimal("1") - config.MAKER_FEE)
    amount *= (Decimal("1") - config.SLIP_RESERVE)
    profit = (amount / usdt_in) - Decimal("1")
    return amount, profit, "; ".join(snap_parts)


def maker_price(symbol: str, side: str, bid: Decimal, ask: Decimal) -> Decimal:
    """
    BUY: bid + tick (но < ask); SELL: ask - tick (но > bid).
    """
    t = exchange.tick_size(symbol)
    if t <= 0:
        return exchange.quantize_price(symbol, bid if side == "buy" else ask)
    if side == "buy":
        p = bid + t
        if p >= ask:
            p = bid
        return exchange.quantize_price(symbol, p)
    else:
        p = ask - t
        if p <= bid:
            p = ask
        return exchange.quantize_price(symbol, p)


def paper_can_fill(symbol: str, side: str, price: Decimal) -> bool:
    bid = state.TOB[symbol]["bid"]
    ask = state.TOB[symbol]["ask"]
    mid = (bid + ask) / Decimal("2")
    t = exchange.tick_size(symbol)
    if t <= 0:
        t = (ask - bid) / Decimal("10") if ask > bid else Decimal("0.00000001")
    max_dist = t * Decimal(config.PAPER_MAX_MID_DISTANCE_TICKS)
    if abs(price - mid) > max_dist:
        return False
    spread = ask - bid
    spread_factor = Decimal("1")
    if mid > 0 and (spread / mid) < Decimal("0.00010"):
        spread_factor = Decimal("0.85")
    p = Decimal(str(config.PAPER_FILL_PROB_BASE)) * spread_factor
    r = Decimal(str((time.time_ns() % 1000) / 1000))
    return r < p


def paper_exec_leg(
    symbol: str, side: str, amount_base: Decimal, price: Decimal
) -> tuple[bool, str, Decimal]:
    """
    Применить бумажную сделку к балансу. Возвращает (filled, note, filled_amount_base).
    """
    base, quote = exchange.parse_base_quote(symbol)
    if not paper_can_fill(symbol, side, price):
        state.FILL_HISTORY.append(False)
        return False, "not_filled_sim", Decimal("0")
    if side == "buy":
        cost_quote = amount_base * price
        if state.paper_bal[quote] < cost_quote:
            state.FILL_HISTORY.append(False)
            return False, "insufficient_quote", Decimal("0")
        state.paper_bal[quote] -= cost_quote
        recv_base = amount_base * (Decimal("1") - config.MAKER_FEE)
        state.paper_bal[base] += recv_base
        state.FILL_HISTORY.append(True)
        return True, "filled", recv_base
    else:
        if state.paper_bal[base] < amount_base:
            state.FILL_HISTORY.append(False)
            return False, "insufficient_base", Decimal("0")
        state.paper_bal[base] -= amount_base
        recv_quote = (amount_base * price) * (Decimal("1") - config.MAKER_FEE)
        state.paper_bal[quote] += recv_quote
        state.FILL_HISTORY.append(True)
        return True, "filled", amount_base


def paper_flatten(asset: str, amount_asset: Decimal) -> str:
    if asset == "USDT":
        return "Already USDT"
    sym = f"{asset}/USDT"
    if sym not in state.TOB:
        return f"No TOB for {sym}"
    bid = state.TOB[sym]["bid"]
    if amount_asset <= 0:
        return "Nothing to flatten"
    if state.paper_bal[asset] < amount_asset:
        amount_asset = state.paper_bal[asset]
    state.paper_bal[asset] -= amount_asset
    recv = (amount_asset * bid) * (Decimal("1") - config.TAKER_FEE)
    state.paper_bal["USDT"] += recv
    return f"Flattened {amount_asset} {asset} -> {recv} USDT (sim taker)"


def execute_triangle(tri: dict, dyn_min_profit: Decimal) -> bool:
    legs = tri["legs"]
    tri_name = tri["name"]
    usdt_in = config.CYCLE_USDT

    usdt_out_est, profit_est, snapshot = estimate_triangle(usdt_in, legs)
    symbols = sorted(state.TOB.keys())
    logs.log_signal(
        tri_name, usdt_in, usdt_out_est, profit_est,
        dyn_min_profit, state.jitter_score(symbols), state.fill_rate(), snapshot,
    )

    if profit_est <= dyn_min_profit:
        return False

    if config.PAPER_TRADING and config.FORCE_FLATTEN_ON_EXPOSURE:
        exp = state.paper_exposure_usdt()
        if exp > config.MAX_EXPOSURE_USDT_EQ:
            notes = []
            for a in ("BTC", "ETH", "BNB"):
                if state.paper_bal[a] > 0:
                    notes.append(paper_flatten(a, state.paper_bal[a]))
            logs.log_trade(
                tri_name, "FORCE_FLATTEN", usdt_in, usdt_out_est, profit_est,
                dyn_min_profit, " | ".join(notes),
            )
            return False

    if config.PAPER_TRADING:
        if state.paper_bal["USDT"] < usdt_in:
            logs.log_trade(
                tri_name, "SKIP", usdt_in, usdt_out_est, profit_est, dyn_min_profit,
                "paper: insufficient USDT",
            )
            return False

        # Leg1
        sym1, side1 = legs[0]
        bid1 = state.TOB[sym1]["bid"]
        ask1 = state.TOB[sym1]["ask"]
        p1 = maker_price(sym1, side1, bid1, ask1)
        amt1 = exchange.quantize_amount(sym1, usdt_in / p1)
        ok1, n1, filled1 = paper_exec_leg(sym1, side1, amt1, p1)
        if not ok1:
            logs.log_trade(tri_name, "ABORT", usdt_in, usdt_out_est, profit_est, dyn_min_profit, f"paper leg1 {n1}")
            return False
        base1, _ = exchange.parse_base_quote(sym1)

        # Leg2
        sym2, side2 = legs[1]
        bid2 = state.TOB[sym2]["bid"]
        ask2 = state.TOB[sym2]["ask"]
        p2 = maker_price(sym2, side2, bid2, ask2)
        amt2 = exchange.quantize_amount(sym2, filled1 / p2)
        ok2, n2, filled2 = paper_exec_leg(sym2, side2, amt2, p2)
        if not ok2:
            fl = paper_flatten(base1, state.paper_bal[base1])
            logs.log_trade(
                tri_name, "FLATTEN", usdt_in, usdt_out_est, profit_est, dyn_min_profit,
                f"paper leg2 {n2} | {fl}",
            )
            return False
        base2, _ = exchange.parse_base_quote(sym2)

        # Leg3
        sym3, side3 = legs[2]
        bid3 = state.TOB[sym3]["bid"]
        ask3 = state.TOB[sym3]["ask"]
        p3 = maker_price(sym3, side3, bid3, ask3)
        amt3 = exchange.quantize_amount(sym3, filled2)
        ok3, n3, _ = paper_exec_leg(sym3, side3, amt3, p3)
        if not ok3:
            fl = paper_flatten(base2, state.paper_bal[base2])
            logs.log_trade(
                tri_name, "FLATTEN", usdt_in, usdt_out_est, profit_est, dyn_min_profit,
                f"paper leg3 {n3} | {fl}",
            )
            return False

        logs.log_trade(tri_name, "DONE", usdt_in, usdt_out_est, profit_est, dyn_min_profit, "paper cycle done")
        logs.log_state()
        state.trades_count += 1
        if state.best_profit_pct is None or profit_est > state.best_profit_pct:
            state.best_profit_pct = profit_est
        if config.TELEGRAM_ENABLED:
            import telegram_notify
            telegram_notify.send_trade_notification(tri_name, "DONE", usdt_in, usdt_out_est, profit_est)
        return True

    logs.log_trade(
        tri_name, "SKIP", usdt_in, usdt_out_est, profit_est, dyn_min_profit,
        "LIVE mode not implemented — keep PAPER_TRADING=True",
    )
    return False
