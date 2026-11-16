import logging

from aiogram import Router, types
from aiogram.filters import Command

import database

router = Router()


def format_money(value) -> str:
    """Форматує суму з десятковою комою та пробілами між розрядами."""
    amount = float(value or 0)
    formatted = f"{abs(amount):,.2f}".replace(",", " ").replace(".", ",")
    sign = "−" if amount < 0 else ""
    return f"{sign}{formatted} грн"


def format_balance_message(summary: dict) -> str:
    """Готує повідомлення /balance з результату database.get_cash_summary()."""
    month = summary.get("month") or database.current_month()
    if not summary.get("configured"):
        return (
            f"💰 Облік коштів за {month} ще не налаштовано для вашого ЦН. "
            "Зверніться до адміністратора."
        )

    lines = [
        f"💰 Кошти ЦН за {month}",
        f"На початок місяця: {format_money(summary.get('opening_balance'))}",
        f"Надійшло (нетто): {format_money(summary.get('received'))}",
        f"Витрачено: {format_money(summary.get('spent'))}",
        f"Залишок: {format_money(summary.get('closing_balance'))}",
    ]

    if summary.get("status") == "closed":
        lines.append("Місяць закрито.")
        if summary.get("matches") is False:
            lines.append("⚠️ Розрахунок не збігається із закритим знімком; зверніться до адміністратора.")
    return "\n".join(lines)


@router.message(Command("balance"))
async def cmd_balance(message: types.Message):
    """Показує користувачу залишок коштів його центру за поточний місяць."""
    user_id = message.from_user.id
    user_key = str(user_id)

    try:
        if user_key not in database.users_cache:
            await database.load_users()
        user_info = database.users_cache.get(user_key)
        if not user_info:
            await message.answer("Спочатку зареєструйтеся за допомогою команди /start.")
            return
        if user_info.get("status", "pending") != "active":
            if user_info.get("status") == "blocked":
                await message.answer("Ваш обліковий запис заблоковано. Зверніться до адміністратора.")
            else:
                await message.answer("Ваш обліковий запис ще не активовано. Очікуйте підтвердження від адміністратора.")
            return

        center_id = await database.get_user_center_id(user_id)
        if not center_id:
            await message.answer("За вашим профілем не закріплено ЦН. Зверніться до адміністратора.")
            return
        summary = await database.get_cash_summary(center_id, database.current_month())
        await message.answer(format_balance_message(summary))
    except Exception:
        logging.exception("Не вдалося отримати залишок коштів для user_id=%s", user_id)
        await message.answer("Не вдалося завантажити залишок коштів. Спробуйте пізніше.")
