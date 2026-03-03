"""
Рассылка в Telegram: уведомление о сделке и ежедневный отчёт в 8:00.
"""

import asyncio
import time
from datetime import datetime
from decimal import Decimal

import requests

import config
import state


def _send_message(text: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    text = text[:4096]
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"[Telegram] Ошибка отправки: {e}")
        return False


def send_trade_notification(
    tri_name: str,
    status: str,
    usdt_in: Decimal,
    usdt_out: Decimal,
    profit_pct: Decimal,
) -> None:
    """Отправить в группу сообщение о совершённой сделке."""
    if not config.TELEGRAM_ENABLED:
        return
    mode = "📄 Paper" if config.PAPER_TRADING else "🔴 Live"
    profit_str = f"{float(profit_pct) * 100:.3f}%"
    text = (
        f"✅ Сделка ({mode})\n"
        f"Треугольник: {tri_name}\n"
        f"Статус: {status}\n"
        f"Вход: {usdt_in} USDT → Выход: ~{usdt_out} USDT\n"
        f"Профит: {profit_str}"
    )
    _send_message(text)


def _get_daily_report_text() -> str:
    """Текст ежедневного отчёта: баланс, число сделок, лучший профит."""
    usdt = state.paper_bal.get("USDT", Decimal("0"))
    exposure = state.paper_exposure_usdt()
    total_usdt = usdt + exposure
    trades = state.trades_count
    best = state.best_profit_pct
    best_str = f"{float(best) * 100:.3f}%" if best is not None else "—"
    mode = "Paper" if config.PAPER_TRADING else "Live"
    lines = [
        f"📊 Ежедневный отчёт ({mode})",
        "",
        f"💰 Баланс (USDT): {usdt:.2f}",
        f"📈 Экспозиция в альтах (USDT): {exposure:.2f}",
        f"💵 Итого эквивалент: {total_usdt:.2f} USDT",
        "",
        f"🔢 Сделок за всё время: {trades}",
        f"🏆 Лучший профит по сделке: {best_str}",
    ]
    return "\n".join(lines)


async def run_daily_scheduler() -> None:
    """Раз в минуту проверяет: если сейчас 8:00 — отправить ежедневный отчёт (раз в день)."""
    last_sent_date = None
    while True:
        await asyncio.sleep(60)
        if not config.TELEGRAM_ENABLED or not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
            continue
        now = datetime.now()
        if now.hour != config.TELEGRAM_DAILY_HOUR:
            continue
        today = now.date()
        if last_sent_date == today:
            continue
        text = _get_daily_report_text()
        ok = await asyncio.to_thread(_send_message, text)
        if ok:
            last_sent_date = today
