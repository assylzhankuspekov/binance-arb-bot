"""
Binance Spot Triangular Arbitrage Bot — v3.1

Модули:
  config   — константы, TRIANGLES, пути логов
  exchange — ccxt-клиент, квантование, tick_size
  state    — TOB, JITTER, paper_bal, tob_ready, jitter_score, fill_rate
  logs     — CSV: сигналы, сделки, снимки баланса
  execution — оценка треугольника, paper/live исполнение
  ws_feed  — WebSocket bookTicker Binance

Запуск:
  python main.py

⚠️ Сначала запускайте с PAPER_TRADING=True 1–3 дня.
"""

import asyncio
import time
from datetime import datetime

import config
import state
import exchange
import logs
import execution
import ws_feed
import telegram_notify


async def trader_loop(symbols: list) -> None:
    last_trade_ts = 0.0
    last_status_ts = 0.0
    last_wait_ts = 0.0

    while True:
        await asyncio.sleep(0.05)
        now = time.time()

        if not state.tob_ready(symbols):
            if now - last_wait_ts >= 15.0:
                last_wait_ts = now
                parts = []
                for s in symbols:
                    if s in state.TOB and state.TOB[s].get("ts"):
                        age = now - state.TOB[s]["ts"]
                        parts.append(f"{s}: {age:.1f}с")
                    else:
                        parts.append(f"{s}: нет")
                print(f"[...] Ожидание котировок с Binance… {', '.join(parts)}")
            continue

        if now - last_status_ts >= 30.0:
            last_status_ts = now
            tob_age = max((now - state.TOB[s]["ts"]) for s in symbols) if symbols else 0
            best = None
            for tri in config.TRIANGLES:
                out_est, prof_est, snap = execution.estimate_triangle(config.CYCLE_USDT, tri["legs"])
                if best is None or prof_est > best["profit"]:
                    best = {"tri": tri, "profit": prof_est, "out": out_est, "snapshot": snap}
            if best:
                j = state.jitter_score(symbols)
                fr = state.fill_rate()
                dyn = execution.dynamic_min_profit(config.BASE_MIN_PROFIT, j, fr)
                t = datetime.now().strftime("%H:%M:%S")
                print(
                    f"[OK] {t} | котировки {tob_age:.2f} сек назад | "
                    f"лучший {best['tri']['name']} ~{best['profit']*100:.3f}% | "
                    f"порог {dyn*100:.3f}% | fill {fr:.2f}"
                )
                logs.log_signal(
                    best["tri"]["name"], config.CYCLE_USDT, best["out"], best["profit"],
                    dyn, j, fr, best["snapshot"],
                )

        j = state.jitter_score(symbols)
        fr = state.fill_rate()
        dyn = execution.dynamic_min_profit(config.BASE_MIN_PROFIT, j, fr)

        best = None
        for tri in config.TRIANGLES:
            out_est, prof_est, _ = execution.estimate_triangle(config.CYCLE_USDT, tri["legs"])
            if best is None or prof_est > best["profit"]:
                best = {"tri": tri, "out": out_est, "profit": prof_est}

        if not best or best["profit"] <= dyn:
            continue

        if now - last_trade_ts < config.COOLDOWN_AFTER_TRADE_SEC:
            continue

        tri = best["tri"]
        print(
            f"[SIGNAL] {tri['name']} est {best['profit']*100:.3f}% | "
            f"dynMin {dyn*100:.3f}% | fill {fr:.2f} | jitter {j:.6f}"
        )

        executed = await asyncio.to_thread(execution.execute_triangle, tri, dyn)
        if executed:
            last_trade_ts = time.time()


async def main() -> None:
    logs.ensure_logs()

    if config.PAPER_TRADING and config.API_KEY in ("PUT_YOUR_KEY", "PUT_YOUR_KEY_HERE", ""):
        try:
            exchange.ex.options["fetchMargins"] = False
            markets = exchange.ex.fetch_markets()
            exchange.ex.set_markets(markets)
        except Exception as e:
            print(f"Ошибка загрузки рынков: {e}")
            raise
    else:
        exchange.ex.load_markets()

    symbols = sorted({sym for tri in config.TRIANGLES for (sym, _) in tri["legs"]})
    state.init_tob(symbols)

    print("[OK] Бот запущен. Ожидание котировок с Binance… Раз в 30 сек — статус в консоль.")
    tasks = [
        ws_feed.ws_book_ticker(symbols),
        trader_loop(symbols),
    ]
    if config.TELEGRAM_ENABLED and config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        tasks.append(telegram_notify.run_daily_scheduler())
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
