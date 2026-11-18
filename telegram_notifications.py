"""Спільні засоби Telegram-сповіщень адміністраторам."""
import logging

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot_setup import bot
from config import WEBAPP_URL
from database import users_cache


def admin_notification_keyboard(user_id=None, notification_id=None):
    """Кнопки рішення щодо чека, переходу в чат користувача та адмін-панель."""
    rows = []
    if notification_id is not None:
        rows.append([
            InlineKeyboardButton(
                text="✅ Погодити чек",
                callback_data=f"invalid_receipt:approved:{int(notification_id)}",
            ),
            InlineKeyboardButton(
                text="❌ Відхилити",
                callback_data=f"invalid_receipt:rejected:{int(notification_id)}",
            ),
        ])
    try:
        if user_id is not None:
            rows.append([
                InlineKeyboardButton(
                    text="💬 Відкрити чат користувача",
                    url=f"tg://user?id={int(user_id)}",
                )
            ])
    except (TypeError, ValueError):
        pass

    if WEBAPP_URL:
        rows.append([
            InlineKeyboardButton(
                text="📋 Відкрити адмін-панель",

                url=f"{WEBAPP_URL.rstrip('/')}/admin",
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _admin_ids():
    return [
        int(user_id) for user_id, info in users_cache.items()
        if str(info.get('role', '')).strip().lower() == 'admin'
    ]


async def notify_admins(text: str, user_id=None, photo=None, parse_mode=None,
                        notification_id=None) -> int:
    """Надсилає повідомлення адміністраторам; помилка одного адресата не зупиняє решту."""
    reply_markup = admin_notification_keyboard(user_id, notification_id)
    sent = 0
    for admin_id in _admin_ids():
        try:
            if photo:
                await bot.send_photo(
                    admin_id, photo=photo, caption=text,
                    parse_mode=parse_mode, reply_markup=reply_markup,
                )
            else:
                await bot.send_message(
                    admin_id, text, parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
            sent += 1
        except Exception as e:
            logging.error(f"Не вдалося надіслати Telegram-сповіщення адміну {admin_id}: {e}")
    return sent
