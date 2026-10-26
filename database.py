import asyncio
from datetime import datetime
import logging
import uuid
import time
import gspread
from google.oauth2.service_account import Credentials
from config import SPREADSHEET_ID
from fastapi import HTTPException

# Авторизація через сервісний акаунт Google
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)

gc = gspread.authorize(creds)
sh = gc.open_by_key(SPREADSHEET_ID)
users_sheet = sh.worksheet("Users")
expenses_sheet = sh.worksheet("Expenses")

try:
    categories_sheet = sh.worksheet("Categories")
except gspread.exceptions.WorksheetNotFound:
    categories_sheet = None

# Глобальний кеш даних користувачів
users_cache = {}
DEFAULT_CATEGORIES = ["Продукти", "Кафе/Ресторани", "Транспорт", "Аптека", "Інше"]

# Підключаємо аркуш API_Logs
try:
    api_logs_sheet = sh.worksheet("API_Logs")
except Exception:
    api_logs_sheet = None

# Підключаємо аркуш Budgets
try:
    budgets_sheet = sh.worksheet("Budgets")
except gspread.exceptions.WorksheetNotFound:
    budgets_sheet = None

async def log_api_usage(user_id: int, user_name: str, input_tokens: int, output_tokens: int):
    """
    Записує статистику використання Gemini API у Google Таблицю
    """
    if not api_logs_sheet:
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Formula: (Input Tokens [Col D] * $0.075 / 1M) + (Output Tokens [Col E] * $0.30 / 1M)
    cost_formula = '=(INDIRECT("D"&ROW()) * 0,75 / 1000000) + (INDIRECT("E"&ROW()) * 0,75 / 1000000)'
    
    row_data = [
        now_str,
        user_id,
        user_name,
        input_tokens,
        output_tokens,
        cost_formula
    ]
    
    # Використовуємо asyncio.to_thread, щоб не блокувати бота
    await asyncio.to_thread(
        api_logs_sheet.append_row, 
        row_data, 
        value_input_option='USER_ENTERED'
    )
    
# ==========================================
# 1. ПЕРСОНАЛЬНІ КАТЕГОРІЇ (CATEGORIES)
# ==========================================

def get_categories(user_id: int = None):
    """
    Повертає список категорій у вигляді [{ 'id': 'cat_xxx', 'name': 'Назва', 'sort': 1 }, ...].
    Якщо для user_id категорії відсутні у таблиці, автоматично генерує дефолтні.
    """
    if not categories_sheet:
        return [{'id': f'cat_default_{i}', 'name': cat, 'sort': i + 1} for i, cat in enumerate(DEFAULT_CATEGORIES)]
    
    try:
        records = categories_sheet.get_all_records()
        user_cats = []
        
        for row in records:
            if user_id is None or str(row.get('Telegram_ID', '')).strip() == str(user_id).strip():
                cat_id = str(row.get('Category_ID', '')).strip()
                cat_name = str(row.get('Category', '')).strip()
                sort_order = row.get('Sort_order', 999)
                
                try:
                    sort_order = int(sort_order)
                except (ValueError, TypeError):
                    sort_order = 999
                    
                if cat_name and cat_id:
                    user_cats.append({'id': cat_id, 'name': cat_name, 'sort': sort_order})
        
        if user_cats:
            user_cats.sort(key=lambda x: (x['sort'], x['name'].lower()))
            regular_cats = [c for c in user_cats if c['name'] != "Інше"]
            other_cats = [c for c in user_cats if c['name'] == "Інше"]
            return regular_cats + other_cats

        # Створення категорій за замовчуванням для нового користувача
        if user_id is not None:
            headers = categories_sheet.row_values(1)
            if not headers or "Category_ID" not in headers:
                categories_sheet.clear()
                categories_sheet.append_row(["Category_ID", "Telegram_ID", "Category", "Sort_order"], value_input_option='USER_ENTERED')

            new_rows = []
            created_cats = []
            for idx, cat_name in enumerate(DEFAULT_CATEGORIES):
                cat_id = f"cat_{uuid.uuid4().hex[:8]}"
                new_rows.append([cat_id, str(user_id), cat_name, idx + 1])
                created_cats.append({'id': cat_id, 'name': cat_name, 'sort': idx + 1})
            
            categories_sheet.append_rows(new_rows, value_input_option='USER_ENTERED')
            return created_cats

    except Exception as e:
        logging.error(f"Помилка зчитування категорій з таблиці: {e}")
        
    return [{'id': f'cat_default_{i}', 'name': cat, 'sort': i + 1} for i, cat in enumerate(DEFAULT_CATEGORIES)]


def get_category_id_by_name(category_name: str, user_id: int = None) -> str:
    """Знаходить Category_ID за назвою категорії або повертає переданий ID."""
    if not category_name or not str(category_name).strip():
        category_name = "Інше"

    cats = get_categories(user_id)
    target = str(category_name).strip().lower()

    for c in cats:
        if str(c['id']).strip().lower() == target:
            return str(c['id']).strip()

    for c in cats:
        if str(c['name']).strip().lower() == target:
            return str(c['id']).strip()

    for c in cats:
        if str(c['name']).strip().lower() == "інше":
            return str(c['id']).strip()

    return str(cats[0]['id']).strip() if cats else 'cat_other'


def build_category_formula(category_input: str, user_id: int = None) -> str:
    """Генерує формулу Google Sheets =XLOOKUP для відносної прив'язки назви категорії за ID."""
    cat_str = str(category_input).strip()
    cats = get_categories(user_id)
    
    existing_ids = [str(c['id']).strip() for c in cats]
    
    if cat_str in existing_ids:
        cat_id = cat_str
    else:
        cat_id = get_category_id_by_name(cat_str, user_id)

    formatted_id = cat_id if cat_id.isdigit() else f'"{cat_id}"'
    return f'=XLOOKUP({formatted_id}; Categories!A:A; Categories!C:C; "Інше")'


async def add_user_category(user_id: int, category_name: str, sort_order: int = 999):
    """Додавання персональної категорії користувача."""
    if not categories_sheet:
        return
    
    category_name = category_name.strip()
    if not category_name:
        return

    try:
        headers = await asyncio.to_thread(categories_sheet.row_values, 1)
        if not headers or "Category_ID" not in headers:
            await asyncio.to_thread(categories_sheet.clear)
            await asyncio.to_thread(categories_sheet.append_row, ["Category_ID", "Telegram_ID", "Category", "Sort_order"], value_input_option='USER_ENTERED')

        #new_cat_id = f"cat_{uuid.uuid4().hex[:8]}"
        new_cat_id = f"cat_{user_id}_{uuid.uuid4().hex[:8]}"
        row_data = [new_cat_id, str(user_id), category_name, sort_order]

        await asyncio.to_thread(
            categories_sheet.append_row, 
            row_data, 
            value_input_option='USER_ENTERED'
        )
    except Exception as e:
        logging.error(f"Помилка додавання категорії: {e}")


async def delete_user_category(user_id: int, category_name: str):
    """Видаляє персональну категорію користувача."""
    if not categories_sheet:
        return
        
    if category_name.strip() == "Інше":
        raise HTTPException(status_code=400, detail="Категорію 'Інше' заблоковано від видалення")
    
    try:
        records = await asyncio.to_thread(categories_sheet.get_all_records)
        for i, row in enumerate(records):
            if str(row.get('Telegram_ID', '')).strip() == str(user_id).strip() and str(row.get('Category', '')).strip().lower() == category_name.strip().lower():
                await asyncio.to_thread(categories_sheet.delete_rows, i + 2)
                break
    except Exception as e:
        logging.error(f"Помилка видалення категорії: {e}")


async def rename_user_category(user_id: int, old_name: str, new_name: str):
    """Оновлює назву персональної категорії."""
    if not categories_sheet:
        return
    
    try:
        records = await asyncio.to_thread(categories_sheet.get_all_records)
        for i, row in enumerate(records):
            if str(row.get('Telegram_ID', '')).strip() == str(user_id).strip() and str(row.get('Category', '')).strip().lower() == old_name.strip().lower():
                await asyncio.to_thread(categories_sheet.update_cell, i + 2, 3, new_name.strip())
                break
    except Exception as e:
        logging.error(f"Помилка перейменування категорії: {e}")


async def save_user_categories(user_id: int, categories_list: list):
    """Перезаписує список категорій користувача."""
    if not categories_sheet:
        return
    
    clean_cats = []
    for c in categories_list:
        c_str = str(c).strip()
        if c_str and c_str not in clean_cats:
            clean_cats.append(c_str)
            
    if "Інше" not in clean_cats:
        clean_cats.append("Інше")

    try:
        headers = await asyncio.to_thread(categories_sheet.row_values, 1)
        if not headers or "Category_ID" not in headers:
            await asyncio.to_thread(categories_sheet.clear)
            await asyncio.to_thread(categories_sheet.append_row, ["Category_ID", "Telegram_ID", "Category", "Sort_order"], value_input_option='USER_ENTERED')

        records = await asyncio.to_thread(categories_sheet.get_all_records)
        
        rows_to_delete = []
        for i, row in enumerate(records):
            if str(row.get('Telegram_ID', '')).strip() == str(user_id).strip():
                rows_to_delete.append(i + 2)
                
        for row_num in reversed(rows_to_delete):
            await asyncio.to_thread(categories_sheet.delete_rows, row_num)
            
        new_rows = [[f"cat_{uuid.uuid4().hex[:8]}", str(user_id), cat, idx + 1] for idx, cat in enumerate(clean_cats)]
        if new_rows:
            await asyncio.to_thread(categories_sheet.append_rows, new_rows, value_input_option='USER_ENTERED')
    except Exception as e:
        logging.error(f"Помилка збереження категорій: {e}")


# ==========================================
# 2. КОРИСТУВАЧІ ТА ЦЕНТРИ (USERS)
# ==========================================

def load_users():
    """Завантажує список користувачів у кеш пам'яті."""
    records = users_sheet.get_all_records()
    for row in records:
        users_cache[str(row['Telegram_ID'])] = {
            'name': row.get('Name', 'Невідомо'),
            'center': row.get('Center', 'МійЦентр'),
            'role': row.get('Role', 'user')
        }

async def add_user(user_id: int, name: str, center: str, date_str: str, role: str = 'user'):
    """Додає нового користувача в кеш та у таблицю Users."""
    await asyncio.to_thread(
        users_sheet.append_row, 
        [str(user_id), name, center, date_str, role], 
        value_input_option='USER_ENTERED'
    )
    users_cache[str(user_id)] = {'name': name, 'center': center, 'role': role}


async def update_user_center(user_id: int, new_center: str):
    """Оновлює назву центру користувача."""
    u_key = str(user_id)
    if u_key in users_cache:
        users_cache[u_key]['center'] = new_center
    records = await asyncio.to_thread(users_sheet.get_all_records)
    for i, row in enumerate(records):
        if str(row.get('Telegram_ID')).strip() == u_key:
            await asyncio.to_thread(users_sheet.update_cell, i + 2, 3, new_center)
            break


# ==========================================
# 3. ВИ ТРАТИ (EXPENSES) З ДИНАМІЧНИМ ПОШУКОМ
# ==========================================

async def add_expense(row_data: list) -> str:
    """
    Очікує row_data: [date, user_id, user_name, amount, expense_name, category_id_or_formula, file_path]
    Генерує унікальний Expense_ID і додає його першим елементом у колонку A.
    """
    user_id = row_data[1]
    category_val = str(row_data[5])
    if not category_val.startswith('='):
        row_data[5] = await asyncio.to_thread(build_category_formula, category_val, user_id)

    timestamp_ms = int(time.time() * 1000)
    expense_id = f"exp_{timestamp_ms}_{user_id}_{uuid.uuid4().hex[:4]}"
    full_row = [expense_id] + row_data

    await asyncio.to_thread(
        expenses_sheet.append_row, 
        full_row, 
        value_input_option='USER_ENTERED'
    )
    return expense_id


async def find_row_by_expense_id(expense_id: str, user_id: int):
    """
    Шукає актуальний номер рядка у Google Таблиці за сумісним збігом:
    Expense_ID ТА Telegram_ID користувача. Гарантує захист від перехресного доступу та зсуву рядків.
    """
    records = await asyncio.to_thread(expenses_sheet.get_all_records, value_render_option='UNFORMATTED_VALUE')
    for i, row in enumerate(records):
        if str(row.get('Expense_ID', '')).strip() == str(expense_id).strip() and str(row.get('Telegram_ID', '')).strip() == str(user_id).strip():
            return i + 2
    return None


async def update_expense(expense_id: str, user_id: int, row_data: list):
    """
    Знаходить актуальний рядок за expense_id та user_id і оновлює його.
    """
    row_num = await find_row_by_expense_id(expense_id, user_id)
    if not row_num:
        raise HTTPException(status_code=403, detail="Запис не знайдено або доступ заборонено")

    category_val = str(row_data[5])
    if not category_val.startswith('='):
        row_data[5] = await asyncio.to_thread(build_category_formula, category_val, user_id)

    full_row = [expense_id] + row_data
    range_name = f"A{row_num}:H{row_num}"
    await asyncio.to_thread(expenses_sheet.update, values=[full_row], range_name=range_name, value_input_option='USER_ENTERED')
    return True


async def delete_expense(expense_id: str, user_id: int):
    """
    Знаходить актуальний рядок за expense_id та user_id і видаляє його.
    """
    row_num = await find_row_by_expense_id(expense_id, user_id)
    if not row_num:
        raise HTTPException(status_code=403, detail="Запис не знайдено або доступ заборонено")

    await asyncio.to_thread(expenses_sheet.delete_rows, row_num)
    return True


async def get_user_expenses(user_id: int):
    """
    Отримує витрати ТІЛЬКИ вказаного користувача user_id разом із їх Expense_ID.
    """
    records = await asyncio.to_thread(expenses_sheet.get_all_records, value_render_option='UNFORMATTED_VALUE')
    user_expenses = []
    for i, row in enumerate(records):
        if str(row.get('Telegram_ID', '')).strip() == str(user_id).strip():
            row_data = dict(row)
            row_data['row_num'] = i + 2 
            user_expenses.append(row_data)
    user_expenses.reverse()
    return user_expenses


# ==========================================
# 4. ДОДАТКОВІ ФУНКЦІЇ КОРИСТУВАЧІВ
# ==========================================

def is_admin(user_id: int) -> bool:
    """Перевіряє, чи має користувач права адміністратора."""
    u_info = users_cache.get(str(user_id), {})
    return str(u_info.get('role', '')).strip().lower() == 'admin'

def get_all_users() -> list:
    """Повертає список усіх користувачів (для адміна)."""
    users_list = []
    for uid, info in users_cache.items():
        users_list.append({
            'user_id': uid,
            'name': info.get('name', 'Невідомо'),
            'center': info.get('center', 'Невідомо')
        })
    # Сортуємо за ім'ям
    users_list.sort(key=lambda x: x['name'].lower())
    return users_list

# ==========================================
# 5. БЮДЖЕТИ (BUDGETS)
# ==========================================

async def setup_budgets_sheet_if_needed():
    """Створює колонки на аркуші Budgets, якщо він порожній."""
    global budgets_sheet
    if not budgets_sheet:
        try:
            budgets_sheet = await asyncio.to_thread(sh.add_worksheet, title="Budgets", rows="1000", cols="10")
        except Exception as e:
            logging.error(f"Помилка створення аркуша Budgets: {e}")
            return
            
    try:
        headers = await asyncio.to_thread(budgets_sheet.row_values, 1)
        if not headers or "Budget_ID" not in headers:
            await asyncio.to_thread(budgets_sheet.clear)
            await asyncio.to_thread(
                budgets_sheet.append_row, 
                ["Budget_ID", "Telegram_ID", "Category_ID", "Month", "Amount", "Updated_At"], 
                value_input_option='USER_ENTERED'
            )
    except Exception as e:
        logging.error(f"Помилка ініціалізації заголовків Budgets: {e}")


async def set_user_budget(user_id: int, category_id: str, month: str, amount: float):
    """
    Встановлює або оновлює бюджет для користувача на певну категорію і місяць.
    month очікується у форматі 'YYYY-MM'.
    """
    await setup_budgets_sheet_if_needed()
    if not budgets_sheet:
        return None
        
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    budget_id = f"bgt_{month}_{user_id}_{category_id}"
    
    try:
        records = await asyncio.to_thread(budgets_sheet.get_all_records, value_render_option='UNFORMATTED_VALUE')
        
        # Шукаємо існуючий запис
        for i, row in enumerate(records):
            if str(row.get('Telegram_ID', '')).strip() == str(user_id).strip() and \
               str(row.get('Category_ID', '')).strip() == str(category_id).strip() and \
               str(row.get('Month', '')).strip() == str(month).strip():
                
                # Оновлюємо існуючий
                row_num = i + 2
                range_name = f"A{row_num}:F{row_num}"
                row_data = [budget_id, str(user_id), category_id, month, amount, now_str]
                await asyncio.to_thread(budgets_sheet.update, values=[row_data], range_name=range_name, value_input_option='USER_ENTERED')
                return budget_id
                
        # Якщо не знайдено, додаємо новий
        row_data = [budget_id, str(user_id), category_id, month, amount, now_str]
        await asyncio.to_thread(budgets_sheet.append_row, row_data, value_input_option='USER_ENTERED')
        return budget_id
        
    except Exception as e:
        logging.error(f"Помилка встановлення бюджету: {e}")
        raise HTTPException(status_code=500, detail="Помилка збереження бюджету")


async def get_user_budgets(user_id: int, month: str) -> dict:
    """
    Отримує заплановані бюджети користувача на вказаний місяць.
    Повертає словник { category_id: amount }
    """
    if not budgets_sheet:
        return {}
        
    try:
        records = await asyncio.to_thread(budgets_sheet.get_all_records, value_render_option='UNFORMATTED_VALUE')
        budgets_map = {}
        
        for row in records:
            if str(row.get('Telegram_ID', '')).strip() == str(user_id).strip() and \
               str(row.get('Month', '')).strip() == str(month).strip():
               
                cat_id = str(row.get('Category_ID', '')).strip()
                try:
                    amount = float(row.get('Amount', 0))
                except (ValueError, TypeError):
                    amount = 0.0
                    
                if cat_id:
                    budgets_map[cat_id] = amount
                    
        return budgets_map
    except Exception as e:
        logging.error(f"Помилка отримання бюджетів: {e}")
        return {}
