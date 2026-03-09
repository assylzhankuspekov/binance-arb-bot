"""
Конфигурация бота треугольного арбитража Binance Spot.
"""

import os
from decimal import Decimal

# Загрузить переменные из .env (путь от папки с config.py)
_env_dir = os.path.dirname(os.path.abspath(__file__))
_env_path = os.path.join(_env_dir, ".env")
try:
    from dotenv import load_dotenv
    if os.path.isfile(_env_path):
        load_dotenv(_env_path, encoding="utf-8-sig")
    else:
        print(f"[Config] Файл .env не найден: {_env_path}")
except ImportError:
    pass
# Запасная загрузка Telegram из .env, если dotenv не подхватил
if (not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID")) and os.path.isfile(_env_path):
    try:
        with open(_env_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key in ("TELEGRAM_ENABLED", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_DAILY_HOUR"):
                    os.environ[key] = val
    except Exception as e:
        print(f"[Config] Ошибка чтения .env: {e}")

# API (для live — подставьте ключи или читайте из env)
API_KEY = os.environ.get("BINANCE_API_KEY", "PUT_YOUR_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "PUT_YOUR_SECRET")

PAPER_TRADING = True  # сначала бумажная торговля; False для live

QUOTE = "USDT"
START_BALANCE_USDT = Decimal("200")   # эквивалент ~100k ₸ (подстройте под себя)
CYCLE_USDT = Decimal("20")            # 15–25 USDT рекомендуется

BASE_MIN_PROFIT = Decimal("0.0001")   # 0.01% — для теста; обычно 0.0025 = 0.25%
MAKER_FEE = Decimal("0.00075")        # ~0.075% при оплате комиссии BNB
TAKER_FEE = Decimal("0.0010")        # оценка при экстренном flatten
SLIP_RESERVE = Decimal("0.00025")     # запас на проскальзывание
ORDER_TIMEOUT_SEC = Decimal("2.0")
COOLDOWN_AFTER_TRADE_SEC = 1.5

# Свежесть котировок (top-of-book)
MAX_TOB_AGE_SEC = 0.8

# Лимиты риска (экспозиция в не-USDT)
MAX_EXPOSURE_USDT_EQ = Decimal("60")
FORCE_FLATTEN_ON_EXPOSURE = True

# SSL: отключить проверку за корпоративным прокси
VERIFY_SSL = False

# Симуляция исполнения в paper-режиме
PAPER_MAX_MID_DISTANCE_TICKS = 2
PAPER_FILL_PROB_BASE = 0.85

# Окна для динамического порога
JITTER_WINDOW = 120
FILL_WINDOW = 50

# CSV-логи
LOG_DIR = "./logs"
SIGNALS_CSV = os.path.join(LOG_DIR, "arb_signals_v3_1.csv")
TRADES_CSV = os.path.join(LOG_DIR, "arb_trades_v3_1.csv")
STATE_CSV = os.path.join(LOG_DIR, "arb_state_v3_1.csv")

# Telegram: ежедневный отчёт в 8:00 и уведомления о сделках
# Токен и chat_id — из переменных окружения или подставьте сюда (не коммитьте в git).
TELEGRAM_ENABLED = os.environ.get("TELEGRAM_ENABLED", "true").strip().lower() in ("1", "true", "yes")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_DAILY_HOUR = int(os.environ.get("TELEGRAM_DAILY_HOUR", "8").strip() or "8")

TRIANGLES = [
    {"name": "USDT-BTC-ETH-USDT",
     "legs": [("BTC/USDT", "buy"), ("ETH/BTC", "buy"), ("ETH/USDT", "sell")]},
    {"name": "USDT-BTC-BNB-USDT",
     "legs": [("BTC/USDT", "buy"), ("BNB/BTC", "buy"), ("BNB/USDT", "sell")]},
    {"name": "USDT-ETH-BNB-USDT",
     "legs": [("ETH/USDT", "buy"), ("BNB/ETH", "buy"), ("BNB/USDT", "sell")]},
]
