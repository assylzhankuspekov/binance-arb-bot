"""
Юнит-тесты: расчёт профита, динамический порог, оценка треугольника.

Запуск из корня проекта:
  pytest tests/ -v
  pytest tests/test_execution.py -v
"""

import pytest
from decimal import Decimal

import config
import state
import execution


# --------------- dynamic_min_profit (чистая функция) ---------------

def test_dynamic_min_profit_base_only():
    """Без jitter и с fill_rate=1 порог = base."""
    base = Decimal("0.001")
    assert execution.dynamic_min_profit(base, Decimal("0"), Decimal("1")) == base


def test_dynamic_min_profit_jitter_increases_threshold():
    """Высокий jitter повышает минимальный порог."""
    base = Decimal("0.001")
    low = execution.dynamic_min_profit(base, Decimal("0"), Decimal("1"))
    high = execution.dynamic_min_profit(base, Decimal("0.001"), Decimal("1"))
    assert high > low
    assert high <= base + Decimal("0.002")  # cap ~0.20%


def test_dynamic_min_profit_low_fill_rate_increases_threshold():
    """Низкий fill-rate повышает порог."""
    base = Decimal("0.001")
    high_fr = execution.dynamic_min_profit(base, Decimal("0"), Decimal("1"))
    low_fr = execution.dynamic_min_profit(base, Decimal("0"), Decimal("0.5"))
    assert low_fr > high_fr


def test_dynamic_min_profit_fill_penalty_capped():
    """Штраф за fill-rate ограничен сверху."""
    base = Decimal("0.001")
    # fill_rate 0 => большая добавка, но не больше 0.0025
    result = execution.dynamic_min_profit(base, Decimal("0"), Decimal("0"))
    assert result == base + Decimal("0.0025")


# --------------- estimate_triangle (нужен TOB в state) ---------------

@pytest.fixture
def tob_triangle():
    """TOB для одного треугольника: USDT->BTC->ETH->USDT."""
    legs = [
        ("BTC/USDT", "buy"),   # тратим USDT, получаем BTC по ask
        ("ETH/BTC", "buy"),    # тратим BTC, получаем ETH по ask
        ("ETH/USDT", "sell"),  # продаём ETH по bid за USDT
    ]
    # Реалистичные котировки (упрощённо)
    state.TOB["BTC/USDT"] = {"bid": Decimal("50000"), "ask": Decimal("50010"), "ts": 0}
    state.TOB["ETH/BTC"] = {"bid": Decimal("0.05"), "ask": Decimal("0.05002"), "ts": 0}
    state.TOB["ETH/USDT"] = {"bid": Decimal("2500"), "ask": Decimal("2502"), "ts": 0}
    yield
    # очистка не обязательна, т.к. другие тесты могут перезаписать


def test_estimate_triangle_returns_three_values(tob_triangle):
    """estimate_triangle возвращает (amount_out, profit, snapshot)."""
    usdt_in = Decimal("100")
    legs = [("BTC/USDT", "buy"), ("ETH/BTC", "buy"), ("ETH/USDT", "sell")]
    amount, profit, snapshot = execution.estimate_triangle(usdt_in, legs)
    assert amount > 0
    assert "BTC/USDT" in snapshot and "ETH/USDT" in snapshot
    # При симметричном спреде и комиссиях профит обычно отрицательный или малый
    assert profit > Decimal("-0.01")  # не катастрофа


def test_estimate_triangle_profit_formula(tob_triangle):
    """Профит = (amount_out / usdt_in) - 1."""
    usdt_in = Decimal("20")
    legs = [("BTC/USDT", "buy"), ("ETH/BTC", "buy"), ("ETH/USDT", "sell")]
    amount, profit, _ = execution.estimate_triangle(usdt_in, legs)
    expected_profit = (amount / usdt_in) - Decimal("1")
    assert abs(profit - expected_profit) < Decimal("1e-10")


def test_estimate_triangle_uses_maker_fee_and_slip(tob_triangle):
    """В расчёте участвуют MAKER_FEE и SLIP_RESERVE (итоговый amount меньше, чем без комиссий)."""
    usdt_in = Decimal("100")
    legs = [("BTC/USDT", "buy"), ("ETH/BTC", "buy"), ("ETH/USDT", "sell")]
    amount, profit, _ = execution.estimate_triangle(usdt_in, legs)
    # Без комиссий: 100/ask_btc / ask_eth_btc * bid_eth = 100 * 2500 / (50010 * 0.05002)
    no_fee = usdt_in * Decimal("2500") / (Decimal("50010") * Decimal("0.05002"))
    assert amount < no_fee
