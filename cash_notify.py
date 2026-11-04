"""Сповіщення в бот про рух коштів ЦН (каса).

Бот і веб-сервер працюють в одному event loop, тому відправка виконується
фоновою задачею: HTTP-відповідь не чекає на Telegram.
Вимкнути сповіщення можна змінною оточення CASH_NOTIFY=0 (див. config.py).
"""
import asyncio
import logging

from bot_setup import bot
from config import CASH_NOTIFY
from database import users_cache, get_centers

_bg_tasks = set()

KIND_LABELS = {
    'funding': '💰 Надійшли кошти',
    'return': '↩️ Повернення коштів',
    'adjustment': '✏️ Коригування коштів',
}


def _money(value) -> str:
    """1500.5 -> '1 500,50' (для повідомлень у боті)."""
    return f"{float(value or 0):,.2f}".replace(",", "\u00a0").replace(".", ",")


def _admin_ids() -> list:
    """Telegram ID усіх адміністраторів (з кешу користувачів)."""
    return [
        int(uid) for uid, info in users_cache.items()
        if str(info.get('role', '')).strip().lower() == 'admin'
    ]


def _center_user_ids(center_id: int) -> list:
    """Активні (не адміни) користувачі конкретного ЦН."""
    result = []
    for uid, info in users_cache.items():
        if str(info.get('role', '')).strip().lower() == 'admin':
            continue
        if str(info.get('status', '')).strip().lower() != 'active':
            continue
        if info.get('center_id') == center_id:
            result.append(int(uid))
    return sorted(result)


async def _center_name(center_id: int) -> str:
    try:
        centers = await get_centers()
        for c in centers:
            if c['id'] == center_id:
                return c['name']
    except Exception as e:
        logging.error(f"cash_notify: назва ЦН {center_id}: {e}")
    return f"ЦН #{center_id}"


async def _send_many(user_ids, text: str) -> int:
    """Розсилка без падінь: одна помилка не заважає решті."""
    sent = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception as e:
            logging.warning(f"cash_notify: не вдалося надіслати {uid}: {e}")
    return sent


def _spawn(coro):
    if not CASH_NOTIFY:
        return
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def _notify_center(center_id: int, op: dict, closing) -> None:
    recipients = _center_user_ids(center_id)
    if not recipients:
        return
    center_name = await _center_name(center_id)
    lines = [KIND_LABELS.get(op.get('kind'), 'Рух коштів'), f"ЦН «{center_name}»"]
    signed = float(op.get('signed_amount') or 0)
    lines.append(f"Сума: {_money(signed)} грн")
    if op.get('counterparty'):
        lines.append(f"Контрагент: {op['counterparty']}")
    if op.get('comment'):
        lines.append(f"Коментар: {op['comment']}")
    if closing is not None:
        lines.append(f"Залишок на кінець місяця {op.get('month')}: {_money(closing)} грн")
    await _send_many(recipients, "\n".join(lines))


async def _notify_negative(center_id: int, op: dict, closing) -> None:
    admins = _admin_ids()
    if not admins:
        return
    center_name = await _center_name(center_id)
    text = "\n".join([
        "⚠️ Мінусовий залишок коштів",
        f"ЦН «{center_name}», місяць {op.get('month')}",
        f"Залишок: {_money(closing)} грн",
        f"Остання операція: {KIND_LABELS.get(op.get('kind'), '—')} "
        f"{_money(op.get('signed_amount'))} грн",
    ])
    await _send_many(admins, text)


def after_operation(op: dict, summary: dict) -> None:
    """Фонові сповіщення після руху коштів.

    op      — результат database.add_cash_operation()
    summary — database.get_cash_summary() за місяцем операції (після перерахунку)
    """
    if not CASH_NOTIFY:
        return
    closing = None
    if summary and summary.get('configured'):
        closing = summary.get('closing_balance')

    _spawn(_notify_center(op['center_id'], op, closing))

    # Мінусовий залишок — тільки момент переходу в мінус, щоб не спамити
    if closing is not None and closing < 0:
        before = float(closing) - float(op.get('signed_amount') or 0)
        if before >= 0:
            _spawn(_notify_negative(op['center_id'], op, closing))
