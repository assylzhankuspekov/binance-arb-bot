# Binance Spot Triangular Arbitrage Bot

Бот для треугольного арбитража на споте Binance (USDT ↔ BTC ↔ ETH ↔ BNB). Режим бумажной торговли (paper trading) и опционально live.

## Требования

- Python 3.10+
- Зависимости: `ccxt`, `websockets`

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

## Конфиг (в начале main.py)

- `PAPER_TRADING = True` — бумажная торговля (рекомендуется сначала 1–3 дня).
- `API_KEY` / `API_SECRET` — для live нужны реальные ключи Binance.
- `BASE_MIN_PROFIT` — минимальный порог прибыли (доля; 0.0001 = 0.01%).
- `VERIFY_SSL = False` — если ошибки SSL за корпоративным прокси.

## Логи

В папке `logs/` создаются CSV:

- `arb_signals_v3_1.csv` — оценка сигналов и лучший треугольник (каждые 30 сек и при попытке сделки).
- `arb_trades_v3_1.csv` — результаты попыток (DONE / SKIP / ABORT / FLATTEN).
- `arb_state_v3_1.csv` — снимки баланса после успешных бумажных сделок.

## Лицензия

Использование на свой страх и риск. Торговля криптовалютой связана с рисками.
