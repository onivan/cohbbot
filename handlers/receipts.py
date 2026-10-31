import os
import io
import asyncio
import logging
import urllib.parse
import uuid
import traceback
from datetime import datetime
from PIL import Image

from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext

from bot_setup import bot
from config import WEBAPP_URL, DEBUG_DIAGNOSTICS
from database import (
    users_cache, get_categories, load_users, log_api_usage,
    get_all_users, get_active_ai_model,
)
from ai_service import parse_receipt_image, AIServiceError
from handlers.states import ReceiptState

router = Router()


def _admin_ids():
    """Список Telegram ID усіх адміністраторів."""
    return [
        u['user_id'] for u in get_all_users()
        if str(users_cache.get(str(u['user_id']), {}).get('role', '')).strip().lower() == 'admin'
    ]


async def notify_admins_ai_error(err, model_config, user_id, user_name):
    """
    Повідомляє адміністраторів про проблему з AI (вичерпані кошти, недійсний ключ,
    відсутня модель тощо). Для «звичайних» помилок розпізнавання — не турбує.
    """
    if not getattr(err, 'is_credit_error', False):
        return

    model_name = (model_config or {}).get('name') or '—'
    model_id = (model_config or {}).get('model_id') or '—'
    err_text = (getattr(err, 'message', None) or str(err))[:500]

    lines = [
        "🚨 Проблема з розпізнаванням чеків (AI)",
        "",
        f"Модель: {model_name}",
        f"ID моделі: {model_id}",
        f"Користувач: {user_name} ({user_id})",
        f"Помилка: {err_text}",
        "",
        "💳 Перевірте баланс OpenRouter або змініть активну модель у панелі адміністратора.",
    ]
    text = "\n".join(lines)

    for admin_id in _admin_ids():
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            logging.error(f"Не вдалося сповістити адміна {admin_id}: {e}")

async def render_summary(message_obj: types.Message, data: dict, state: FSMContext):
    """
    Формує та надсилає (або оновлює) картку з підсумками розпізнаного чека.
    Містить посилання з параметрами для швидкого відкриття у Web App.
    """
    msg_id = message_obj.message_id
    date_only = data.get('receipt_date', '').split(' ')[0] if data.get('receipt_date') else datetime.now().strftime("%Y-%m-%d")
    
    # Формуємо URL-параметри для передзаповнення Web App форми
    params = {
        'draft': '1',
        'date': date_only,
        'amount': data.get('amount', 0),
        'name': data.get('expense_name', '') or '',
        'category': data.get('category', '') or '',
        'path': data.get('file_path', '') or '',
        'msg_id': msg_id
    }
    query_string = urllib.parse.urlencode(params)
    draft_url = f"{WEBAPP_URL}?{query_string}"

    # Кнопки підтвердження та переходу у Web App
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Зберегти все вірно", callback_data="receipt_save")],
        [InlineKeyboardButton(text="✏️ Редагувати у формі", web_app=WebAppInfo(url=draft_url))],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="receipt_cancel")]
    ])
    
    # Застереження, якщо дата була автоматично підставлена
    date_warning = ""
    if data.get('date_not_found'):
        date_warning = "⚠️ **Дату на чеку не знайдено. Встановлено поточну дату!**\n\n"
    
    # Виправлено форматування Markdown для expense_name (прибрано зайве 'в')
    text = (
        f"{date_warning}"
        f"📅 Дата: **{date_only}**\n"
        f"💰 Сума: **{data.get('amount')} грн**\n"
        f"🏷 Назва: **{data.get('expense_name')}**\n"
        f"📂 Категорія: **{data.get('category')}**\n\n"
        f"Зберігаємо одразу чи хочете підправити дані у зручній формі?"
    )
    
    await state.set_state(ReceiptState.waiting_for_confirmation)
    
    if message_obj.from_user.is_bot:
        await message_obj.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await message_obj.answer(text, parse_mode="Markdown", reply_markup=kb)

@router.message(F.photo)
async def process_receipt_photo(message: types.Message, state: FSMContext):
    """Обробка фото чека: розпізнавання, збереження та підготовка до підтвердження"""
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in users_cache:
        await load_users()
        
    if user_id_str not in users_cache:
        await message.answer("Будь ласка, спочатку зареєструйтеся за допомогою команди /start")
        return

    user_info = users_cache[user_id_str]
    if user_info.get('status', 'pending') != 'active' or not user_info.get('center_id'):
        await message.answer("Ваш обліковий запис ще не активовано або вам не призначено Центр Надії. Очікуйте підтвердження від адміністратора.")
        return

    msg = await message.answer("⏳ Читаю чек...")
    
    try:
        # Завантажуємо зображення
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        downloaded_file = await bot.download_file(file_info.file_path)
        
        # Обробка зображення через Pillow у окремому потоці (синхронна операція)
        image = await asyncio.to_thread(Image.open, io.BytesIO(downloaded_file.read()))
        # Важливо завантажити дані зображення в пам'ять перед виходом з потоку
        await asyncio.to_thread(image.load)
        
        # Отримуємо список категорій користувача з бази
        raw_categories = await get_categories(user_id)
        
        # Перетворюємо словники/рядки у чистий список текстових назв
        valid_categories = []
        for cat in raw_categories:
            if isinstance(cat, dict):
                valid_categories.append(cat.get('name', ''))
            else:
                valid_categories.append(str(cat))
        valid_categories = [c for c in valid_categories if c]

        user_info = users_cache.get(user_id_str, {'name': 'User', 'center': 'Центр'})
        user_name = user_info.get('name', 'Невідомо')

        # Отримуємо активну AI-модель (з БД або фолбек з .env)
        model_config = await get_active_ai_model()
        if not model_config:
            await msg.edit_text(
                "⚙️ Сервіс розпізнавання чеків не налаштований.\n"
                "Адміністратора повідомлено — спробуйте, будь ласка, пізніше."
            )
            await notify_admins_ai_error(
                AIServiceError(
                    "Активна AI-модель не налаштована (немає ні в ai_settings, ні в OPENROUTER_API_KEY).",
                    is_credit_error=True,
                ),
                model_config=None,
                user_id=user_id,
                user_name=user_name,
            )
            return

        # Передаємо зображення в модуль AI
        try:
            data = await parse_receipt_image(image, valid_categories, model_config)
        except AIServiceError as ai_err:
            logging.error(f"AI-помилка: {ai_err.message}")
            await notify_admins_ai_error(ai_err, model_config, user_id, user_name)
            await msg.edit_text(
                "⚠️ Не вдалося розпізнати чек через технічну проблему сервісу.\n"
                "Адміністратора повідомлено. Спробуйте, будь ласка, пізніше."
            )
            return

        usage = data.get('_usage', {})
        if usage:
            # Асинхронно записуємо лог із прив'язкою до конкретної моделі
            asyncio.create_task(
                log_api_usage(
                    user_id=user_id,
                    user_name=user_name,
                    input_tokens=usage.get('input_tokens', 0),
                    output_tokens=usage.get('output_tokens', 0),
                    model_id=usage.get('model_id') or model_config.get('model_id'),
                    ai_model_id=model_config.get('id'),
                )
            )
        
        # A1. Валідація «це чек?»: якщо AI визначив, що це не фіскальний чек
        if not data.get('is_receipt', True):
            doc_type = (data.get('document_type') or 'невідомий документ').strip()
            await msg.edit_text(
                "❌ Це не схоже на фіскальний чек.\n"
                f"Розпізнано як: {doc_type}.\n\n"
                "Будь ласка, надішліть фото саме фіскального чека."
            )
            # Сповіщаємо адмінів із фото цього документа
            user_info = users_cache.get(user_id_str, {'name': 'Невідомо', 'center': '—'})
            caption = (
                "⚠️ **Спроба надіслати невалідний чек**\n\n"
                f"Користувач: {user_info.get('name', 'Невідомо')}\n"
                f"ЦН: {user_info.get('center', '—')}\n"
                f"Telegram ID: `{user_id}`\n"
                f"Тип документа: {doc_type}"
            )
            admins = [u for u in get_all_users()
                      if str(users_cache.get(str(u['user_id']), {}).get('role', '')).strip().lower() == 'admin']
            for admin in admins:
                try:
                    await bot.send_photo(
                        admin['user_id'],
                        photo=photo.file_id,
                        caption=caption,
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
            return

        amount = data['amount']
        expense_name = data['expense_name']
        category = data['category']
        
        # Валідація дати з чека
        raw_date = data.get('receipt_date')
        date_not_found = False
        if not raw_date or not str(raw_date).strip():
            receipt_date = datetime.now().strftime("%Y-%m-%d")
            date_not_found = True
        else:
            receipt_date = str(raw_date).strip().split(' ')[0]
            
        # Валідація часу з чека
        raw_time = data.get('receipt_time')
        if raw_time and str(raw_time).strip():
            clean_time = str(raw_time).strip().replace(':', '-')
            if len(clean_time.split('-')) == 2:
                clean_time += "-00"
            time_str = clean_time
        else:
            time_str = datetime.now().strftime("%H-%M-%S")
        
    except Exception as e:
        logging.error(f"Помилка аналізу чека: {e}", exc_info=True)
        
        err_message = "❌ Не вдалося розпізнати чек."
        # Виведення детальної діагностики за наявності прапорця в config.py
        if DEBUG_DIAGNOSTICS:
            tb_str = traceback.format_exc()
            short_tb = tb_str[-800:] if len(tb_str) > 800 else tb_str
            err_message += f"\n\n⚙️ **Діагностика помилки:**\n`{type(e).__name__}: {str(e)}`\n\n```text\n{short_tb}\n```"
            
        await msg.edit_text(err_message, parse_mode="Markdown")
        return

    # Локальне збереження файлу в структуровану папку receipts/USER_ID/YYYY/MM
    user_info = users_cache.get(user_id_str, {'name': 'User', 'center': 'Центр'})
    safe_center = "".join(c for c in user_info['center'] if c.isalnum() or c in (' ', '-', '_')).strip().replace(" ", "_")

    try:
        dt = datetime.strptime(receipt_date, "%Y-%m-%d")
    except ValueError:
        dt = datetime.now()

    year = dt.strftime("%Y")
    month = dt.strftime("%m")
    date_str = dt.strftime("%Y-%m-%d")
    
    random_suffix = uuid.uuid4().hex[:6]
    folder_path = f"receipts/{user_id}/{year}/{month}"
    
    # Використовуємо asyncio.to_thread для операцій з файловою системою
    await asyncio.to_thread(os.makedirs, folder_path, exist_ok=True)

    file_name = f"{date_str}_{time_str}-{safe_center}_{random_suffix}.jpg"
    local_path = f"{folder_path}/{file_name}"
    
    await bot.download_file(file_info.file_path, destination=local_path)
    local_url = f"{WEBAPP_URL}/{local_path}"

    # Зберігаємо отримані дані у пам'ять FSM
    await state.update_data(
        amount=amount, 
        expense_name=expense_name, 
        category=category, 
        receipt_date=receipt_date, 
        file_path=local_url,
        local_fs_path=local_path, # Зберігаємо локальний шлях для безпечного видалення при скасуванні
        valid_categories=valid_categories,
        date_not_found=date_not_found
    )                             
    
    # Якщо AI не зміг впевнено підібрати категорію — пропонуємо обрати вручну
    if not category or category not in valid_categories:
        await state.set_state(ReceiptState.waiting_for_category_selection)
        
        # Перевіряємо, чи є категорії, щоб уникнути створення клавіатури без кнопок
        if valid_categories:
            buttons = [[InlineKeyboardButton(text=cat, callback_data=f"selcat_{i}")] for i, cat in enumerate(valid_categories)]
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            reply_markup = kb
        else:
            reply_markup = None
            
        warning_msg = "⚠️ **Дату на чеку не знайдено. Встановлено поточну дату!**\n\n" if date_not_found else ""
        await msg.edit_text(
            f"{warning_msg}⚠️ Не вдалося автоматично підібрати категорію.\nБудь ласка, оберіть найбільш підходящу зі списку:", 
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        data_fsm = await state.get_data()
        await render_summary(msg, data_fsm, state)
