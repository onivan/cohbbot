"""Спільні засоби Telegram-сповіщень адміністраторам."""
import logging

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import database
from bot_setup import bot
from config import WEBAPP_URL
from database import users_cache


def admin_notification_keyboard(user_id=None, notification_id=None, can_approve=True):
    """Кнопки рішення щодо чека, переходу в чат користувача та адмін-панель.

    ``can_approve=False`` — коли суму ще не введено: погодити документ без суми
    неможливо, тому лишаємо тільки «Відхилити».
    """
    rows = []
    if notification_id is not None:
        decision_buttons = []
        if can_approve:
            decision_buttons.append(
                InlineKeyboardButton(
                    text="✅ Погодити чек",
                    callback_data=f"invalid_receipt:approved:{int(notification_id)}",
                )
            )
        decision_buttons.append(
            InlineKeyboardButton(
                text="❌ Відхилити",
                callback_data=f"invalid_receipt:rejected:{int(notification_id)}",
            )
        )
        rows.append(decision_buttons)
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
                        notification_id=None) -> list:
    """Надсилає повідомлення адміністраторам і повертає посилання на них.

    Якщо передано ``notification_id``, ID надісланих повідомлень зберігаються
    в payload події, щоб надалі редагувати картку на місці, а не слати нову.
    Помилка одного адресата не зупиняє решту.
    """
    reply_markup = admin_notification_keyboard(user_id, notification_id)
    sent_refs = []
    for admin_id in _admin_ids():
        try:
            if photo:
                message = await bot.send_photo(
                    admin_id, photo=photo, caption=text,
                    parse_mode=parse_mode, reply_markup=reply_markup,
                )
                kind = 'photo'
            else:
                message = await bot.send_message(
                    admin_id, text, parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
                kind = 'text'
            sent_refs.append({
                'chat_id': admin_id,
                'message_id': message.message_id,
                'kind': kind,
            })
        except Exception as e:
            logging.error(f"Не вдалося надіслати Telegram-сповіщення адміну {admin_id}: {e}")

    if notification_id and sent_refs:
        try:
            await database.save_admin_notification_messages(notification_id, sent_refs)
        except Exception as e:
            logging.error(
                f"Не вдалося зберегти ID повідомлень сповіщення {notification_id}: {e}"
            )
    return sent_refs


def _md_escape(value) -> str:
    """Екранує символи Markdown у даних користувача (ім'я, назва ЦН), щоб
    edit_message_caption не падав з «can't parse entities»."""
    text = str(value if value is not None else '')
    for ch in ('_', '*', '`', '['):
        text = text.replace(ch, f'\\{ch}')
    return text


def build_invalid_receipt_caption(notification: dict) -> str:
    """Єдиний текст картки невалідного чека.

    Використовується і при першому надсиланні, і при кожному наступному
    редагуванні (сума від користувача, рішення адміністратора, скасування
    автором), щоб адміністратор бачив актуальний стан в одному повідомленні.
    """
    notification = notification or {}
    payload = notification.get('payload') or {}

    if payload.get('amount'):
        amount_line = f"{float(payload['amount']):.2f} грн"
    elif payload.get('amount_missing'):
        amount_line = "очікується від користувача"
    else:
        amount_line = "не визначена"

    lines = [
        "⚠️ **Спроба надіслати невалідний чек**",
        "",
        f"Користувач: {_md_escape(notification.get('user_name') or 'Невідомо')}",
        f"ЦН: {_md_escape(notification.get('center_name') or '—')}",
        f"Telegram ID: `{notification.get('user_id')}`",
        f"Тип документа: {_md_escape(payload.get('document_type') or '—')}",
        f"Дата: {_md_escape(payload.get('receipt_date') or '—')}",
        f"Сума: {amount_line}",
        f"Назва: {_md_escape(payload.get('expense_name') or '—')}",
        f"Категорія: {_md_escape(payload.get('category') or '—')}",
    ]
    if notification.get('receipt_path'):
        lines.append(f"[Відкрити чек у панелі]({notification['receipt_path']})")

    decision = payload.get('decision')
    if decision == 'approved':
        lines += ["", "✅ Погоджено адміністратором"]
    elif decision == 'rejected':
        lines += ["", "🚫 Скасовано автором" if payload.get('canceled_by_user')
                  else "❌ Відхилено адміністратором"]
    elif payload.get('amount_missing'):
        lines += ["", "⏳ Чекаємо суму від користувача"]

    # Ліміт Telegram на підпис до фото — 1024 символи.
    return "\n".join(lines)[:1024]


async def update_invalid_receipt_notification(notification_id: int) -> bool:
    """Оновлює вже надіслані адмінам картки чека (без нових повідомлень).

    Викликається після будь-якої зміни стану події: користувач надав суму,
    адміністратор погодив/відхилив, автор скасував звернення. Будь-яка
    помилка Telegram не повинна ламати основну операцію.
    """
    try:
        notification = await database.get_admin_notification(int(notification_id))
    except Exception as e:
        logging.error(f"Не вдалося прочитати сповіщення {notification_id}: {e}")
        return False
    if not notification or notification.get('type') != 'invalid_receipt':
        return False

    payload = notification.get('payload') or {}
    decided = payload.get('decision') in ('approved', 'rejected')
    reply_markup = None if decided else admin_notification_keyboard(
        notification.get('user_id'),
        notification_id,
        can_approve=bool(payload.get('amount')),
    )
    caption = build_invalid_receipt_caption(notification)

    for ref in notification.get('telegram_messages') or []:
        chat_id = ref.get('chat_id')
        message_id = ref.get('message_id')
        if not chat_id or not message_id:
            continue
        try:
            if ref.get('kind') == 'photo':
                await bot.edit_message_caption(
                    chat_id=chat_id, message_id=message_id, caption=caption,
                    parse_mode='Markdown', reply_markup=reply_markup,
                )
            else:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=caption,
                    parse_mode='Markdown', reply_markup=reply_markup,
                )
        except Exception as e:
            logging.info(
                f"Картку сповіщення {notification_id} не оновлено у чаті {chat_id}: {e}"
            )
    return True
