"""
Состояние бота: top-of-book, jitter, история исполнений, бумажный баланс.
"""

import time
from collections import deque, defaultdict
from decimal import Decimal

import config

# Top-of-book: {"BTC/USDT": {"bid": Decimal, "ask": Decimal, "ts": float}}
TOB: dict = {}

# Прокси волатильности (изменения mid по символам)
JITTER: defaultdict = defaultdict(lambda: deque(maxlen=config.JITTER_WINDOW))

# История исполнений ног (True/False) для расчёта fill-rate
FILL_HISTORY: deque = deque(maxlen=config.FILL_WINDOW)

# Бумажный портфель
paper_bal: defaultdict = defaultdict(Decimal)
paper_bal["USDT"] = config.START_BALANCE_USDT

# Счётчики для Telegram-отчётов
trades_count: int = 0           # количество успешно завершённых циклов (DONE)
best_profit_pct: Decimal | None = None  # лучший профит по сделке, %


def tob_ready(symbols: list) -> bool:
    now = time.time()
    for s in symbols:
        if s not in TOB:
            return False
        if now - TOB[s]["ts"] > config.MAX_TOB_AGE_SEC:
            return False
        if TOB[s]["bid"] <= 0 or TOB[s]["ask"] <= 0:
            return False
    return True


def update_jitter(symbol: str, bid: Decimal, ask: Decimal) -> None:
    mid = (bid + ask) / Decimal("2")
    JITTER[symbol].append(mid)


def jitter_score(symbols: list) -> Decimal:
    """
    Прокси волатильности: среднее |Δmid/mid| по символам за окно.
    """
    scores = []
    for s in symbols:
        mids = JITTER[s]
        if len(mids) < 3:
            continue
        diffs = [
            abs(mids[i] - mids[i - 1]) / mids[i - 1]
            for i in range(1, len(mids))
            if mids[i - 1] != 0
        ]
        if diffs:
            scores.append(sum(diffs) / Decimal(len(diffs)))
    if not scores:
        return Decimal("0")
    return sum(scores) / Decimal(len(scores))


def fill_rate() -> Decimal:
    if not FILL_HISTORY:
        return Decimal("1")
    return Decimal(sum(1 for x in FILL_HISTORY if x)) / Decimal(len(FILL_HISTORY))


def paper_exposure_usdt() -> Decimal:
    exp = Decimal("0")
    for asset in ("BTC", "ETH", "BNB"):
        amt = paper_bal.get(asset, Decimal("0"))
        sym = f"{asset}/USDT"
        if sym in TOB and TOB[sym]["bid"] > 0:
            mid = (TOB[sym]["bid"] + TOB[sym]["ask"]) / Decimal("2")
            exp += amt * mid
    return exp


def init_tob(symbols: list) -> None:
    """Инициализировать TOB нулевыми котировками для всех символов."""
    for s in symbols:
        TOB[s] = {"bid": Decimal("0"), "ask": Decimal("0"), "ts": 0.0}
