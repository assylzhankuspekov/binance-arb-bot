"""
Логирование в CSV: сигналы, сделки, снимки баланса.
"""

import csv
import os
import time
from decimal import Decimal

import config
import state


def ensure_logs() -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    if not os.path.exists(config.SIGNALS_CSV):
        with open(config.SIGNALS_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "ts", "triangle", "usdt_in", "usdt_out_est", "profit_est",
                "dyn_min_profit", "jitter_score", "fill_rate", "snapshot",
            ])
    if not os.path.exists(config.TRADES_CSV):
        with open(config.TRADES_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "ts", "triangle", "mode", "status", "usdt_in", "usdt_out_est", "profit_est",
                "dyn_min_profit", "notes",
            ])
    if not os.path.exists(config.STATE_CSV):
        with open(config.STATE_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts", "mode", "USDT", "BTC", "ETH", "BNB", "exposure_usdt_eq"])


def log_signal(
    tri_name: str,
    usdt_in: Decimal,
    usdt_out: Decimal,
    profit: Decimal,
    dyn_min_profit: Decimal,
    jitter_score_val: Decimal,
    fill_rate_val: Decimal,
    snapshot: str,
) -> None:
    with open(config.SIGNALS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            time.time(), tri_name, str(usdt_in), str(usdt_out), str(profit),
            str(dyn_min_profit), str(jitter_score_val), str(fill_rate_val), snapshot[:500],
        ])


def log_trade(
    tri_name: str,
    status: str,
    usdt_in: Decimal,
    usdt_out: Decimal,
    profit: Decimal,
    dyn_min_profit: Decimal,
    notes: str = "",
) -> None:
    mode = "PAPER" if config.PAPER_TRADING else "LIVE"
    with open(config.TRADES_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            time.time(), tri_name, mode, status,
            str(usdt_in), str(usdt_out), str(profit), str(dyn_min_profit), notes[:300],
        ])


def log_state() -> None:
    exposure = Decimal("0")
    for asset in ("BTC", "ETH", "BNB"):
        amt = state.paper_bal.get(asset, Decimal("0"))
        sym = f"{asset}/USDT"
        if sym in state.TOB and state.TOB[sym]["bid"] > 0:
            mid = (state.TOB[sym]["bid"] + state.TOB[sym]["ask"]) / Decimal("2")
            exposure += amt * mid
    mode = "PAPER" if config.PAPER_TRADING else "LIVE"
    with open(config.STATE_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            time.time(), mode,
            str(state.paper_bal.get("USDT", 0)),
            str(state.paper_bal.get("BTC", 0)),
            str(state.paper_bal.get("ETH", 0)),
            str(state.paper_bal.get("BNB", 0)),
            str(exposure),
        ])
