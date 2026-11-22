import asyncio
import hashlib
import logging
import json
import math
import os
import re
import uuid
import time
from datetime import datetime
from urllib.parse import unquote, urlsplit
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

def get_cached_center_id(user_id: int):
    """ID ЦН користувача з кешу пам'яті (швидкий шлях)."""
    if user_id is None:
        return None
    cid = users_cache.get(str(user_id), {}).get('center_id')
    try:
        return int(cid) if cid else None
    except (TypeError, ValueError):
        return None

async def get_user_center_id(user_id: int):
    """ID ЦН користувача: з кешу, а якщо там порожньо — напряму з БД."""
    cid = get_cached_center_id(user_id)
    if cid:
        return cid
    if user_id is None:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT center_id FROM users WHERE telegram_id = %s", (user_id,))
            row = await cur.fetchone()
            if row and row[0]:
                return int(row[0])
    return None

def _mark_own_center(centers: list, my_center_id) -> list:
    """Додає прапорець is_my_center і ставить свій ЦН першим у списку."""
    for c in centers:
        try:
            c['is_my_center'] = bool(my_center_id) and int(c['id']) == int(my_center_id)
        except (TypeError, ValueError, KeyError):
            c['is_my_center'] = False
    if my_center_id:
        centers.sort(key=lambda c: (0 if c.get('is_my_center') else 1, str(c.get('name', '')).lower()))
    return centers

async def get_centers(only_active: bool = False, user_id: int = None):
    """Список ЦН. Якщо передано user_id — свій ЦН позначено is_my_center і стоїть першим."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = "SELECT * FROM centers"
            if only_active:
                query += " WHERE is_active = 1"
            await cur.execute(query)
            centers = list(await cur.fetchall())
    my_center_id = await get_user_center_id(user_id) if user_id else None
    return _mark_own_center(centers, my_center_id)

async def get_centers_summary(month: str = None, user_id: int = None):
    """Отримує зведення по всіх активних центрах: підсумок витрат та бюджету на місяць.
    Якщо передано user_id — свій ЦН позначено is_my_center і стоїть першим."""
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

    my_center_id = await get_user_center_id(user_id) if user_id else None
    return _mark_own_center(result, my_center_id)

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

def _notify_budget_safe(center_id, category_id, day, expense_id, amount=0):
    """B2/B3: збій запуску сповіщення не скасовує вже збережену витрату."""
    try:
        import budget_notify
        budget_notify.after_expense(center_id, category_id, day, expense_id, amount)
    except Exception:
        logging.exception("Не вдалося запустити перевірку ліміту ЦН %s", center_id)


_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')


def _sha256_file(file_path: str) -> str:
    """Обчислює SHA-256 потоково, не завантажуючи весь чек у пам'ять."""
    digest = hashlib.sha256()
    with open(file_path, 'rb') as receipt:
        for chunk in iter(lambda: receipt.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def receipt_bytes_sha256(receipt_bytes: bytes) -> str:
    """SHA-256 вже завантажених байтів фото (для перевірки до AI)."""
    return hashlib.sha256(receipt_bytes).hexdigest()


async def receipt_sha256(user_id: int, receipt_path: str) -> str | None:
    """Хешує лише наявний локальний чек із receipts/{user_id}/; довільні шляхи відхиляє."""
    if not user_id or not receipt_path:
        return None
    try:
        url_path = unquote(urlsplit(str(receipt_path)).path)
        relative_path = os.path.normpath(url_path).lstrip(os.sep)
        expected_prefix = f"receipts/{int(user_id)}/"
        receipts_root = os.path.realpath('receipts')
        local_path = os.path.realpath(os.path.join(os.getcwd(), relative_path))
        if not relative_path.startswith(expected_prefix):
            return None
        if os.path.commonpath((receipts_root, local_path)) != receipts_root:
            return None
        if not os.path.isfile(local_path):
            return None
        return await asyncio.to_thread(_sha256_file, local_path)
    except (OSError, TypeError, ValueError):
        return None


async def ensure_duplicate_expense_schema():
    """Ідемпотентно додає SHA-256 чека та індекси для швидкого пошуку дублів."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for ddl in (
                "ALTER TABLE `expenses` ADD COLUMN `receipt_sha256` CHAR(64) NULL AFTER `receipt_path`",
                "ALTER TABLE `expenses` ADD INDEX `idx_expenses_center_receipt_hash` (`center_id`, `receipt_sha256`)",
                "ALTER TABLE `expenses` ADD INDEX `idx_expenses_center_amount` (`center_id`, `amount`)",
            ):
                try:
                    await cur.execute(ddl)
                except Exception as error:
                    # MySQL/MariaDB: колонка/індекс уже існує.
                    if getattr(error, 'args', (None,))[0] not in (1060, 1061, 1831):
                        raise


async def backfill_center_receipt_hashes(center_id: int) -> int:
    """Ліниво хешує legacy-фото одного ЦН пакетами, не блокуючи event loop."""
    if not center_id:
        return 0
    pool = await get_pool()
    last_id = ''
    updated_count = 0
    while True:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT id, telegram_id, receipt_path FROM expenses
                       WHERE center_id = %s AND id > %s AND receipt_sha256 IS NULL
                         AND receipt_path IS NOT NULL AND receipt_path <> ''
                       ORDER BY id LIMIT 250""",
                    (center_id, last_id),
                )
                rows = await cur.fetchall() or []
        if not rows:
            break
        last_id = rows[-1]['id']

        updates = []
        for start in range(0, len(rows), 8):
            batch = rows[start:start + 8]
            hashes = await asyncio.gather(*(
                receipt_sha256(row['telegram_id'], row['receipt_path']) for row in batch
            ))
            updates.extend(
                (digest, row['id']) for row, digest in zip(batch, hashes) if digest
            )
        if updates:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.executemany(
                        """UPDATE expenses SET receipt_sha256 = %s
                           WHERE id = %s AND receipt_sha256 IS NULL""",
                        updates,
                    )
            updated_count += len(updates)
    return updated_count


async def backfill_existing_receipt_hashes() -> int:
    """Одноразово заповнює доступні legacy-хеші при запуску, окремо по ЦН."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT DISTINCT center_id FROM expenses
                   WHERE receipt_sha256 IS NULL AND receipt_path IS NOT NULL
                     AND receipt_path <> '' ORDER BY center_id"""
            )
            center_rows = await cur.fetchall() or []
    total = 0
    for row in center_rows:
        center_id = row.get('center_id') if isinstance(row, dict) else row[0]
        total += await backfill_center_receipt_hashes(center_id)
    return total


async def find_duplicate_receipt_hash(center_id: int, receipt_hash: str):
    """Швидко знаходить тотожні байти чека до запуску AI-розпізнавання."""
    receipt_hash = _normalize_receipt_hash(receipt_hash)
    if not center_id or not receipt_hash:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """SELECT id, date, amount, expense_name, category_id
                   FROM expenses
                   WHERE center_id = %s AND receipt_sha256 = %s
                   ORDER BY created_at DESC LIMIT 1""",
                (center_id, receipt_hash),
            )
            row = await cur.fetchone()
    return _duplicate_expense_result(row)


def _duplicate_expense_result(row):
    if not row:
        return None
    return {
        'expense_id': row['id'],
        'date': str(row['date']),
        'amount': float(row['amount']),
        'expense_name': row['expense_name'],
        'category_id': row['category_id'],
    }


def _normalize_receipt_hash(receipt_hash):
    value = str(receipt_hash or '').strip().lower()
    return value if _SHA256_RE.fullmatch(value) else None


async def find_duplicate_expense(center_id: int, date, amount, category_id: str,
                                 name: str, receipt_hash: str = None):
    """Спершу шукає однаковий файл у ЦН, потім legacy-збіг за сумою/полями."""
    if not center_id:
        return None
    expense_date = str(date or '').strip().split(' ')[0]
    category_id = str(category_id or '').strip()
    expense_name = str(name or '').strip()
    receipt_hash = _normalize_receipt_hash(receipt_hash)
    try:
        amount_value = round(float(amount), 2)
    except (TypeError, ValueError):
        amount_value = None
    if amount_value is not None and not math.isfinite(amount_value):
        amount_value = None
    if not receipt_hash and (
        amount_value is None or not (expense_date and category_id and expense_name)
    ):
        return None

    pool = await get_pool()
    if receipt_hash:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT id, date, amount, expense_name, category_id, receipt_path
                       FROM expenses
                       WHERE center_id = %s AND receipt_sha256 = %s
                       ORDER BY created_at DESC LIMIT 1""",
                    (center_id, receipt_hash),
                )
                row = await cur.fetchone()
        if row:
            return _duplicate_expense_result(row)

    if receipt_hash and amount_value is not None:
        # Старі записи без хешу: звіряємо лише той самий ЦН і суму, а потім кешуємо SHA.
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT id, telegram_id, date, amount, expense_name, category_id, receipt_path
                       FROM expenses
                       WHERE center_id = %s AND amount = %s AND receipt_sha256 IS NULL
                         AND receipt_path IS NOT NULL AND receipt_path <> ''
                       ORDER BY created_at DESC""",
                    (center_id, amount_value),
                )
                legacy_rows = await cur.fetchall() or []

        for legacy in legacy_rows:
            old_hash = await receipt_sha256(legacy['telegram_id'], legacy['receipt_path'])
            if not old_hash:
                continue
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """UPDATE expenses SET receipt_sha256 = %s
                           WHERE id = %s AND receipt_sha256 IS NULL""",
                        (old_hash, legacy['id']),
                    )
            if old_hash == receipt_hash:
                return _duplicate_expense_result(legacy)

    if amount_value is None or not (expense_date and category_id and expense_name):
        return None
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """SELECT id, date, amount, expense_name, category_id, receipt_path
                   FROM expenses
                   WHERE center_id = %s AND date = %s AND amount = %s
                     AND category_id = %s
                     AND LOWER(TRIM(expense_name)) = LOWER(TRIM(%s))
                   ORDER BY created_at DESC LIMIT 1""",
                (center_id, expense_date, amount_value, category_id, expense_name),
            )
            row = await cur.fetchone()
    return _duplicate_expense_result(row)


async def add_expense(row_data: list, receipt_hash: str = None) -> str:
    date, user_id, amount, expense_name, cat_input, file_path = row_data
    receipt_hash = _normalize_receipt_hash(receipt_hash) or await receipt_sha256(user_id, file_path)
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
                INSERT INTO expenses
                    (id, date, telegram_id, center_id, amount, expense_name, category_id, receipt_path, receipt_sha256)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                expense_id, date, user_id, center_id, amount, expense_name,
                cat_id, file_path, _normalize_receipt_hash(receipt_hash),
            ))
            
    await _touch_cash_safe(center_id, date, reason=f"витрату додано ({expense_id})")
    _notify_budget_safe(center_id, cat_id, date, expense_id, amount)
    return expense_id

async def update_expense(expense_id: str, user_id: int, row_data: list):
    date, uid, amount, expense_name, cat_input, file_path = row_data
    cat_id = await get_category_id_by_name(cat_input, user_id)
    receipt_hash = _normalize_receipt_hash(await receipt_sha256(user_id, file_path))
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT center_id, date FROM expenses WHERE id=%s AND telegram_id=%s",
                (expense_id, user_id)
            )
            old = await cur.fetchone()
            if not old:
                return False
            await cur.execute("""
                UPDATE expenses 
                SET date=%s, amount=%s, expense_name=%s, category_id=%s,
                    receipt_path=%s, receipt_sha256=%s
                WHERE id=%s AND telegram_id=%s
            """, (
                date, amount, expense_name, cat_id, file_path, receipt_hash,
                expense_id, user_id,
            ))
            if cur.rowcount == 0:
                return False
            center_id = old['center_id']
            old_date = str(old['date'])

    # Перераховуємо від найранішого з двох місяців (дата могла змінитись)
    first_day = min(str(old_date)[:10], str(date)[:10])
    await _touch_cash_safe(center_id, first_day, reason=f"витрату змінено ({expense_id})")
    return True

async def delete_expense(expense_id: str, user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT center_id, date FROM expenses WHERE id=%s AND telegram_id=%s",
                (expense_id, user_id)
            )
            old = await cur.fetchone()
            if not old:
                return False
            await cur.execute("DELETE FROM expenses WHERE id=%s AND telegram_id=%s", (expense_id, user_id))
            if cur.rowcount == 0:
                return False
            center_id = old['center_id']
            old_date = str(old['date'])

    await _touch_cash_safe(center_id, old_date, reason=f"витрату видалено ({expense_id})")
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

BUDGET_ALERT_DEFAULT_THRESHOLD = 90.0


async def ensure_budget_alert_schema():
    """Ідемпотентно створює налаштування й антиспам-ключі бюджетних сповіщень."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS `app_settings` (
                    `key` VARCHAR(64) PRIMARY KEY,
                    `value` VARCHAR(255) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            await cur.execute(
                "INSERT IGNORE INTO app_settings (`key`, `value`) VALUES (%s, %s)",
                ('budget_alert_threshold', str(BUDGET_ALERT_DEFAULT_THRESHOLD)),
            )
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS `budget_alerts` (
                    `center_id` INT NOT NULL,
                    `category_id` VARCHAR(50) NOT NULL,
                    `month` CHAR(7) NOT NULL,
                    `threshold` DECIMAL(5,2) NOT NULL,
                    `sent_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY `uq_budget_alert` (`center_id`, `category_id`, `month`, `threshold`),
                    CONSTRAINT `fk_budget_alert_center` FOREIGN KEY (`center_id`)
                        REFERENCES `centers` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
                    CONSTRAINT `fk_budget_alert_category` FOREIGN KEY (`category_id`)
                        REFERENCES `categories` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)


async def get_budget_alert_threshold() -> float:
    """Поточний поріг сповіщення у відсотках (за замовчуванням 90%)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT `value` FROM app_settings WHERE `key` = %s",
                              ('budget_alert_threshold',))
            row = await cur.fetchone()
    if not row:
        return BUDGET_ALERT_DEFAULT_THRESHOLD
    try:
        value = float(row[0])
        if math.isfinite(value) and 1 <= value <= 100:
            return value
    except (TypeError, ValueError, IndexError):
        pass
    logging.error("Некоректне значення budget_alert_threshold; використовуємо 90%%")
    return BUDGET_ALERT_DEFAULT_THRESHOLD


async def set_budget_alert_threshold(value) -> float:
    """Зберігає поріг від 1 до 100 відсотків."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError("Поріг має бути числом від 1 до 100")
    if not math.isfinite(value) or not 1 <= value <= 100:
        raise ValueError("Поріг має бути від 1 до 100 відсотків")
    value = round(value, 2)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO app_settings (`key`, `value`) VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)""",
                ('budget_alert_threshold', f'{value:g}'),
            )
    return value


async def claim_budget_alert(center_id: int, category_id: str, month: str,
                             threshold: float, title: str, message: str,
                             payload: dict) -> bool:
    """Одноразово записує B3-сповіщення й подію B4 атомарно."""
    if not is_valid_month(month):
        raise ValueError("Місяць має бути у форматі YYYY-MM")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        raise ValueError("Поріг має бути числом від 1 до 100")
    if not math.isfinite(threshold) or not 1 <= threshold <= 100:
        raise ValueError("Поріг має бути від 1 до 100 відсотків")
    threshold = round(threshold, 2)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.begin()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT IGNORE INTO budget_alerts
                           (center_id, category_id, month, threshold)
                       VALUES (%s, %s, %s, %s)""",
                    (center_id, category_id, month, threshold),
                )
                if cur.rowcount != 1:
                    await conn.rollback()
                    return False
                await cur.execute(
                    """INSERT INTO admin_notifications
                           (type, title, message, center_id, payload, action_status, action_at)
                       VALUES ('budget_threshold', %s, %s, %s, %s, 'resolved', NOW())""",
                    (title, message, center_id, json.dumps(payload or {}, ensure_ascii=False)),
                )
            await conn.commit()
            return True
        except Exception:
            await conn.rollback()
            raise


async def get_category_spent(center_id: int, category_id: str, month: str) -> float:
    """Сума витрат категорії ЦН за місяць YYYY-MM; без витрат — 0.0."""
    if not is_valid_month(month):
        raise ValueError("Місяць має бути у форматі YYYY-MM")
    date_from, date_to = _month_bounds(month)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """SELECT COALESCE(SUM(amount), 0) AS spent
                   FROM expenses
                   WHERE center_id = %s AND category_id = %s
                     AND date >= %s AND date < %s""",
                (center_id, category_id, date_from, date_to),
            )
            row = await cur.fetchone()
    return _r2(row['spent'])


async def get_monthly_expense_report(center_id: int, month: str) -> dict | None:
    """Read-only report data for one center and one YYYY-MM period."""
    if not center_id:
        raise ValueError("Не вказано ЦН")
    if not is_valid_month(month):
        raise ValueError("Місяць має бути у форматі YYYY-MM")

    date_from, date_to = _month_bounds(month)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT id, name, city FROM centers WHERE id = %s",
                (center_id,),
            )
            center = await cur.fetchone()
            if not center:
                return None

            await cur.execute(
                """SELECT e.date, e.expense_name, e.amount,
                          COALESCE(c.name, 'Інше') AS category_name
                   FROM expenses e
                   LEFT JOIN categories c ON c.id = e.category_id
                   WHERE e.center_id = %s AND e.date >= %s AND e.date < %s
                   ORDER BY e.date ASC, e.created_at ASC, e.id ASC""",
                (center_id, date_from, date_to),
            )
            rows = await cur.fetchall() or []

    expenses = [{
        'date': str(row['date']),
        'expense_name': str(row.get('expense_name') or ''),
        'category_name': str(row.get('category_name') or 'Інше'),
        'amount': _r2(row.get('amount')),
    } for row in rows]
    return {
        'center_id': int(center['id']),
        'center_name': str(center['name']),
        'city': str(center.get('city') or ''),
        'month': month,
        'expenses': expenses,
    }


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


# ==========================================
# 7. КОШТИ (КАСА ЦН)
# ==========================================
# `budgets` — планові ліміти по категоріях, вони не впливають на реальний залишок.
# Реальні гроші ведуться тут:
#   cash_operations       — надходження (funding), повернення (return), коригування (adjustment)
#   expenses              — витрати (єдине джерело; журнал каси їх НЕ дублює)
#   center_month_balances — зафіксовані залишки на місяць (еталон для звірки)
#
# opening(m) = opening_balance, якщо m = start_month, інакше closing(m-1)
# closing(m) = opening(m) + received(m) - spent(m),  received = funding - return ± adjustment
# Місяці до start_month не показуються взагалі.

CASH_KINDS = ('funding', 'return', 'adjustment')

_MONTH_RE = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')

_CASH_DDL = (
    """CREATE TABLE IF NOT EXISTS `center_cash_settings` (
        `center_id` INT PRIMARY KEY COMMENT 'ЦН',
        `start_month` CHAR(7) NOT NULL COMMENT 'Місяць початку обліку YYYY-MM',
        `opening_balance` DECIMAL(12, 2) NOT NULL DEFAULT 0.00 COMMENT 'Реальний залишок на 1-ше start_month',
        `note` VARCHAR(255) NULL,
        `updated_by` BIGINT NULL,
        `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT `fk_ccs_center` FOREIGN KEY (`center_id`) REFERENCES `centers` (`id`)
            ON DELETE CASCADE ON UPDATE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `cash_operations` (
        `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
        `center_id` INT NOT NULL,
        `op_date` DATE NOT NULL COMMENT 'Дата операції; визначає місяць обліку',
        `kind` ENUM('funding','return','adjustment') NOT NULL,
        `amount` DECIMAL(12, 2) NOT NULL COMMENT 'Сума за модулем (> 0)',
        `signed_amount` DECIMAL(12, 2) NOT NULL COMMENT 'Знакова сума: + funding, - return, ± adjustment',
        `method` ENUM('cash','bank') NOT NULL DEFAULT 'cash',
        `counterparty` VARCHAR(191) NULL,
        `comment` VARCHAR(255) NULL,
        `batch_id` VARCHAR(64) NULL COMMENT 'Групує масову видачу по кількох ЦН',
        `created_by` BIGINT NOT NULL COMMENT 'telegram_id адміна',
        `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX `idx_cash_center_date` (`center_id`, `op_date`),
        INDEX `idx_cash_batch` (`batch_id`),
        CONSTRAINT `fk_cash_center` FOREIGN KEY (`center_id`) REFERENCES `centers` (`id`)
            ON DELETE CASCADE ON UPDATE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `center_month_balances` (
        `center_id` INT NOT NULL,
        `month` CHAR(7) NOT NULL COMMENT 'YYYY-MM',
        `opening_balance` DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
        `received` DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
        `spent` DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
        `closing_balance` DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
        `status` ENUM('open','closed') NOT NULL DEFAULT 'open',
        `computed_at` DATETIME NULL,
        `closed_at` DATETIME NULL,
        `closed_by` BIGINT NULL,
        PRIMARY KEY (`center_id`, `month`),
        CONSTRAINT `fk_cmb_center` FOREIGN KEY (`center_id`) REFERENCES `centers` (`id`)
            ON DELETE CASCADE ON UPDATE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `cash_audit` (
        `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
        `center_id` INT NULL,
        `month` CHAR(7) NULL,
        `action` VARCHAR(64) NOT NULL,
        `details` TEXT NULL,
        `actor_id` BIGINT NULL,
        `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX `idx_audit_month` (`month`, `center_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
)


def is_valid_month(month) -> bool:
    """Перевіряє формат місяця YYYY-MM."""
    return bool(month) and bool(_MONTH_RE.match(str(month)))


def _month_to_int(month: str) -> int:
    y, m = str(month).split('-')
    return int(y) * 12 + int(m) - 1


def _int_to_month(value: int) -> str:
    return f"{value // 12:04d}-{value % 12 + 1:02d}"


def current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def prev_month(month: str) -> str:
    return _int_to_month(_month_to_int(month) - 1)


def months_range(start_month: str, end_month: str) -> list:
    """Перелік місяців YYYY-MM від start_month до end_month включно."""
    if not (is_valid_month(start_month) and is_valid_month(end_month)):
        return []
    a, b = _month_to_int(start_month), _month_to_int(end_month)
    return [_int_to_month(v) for v in range(a, b + 1)] if b >= a else []


def _month_bounds(month: str):
    """(перший день місяця, перший день наступного) — межі для діапазонних запитів."""
    return f"{month}-01", f"{_int_to_month(_month_to_int(month) + 1)}-01"


def _r2(value) -> float:
    return round(float(value or 0), 2)


async def ensure_cash_schema():
    """Ідемпотентно створює таблиці обліку коштів (для вже розгорнутих БД)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for stmt in _CASH_DDL:
                await cur.execute(stmt)
            # Індекс для агрегації витрат по ЦН за період (може вже існувати)
            try:
                await cur.execute(
                    "ALTER TABLE `expenses` ADD INDEX `idx_expenses_center_date` (`center_id`, `date`)"
                )
            except Exception:
                pass


async def _cash_audit(cur, action: str, center_id=None, month=None, details=None, actor_id=None):
    """Запис у аудит обліку коштів (не ламає основну операцію при помилці)."""
    try:
        await cur.execute(
            """INSERT INTO cash_audit (center_id, month, action, details, actor_id)
               VALUES (%s, %s, %s, %s, %s)""",
            (center_id, month, action, details, actor_id)
        )
    except Exception as e:
        logging.error(f"cash_audit({action}): {e}")


# ---------- Налаштування обліку ----------

async def get_cash_settings(center_id: int):
    """Налаштування обліку коштів для ЦН або None, якщо облік не ведеться."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """SELECT center_id, start_month, opening_balance, note, updated_at
                   FROM center_cash_settings WHERE center_id = %s""",
                (center_id,)
            )
            row = await cur.fetchone()
    return _cash_settings_row(row)


def _cash_settings_row(row):
    if not row:
        return None
    return {
        'center_id': int(row['center_id']),
        'start_month': str(row['start_month']),
        'opening_balance': _r2(row['opening_balance']),
        'note': row.get('note'),
        'updated_at': str(row['updated_at']) if row.get('updated_at') else None,
    }


async def get_all_cash_settings() -> dict:
    """{center_id: {'start_month', 'opening_balance'}} для всіх ЦН з обліком."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            return await _cash_settings_map(cur)


async def _cash_settings_map(cur) -> dict:
    await cur.execute(
        "SELECT center_id, start_month, opening_balance FROM center_cash_settings"
    )
    rows = await cur.fetchall() or []
    return {
        int(r['center_id']): {
            'start_month': str(r['start_month']),
            'opening_balance': _r2(r['opening_balance']),
        }
        for r in rows
    }


async def set_cash_settings(center_id: int, start_month: str, opening_balance: float = 0,
                            note: str = None, actor_id: int = None):
    """Задає/оновлює початок обліку та реальний залишок на 1-ше число цього місяця."""
    if not is_valid_month(start_month):
        raise ValueError("Місяць початку обліку має бути у форматі YYYY-MM")
    opening_balance = _r2(opening_balance)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO center_cash_settings
                       (center_id, start_month, opening_balance, note, updated_by)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                       start_month = VALUES(start_month),
                       opening_balance = VALUES(opening_balance),
                       note = VALUES(note),
                       updated_by = VALUES(updated_by)""",
                (center_id, start_month, opening_balance, note, actor_id)
            )
            # Знімки до нового початку обліку стають неактуальними
            await cur.execute(
                "DELETE FROM center_month_balances WHERE center_id = %s AND month < %s",
                (center_id, start_month)
            )
            await _cash_audit(
                cur, 'settings', center_id, start_month,
                f"start_month={start_month}, opening_balance={opening_balance}", actor_id
            )
    await recalc_chain(center_id, start_month, actor_id=actor_id)
    return await get_cash_settings(center_id)


# ---------- Агрегати ----------

async def _cash_ops_agg(cur, center_id: int, date_from: str, date_to: str) -> dict:
    """Надходження/повернення/коригування за період [date_from, date_to)."""
    await cur.execute(
        """SELECT
               COALESCE(SUM(CASE WHEN kind = 'funding'    THEN amount ELSE 0 END), 0) AS funding,
               COALESCE(SUM(CASE WHEN kind = 'return'     THEN amount ELSE 0 END), 0) AS returned,
               COALESCE(SUM(CASE WHEN kind = 'adjustment' THEN signed_amount ELSE 0 END), 0) AS adjustment,
               COALESCE(SUM(signed_amount), 0) AS net
           FROM cash_operations
           WHERE center_id = %s AND op_date >= %s AND op_date < %s""",
        (center_id, date_from, date_to)
    )
    row = await cur.fetchone() or {}
    return {
        'funding': _r2(row.get('funding')),
        'returned': _r2(row.get('returned')),
        'adjustment': _r2(row.get('adjustment')),
        'net': _r2(row.get('net')),
    }


async def _cash_spent_agg(cur, center_id: int, date_from: str, date_to: str) -> float:
    """Витрати за період [date_from, date_to) — з таблиці expenses."""
    await cur.execute(
        """SELECT COALESCE(SUM(amount), 0) AS spent
           FROM expenses
           WHERE center_id = %s AND date >= %s AND date < %s""",
        (center_id, date_from, date_to)
    )
    row = await cur.fetchone() or {}
    return _r2(row.get('spent'))


async def _cash_compute(cur, center_id: int, month: str):
    """Розраховує суми за місяць з первинних даних (без знімків)."""
    if not is_valid_month(month):
        return None
    await cur.execute(
        "SELECT start_month, opening_balance FROM center_cash_settings WHERE center_id = %s",
        (center_id,)
    )
    st = await cur.fetchone()
    if not st:
        return None
    start_month = str(st['start_month'])
    if _month_to_int(month) < _month_to_int(start_month):
        return None

    start_from, _ = _month_bounds(start_month)
    month_from, month_to = _month_bounds(month)

    before_ops = await _cash_ops_agg(cur, center_id, start_from, month_from)
    before_spent = await _cash_spent_agg(cur, center_id, start_from, month_from)
    opening = _r2(_r2(st['opening_balance']) + before_ops['net'] - before_spent)

    ops = await _cash_ops_agg(cur, center_id, month_from, month_to)
    spent = await _cash_spent_agg(cur, center_id, month_from, month_to)

    return {
        'configured': True,
        'center_id': center_id,
        'month': month,
        'start_month': start_month,
        'opening_balance': opening,
        'funding': ops['funding'],
        'returned': ops['returned'],
        'adjustment': ops['adjustment'],
        'received': ops['net'],
        'spent': spent,
        'closing_balance': _r2(opening + ops['net'] - spent),
    }


# ---------- Підсумок за місяць ----------

async def _cash_snapshot_cur(cur, center_id: int, month: str):
    """Зафіксований знімок місяця (або None), у межах відкритого курсора."""
    await cur.execute(
        """SELECT opening_balance, received, spent, closing_balance, status,
                  computed_at, closed_at
           FROM center_month_balances
           WHERE center_id = %s AND month = %s""",
        (center_id, month)
    )
    snap = await cur.fetchone()
    if not snap:
        return None
    return {
        'opening_balance': _r2(snap['opening_balance']),
        'received': _r2(snap['received']),
        'spent': _r2(snap['spent']),
        'closing_balance': _r2(snap['closing_balance']),
        'status': str(snap['status']),
        'computed_at': str(snap['computed_at']) if snap.get('computed_at') else None,
        'closed_at': str(snap['closed_at']) if snap.get('closed_at') else None,
    }


async def _cash_snapshot(center_id: int, month: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            return await _cash_snapshot_cur(cur, center_id, month)


async def get_cash_summary(center_id: int, month: str = None):
    """Залишки ЦН за місяць: розрахунок + порівняння із зафіксованим знімком."""
    month = month or current_month()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            data = await _cash_compute(cur, center_id, month)
            if not data:
                return {'configured': False, 'center_id': center_id, 'month': month}
            snapshot = await _cash_snapshot_cur(cur, center_id, month)

    if snapshot:
        data['status'] = snapshot['status']
        data['matches'] = (
            abs(snapshot['closing_balance'] - data['closing_balance']) < 0.01
            and abs(snapshot['spent'] - data['spent']) < 0.01
        )
    else:
        data['status'] = 'open'
        data['matches'] = None
    data['snapshot'] = snapshot
    return data


# ---------- Журнал (рух коштів за місяць) ----------

async def get_cash_ledger(center_id: int, month: str = None, limit: int = 300):
    """Рух коштів за місяць із наростаючим залишком (надходження + витрати)."""
    month = month or current_month()
    month_from, month_to = _month_bounds(month)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            summary = await _cash_compute(cur, center_id, month)
            if not summary:
                return {'configured': False, 'center_id': center_id, 'month': month,
                    'rows': [], 'summary': None}
            snapshot = await _cash_snapshot_cur(cur, center_id, month)
            await cur.execute(
                """SELECT * FROM (
                       SELECT o.op_date       AS d,
                              o.created_at    AS ts,
                              o.kind          AS kind,
                              CASE o.kind
                                  WHEN 'funding' THEN 'Надходження коштів'
                                  WHEN 'return'  THEN 'Повернення коштів'
                                  ELSE 'Коригування'
                              END             AS title,
                              NULL            AS category_name,
                              o.comment       AS comment,
                              o.signed_amount AS amount,
                              NULL            AS ref_id
                       FROM cash_operations o
                       WHERE o.center_id = %s AND o.op_date >= %s AND o.op_date < %s
                       UNION ALL
                       SELECT e.date, e.created_at, 'expense', e.expense_name,
                              c.name, NULL, -e.amount, e.id
                       FROM expenses e
                       LEFT JOIN categories c ON c.id = e.category_id
                       WHERE e.center_id = %s AND e.date >= %s AND e.date < %s
                   ) t
                   ORDER BY t.d ASC, t.ts ASC
                   LIMIT %s""",
                (center_id, month_from, month_to,
                 center_id, month_from, month_to, int(limit))
            )
            raw = await cur.fetchall() or []

    balance = summary['opening_balance']
    rows = []
    for r in raw:
        amount = _r2(r['amount'])
        balance = _r2(balance + amount)
        rows.append({
            'date': str(r['d']),
            'kind': str(r['kind']),
            'title': r['title'],
            'category_name': r['category_name'],
            'comment': r['comment'],
            'amount': amount,
            'balance': balance,
            'ref_id': r['ref_id'],
        })
    return {
        'configured': True,
        'center_id': center_id,
        'month': month,
        'summary': summary,
        'rows': rows,
        'truncated': len(rows) >= int(limit),
        # Стан місяця: як у get_cash_summary (журнал не дублює цю логіку на клієнті)
        'status': (snapshot or {}).get('status', 'open'),
        'matches': None if not snapshot else (
            abs(snapshot['closing_balance'] - summary['closing_balance']) < 0.01
            and abs(snapshot['spent'] - summary['spent']) < 0.01
        ),
        'snapshot': snapshot,
    }


# ---------- Огляд по роках / місяцях (адмінка) ----------

async def get_cash_overview(year: int = None):
    """Зведення «надійшло / витрачено / залишок» по всіх ЦН за рік, по місяцях.

    Один набір агрегатних запитів на рік — без циклів по центрах.
    """
    year = int(year or datetime.now().year)
    y_from, y_to = f"{year}-01-01", f"{year + 1}-01-01"
    start_filter = "STR_TO_DATE(CONCAT(s.start_month, '-01'), '%%Y-%%m-%%d')"

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT id, name, city, is_active FROM centers ORDER BY name ASC")
            centers = [
                {'id': int(r['id']), 'name': r['name'], 'city': r['city'],
                 'is_active': bool(r['is_active'])}
                for r in (await cur.fetchall() or [])
            ]
            settings = await _cash_settings_map(cur)

            # Стан на початок року (тільки в межах періоду обліку кожного ЦН)
            await cur.execute(
                f"""SELECT o.center_id AS cid, COALESCE(SUM(o.signed_amount), 0) AS net
                    FROM cash_operations o
                    JOIN center_cash_settings s ON s.center_id = o.center_id
                    WHERE o.op_date < %s AND o.op_date >= {start_filter}
                    GROUP BY o.center_id""",
                (y_from,)
            )
            net_before = {int(r['cid']): _r2(r['net']) for r in await cur.fetchall() or []}

            await cur.execute(
                f"""SELECT e.center_id AS cid, COALESCE(SUM(e.amount), 0) AS spent
                    FROM expenses e
                    JOIN center_cash_settings s ON s.center_id = e.center_id
                    WHERE e.date < %s AND e.date >= {start_filter}
                    GROUP BY e.center_id""",
                (y_from,)
            )
            spent_before = {int(r['cid']): _r2(r['spent']) for r in await cur.fetchall() or []}

            await cur.execute(
                """SELECT center_id AS cid, DATE_FORMAT(op_date, '%%Y-%%m') AS m,
                          COALESCE(SUM(CASE WHEN kind = 'funding' THEN amount ELSE 0 END), 0) AS funding,
                          COALESCE(SUM(CASE WHEN kind = 'return'  THEN amount ELSE 0 END), 0) AS returned,
                          COALESCE(SUM(CASE WHEN kind = 'adjustment' THEN signed_amount ELSE 0 END), 0) AS adjustment,
                          COALESCE(SUM(signed_amount), 0) AS net
                   FROM cash_operations
                   WHERE op_date >= %s AND op_date < %s
                   GROUP BY center_id, m""",
                (y_from, y_to)
            )
            ops_map = {
                (int(r['cid']), str(r['m'])): {
                    'funding': _r2(r['funding']),
                    'returned': _r2(r['returned']),
                    'adjustment': _r2(r['adjustment']),
                    'net': _r2(r['net']),
                }
                for r in await cur.fetchall() or []
            }

            await cur.execute(
                """SELECT center_id AS cid, DATE_FORMAT(date, '%%Y-%%m') AS m,
                          COALESCE(SUM(amount), 0) AS spent
                   FROM expenses
                   WHERE date >= %s AND date < %s
                   GROUP BY center_id, m""",
                (y_from, y_to)
            )
            spent_map = {
                (int(r['cid']), str(r['m'])): _r2(r['spent'])
                for r in await cur.fetchall() or []
            }

            await cur.execute(
                """SELECT center_id AS cid, month AS m, status, closing_balance, received, spent
                   FROM center_month_balances
                   WHERE month >= %s AND month < %s""",
                (f"{year}-01", f"{year + 1}-01")
            )
            snap_map = {
                (int(r['cid']), str(r['m'])): r
                for r in await cur.fetchall() or []
            }

    running = {
        cid: _r2(s['opening_balance'] + net_before.get(cid, 0.0) - spent_before.get(cid, 0.0))
        for cid, s in settings.items()
    }

    totals_by_center = {
        c['id']: {'funding': 0.0, 'returned': 0.0, 'adjustment': 0.0,
                  'received': 0.0, 'spent': 0.0, 'closing_balance': 0.0}
        for c in centers
    }
    months_out = []

    for mi in range(1, 13):
        m = f"{year}-{mi:02d}"
        rows = []
        t = {'funding': 0.0, 'returned': 0.0, 'adjustment': 0.0,
             'received': 0.0, 'spent': 0.0, 'closing_balance': 0.0}

        for c in centers:
            cid = c['id']
            s = settings.get(cid)
            ops = ops_map.get((cid, m))
            spent = spent_map.get((cid, m), 0.0)

            if not s:
                # Облік не налаштовано, але рухи/витрати вже є — показуємо як проблему
                if ops or spent:
                    rows.append({
                        'center_id': cid, 'name': c['name'], 'configured': False,
                        'start_month': None,
                        'opening_balance': 0.0, 'funding': _r2(ops['funding']) if ops else 0.0,
                        'returned': _r2(ops['returned']) if ops else 0.0,
                        'adjustment': _r2(ops['adjustment']) if ops else 0.0,
                        'received': _r2(ops['net']) if ops else 0.0,
                        'spent': spent, 'closing_balance': None,
                        'status': 'unconfigured', 'matches': None,
                    })
                continue

            if _month_to_int(m) < _month_to_int(s['start_month']):
                continue

            opening = running.get(cid, 0.0)
            received = _r2(ops['net']) if ops else 0.0
            closing = _r2(opening + received - spent)
            running[cid] = closing

            snap = snap_map.get((cid, m))
            if snap:
                status = str(snap['status'])
                matches = (
                    abs(_r2(snap['closing_balance']) - closing) < 0.01
                    and abs(_r2(snap['spent']) - spent) < 0.01
                )
            else:
                status = 'open'
                matches = None

            row = {
                'center_id': cid, 'name': c['name'], 'configured': True,
                'start_month': s['start_month'],
                'opening_balance': opening,
                'funding': _r2(ops['funding']) if ops else 0.0,
                'returned': _r2(ops['returned']) if ops else 0.0,
                'adjustment': _r2(ops['adjustment']) if ops else 0.0,
                'received': received,
                'spent': spent,
                'closing_balance': closing,
                'status': status,
                'matches': matches,
            }
            rows.append(row)

            tc = totals_by_center[cid]
            tc['funding'] = _r2(tc['funding'] + row['funding'])
            tc['returned'] = _r2(tc['returned'] + row['returned'])
            tc['adjustment'] = _r2(tc['adjustment'] + row['adjustment'])
            tc['received'] = _r2(tc['received'] + received)
            tc['spent'] = _r2(tc['spent'] + spent)
            tc['closing_balance'] = closing

            t['funding'] = _r2(t['funding'] + row['funding'])
            t['returned'] = _r2(t['returned'] + row['returned'])
            t['adjustment'] = _r2(t['adjustment'] + row['adjustment'])
            t['received'] = _r2(t['received'] + received)
            t['spent'] = _r2(t['spent'] + spent)
            t['closing_balance'] = _r2(t['closing_balance'] + closing)

        months_out.append({'month': m, 'rows': rows, 'totals': t})

    centers_out = []
    for c in centers:
        tc = totals_by_center[c['id']]
        centers_out.append({
            'id': c['id'],
            'name': c['name'],
            'city': c['city'],
            'is_active': c['is_active'],
            'configured': c['id'] in settings,
            'start_month': settings.get(c['id'], {}).get('start_month'),
            'opening_balance': settings.get(c['id'], {}).get('opening_balance'),
            'funding': tc['funding'],
            'returned': tc['returned'],
            'adjustment': tc['adjustment'],
            'received': tc['received'],
            'spent': tc['spent'],
            'closing_balance': tc['closing_balance'],
        })

    year_totals = {k: 0.0 for k in ('funding', 'returned', 'adjustment', 'received', 'spent')}
    for mo in months_out:
        for k in year_totals:
            year_totals[k] = _r2(year_totals[k] + mo['totals'][k])

    return {
        'year': year,
        'months': months_out,
        'centers': centers_out,
        'totals': year_totals,
        'unconfigured': [c['name'] for c in centers_out if not c['configured']],
    }


# ---------- Таблиця стану коштів за місяць (адмінка) ----------

async def get_cash_admin_table(month: str = None):
    """Стан коштів по всіх ЦН за один місяць — рядок таблиці адмінки «Кошти».

    Використовує агрегатний `get_cash_overview()` (один набір запитів на рік).
    """
    month = month or current_month()
    if not is_valid_month(month):
        raise ValueError("Місяць має бути у форматі YYYY-MM")
    year = int(month[:4])

    overview = await get_cash_overview(year)
    month_data = next((m for m in overview['months'] if m['month'] == month), None)
    by_center = {r['center_id']: r for r in (month_data or {}).get('rows', [])}

    rows = []
    for c in overview['centers']:
        row = {
            'center_id': c['id'],
            'name': c['name'],
            'city': c['city'],
            'is_active': c['is_active'],
            'configured': c['configured'],
            'start_month': c['start_month'],
            'opening_balance': c['opening_balance'],  # стартовий залишок обліку (налаштування)
            'month_opening': None,
            'funding': None,
            'returned': None,
            'adjustment': None,
            'received': None,
            'spent': None,
            'closing_balance': None,
            'status': 'unconfigured' if not c['configured'] else 'not_started',
            'matches': None,
        }
        state = by_center.get(c['id'])
        if state:
            row['month_opening'] = state['opening_balance']
            for key in ('funding', 'returned', 'adjustment', 'received',
                        'spent', 'closing_balance', 'status', 'matches'):
                row[key] = state[key]
        rows.append(row)

    started = [
        r for r in rows
        if r['configured'] and r['start_month']
        and _month_to_int(r['start_month']) <= _month_to_int(month)
    ]
    negative = [
        {'center_id': r['center_id'], 'name': r['name'],
         'closing_balance': r['closing_balance']}
        for r in started if (r['closing_balance'] or 0) < 0
    ]
    return {
        'month': month,
        'year': year,
        'rows': rows,
        'totals': {k: _r2(v) for k, v in ((month_data or {}).get('totals') or {}).items()},
        'active_count': len(started),
        'negative': negative,
        'unconfigured': [r['name'] for r in rows if not r['configured']],
    }


# ---------- Перерахунок знімків ----------

async def recalc_month(center_id: int, month: str, write: bool = True,
                       reopen: bool = False, actor_id: int = None):
    """Перераховує знімок місяця (за потреби — зберігає його).

    write=False  — тільки розрахунок, знімок не змінюється (для звірки);
    reopen=False — закритий місяць НЕ перезаписується: розбіжність із знімком
                   покажеться у звірці, рішення ухвалює адмін;
    reopen=True  — закритий місяць відкривається (+ запис у cash_audit) і
                   перераховується (операції адміністратора).
    """
    if not is_valid_month(month):
        return None

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT status FROM center_month_balances WHERE center_id = %s AND month = %s",
                (center_id, month)
            )
            existing = await cur.fetchone()
            if existing and str(existing['status']) == 'closed':
                if not (reopen and write):
                    return await _cash_compute(cur, center_id, month)
                await cur.execute(
                    """UPDATE center_month_balances
                       SET status = 'open', closed_at = NULL, closed_by = NULL
                       WHERE center_id = %s AND month = %s""",
                    (center_id, month)
                )
                await _cash_audit(
                    cur, 'reopen_month', center_id, month,
                    'відкрито для перерахунку після зміни даних', actor_id
                )
            data = await _cash_compute(cur, center_id, month)
            if not data or not write:
                return data

        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO center_month_balances
                       (center_id, month, opening_balance, received, spent, closing_balance,
                        status, computed_at)
                   VALUES (%s, %s, %s, %s, %s, %s, 'open', NOW())
                   ON DUPLICATE KEY UPDATE
                       opening_balance = VALUES(opening_balance),
                       received = VALUES(received),
                       spent = VALUES(spent),
                       closing_balance = VALUES(closing_balance),
                       computed_at = NOW()""",
                (center_id, month, data['opening_balance'], data['received'],
                 data['spent'], data['closing_balance'])
            )
    return data


async def recalc_chain(center_id: int, from_month: str, actor_id: int = None,
                       reopen: bool = True):
    """Перераховує знімки від from_month до поточного місяця включно.

    Залишок кожного місяця залежить від попереднього, тому зміна в минулому
    зобов'язує перерахувати весь ланцюжок далі. Якщо reopen=True, закриті місяці
    відкриваються з записом у cash_audit (операції адміністратора);
    reopen=False — закриті місяці лишаються зафіксованими (витрати ЦН:
    розбіжність зі знімком покажеться у звірці, адмін вирішує сам).
    Якщо from_month у майбутньому — рахуємо до нього.
    """
    settings_row = await get_cash_settings(center_id)
    if not settings_row:
        return []
    start = max(_month_to_int(from_month), _month_to_int(settings_row['start_month']))

    # Кінець ланцюжка: поточний місяць або останній місяць, де вже є дані/знімок
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT GREATEST(
                       COALESCE((SELECT MAX(month) FROM center_month_balances
                                 WHERE center_id = %s), ''),
                       COALESCE((SELECT DATE_FORMAT(MAX(op_date), '%%Y-%%m')
                                 FROM cash_operations WHERE center_id = %s), ''),
                       COALESCE((SELECT DATE_FORMAT(MAX(date), '%%Y-%%m')
                                 FROM expenses WHERE center_id = %s), '')
                   ) AS last_month""",
                (center_id, center_id, center_id)
            )
            row = await cur.fetchone()
    last_month = str(row[0]) if row and row[0] else ''
    end = _month_to_int(current_month())
    if is_valid_month(last_month):
        end = max(end, _month_to_int(last_month))
    end = max(end, start)

    touched = []
    for value in range(start, end + 1):
        data = await recalc_month(center_id, _int_to_month(value),
                                  write=True, reopen=reopen, actor_id=actor_id)
        if data:
            touched.append(_int_to_month(value))
    return touched


async def touch_cash_month(center_id: int, day, actor_id: int = None, reason: str = None,
                           reopen: bool = True):
    """Хук для витрат/операцій у минулому місяці: перерахувати ланцюжок залишків."""
    month = str(day)[:7]
    if not center_id or not is_valid_month(month):
        return []
    touched = await recalc_chain(center_id, month, actor_id=actor_id, reopen=reopen)
    if touched:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await _cash_audit(
                    cur, 'recalc', center_id, month,
                    reason or f"перераховано {touched[0]}..{touched[-1]}", actor_id
                )
    return touched


async def _touch_cash_safe(center_id, day, reason: str = None):
    """Тихо перераховує залишки після зміни витрат; не ламає основну операцію."""
    if not center_id:
        return
    try:
        await touch_cash_month(center_id, day, reason=reason, reopen=False)
    except Exception as e:
        logging.error(f"Перерахунок коштів ЦН {center_id} за {day}: {e}")


# ---------- Закриття місяця та звірка ----------

async def close_month(month: str, actor_id: int = None):
    """Фіксує залишки всіх ЦН на кінець місяця: знімки стають status='closed'."""
    if not is_valid_month(month):
        raise ValueError("Місяць має бути у форматі YYYY-MM")

    settings = await get_all_cash_settings()
    closed, skipped = [], []
    for center_id, st in settings.items():
        if _month_to_int(month) < _month_to_int(st['start_month']):
            skipped.append(center_id)
            continue
        data = await recalc_month(center_id, month, write=True)
        if not data:
            skipped.append(center_id)
            continue
        closed.append(data)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """UPDATE center_month_balances
                   SET status = 'closed', closed_at = NOW(), closed_by = %s
                   WHERE month = %s AND status = 'open'""",
                (actor_id, month)
            )
            locked = cur.rowcount
            await _cash_audit(
                cur, 'close_month', None, month,
                f"закрито ЦН: {len(closed)}, пропущено: {len(skipped)}", actor_id
            )
    return {'month': month, 'closed': closed, 'skipped': skipped, 'locked_rows': locked}


async def reopen_month(month: str, actor_id: int = None, reason: str = None):
    """Знімає фіксацію місяця (після цього знімки перераховуються звичайним шляхом)."""
    if not is_valid_month(month):
        raise ValueError("Місяць має бути у форматі YYYY-MM")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """UPDATE center_month_balances
                   SET status = 'open', closed_at = NULL, closed_by = NULL
                   WHERE month = %s AND status = 'closed'""",
                (month,)
            )
            affected = cur.rowcount
            await _cash_audit(
                cur, 'reopen_month', None, month,
                reason or f"відкрито знімків: {affected}", actor_id
            )
    return {'month': month, 'reopened': affected}


async def reconcile_month(month: str = None):
    """Подвійна перевірка: неперервність ланцюжка залишків і збіг зі знімками.

    Нічого не змінює: рахує з первинних даних і порівнює із center_month_balances,
    тому саме тут видно розбіжності, залишені закритими місяцями.
    """
    month = month or current_month()
    if not is_valid_month(month):
        raise ValueError("Місяць має бути у форматі YYYY-MM")

    settings = await get_all_cash_settings()
    issues = []
    for center_id, st in settings.items():
        if _month_to_int(month) < _month_to_int(st['start_month']):
            continue
        prev_closing = None
        for m in months_range(st['start_month'], month):
            data = await recalc_month(center_id, m, write=False)
            if not data:
                prev_closing = None
                continue
            if prev_closing is not None and abs(data['opening_balance'] - prev_closing) > 0.01:
                issues.append({
                    'center_id': center_id,
                    'month': m,
                    'type': 'chain',
                    'detail': (f"залишок на початок {data['opening_balance']} "
                               f"!= залишок попереднього місяця {prev_closing}"),
                })
            snap = await _cash_snapshot(center_id, m)
            if snap and (
                abs(snap['closing_balance'] - data['closing_balance']) > 0.01
                or abs(snap['spent'] - data['spent']) > 0.01
            ):
                issues.append({
                    'center_id': center_id,
                    'month': m,
                    'type': 'snapshot',
                    'detail': (f"розрахунок {data['closing_balance']} "
                               f"!= знімок {snap['closing_balance']}"),
                })
            prev_closing = data['closing_balance']
    return {'month': month, 'issues': issues, 'ok': not issues}


# ---------- Операції з коштами ----------

async def add_cash_operation(center_id: int, op_date, kind: str, amount: float,
                             method: str = 'cash', counterparty: str = None,
                             comment: str = None, actor_id: int = None,
                             batch_id: str = None):
    """Додає рух коштів: funding (+), return (−), adjustment (±, знак зберігається)."""
    if kind not in CASH_KINDS:
        raise ValueError("Невідомий тип операції")

    day = str(op_date)[:10]
    datetime.strptime(day, "%Y-%m-%d")
    month = day[:7]

    settings_row = await get_cash_settings(center_id)
    if not settings_row:
        raise ValueError("Для цього ЦН не налаштовано облік коштів")
    if month < settings_row['start_month']:
        raise ValueError(f"Місяць операції раніше початку обліку ({settings_row['start_month']})")

    raw = float(amount)
    value = _r2(abs(raw))
    if value <= 0:
        raise ValueError("Сума має бути більше нуля")
    signed = _r2(raw) if kind == 'adjustment' else (value if kind == 'funding' else -value)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO cash_operations
                       (center_id, op_date, kind, amount, signed_amount, method,
                        counterparty, comment, batch_id, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (center_id, day, kind, value, signed, method or 'cash',
                 counterparty, comment, batch_id, actor_id)
            )
            op_id = cur.lastrowid
            await _cash_audit(
                cur, kind, center_id, month,
                f"op#{op_id} {signed} {comment or ''}".strip(), actor_id
            )

    touched = await recalc_chain(center_id, month, actor_id=actor_id)
    return {
        'id': op_id,
        'center_id': center_id,
        'op_date': day,
        'month': month,
        'kind': kind,
        'amount': value,
        'signed_amount': signed,
        'method': method or 'cash',
        'recalculated': touched,
    }


async def add_funding_batch(amounts_by_center: dict, op_date, method: str = 'cash',
                            counterparty: str = None, comment: str = None,
                            actor_id: int = None):
    """Масова видача коштів: {center_id: amount}, спільний batch_id для всіх рядків."""
    batch_id = uuid.uuid4().hex[:16]
    created, errors = [], []
    for center_id, amount in (amounts_by_center or {}).items():
        try:
            if _r2(amount) <= 0:
                continue
            created.append(await add_cash_operation(
                int(center_id), op_date, 'funding', amount, method=method,
                counterparty=counterparty, comment=comment,
                actor_id=actor_id, batch_id=batch_id,
            ))
        except Exception as e:
            errors.append({'center_id': center_id, 'error': str(e)})
    return {
        'batch_id': batch_id,
        'created': created,
        'errors': errors,
        'total': _r2(sum(c['amount'] for c in created)),
    }


# ---------- Адмінські сповіщення ----------

async def ensure_notifications_schema():
    """Ідемпотентна схема журналу сповіщень та адміністрування."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS `admin_notifications` (
                    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
                    `type` VARCHAR(64) NOT NULL,
                    `title` VARCHAR(191) NOT NULL,
                    `message` TEXT NOT NULL,
                    `center_id` INT NULL,
                    `user_id` BIGINT NULL,
                    `receipt_path` TEXT NULL,
                    `payload` TEXT NULL,
                    `status` ENUM('open','resolved') NOT NULL DEFAULT 'open',
                    `action_status` ENUM('pending','approved','rejected','resolved') NOT NULL DEFAULT 'pending',
                    `action_at` DATETIME NULL,
                    `action_by` BIGINT NULL,
                    `read_at` DATETIME NULL,
                    `read_by` BIGINT NULL,
                    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    `resolved_at` DATETIME NULL,
                    `resolved_by` BIGINT NULL,
                    INDEX `idx_admin_notifications_status_date` (`status`, `created_at`),
                    INDEX `idx_admin_notifications_type_date` (`type`, `created_at`),
                    INDEX `idx_admin_notifications_center` (`center_id`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            # Міграція ідемпотентна для інсталяцій, де журнал уже створений.
            for ddl in (
                "ALTER TABLE `admin_notifications` ADD COLUMN `action_status` ENUM('pending','approved','rejected','resolved') NOT NULL DEFAULT 'pending'",
                "ALTER TABLE `admin_notifications` ADD COLUMN `action_at` DATETIME NULL",
                "ALTER TABLE `admin_notifications` ADD COLUMN `action_by` BIGINT NULL",
                "ALTER TABLE `admin_notifications` ADD COLUMN `read_at` DATETIME NULL",
                "ALTER TABLE `admin_notifications` ADD COLUMN `read_by` BIGINT NULL",
                "ALTER TABLE `admin_notifications` ADD INDEX `idx_admin_notifications_unread` (`read_at`)",
            ):
                try:
                    await cur.execute(ddl)
                except Exception:
                    pass  # колонка вже існує
            await cur.execute(
                "UPDATE admin_notifications SET action_status = 'resolved' WHERE status = 'resolved' AND action_status = 'pending'"
            )


# Типи подій, що потребують рішення адміністратора (решта — лише інформаційні).
ACTIONABLE_NOTIFICATION_TYPES = {'invalid_receipt'}
NOTIFICATION_ACTION_STATUSES = ('pending', 'approved', 'rejected', 'resolved')


async def create_admin_notification(type: str, title: str, message: str,
                                   center_id: int = None, user_id: int = None,
                                   receipt_path: str = None, payload: dict = None,
                                   action_status: str = None):
    """Створює подію журналу.

    Для типів, що потребують рішення адміністратора (``invalid_receipt``), статус дії
    лишається ``pending``. Для інформаційних подій (``cash_operation``,
    ``negative_balance``) одразу ставимо ``resolved``, щоб вони не потрапляли
    у фільтр «Очікує рішення».
    """
    if action_status is None:
        action_status = 'pending' if type in ACTIONABLE_NOTIFICATION_TYPES else 'resolved'
    if action_status not in NOTIFICATION_ACTION_STATUSES:
        raise ValueError(f'Невідомий статус дії сповіщення: {action_status}')
    action_at = None if action_status == 'pending' else datetime.now()

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO admin_notifications
                       (type, title, message, center_id, user_id, receipt_path,
                        payload, action_status, action_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (type, title, message, center_id, user_id, receipt_path,
                 json.dumps(payload or {}, ensure_ascii=False), action_status, action_at)
            )
            return cur.lastrowid


def _notification_row(row):
    """Нормалізує рядок журналу: payload → dict, дати → str, зручні прапорці."""
    item = dict(row)
    try:
        payload = json.loads(item.get('payload') or '{}')
    except (TypeError, ValueError):
        payload = {}
    item['payload'] = payload if isinstance(payload, dict) else {}
    for key in ('created_at', 'resolved_at', 'action_at', 'read_at'):
        if item.get(key):
            item[key] = str(item[key])
    item['canceled_by_user'] = bool(item['payload'].get('canceled_by_user'))
    item['telegram_messages'] = item['payload'].get('telegram') or []
    return item


def _notification_conditions(status: str = None, type: str = None, center_id: int = None,
                             date_from: str = None, date_to: str = None,
                             is_read: bool = None, action_status: str = None):
    """Спільні умови фільтрації журналу: (SQL-фрагмент WHERE, параметри)."""
    conditions, params = [], []
    if status in ('open', 'resolved'):
        conditions.append("n.status = %s")
        params.append(status)
    if type:
        conditions.append("n.type = %s")
        params.append(type)
    if is_read is not None:
        conditions.append("n.read_at IS NOT NULL" if is_read else "n.read_at IS NULL")
    if action_status in NOTIFICATION_ACTION_STATUSES:
        conditions.append("n.action_status = %s")
        params.append(action_status)
    if center_id:
        conditions.append("n.center_id = %s")
        params.append(center_id)
    if date_from:
        conditions.append("n.created_at >= %s")
        params.append(f"{date_from} 00:00:00")
    if date_to:
        conditions.append("n.created_at < DATE_ADD(%s, INTERVAL 1 DAY)")
        params.append(date_to)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    return where, params


async def list_admin_notifications(status: str = None, type: str = None,
                                  center_id: int = None, date_from: str = None,
                                  date_to: str = None, is_read: bool = None,
                                  action_status: str = None, limit: int = 100,
                                  offset: int = 0):
    where, params = _notification_conditions(
        status=status, type=type, center_id=center_id, date_from=date_from,
        date_to=date_to, is_read=is_read, action_status=action_status,
    )
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                f"""SELECT n.*, c.name AS center_name, u.name AS user_name
                    FROM admin_notifications n
                    LEFT JOIN centers c ON c.id = n.center_id
                    LEFT JOIN users u ON u.telegram_id = n.user_id
                    {where}
                    ORDER BY n.created_at DESC, n.id DESC LIMIT %s OFFSET %s""",
                tuple(params) + (limit, offset)
            )
            rows = await cur.fetchall() or []
    return [_notification_row(row) for row in rows]


async def count_admin_notifications(status: str = None, type: str = None,
                                    center_id: int = None, date_from: str = None,
                                    date_to: str = None, is_read: bool = None,
                                    action_status: str = None) -> int:
    """Кількість подій за тими самими фільтрами (для пагінації журналу)."""
    where, params = _notification_conditions(
        status=status, type=type, center_id=center_id, date_from=date_from,
        date_to=date_to, is_read=is_read, action_status=action_status,
    )
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"SELECT COUNT(*) FROM admin_notifications n{where}", tuple(params)
            )
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def get_admin_notification(notification_id: int):
    """Одна подія журналу з назвами ЦН/користувача; None, якщо не знайдено."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """SELECT n.*, c.name AS center_name, u.name AS user_name
                   FROM admin_notifications n
                   LEFT JOIN centers c ON c.id = n.center_id
                   LEFT JOIN users u ON u.telegram_id = n.user_id
                   WHERE n.id = %s""",
                (notification_id,)
            )
            row = await cur.fetchone()
    return _notification_row(row) if row else None


async def find_open_invalid_receipt(user_id: int, receipt_path: str):
    """Знаходить уже поданий відкритий чек, щоб повторний запит не створив дублікат."""
    if not user_id or not receipt_path:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT id FROM admin_notifications
                   WHERE type = 'invalid_receipt' AND user_id = %s
                     AND receipt_path = %s AND status = 'open'
                   ORDER BY id DESC LIMIT 1""",
                (user_id, receipt_path)
            )
            row = await cur.fetchone()
    return int(row[0]) if row else None


async def save_admin_notification_messages(notification_id: int, messages: list) -> bool:
    """Зберігає ID надісланих у Telegram повідомлень, щоб редагувати їх на місці."""
    if not notification_id or not messages:
        return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT payload FROM admin_notifications WHERE id = %s", (notification_id,)
            )
            row = await cur.fetchone()
            if not row:
                return False
            try:
                payload = json.loads(row.get('payload') or '{}')
            except (TypeError, ValueError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            payload['telegram'] = messages
            await cur.execute(
                "UPDATE admin_notifications SET payload = %s WHERE id = %s",
                (json.dumps(payload, ensure_ascii=False), notification_id)
            )
            return cur.rowcount > 0


async def get_admin_notification_messages(notification_id: int) -> list:
    """Повертає збережені посилання на Telegram-повідомлення події."""
    notification = await get_admin_notification(notification_id)
    return notification.get('telegram_messages') or [] if notification else []


async def set_admin_notification_status(notification_id: int, status: str, actor_id: int):
    if status not in ('open', 'resolved'):
        raise ValueError('Невідомий статус сповіщення')
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """UPDATE admin_notifications
                   SET status = %s,
                       action_status = CASE
                           WHEN action_status IN ('approved','rejected') THEN action_status
                           WHEN %s = 'resolved' THEN 'resolved'
                           ELSE 'pending'
                       END,
                       action_at = IF(%s = 'resolved', NOW(), action_at),
                       action_by = IF(%s = 'resolved', %s, action_by),
                       resolved_at = IF(%s = 'resolved', NOW(), NULL),
                       resolved_by = IF(%s = 'resolved', %s, NULL)
                   WHERE id = %s""",
                (status, status, status, status, actor_id, status, status, actor_id, notification_id)
            )
            return cur.rowcount > 0


async def set_admin_notification_read(notification_id: int, is_read: bool, actor_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """UPDATE admin_notifications
                   SET read_at = IF(%s, NOW(), NULL), read_by = IF(%s, %s, NULL)
                   WHERE id = %s""",
                (bool(is_read), bool(is_read), actor_id, notification_id)
            )
            if cur.rowcount > 0:
                return True
            await cur.execute("SELECT 1 FROM admin_notifications WHERE id = %s", (notification_id,))
            return await cur.fetchone() is not None


async def set_invalid_receipt_amount(notification_id: int, user_id: int, amount: float) -> bool:
    """Зберігає суму, надану автором, лише для його відкритого документа."""
    amount = float(amount)
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError('Сума має бути більшою за нуль')
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """SELECT payload, message FROM admin_notifications
                   WHERE id = %s AND type = 'invalid_receipt' AND user_id = %s
                     AND status = 'open' FOR UPDATE""",
                (notification_id, user_id)
            )
            row = await cur.fetchone()
            if not row:
                return False
            try:
                payload = json.loads(row.get('payload') or '{}')
            except (TypeError, ValueError):
                payload = {}
            payload['amount'] = round(amount, 2)
            payload['amount_missing'] = False
            message = row.get('message') or ''
            if 'Сума від користувача:' not in message:
                message += f"\nСума від користувача: {amount:g} грн"
            await cur.execute(
                """UPDATE admin_notifications SET payload = %s, message = %s
                   WHERE id = %s AND status = 'open'""",
                (json.dumps(payload, ensure_ascii=False), message, notification_id)
            )
            return cur.rowcount > 0


async def close_invalid_receipt_by_user(notification_id: int, user_id: int) -> bool:
    """Закриває запит на суму, якщо його скасував автор документа."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """SELECT payload FROM admin_notifications
                   WHERE id = %s AND type = 'invalid_receipt' AND user_id = %s
                     AND status = 'open' FOR UPDATE""",
                (notification_id, user_id)
            )
            row = await cur.fetchone()
            if not row:
                return False
            try:
                payload = json.loads(row.get('payload') or '{}')
            except (TypeError, ValueError):
                payload = {}
            payload['decision'] = 'rejected'
            payload['canceled_by_user'] = True
            payload['canceled_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            # Скасування автором — не дія адміністратора, тому action_by/resolved_by лишаються NULL.
            await cur.execute(
                """UPDATE admin_notifications
                   SET status = 'resolved', action_status = 'rejected',
                       action_at = NOW(), action_by = NULL, resolved_at = NOW(),
                       resolved_by = NULL, payload = %s
                   WHERE id = %s AND status = 'open'""",
                (json.dumps(payload, ensure_ascii=False), notification_id)
            )
            return cur.rowcount > 0


async def decide_invalid_receipt(notification_id: int, decision: str, actor_id: int,
                                 expense_data: dict = None):
    """Вирішує звернення щодо чека; погоджений чек додається як витрата атомарно."""
    if decision not in ('approved', 'rejected'):
        raise ValueError('Невідоме рішення щодо чека')

    receipt_hash = None
    if decision == 'approved':
        pending_event = await get_admin_notification(notification_id)
        if pending_event and pending_event.get('user_id') and pending_event.get('receipt_path'):
            receipt_hash = await receipt_sha256(
                int(pending_event['user_id']), pending_event['receipt_path']
            )

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT * FROM admin_notifications
                       WHERE id = %s AND type = 'invalid_receipt' FOR UPDATE""",
                    (notification_id,)
                )
                notification = await cur.fetchone()
                if not notification:
                    await conn.rollback()
                    return None

                try:
                    payload = json.loads(notification.get('payload') or '{}')
                except (TypeError, ValueError):
                    payload = {}

                if notification['status'] != 'open' or notification.get('action_status') in ('approved', 'rejected'):
                    await conn.rollback()
                    return {
                        'already_decided': True,
                        'decision': notification.get('action_status') or payload.get('decision'),
                        'user_id': notification['user_id'],
                    }

                expense_id = None
                amount = None
                receipt_date = None
                category_name = None
                expense_name = None
                center_id = notification['center_id']

                if decision == 'approved':
                    user_id = notification.get('user_id')
                    if not user_id:
                        raise ValueError('Подія не пов\'язана з користувачем — погодити чек неможливо')
                    user_id = int(user_id)
                    # ЦН може бути не вказаний у самій події — тоді беремо з профілю користувача.
                    center_id = (expense_data or {}).get('center_id') or center_id
                    if not center_id:
                        center_id = await get_user_center_id(user_id)
                    if not center_id:
                        raise ValueError(
                            'Користувачу не призначено Центр Надії — призначте ЦН в адмін-панелі '
                            'і погодьте документ повторно'
                        )
                    try:
                        center_id = int(center_id)
                    except (TypeError, ValueError):
                        raise ValueError('Некоректний Центр Надії для цієї витрати')
                    amount_value = (expense_data or {}).get('amount', payload.get('amount'))
                    try:
                        amount = float(amount_value or 0)
                    except (TypeError, ValueError):
                        amount = 0
                    if not math.isfinite(amount) or amount <= 0:
                        if not expense_data and not payload.get('amount'):
                            await conn.rollback()
                            return {
                                'needs_amount': True,
                                'user_id': notification['user_id'],
                                'notification_id': notification_id,
                            }
                        raise ValueError('Вкажіть коректну суму витрати, більшу за нуль')

                    overrides = expense_data or {}
                    receipt_date = str(
                        overrides.get('date') or payload.get('receipt_date')
                        or datetime.now().strftime('%Y-%m-%d')
                    )[:10]
                    try:
                        datetime.strptime(receipt_date, '%Y-%m-%d')
                    except ValueError:
                        raise ValueError('Дата витрати має бути у форматі YYYY-MM-DD')
                    expense_name = str(
                        overrides.get('expense_name') or payload.get('expense_name')
                        or payload.get('document_type') or 'Чек'
                    ).strip()[:191]
                    category_name = str(
                        overrides.get('category') or payload.get('category') or 'Інше'
                    ).strip()
                    if not expense_name or not category_name:
                        raise ValueError('Вкажіть назву витрати та категорію')
                    category_id = await get_category_id_by_name(category_name, user_id)
                    expense_id = f"exp_{int(time.time() * 1000)}_{user_id}_{uuid.uuid4().hex[:4]}"
                    await cur.execute(
                        """INSERT INTO expenses
                               (id, date, telegram_id, center_id, amount, expense_name,
                                category_id, receipt_path, receipt_sha256)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (expense_id, receipt_date, user_id, center_id, amount,
                         expense_name, category_id, notification.get('receipt_path'),
                         _normalize_receipt_hash(receipt_hash))
                    )

                payload['decision'] = decision
                payload['decided_by'] = int(actor_id)
                payload['expense_id'] = expense_id
                payload['canceled_by_user'] = False
                await cur.execute(
                    """UPDATE admin_notifications
                       SET status = 'resolved', action_status = %s,
                           action_at = NOW(), action_by = %s, payload = %s,
                           resolved_at = NOW(), resolved_by = %s
                       WHERE id = %s AND status = 'open'""",
                    (decision, actor_id, json.dumps(payload, ensure_ascii=False), actor_id, notification_id)
                )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    if decision == 'approved':
        await _touch_cash_safe(center_id, receipt_date, reason=f"чек погоджено адміном ({expense_id})")
        _notify_budget_safe(center_id, category_id, receipt_date, expense_id, amount)

    return {
        'already_decided': False,
        'decision': decision,
        'user_id': notification['user_id'],
        'amount': amount,
        'receipt_date': receipt_date,
        'category': category_name,
        'expense_name': expense_name,
        'expense_id': expense_id,
    }

