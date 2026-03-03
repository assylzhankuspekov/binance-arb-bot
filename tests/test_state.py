"""
Юнит-тесты: jitter_score, fill_rate, tob_ready, paper_exposure_usdt.

Запуск:
  pytest tests/test_state.py -v
"""

import time
import pytest
from decimal import Decimal
from collections import deque, defaultdict

import config
import state


@pytest.fixture(autouse=True)
def reset_state():
    """Сбрасывать глобальное состояние перед тестом (где нужно)."""
    yield
    # после теста при необходимости можно очистить state для изоляции


def test_jitter_score_empty_returns_zero():
    """При пустом окне jitter_score = 0."""
    state.JITTER.clear()
    assert state.jitter_score(["BTC/USDT"]) == Decimal("0")


def test_jitter_score_with_few_points_skipped():
    """Меньше 3 точек по символу — символ не учитывается."""
    state.JITTER.clear()
    q = deque([Decimal("100"), Decimal("101")], maxlen=10)
    state.JITTER["BTC/USDT"] = q
    assert state.jitter_score(["BTC/USDT"]) == Decimal("0")


def test_jitter_score_computes_average_delta():
    """jitter_score считает среднее |Δmid|/mid."""
    state.JITTER.clear()
    # mid: 100 -> 101 -> 100.5 => относительные изменения 0.01 и ~0.005
    q = deque([Decimal("100"), Decimal("101"), Decimal("100.5")], maxlen=10)
    state.JITTER["BTC/USDT"] = q
    score = state.jitter_score(["BTC/USDT"])
    assert score > 0
    assert score < Decimal("0.02")


def test_fill_rate_empty_returns_one():
    """При пустой истории fill_rate = 1."""
    state.FILL_HISTORY.clear()
    assert state.fill_rate() == Decimal("1")


def test_fill_rate_half_filled():
    """Половина True — fill_rate = 0.5."""
    state.FILL_HISTORY.clear()
    for _ in range(5):
        state.FILL_HISTORY.append(True)
    for _ in range(5):
        state.FILL_HISTORY.append(False)
    assert state.fill_rate() == Decimal("0.5")


def test_tob_ready_false_when_missing_symbol():
    """tob_ready False, если нет котировки по символу."""
    state.TOB.clear()
    state.TOB["BTC/USDT"] = {"bid": Decimal("1"), "ask": Decimal("1"), "ts": time.time()}
    assert state.tob_ready(["BTC/USDT", "ETH/USDT"]) is False


def test_tob_ready_false_when_stale():
    """tob_ready False, если котировка устарела."""
    state.TOB.clear()
    state.TOB["BTC/USDT"] = {"bid": Decimal("1"), "ask": Decimal("1"), "ts": time.time() - 10}
    assert state.tob_ready(["BTC/USDT"]) is False


def test_tob_ready_true_when_fresh():
    """tob_ready True при свежих котировках."""
    state.TOB.clear()
    state.TOB["BTC/USDT"] = {"bid": Decimal("1"), "ask": Decimal("2"), "ts": time.time()}
    assert state.tob_ready(["BTC/USDT"]) is True


def test_paper_exposure_usdt_no_holdings():
    """Без альткоинов экспозиция 0."""
    state.TOB["BTC/USDT"] = {"bid": Decimal("50000"), "ask": Decimal("50000"), "ts": 0}
    state.paper_bal["BTC"] = Decimal("0")
    state.paper_bal["ETH"] = Decimal("0")
    state.paper_bal["BNB"] = Decimal("0")
    assert state.paper_exposure_usdt() == Decimal("0")


def test_paper_exposure_usdt_with_btc():
    """Экспозиция = сумма (баланс * mid) по BTC, ETH, BNB."""
    state.TOB["BTC/USDT"] = {"bid": Decimal("50000"), "ask": Decimal("50100"), "ts": 0}
    state.TOB["ETH/USDT"] = {"bid": Decimal("2500"), "ask": Decimal("2510"), "ts": 0}
    state.TOB["BNB/USDT"] = {"bid": Decimal("300"), "ask": Decimal("302"), "ts": 0}
    state.paper_bal["BTC"] = Decimal("0.001")   # mid 50050 => 50.05
    state.paper_bal["ETH"] = Decimal("0")
    state.paper_bal["BNB"] = Decimal("0")
    exp = state.paper_exposure_usdt()
    expected = Decimal("0.001") * (Decimal("50000") + Decimal("50100")) / 2
    assert abs(exp - expected) < Decimal("1")
