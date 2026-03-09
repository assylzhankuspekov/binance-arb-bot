# Binance Spot Triangular Arbitrage Bot

Бот для треугольного арбитража на споте Binance (USDT ↔ BTC ↔ ETH ↔ BNB). Режим бумажной торговли (paper trading) и опционально live.

## Структура проекта

- `config.py` — константы, API-ключи, пороги, пути логов, список треугольников
- `exchange.py` — клиент ccxt, квантование объёма/цены, tick size, маппинг символов Binance
- `state.py` — top-of-book (TOB), jitter, история исполнений, бумажный баланс
- `logs.py` — создание и запись CSV (сигналы, сделки, снимки баланса)
- `execution.py` — оценка треугольника, динамический порог, paper/live исполнение
- `ws_feed.py` — WebSocket подписка на bookTicker Binance
- `telegram_notify.py` — рассылка в Telegram: уведомление о сделке, ежедневный отчёт в 8:00
- `main.py` — точка входа: инициализация, цикл трейдера, запуск

## Требования

- Python 3.10+
- Зависимости: `ccxt`, `websockets`, `requests` (Telegram), `python-dotenv` (опционально, для .env), `pytest` (для тестов)

## Установка

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
# source venv/bin/activate

pip install -r requirements.txt
```

## Запуск

```bash
python main.py
```

Перед первым запуском в `main.py` можно оставить заглушки API ключей для теста — котировки идут по публичному WebSocket, для бумажной торговли ключ не обязателен.

## Конфиг (`config.py`)

- `PAPER_TRADING = True` — бумажная торговля (рекомендуется сначала 1–3 дня).
- `API_KEY` / `API_SECRET` — для live нужны реальные ключи Binance (или переменные `BINANCE_API_KEY` / `BINANCE_API_SECRET`).
- `BASE_MIN_PROFIT` — минимальный порог прибыли (доля; 0.0001 = 0.01%).
- `VERIFY_SSL = False` — если ошибки SSL за корпоративным прокси.

## Telegram

Если бот подключён к группе, можно включить рассылку:

1. **Ежедневный отчёт в 8:00** — текущий баланс (USDT + экспозиция в альтах), число сделок за всё время, лучший профит по сделке.
2. **При каждой успешной сделке (DONE)** — сообщение с треугольником, суммой входа/выхода и профитом.

Включение: задать переменные окружения (или в `config.py`):

- `TELEGRAM_ENABLED=true`
- `TELEGRAM_BOT_TOKEN` — токен от @BotFather
- `TELEGRAM_CHAT_ID` — ID группы (например `-1001234567890`; как получить: добавить бота в группу, отправить сообщение, открыть `https://api.telegram.org/bot<TOKEN>/getUpdates`, в ответе смотреть `chat.id`)
- `TELEGRAM_DAILY_HOUR=8` — час отправки ежедневного отчёта (по умолчанию 8:00 локального времени сервера)

### Переменные окружения и перенос на сервер

**1. Нужно ли каждый раз вводить переменные перед запуском?**  
Нет. Создайте один раз файл `.env` в корне проекта (скопируйте `.env.example` в `.env` и подставьте значения). Бот подхватит переменные при старте. Файл `.env` в `.gitignore`, в репозиторий не попадёт.

**2. Как загружать токены на сервере?**

- **Файл .env** — на сервере создайте `.env` в корне проекта с `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` и т.д. Запуск: `python main.py`.
- **systemd** — в unit-файле в секции `[Service]`: `Environment="TELEGRAM_BOT_TOKEN=..."` или `EnvironmentFile=/path/to/.env`.
- **Docker** — `docker run -e TELEGRAM_BOT_TOKEN=... -e TELEGRAM_CHAT_ID=...` или `--env-file .env`.

## Тесты

Юнит-тесты проверяют расчёт профита, квантование, динамический порог и логику paper fill. Запуск из корня проекта:

```bash
pip install -r requirements.txt
pytest tests/ -v
```

- `tests/test_execution.py` — `dynamic_min_profit`, `estimate_triangle`
- `tests/test_exchange.py` — `parse_base_quote`, `d()`, квантование (с моком биржи)
- `tests/test_state.py` — `jitter_score`, `fill_rate`, `tob_ready`, `paper_exposure_usdt`
- `tests/test_paper_fill.py` — границы логики `paper_can_fill` (расстояние от mid)

## Логи

В папке `logs/` создаются CSV:

- `arb_signals_v3_1.csv` — оценка сигналов и лучший треугольник (каждые 30 сек и при попытке сделки).
- `arb_trades_v3_1.csv` — результаты попыток (DONE / SKIP / ABORT / FLATTEN).
- `arb_state_v3_1.csv` — снимки баланса после успешных бумажных сделок.

## Лицензия

Использование на свой страх и риск. Торговля криптовалютой связана с рисками.
