import asyncio
import logging
import uuid
import time
from datetime import datetime
import aiomysql
from fastapi import HTTPException
from config import (
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME,
    OPENROUTER_API_KEY, OPENROUTER_MODEL,
)

# Глобальний кеш даних користувачів
users_cache = {}

_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await aiomysql.create_pool(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            autocommit=True
        )
    return _pool

# ==========================================
# 1. КОРИСТУВАЧІ ТА ЦЕНТРИ (USERS & CENTERS)
# ==========================================

async def load_users():
    """Завантажує список користувачів у кеш пам'яті з MySQL."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT u.telegram_id, u.name, u.role, u.status, u.center_id, c.name as center_name 
                FROM users u
                LEFT JOIN centers c ON u.center_id = c.id
            """)
            records = await cur.fetchall()
            users_cache.clear()
            for r in records:
                users_cache[str(r['telegram_id'])] = {
                    'name': r['name'],
                    'center': r['center_name'] or 'Не призначено',
                    'center_id': r['center_id'],
                    'role': r['role'],
                    'status': r['status']
                }

async def add_user(user_id: int, name: str, city: str, center_id: int = None, role: str = 'user', status: str = 'pending'):
    """Додає нового користувача в кеш та у таблицю MySQL."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO users (telegram_id, name, city, center_id, role, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    name=VALUES(name), city=VALUES(city), center_id=VALUES(center_id), 
                    role=VALUES(role), status=VALUES(status)
            """, (user_id, name, city, center_id, role, status))
            
    # Завантажуємо оновленого користувача в кеш, щоб отримати назву центру (якщо є)
    await load_users()

async def update_user_center(user_id: int, new_center: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM centers WHERE name = %s", (new_center,))
            row = await cur.fetchone()
            if row:
                center_id = row[0]
            else:
                city = new_center.replace("ЦН", "").replace("цн", "").strip() or "Україна"
                await cur.execute("INSERT INTO centers (name, city, is_active) VALUES (%s, %s, 1)", (new_center, city))
                center_id = cur.lastrowid
                
            await cur.execute("UPDATE users SET center_id = %s, status = 'active' WHERE telegram_id = %s", (center_id, user_id))
    
    if str(user_id) in users_cache:
        users_cache[str(user_id)]['center'] = new_center
        users_cache[str(user_id)]['center_id'] = center_id
        users_cache[str(user_id)]['status'] = 'active'
        
    return center_id

def is_admin(user_id: int) -> bool:
    return str(users_cache.get(str(user_id), {}).get('role', '')).strip().lower() == 'admin'

def get_all_users() -> list:
    users_list = []
    for uid, info in users_cache.items():
        users_list.append({
            'user_id': uid,
            'name': info.get('name', 'Невідомо'),
            'center': info.get('center', 'Невідомо')
        })
    users_list.sort(key=lambda x: x['name'].lower())
    return users_list

async def get_centers(only_active: bool = False):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = "SELECT * FROM centers"
            if only_active:
                query += " WHERE is_active = 1"
            await cur.execute(query)
            return await cur.fetchall()

async def get_centers_summary(month: str = None):
    """Отримує зведення по всіх активних центрах: підсумок витрат та бюджету на місяць."""
    pool = await get_pool()
    if not month:
        month = datetime.now().strftime("%Y-%m")
        
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT id, name, city FROM centers WHERE is_active = 1 ORDER BY name ASC")
            centers = await cur.fetchall()
            
            # Підсумок бюджету по кожному центру за місяць
            await cur.execute("""
                SELECT center_id, SUM(amount) as total_budget
                FROM budgets
                WHERE month = %s
                GROUP BY center_id
            """, (month,))
            budgets_raw = await cur.fetchall()
            budgets_map = {b['center_id']: float(b['total_budget']) for b in budgets_raw}
            
            # Підсумок витрат по кожному центру за місяць
            await cur.execute("""
                SELECT center_id, SUM(amount) as total_spent
                FROM expenses
                WHERE DATE_FORMAT(date, '%%Y-%%m') = %s
                GROUP BY center_id
            """, (month,))
            expenses_raw = await cur.fetchall()
            expenses_map = {e['center_id']: float(e['total_spent']) for e in expenses_raw}
            
            result = []
            for c in centers:
                cid = c['id']
                b_val = budgets_map.get(cid, 0.0)
                e_val = expenses_map.get(cid, 0.0)
                result.append({
                    'id': cid,
                    'name': c['name'],
                    'city': c['city'],
                    'total_budget': b_val,
                    'total_spent': e_val,
                    'has_budget': cid in budgets_map
                })
            return result

async def get_all_users_details() -> list:
    """Отримує детальний список користувачів для панелі адміна."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT u.telegram_id, u.name, u.city, u.role, u.status, u.center_id, c.name as center_name 
                FROM users u
                LEFT JOIN centers c ON u.center_id = c.id
                ORDER BY u.name ASC
            """)
            return await cur.fetchall()

async def create_center(name: str, city: str, is_active: int = 1) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO centers (name, city, is_active) VALUES (%s, %s, %s)", (name, city, is_active))
            return cur.lastrowid

async def update_center_details(center_id: int, name: str, city: str, is_active: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE centers SET name=%s, city=%s, is_active=%s WHERE id=%s", (name, city, is_active, center_id))
            return cur.rowcount > 0

async def admin_set_user_center(user_id: int, center_id: int = None) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if center_id:
                await cur.execute("UPDATE users SET center_id = %s, status = 'active' WHERE telegram_id = %s", (center_id, user_id))
            else:
                await cur.execute("UPDATE users SET center_id = NULL WHERE telegram_id = %s", (user_id,))
            if cur.rowcount > 0:
                await load_users() # Оновлюємо кеш
                return True
    return False

# ==========================================
# 2. КАТЕГОРІЇ
# ==========================================

async def get_categories(user_id: int = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            if user_id:
                u_info = users_cache.get(str(user_id), {})
                center_id = u_info.get('center_id')
                if center_id:
                    await cur.execute("""
                        SELECT c.id, c.name, c.sort_order as sort
                        FROM categories c
                        JOIN center_categories cc ON c.id = cc.category_id
                        WHERE cc.center_id = %s AND c.is_active = 1
                        ORDER BY c.sort_order ASC, c.name ASC
                    """, (center_id,))
                    cats = await cur.fetchall()
                    if cats:
                        regular = [c for c in cats if c['name'] != 'Інше']
                        other = [c for c in cats if c['name'] == 'Інше']
                        return regular + other
            
            await cur.execute("SELECT id, name, sort_order as sort FROM categories WHERE is_active = 1 ORDER BY sort_order ASC, name ASC")
            cats = await cur.fetchall()
            regular = [c for c in cats if c['name'] != 'Інше']
            other = [c for c in cats if c['name'] == 'Інше']
            return regular + other

async def get_category_id_by_name(category_name: str, user_id: int = None) -> str:
    cats = await get_categories(user_id)
    target = str(category_name).strip().lower()
    for c in cats:
        if str(c['id']).strip().lower() == target: return str(c['id']).strip()
    for c in cats:
        if str(c['name']).strip().lower() == target: return str(c['id']).strip()
    for c in cats:
        if str(c['name']).strip().lower() == "інше": return str(c['id']).strip()
    return str(cats[0]['id']).strip() if cats else 'cat_other'

def build_category_formula(*args, **kwargs): 
    return ""

async def get_all_categories(only_active: bool = False):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = "SELECT * FROM categories"
            if only_active: query += " WHERE is_active=1"
            query += " ORDER BY sort_order ASC, name ASC"
            await cur.execute(query)
            return await cur.fetchall()

async def create_category(id: str, name: str, sort_order: int = 999):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO categories (id, name, sort_order) VALUES (%s, %s, %s)", (id, name, sort_order))

async def update_category(id: str, name: str, sort_order: int, is_active: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE categories SET name=%s, sort_order=%s, is_active=%s WHERE id=%s", (name, sort_order, is_active, id))

async def get_category_matrix():
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # Отримуємо всі центри, всі категорії та зв'язки
            await cur.execute("SELECT id, name FROM centers WHERE is_active=1 ORDER BY name ASC")
            centers = await cur.fetchall()
            
            await cur.execute("SELECT id, name FROM categories WHERE is_active=1 ORDER BY sort_order ASC, name ASC")
            categories = await cur.fetchall()
            
            await cur.execute("SELECT center_id, category_id FROM center_categories")
            links = await cur.fetchall()
            
            return {
                "centers": centers,
                "categories": categories,
                "links": links
            }

async def get_categories_for_center(center_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT c.* FROM categories c
                JOIN center_categories cc ON c.id = cc.category_id
                WHERE cc.center_id = %s
            """, (center_id,))
            return await cur.fetchall()

async def set_center_category(center_id: int, category_id: str, is_enabled: bool):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if is_enabled:
                await cur.execute("INSERT IGNORE INTO center_categories (center_id, category_id) VALUES (%s, %s)", (center_id, category_id))
            else:
                await cur.execute("DELETE FROM center_categories WHERE center_id=%s AND category_id=%s", (center_id, category_id))

# Заглушки для сумісності з Phase 0 webapp
# Видалено user-specific категорійні функції



# ==========================================
# 3. ВИТРАТИ
# ==========================================

async def add_expense(row_data: list) -> str:
    date, user_id, amount, expense_name, cat_input, file_path = row_data
    cat_id = await get_category_id_by_name(cat_input, user_id)
    
    u_info = users_cache.get(str(user_id), {})
    center_id = u_info.get('center_id')
    
    if not center_id:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT center_id FROM users WHERE telegram_id = %s", (user_id,))
                row = await cur.fetchone()
                if row: center_id = row[0]
                
    if not center_id: center_id = 1
        
    timestamp_ms = int(time.time() * 1000)
    expense_id = f"exp_{timestamp_ms}_{user_id}_{uuid.uuid4().hex[:4]}"
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO expenses (id, date, telegram_id, center_id, amount, expense_name, category_id, receipt_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (expense_id, date, user_id, center_id, amount, expense_name, cat_id, file_path))
            
    return expense_id

async def update_expense(expense_id: str, user_id: int, row_data: list):
    date, uid, amount, expense_name, cat_input, file_path = row_data
    cat_id = await get_category_id_by_name(cat_input, user_id)
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                UPDATE expenses 
                SET date=%s, amount=%s, expense_name=%s, category_id=%s, receipt_path=%s
                WHERE id=%s AND telegram_id=%s
            """, (date, amount, expense_name, cat_id, file_path, expense_id, user_id))
            if cur.rowcount == 0:
                return False
    return True

async def delete_expense(expense_id: str, user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM expenses WHERE id=%s AND telegram_id=%s", (expense_id, user_id))
            if cur.rowcount == 0:
                return False
    return True

async def get_expenses_by_center(center_id: int):
    """Отримує всі витрати конкретного ЦН (для адміна)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT e.id as expense_id, e.date, e.amount, e.expense_name, e.receipt_path, c.name as category_name
                FROM expenses e
                LEFT JOIN categories c ON e.category_id = c.id
                WHERE e.center_id = %s
                ORDER BY e.created_at DESC
            """, (center_id,))
            records = await cur.fetchall()
            
            res = []
            for i, r in enumerate(records):
                res.append({
                    'row_num': i,
                    'expense_id': r['expense_id'],
                    'date': str(r['date']),
                    'amount': float(r['amount']),
                    'expense_name': r['expense_name'],
                    'category_name': r['category_name'] or 'Інше',
                    'receipt_path': r['receipt_path']
                })
            return res

async def get_all_expenses():
    """Отримує абсолютно всі витрати (для адміна)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT e.id as expense_id, e.date, e.amount, e.expense_name, e.receipt_path, c.name as category_name,
                       ce.name as center_name
                FROM expenses e
                LEFT JOIN categories c ON e.category_id = c.id
                LEFT JOIN centers ce ON e.center_id = ce.id
                ORDER BY e.created_at DESC
            """)
            records = await cur.fetchall()
            
            res = []
            for i, r in enumerate(records):
                res.append({
                    'row_num': i,
                    'expense_id': r['expense_id'],
                    'date': str(r['date']),
                    'amount': float(r['amount']),
                    'expense_name': f"[{r.get('center_name', 'ЦН')}] {r['expense_name']}", # Додаємо префікс ЦН для адміна
                    'category_name': r['category_name'] or 'Інше',
                    'receipt_path': r['receipt_path']
                })
            return res

async def get_user_expenses(user_id: int):
    pool = await get_pool()
    
    # Спочатку дізнаємося center_id користувача та його роль
    u_info = users_cache.get(str(user_id), {})
    center_id = u_info.get('center_id')
    
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # Для всіх користувачів повертаємо витрати ЇХНЬОГО центру (а не тільки їхні власні)
            # Якщо користувач не має центру, він побачить тільки свої
            if center_id:
                await cur.execute("""
                    SELECT e.id as expense_id, e.date, e.amount, e.expense_name, e.receipt_path, c.name as category_name
                    FROM expenses e
                    LEFT JOIN categories c ON e.category_id = c.id
                    WHERE e.center_id = %s
                    ORDER BY e.created_at DESC
                """, (center_id,))
            else:
                await cur.execute("""
                    SELECT e.id as expense_id, e.date, e.amount, e.expense_name, e.receipt_path, c.name as category_name
                    FROM expenses e
                    LEFT JOIN categories c ON e.category_id = c.id
                    WHERE e.telegram_id = %s
                    ORDER BY e.created_at DESC
                """, (user_id,))
                
            records = await cur.fetchall()
            
            res = []
            for i, r in enumerate(records):
                res.append({
                    'row_num': i,
                    'expense_id': r['expense_id'],
                    'date': str(r['date']),
                    'amount': float(r['amount']),
                    'expense_name': r['expense_name'],
                    'category_name': r['category_name'] or 'Інше',
                    'receipt_path': r['receipt_path']
                })
            return res

# ==========================================
# 4. БЮДЖЕТИ
# ==========================================

async def get_center_budgets(center_id: int, month: str) -> dict:
    pool = await get_pool()
    budgets_map = {}
    if not center_id: return budgets_map
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT category_id, amount FROM budgets 
                WHERE center_id = %s AND month = %s
            """, (center_id, month))
            records = await cur.fetchall()
            for r in records:
                budgets_map[r['category_id']] = float(r['amount'])
    return budgets_map

async def get_user_budgets(user_id: int, month: str) -> dict:
    pool = await get_pool()
    budgets_map = {}
    
    u_info = users_cache.get(str(user_id), {})
    center_id = u_info.get('center_id')
    if not center_id:
        return budgets_map
        
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT category_id, amount FROM budgets 
                WHERE center_id = %s AND month = %s
            """, (center_id, month))
            records = await cur.fetchall()
            for r in records:
                budgets_map[r['category_id']] = float(r['amount'])
    return budgets_map

async def set_user_budget(user_id: int, category_id: str, month: str, amount: float):
    pass # Застаріло

async def set_center_budget(center_id: int, category_id: str, month: str, amount: float):
    pool = await get_pool()
    if not center_id:
        raise HTTPException(status_code=400, detail="Не вказано ЦН")
        
    budget_id = f"bgt_{month}_{center_id}_{category_id}"
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO budgets (id, center_id, category_id, month, amount)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE amount = VALUES(amount)
            """, (budget_id, center_id, category_id, month, amount))
    return budget_id

async def debug_budgets(user_id: int, month: str) -> dict:
    return {"status": "MySQL Budgets Debug", "user_id": user_id, "month": month}

# ==========================================
# 5. API ЛОГИ ТА AI-МОДЕЛІ (OPENROUTER)
# ==========================================

async def ensure_ai_schema():
    """
    Ідемпотентно створює таблицю ai_settings та додає службові колонки
    до api_logs. Викликається один раз під час старту застосунку.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS `ai_settings` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `name` VARCHAR(191) NOT NULL COMMENT 'Назва моделі для адміна',
                    `model_id` VARCHAR(191) NOT NULL COMMENT 'ID моделі OpenRouter',
                    `api_key` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'API-ключ OpenRouter',
                    `is_active` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1 - активна модель',
                    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            # Колонки для статистики по моделях (можуть вже існувати)
            for ddl in (
                "ALTER TABLE `api_logs` ADD COLUMN `model_id` VARCHAR(191) NULL",
                "ALTER TABLE `api_logs` ADD COLUMN `ai_model_id` INT NULL",
            ):
                try:
                    await cur.execute(ddl)
                except Exception:
                    pass  # колонка вже існує (помилка 1060)


async def log_api_usage(user_id: int, user_name: str, input_tokens: int,
                        output_tokens: int, model_id: str = None,
                        ai_model_id: int = None):
    pool = await get_pool()
    estimated_cost = (input_tokens * 0.000075) + (output_tokens * 0.00030)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO api_logs
                    (user_id, user_name, input_tokens, output_tokens, estimated_cost, model_id, ai_model_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (user_id, user_name, input_tokens, output_tokens, estimated_cost, model_id, ai_model_id))


async def get_active_ai_model():
    """
    Повертає активну AI-модель у вигляді {'id', 'name', 'model_id', 'api_key'}.
    Якщо в БД немає активної моделі — фолбек на змінні оточення OPENROUTER_API_KEY.
    Якщо нічого не налаштовано — повертає None.
    """
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("""
                    SELECT id, name, model_id, api_key FROM ai_settings
                    WHERE is_active = 1 ORDER BY id ASC LIMIT 1
                """)
                row = await cur.fetchone()
        if row:
            return {
                'id': row['id'],
                'name': row['name'],
                'model_id': row['model_id'],
                'api_key': (row['api_key'] or '').strip(),
            }
    except Exception as e:
        logging.error(f"Не вдалося прочитати ai_settings: {e}")

    # Фолбек на .env (для сумісності з існуючими розгортаннями)
    if OPENROUTER_API_KEY:
        return {
            'id': None,
            'name': 'ENV (за замовчуванням)',
            'model_id': OPENROUTER_MODEL,
            'api_key': OPENROUTER_API_KEY.strip(),
        }
    return None


async def get_ai_models():
    """Повертає всі AI-моделі разом зі статистикою використання (чеки, токени)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT id, name, model_id, is_active,
                       CASE WHEN api_key IS NULL OR api_key = '' THEN 0 ELSE 1 END AS has_key
                FROM ai_settings
                ORDER BY is_active DESC, name ASC
            """)
            models = await cur.fetchall()

            await cur.execute("""
                SELECT ai_model_id,
                       COUNT(*) AS receipts,
                       COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens
                FROM api_logs
                WHERE ai_model_id IS NOT NULL
                GROUP BY ai_model_id
            """)
            stats_rows = await cur.fetchall()

    stats = {r['ai_model_id']: r for r in stats_rows}
    result = []
    for m in models:
        st = stats.get(m['id'])
        receipts = int(st['receipts']) if st else 0
        total_tokens = int(st['total_tokens']) if st else 0
        result.append({
            'id': m['id'],
            'name': m['name'],
            'model_id': m['model_id'],
            'is_active': int(m['is_active']),
            'has_key': int(m['has_key']),
            'receipts': receipts,
            'total_tokens': total_tokens,
            'tokens_per_receipt': round(total_tokens / receipts, 1) if receipts else 0,
        })
    return result


async def add_ai_model(name: str, model_id: str, api_key: str, is_active: bool = False) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if is_active:
                await cur.execute("UPDATE ai_settings SET is_active = 0")
            await cur.execute("""
                INSERT INTO ai_settings (name, model_id, api_key, is_active)
                VALUES (%s, %s, %s, %s)
            """, (name, model_id, api_key, 1 if is_active else 0))
            return cur.lastrowid


async def update_ai_model(model_pk: int, name: str, model_id: str, api_key: str = None) -> bool:
    """api_key=None означає «не змінювати існуючий ключ»."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if api_key is None:
                await cur.execute(
                    "UPDATE ai_settings SET name=%s, model_id=%s WHERE id=%s",
                    (name, model_id, model_pk)
                )
            else:
                await cur.execute(
                    "UPDATE ai_settings SET name=%s, model_id=%s, api_key=%s WHERE id=%s",
                    (name, model_id, api_key, model_pk)
                )
            return cur.rowcount > 0


async def delete_ai_model(model_pk: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM ai_settings WHERE id=%s", (model_pk,))
            return cur.rowcount > 0


async def set_active_ai_model(model_pk: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE ai_settings SET is_active = 0")
            await cur.execute("UPDATE ai_settings SET is_active = 1 WHERE id=%s", (model_pk,))
            return cur.rowcount > 0

# ==========================================
# 6. АВТЕНТИФІКАЦІЯ
# ==========================================

async def create_auth_code(user_id: int) -> str:
    """Генерує та зберігає 6-значний код для входу в веб-додаток."""
    import random
    code = f"{random.randint(100000, 999999)}"
    # Код дійсний 10 хвилин
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO auth_codes (code, telegram_id, expires_at)
                VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL 10 MINUTE))
                ON DUPLICATE KEY UPDATE code = code
            """, (code, user_id))
    return code

async def validate_auth_code(code: str) -> int:
    """Перевіряє код та повертає user_id. Якщо недійсний - повертає None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT telegram_id FROM auth_codes
                WHERE code = %s AND is_used = 0 AND expires_at > NOW()
            """, (code,))
            row = await cur.fetchone()
            if row:
                await cur.execute("UPDATE auth_codes SET is_used = 1 WHERE code = %s", (code,))
                return row['telegram_id']
    return None

