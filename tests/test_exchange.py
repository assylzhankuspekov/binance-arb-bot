"""
Юнит-тесты: парсинг символа, Decimal-хелпер, квантование (с моком биржи).

Запуск:
  pytest tests/test_exchange.py -v
"""

import pytest
from decimal import Decimal, ROUND_DOWN
from unittest.mock import patch, MagicMock

import exchange


def test_parse_base_quote():
    """Парсинг символа в base и quote."""
    assert exchange.parse_base_quote("BTC/USDT") == ("BTC", "USDT")
    assert exchange.parse_base_quote("ETH/BTC") == ("ETH", "BTC")


def test_d():
    """d() приводит к Decimal."""
    assert exchange.d("0.001") == Decimal("0.001")
    assert exchange.d(100) == Decimal("100")
    assert exchange.d(0.0001) == Decimal("0.0001")


@patch.object(exchange.ex, "market")
def test_quantize_amount(mock_market):
    """Квантование объёма по точности рынка."""
    mock_market.return_value = {"precision": {"amount": 6, "price": 2}}
    result = exchange.quantize_amount("BTC/USDT", Decimal("0.123456789"))
    assert result == Decimal("0.123456")
    mock_market.assert_called_with("BTC/USDT")


@patch.object(exchange.ex, "market")
def test_quantize_price(mock_market):
    """Квантование цены по точности рынка."""
    mock_market.return_value = {"precision": {"amount": 6, "price": 2}}
    result = exchange.quantize_price("BTC/USDT", Decimal("50123.456"))
    assert result == Decimal("50123.45")


@patch.object(exchange.ex, "market")
def test_tick_size(mock_market):
    """tick_size = 10^(-price_precision)."""
    mock_market.return_value = {"precision": {"amount": 8, "price": 2}}
    assert exchange.tick_size("BTC/USDT") == Decimal("0.01")
    mock_market.return_value = {"precision": {"amount": 8, "price": 8}}
    assert exchange.tick_size("ETH/BTC") == Decimal("0.00000001")
