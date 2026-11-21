"""B2: попередження ЦН про перевитрату категорії та події журналу B4.

Перевірка виконується після збереження витрати у фоновій задачі спільного
циклу бота й вебсервера. Помилка сповіщення не скасовує збережену витрату.
Порогові сповіщення адміністраторам та антиспам B3 тут не реалізуються.
"""
import asyncio
import logging

import database
from bot_setup import bot


_bg_tasks = set()


def _money(value) -> str:
    return f"{float(value):,.2f}".replace(",", "\u00a0").replace(".", ",")


async def notify_overrun(center_id: int, category_id: str, month: str,
                         expense_id: str) -> None:
    """Після кожної нової витрати понад заданий ліміт повідомляє її ЦН."""
    try:
        budgets = await database.get_center_budgets(center_id, month)
        if category_id not in budgets:
            return  # Відсутній ліміт не означає нульовий ліміт.
        budget = budgets[category_id]
        spent = await database.get_category_spent(center_id, category_id, month)
        if spent <= budget:
            return

        categories = await database.get_all_categories()
        category_name = next((c['name'] for c in categories if c['id'] == category_id), category_id)
        centers = await database.get_centers()
        center_name = next((c['name'] for c in centers if c['id'] == center_id), f'ЦН #{center_id}')
        text = (
            f'Перевитрата по «{category_name}»: {_money(spent)}/{_money(budget)} грн\n'
            f'ЦН «{center_name}» · {month}'
        )

        try:
            await database.create_admin_notification(
                type='budget_overrun', title='Перевитрата ліміту категорії',
                message=text, center_id=center_id, action_status='resolved',
                payload={
                    'expense_id': expense_id, 'month': month,
                    'category_id': category_id, 'category_name': category_name,
                    'spent': spent, 'budget': budget,
                },
            )
        except Exception:
            logging.exception('B2: не вдалося записати перевитрату в журнал')

        recipients = [
            int(uid) for uid, info in list(database.users_cache.items())
            if str(info.get('status', '')).strip().lower() == 'active'
            and str(info.get('center_id')) == str(center_id)
        ]
        for uid in recipients:
            try:
                await bot.send_message(uid, text, parse_mode=None)
            except Exception:
                logging.exception('B2: не вдалося надіслати попередження користувачу %s', uid)
    except Exception:
        logging.exception('B2: помилка перевірки перевитрати ЦН %s за %s', center_id, month)


def after_expense(center_id: int, category_id: str, day, expense_id: str) -> None:
    """Запускається лише після успішного запису витрати, не затримує відповідь."""
    task = asyncio.create_task(notify_overrun(center_id, category_id, str(day)[:7], expense_id))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
