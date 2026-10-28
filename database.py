import asyncio
import logging
import uuid
import time
from datetime import datetime
import aiomysql
from fastapi import HTTPException
from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

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
                await cur.execute("INSERT INTO centers (name, city) VALUES (%s, %s)", (new_center, city))
                center_id = cur.lastrowid
                
            await cur.execute("UPDATE users SET center_id = %s WHERE telegram_id = %s", (center_id, user_id))
    
    if str(user_id) in users_cache:
        users_cache[str(user_id)]['center'] = new_center
        users_cache[str(user_id)]['center_id'] = center_id

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
            query += " ORDER BY sort_order ASC"
            await cur.execute(query)
            return await cur.fetchall()

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
async def add_user_category(user_id: int, category_name: str, sort_order: int = 999): pass
async def delete_user_category(user_id: int, category_name: str): pass
async def rename_user_category(user_id: int, old_name: str, new_name: str): pass
async def save_user_categories(user_id: int, categories_list: list): pass


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

async def get_user_expenses(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
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
    pool = await get_pool()
    u_info = users_cache.get(str(user_id), {})
    center_id = u_info.get('center_id')
    if not center_id:
        raise HTTPException(status_code=400, detail="Користувач не прив'язаний до ЦН")
        
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
# 5. API ЛОГИ
# ==========================================

async def log_api_usage(user_id: int, user_name: str, input_tokens: int, output_tokens: int):
    pool = await get_pool()
    estimated_cost = (input_tokens * 0.000075) + (output_tokens * 0.00030)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO api_logs (user_id, user_name, input_tokens, output_tokens, estimated_cost) 
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, user_name, input_tokens, output_tokens, estimated_cost))

