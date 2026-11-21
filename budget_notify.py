"""B2/B3: бюджетні попередження ЦН та адміністратору, події журналу B4.

Перевірка виконується після збереження витрати у фоновій задачі. Помилки
сповіщень не скасовують і не дублюють збережену витрату.
"""
import asyncio
import logging

import database
from bot_setup import bot


_bg_tasks = set()


def _money(value) -> str:
    return f"{float(value):,.2f}".replace(",", "\u00a0").replace(".", ",")


def _center_user_ids(center_id: int) -> list:
    """Активні звичайні користувачі ЦН; адміністратори отримують B3 окремо."""
    return sorted(
        int(uid) for uid, info in list(database.users_cache.items())
        if str(info.get('role', '')).strip().lower() != 'admin'
        and str(info.get('status', '')).strip().lower() == 'active'
        and str(info.get('center_id')) == str(center_id)
    )


async def _send_center_users(center_id: int, text: str, source: str) -> None:
    for uid in _center_user_ids(center_id):
        try:
            await bot.send_message(uid, text, parse_mode=None)
        except Exception:
            logging.exception('%s: не вдалося надіслати попередження користувачу %s', source, uid)


async def notify_overrun(center_id: int, category_id: str, month: str,
                         expense_id: str, amount: float = 0) -> None:
    """Перевіряє перевитрату та перший перетин налаштованого порогу."""
    try:
        budgets = await database.get_center_budgets(center_id, month)
        if category_id not in budgets:
            return  # Відсутній ліміт не означає нульовий ліміт.
        budget = budgets[category_id]
        spent = await database.get_category_spent(center_id, category_id, month)
        try:
            threshold = await database.get_budget_alert_threshold()
        except Exception:
            logging.exception('B3: не вдалося прочитати поріг; використовуємо 90%%')
            threshold = database.BUDGET_ALERT_DEFAULT_THRESHOLD
        overrun = spent > budget
        threshold_amount = budget * threshold / 100.0 if budget > 0 else None
        previous_spent = max(0.0, spent - float(amount or 0))
        threshold_crossed = (
            threshold_amount is not None
            and previous_spent < threshold_amount <= spent
        )
        if not overrun and not threshold_crossed:
            return

        categories = await database.get_all_categories()
        category_name = next((c['name'] for c in categories if c['id'] == category_id), category_id)
        centers = await database.get_centers()
        center_name = next((c['name'] for c in centers if c['id'] == center_id), f'ЦН #{center_id}')
        base_payload = {
            'expense_id': expense_id, 'month': month,
            'category_id': category_id, 'category_name': category_name,
            'spent': spent, 'budget': budget,
        }

        if overrun:
            text = (
                f'Перевитрата по «{category_name}»: {_money(spent)}/{_money(budget)} грн\n'
                f'ЦН «{center_name}» · {month}'
            )
            try:
                await database.create_admin_notification(
                    type='budget_overrun', title='Перевитрата ліміту категорії',
                    message=text, center_id=center_id, action_status='resolved',
                    payload=base_payload,
                )
            except Exception:
                logging.exception('B2: не вдалося записати перевитрату в журнал')

            await _send_center_users(center_id, text, 'B2')

        if not threshold_crossed:
            return
        threshold_text = (
            f'Досягнуто {threshold:g}% ліміту по «{category_name}»: '
            f'{_money(spent)}/{_money(budget)} грн\nЦН «{center_name}» · {month}'
        )
        payload = {**base_payload, 'threshold': threshold}
        try:
            claimed = await database.claim_budget_alert(
                center_id, category_id, month, threshold,
                title=f'Досягнуто {threshold:g}% ліміту',
                message=threshold_text, payload=payload,
            )
        except Exception:
            logging.exception('B3: не вдалося зарезервувати поріг і записати його в журнал')
            return
        if not claimed:
            return

        try:
            from telegram_notifications import notify_admins
            await notify_admins(threshold_text)
        except Exception:
            logging.exception('B3: не вдалося надіслати сповіщення адміністраторам')
        await _send_center_users(center_id, threshold_text, 'B3')
    except Exception:
        logging.exception('B2/B3: помилка перевірки ліміту ЦН %s за %s', center_id, month)


def after_expense(center_id: int, category_id: str, day, expense_id: str,
                  amount: float = 0) -> None:
    """Запускається лише після успішного запису витрати, не затримує відповідь."""
    task = asyncio.create_task(
        notify_overrun(center_id, category_id, str(day)[:7], expense_id, amount)
    )
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
