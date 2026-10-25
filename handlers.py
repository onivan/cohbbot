import os
import io
import asyncio
import logging
import urllib.parse
import uuid
import traceback
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from PIL import Image

# Внутрішні модулі проєкту
from config import TELEGRAM_TOKEN, WEBAPP_URL, DEBUG_DIAGNOSTICS
from database import (
    users_cache, add_expense, add_user, update_user_center, 
    get_categories, build_category_formula, get_category_id_by_name,
    load_users, log_api_usage
)
from ai_service import parse_receipt_image

# Ініціалізація бота та диспетчера
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Головне меню з кнопками відкриття Web App та інструкції
webapp_kb = ReplyKeyboardMarkup(
    keyboard=[
        #[KeyboardButton(text="📊 Мої витрати", web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton(text="📖 Інструкція")]
    ],
    resize_keyboard=True
)

# --- ДОПОМІЖНА ФУНКЦІЯ ЗЧИТУВАННЯ ІНСТРУКЦІЇ З .MD ФАЙЛУ ---

def load_instruction_md(file_path: str = "instruction.md") -> str:
    """Зчитує текст інструкції у форматі Markdown з файлу на диску"""
    if not os.path.exists(file_path):
        return "⚠️ Файл інструкції (`instruction.md`) не знайдено."
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logging.error(f"Помилка зчитування {file_path}: {e}")
        return "❌ Не вдалося завантажити інструкцію."


# --- СТАНИ FSM (МАШИНИ СТАНІВ) ---

class UserState(StatesGroup):
    """Стани первинної реєстрації користувача"""
    waiting_for_name = State()    # Очікування введення імені
    waiting_for_center = State()  # Очікування введення назви центру/підрозділу

class SettingsState(StatesGroup):
    """Стани зміни налаштувань"""
    waiting_for_new_center = State()  # Очікування нової назви центру

class ReceiptState(StatesGroup):
    """Стани підтвердження та редагування розпізнаного чека"""
    waiting_for_confirmation = State()        # Головний екран картки чека
    waiting_for_edit_date = State()           # Введення нової дати текстом
    waiting_for_edit_amount = State()         # Введення нової суми текстом
    waiting_for_edit_name = State()           # Введення нової назви текстом
    waiting_for_edit_category = State()       # Введення нової категорії текстом
    waiting_for_category_selection = State()  # Вибір категорії кнопками


# --- ДОПОМІЖНІ ФУНКЦІЇ ВІДОБРАЖЕННЯ ---

async def render_summary(message_obj, data: dict, state: FSMContext):
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
    
    text = (
        f"{date_warning}"
        f"📅 Дата: **{date_only}**\n"
        f"💰 Сума: **{data.get('amount')} грн**\n"
        f"🏷 Назва: *в*{data.get('expense_name')}**\n"
        f"📂 Категорія: **{data.get('category')}**\n\n"
        f"Зберігаємо одразу чи хочете підправити дані у зручній формі?"
    )
    
    await state.set_state(ReceiptState.waiting_for_confirmation)
    
    if message_obj.from_user.is_bot:
        await message_obj.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await message_obj.answer(text, parse_mode="Markdown", reply_markup=kb)


# --- ОБРОБНИКИ КОМАНД СТАРТУ, НАЛАШТУВАНЬ ТА ІНСТРУКЦІЇ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Обробка команди /start: вітання або запуск реєстрації"""
    user_id_str = str(message.from_user.id)
    
    if user_id_str not in users_cache:
        await asyncio.to_thread(load_users)
        
    if user_id_str in users_cache:
        user_name = users_cache[user_id_str].get('name', 'Користувач')
        await message.answer(
            f"Привіт, {user_name}! Надішліть чек або перегляньте статистику.\n(Змінити назву центру можна командою /settings, переглянути інструкцію — /help)",
            reply_markup=webapp_kb
        )
    else:
        await message.answer("Привіт! Я бот для обліку витрат. Введіть своє ім'я:")
        await state.set_state(UserState.waiting_for_name)

@dp.message(UserState.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    """Крок 1 реєстрації: отримання імені"""
    await state.update_data(name=message.text.strip())
    await message.answer("Тепер введіть назву вашого центру (наприклад: ЦН Київ):")
    await state.set_state(UserState.waiting_for_center)

@dp.message(UserState.waiting_for_center)
async def process_center(message: types.Message, state: FSMContext):
    """Крок 2 реєстрації: отримання центру та збереження в базу"""
    center = message.text.strip()
    data = await state.get_data()
    name = data['name']
    user_id = message.from_user.id
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    await add_user(user_id, name, center, date_str)
    await state.clear()
    await message.answer(f"Приємно познайомитись, {name} з «{center}»! Тепер ви можете надсилати фото чеків або додавати витрати вручну натиснувши кнопку «Витрати».", reply_markup=webapp_kb)

@dp.message(Command("settings"))
async def cmd_settings(message: types.Message, state: FSMContext):
    """Запит на зміну центру"""
    await message.answer("Введіть нову назву центру:")
    await state.set_state(SettingsState.waiting_for_new_center)

@dp.message(SettingsState.waiting_for_new_center)
async def process_new_center(message: types.Message, state: FSMContext):
    """Збереження оновленої назви центру"""
    new_center = message.text.strip()
    await update_user_center(message.from_user.id, new_center)
    await state.clear()
    await message.answer(f"✅ Назву центру змінено на «{new_center}».")

@dp.message(Command("help", "instruction", "guide"))
@dp.message(F.text.in_(["📖 Інструкція", "❓ Допомога", "Інструкція"]))
async def cmd_instruction(message: types.Message):
    """
    Обробник виклику інструкції з файлу .md:
    Спрацьовує на команди /help, /instruction, /guide
    та на натискання кнопки «📖 Інструкція».
    """
    instruction_text = await asyncio.to_thread(load_instruction_md, "instruction.md")
    await message.answer(instruction_text, parse_mode="Markdown")


# --- ОБРОБКА ФОТОГРАФІЇ ЧЕКА ---

@dp.message(F.photo)
async def process_receipt_photo(message: types.Message, state: FSMContext):
    """
    Основна функція обробки фото чека:
    1. Завантаження фото.
    2. Отримання категорій користувача.
    3. Виклик Gemini 3.8 Flash.
    4. Збереження файлу локально у структуровані папки (YYYY/MM).
    5. Діагностика помилок у разі збою.
    """
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in users_cache:
        await asyncio.to_thread(load_users)
        
    if user_id_str not in users_cache:
        await message.answer("Будь ласка, спочатку зареєструйтеся за допомогою команди /start")
        return

    msg = await message.answer("⏳ Читаю чек...")
    
    try:
        # Завантажуємо зображення
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        downloaded_file = await bot.download_file(file_info.file_path)
        image = Image.open(io.BytesIO(downloaded_file.read()))
        
        # Отримуємо список категорій користувача з бази
        raw_categories = await asyncio.to_thread(get_categories, user_id)
        
        # Перетворюємо словники/рядки у чистий список текстових назв
        valid_categories = []
        for cat in raw_categories:
            if isinstance(cat, dict):
                valid_categories.append(cat.get('name', ''))
            else:
                valid_categories.append(str(cat))
        valid_categories = [c for c in valid_categories if c]

        # Передаємо зображення в модуль AI
        data = await parse_receipt_image(image, valid_categories)
        
        usage = data.get('_usage', {})
        if usage:
            user_info = users_cache.get(user_id_str, {'name': 'User', 'center': 'Центр'})
            user_name = user_info.get('name', 'Невідомо')
            
            # Асинхронно записуємо лог
            asyncio.create_task(
                log_api_usage(
                    user_id=user_id,
                    user_name=user_name,
                    input_tokens=usage.get('input_tokens', 0),
                    output_tokens=usage.get('output_tokens', 0)
                )
            )
        
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
    os.makedirs(folder_path, exist_ok=True)

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
        valid_categories=valid_categories,
        date_not_found=date_not_found
    )                             
    
    # Якщо AI не зміг впевнено підібрати категорію — пропонуємо обрати вручну
    if not category or category not in valid_categories:
        await state.set_state(ReceiptState.waiting_for_category_selection)
        buttons = [[InlineKeyboardButton(text=cat, callback_data=f"selcat_{i}")] for i, cat in enumerate(valid_categories)]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        warning_msg = "⚠️ **Дату на чеку не знайдено. Встановлено поточну дату!**\n\n" if date_not_found else ""
        await msg.edit_text(
            f"{warning_msg}⚠️ Не вдалося автоматично підібрати категорію.\nБудь ласка, оберіть найбільш підходящу зі списку:", 
            reply_markup=kb,
            parse_mode="Markdown"
        )
    else:
        data_fsm = await state.get_data()
        await render_summary(msg, data_fsm, state)


# --- ОБРОБКА ВИБОРУ КАТЕГОРІЙ ТА ЗБЕРЕЖЕННЯ ---

@dp.callback_query(F.data.startswith("selcat_"), ReceiptState.waiting_for_category_selection)
async def process_category_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """Вибір категорії за допомогою інлайн-кнопок"""
    idx = int(callback_query.data.split("_")[1])
    data = await state.get_data()
    valid_categories = data.get('valid_categories', [])
    
    if idx < len(valid_categories):
        selected_category = valid_categories[idx]
        await state.update_data(category=selected_category)
        
    data_fsm = await state.get_data()
    await render_summary(callback_query.message, data_fsm, state)
    await callback_query.answer()

@dp.callback_query(F.data.in_(["receipt_save", "receipt_cancel"]), ReceiptState.waiting_for_confirmation)
async def process_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Остаточне збереження в Google Таблицю або скасування запису"""
    data = await state.get_data()
    user_id = callback_query.from_user.id
    
    if callback_query.data == "receipt_save":
        user_id_str = str(user_id)
        user_info = users_cache.get(user_id_str, {})
        user_name = user_info.get('name', 'Невідомо')
        
        receipt_date = data.get('receipt_date')
        if not receipt_date or not str(receipt_date).strip():
            receipt_date = datetime.now().strftime("%Y-%m-%d")
        else:
            receipt_date = str(receipt_date).strip().split(' ')[0]

        category_name = data.get('category', 'Інше')
        
        # Формуємо формулу XLOOKUP для відносної прив'язки категорії в Sheets
        cat_id = await asyncio.to_thread(get_category_id_by_name, category_name, user_id)
        category_formula = await asyncio.to_thread(build_category_formula, cat_id, user_id)

        row_data = [
            receipt_date, 
            user_id, 
            user_name, 
            data['amount'], 
            data['expense_name'], 
            category_formula,
            data.get('file_path', '')
        ]
        
        await add_expense(row_data)
        await callback_query.message.edit_text(
            f"✅ Збережено: **{data['amount']} грн** за {receipt_date} у «{category_name}».", 
            parse_mode="Markdown"
        )
    
    elif callback_query.data == "receipt_cancel":
        # Видаляємо локальний файл у разі скасування
        url_path = data.get('file_path', '')
        if url_path:
            parsed_url = urllib.parse.urlparse(url_path)
            local_path = parsed_url.path.lstrip('/')
            if os.path.exists(local_path):
                os.remove(local_path)
                
        await callback_query.message.edit_text("🚫 Скасовано.")
        
    await state.clear()
    await callback_query.answer()
