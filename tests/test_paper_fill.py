"""
Юнит-тесты: логика paper_can_fill (расстояние от mid, порог тиков).

Запуск:
  pytest tests/test_paper_fill.py -v
"""

import pytest
from decimal import Decimal
from unittest.mock import patch

import config
import state
import execution
import exchange


@pytest.fixture
def tob_and_tick():
    """TOB для символа и мок tick_size."""
    state.TOB["BTC/USDT"] = {
        "bid": Decimal("100"),
        "ask": Decimal("102"),
        "ts": 0,
    }
    # mid = 101, spread = 2
    yield
    state.TOB.pop("BTC/USDT", None)


def test_paper_can_fill_far_from_mid_returns_false(tob_and_tick):
    """Если цена далеко от mid (больше max_dist тиков), fill = False."""
    with patch.object(exchange, "tick_size", return_value=Decimal("0.01")):
        # max_dist = 0.01 * 2 = 0.02, mid = 101. Цена 150 — далеко.
        result = execution.paper_can_fill("BTC/USDT", "buy", Decimal("150"))
    assert result is False


def test_paper_can_fill_at_mid_depends_on_random(tob_and_tick):
    """Цена на mid: результат зависит от псевдо-случая (time). Проверяем, что не падает."""
    with patch.object(exchange, "tick_size", return_value=Decimal("0.01")):
        with patch("execution.time") as mock_time:
            mock_time.time_ns.return_value = 0  # r = 0, p ~ 0.85 => r < p => True
            out = execution.paper_can_fill("BTC/USDT", "buy", Decimal("101"))
            assert out is True
            mock_time.time_ns.return_value = 999_999_999  # r ~ 0.999 => False
            out2 = execution.paper_can_fill("BTC/USDT", "sell", Decimal("101"))
            assert out2 is False


def test_paper_can_fill_just_within_distance(tob_and_tick):
    """Цена ровно на границе max_dist от mid — всё ещё в пределах (fill возможен)."""
    with patch.object(exchange, "tick_size", return_value=Decimal("1")):
        # max_dist = 2, mid = 101. Цена 103 — расстояние 2, не строго больше => в пределах
        with patch("execution.time") as mock_time:
            mock_time.time_ns.return_value = 0
            out = execution.paper_can_fill("BTC/USDT", "sell", Decimal("103"))
            assert out is True
