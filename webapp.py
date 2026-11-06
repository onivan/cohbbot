from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import database
import asyncio  
import csv
import io
import os
import uuid
import logging
from datetime import datetime
from itsdangerous import URLSafeSerializer, BadSignature
from config import WEBAPP_URL, SECRET_KEY

app = FastAPI(title="Expense Tracker WebApp")
templates = Jinja2Templates(directory="templates")
serializer = URLSafeSerializer(SECRET_KEY)


def static_version(filename: str) -> str:
    """Версія статичного файлу для cache-busting (?v=...).
    Беремо mtime файлу, щоб після зміни JS браузер/Telegram не показував стару версію."""
    path = os.path.join("static", "js", filename)
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return str(int(datetime.now().timestamp()))

from fastapi import Depends

def get_current_user(request: Request) -> int:
    """Витягує user_id з кукі сесії (для браузера) або з query params/заголовка (якщо з бота)"""
    # 1. Спроба отримати з кукі
    session_cookie = request.cookies.get("session_token")
    if session_cookie:
        try:
            return serializer.loads(session_cookie)
        except BadSignature:
            pass
            
    # 2. Спроба отримати з query parameters (якщо відкрито з Telegram Web App)
    tg_user_id = request.query_params.get("user_id")
    if tg_user_id and tg_user_id.isdigit():
        return int(tg_user_id)
        
    # 3. Спроба отримати з кастомного заголовка
    header_user_id = request.headers.get("x-telegram-user-id")
    if header_user_id and header_user_id.isdigit():
        return int(header_user_id)
        
    raise HTTPException(status_code=401, detail='Unauthorized')

class LoginData(BaseModel):
    code: str

@app.post("/api/auth/login")
async def login_api(data: LoginData, response: Response):
    user_id = await database.validate_auth_code(data.code)
    if user_id:
        token = serializer.dumps(user_id)
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=30 * 24 * 60 * 60 # 30 днів
        )
        return {"status": "ok", "user_id": user_id}
    else:
        raise HTTPException(status_code=401, detail="Невірний або прострочений код")

@app.post("/api/auth/logout")
async def logout_api(response: Response):
    response.delete_cookie("session_token")
    return {"status": "ok"}

# Монтування папки з фотографіями чеків
os.makedirs("receipts", exist_ok=True)
app.mount("/receipts", StaticFiles(directory="receipts"), name="receipts")

# Монтування статики (CSS, JS)
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Pydantic моделі валідації
class ExpenseData(BaseModel):
    date: str
    amount: float
    expense_name: str
    category: str  # Зберігає category_id або назву
    file_path: Optional[str] = ""
    msg_id: Optional[int] = None

class CenterCreationData(BaseModel):
    name: str
    city: str
    is_active: int = 1

class CenterUpdateData(BaseModel):
    name: str
    city: str
    is_active: int

class UserCenterUpdateData(BaseModel):
    center_id: Optional[int] = None

class CategoryCreationData(BaseModel):
    id: str
    name: str
    sort_order: int = 999

class CategoryUpdateData(BaseModel):
    name: str
    sort_order: int
    is_active: int

class MatrixToggleData(BaseModel):
    center_id: int
    category_id: str
    is_enabled: bool

class BudgetData(BaseModel):
    target_center_id: int
    month: str
    category_id: str
    amount: float

class AIModelData(BaseModel):
    name: str
    model_id: str
    api_key: Optional[str] = ""
    is_active: int = 0


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={"request": request})

@app.get("/")
async def read_root(request: Request):
    user_id = None
    try:
        user_id = get_current_user(request)
    except:
        pass
    
    response = templates.TemplateResponse(request=request, name="index.html", context={"request": request, "user_id": user_id, "app_version": static_version("app.js")})
    if user_id:
        token = serializer.dumps(user_id)
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=30 * 24 * 60 * 60 # 30 днів
        )
    return response


# ==========================================
# 1. ЕНДПОЇНТИ КАТЕГОРІЙ ТА НАЛАШТУВАНЬ
# ==========================================

@app.get("/api/categories")
async def fetch_categories(current_user: int = Depends(get_current_user)):
    categories = await database.get_categories(current_user)
    return {"status": "ok", "data": categories}

@app.get("/api/categories/{center_id}")
async def fetch_center_categories(center_id: int, current_user: int = Depends(get_current_user)):
    categories = await database.get_categories_for_center(center_id)
    return {"status": "ok", "data": categories}

@app.get("/api/user/{user_id}/center")
async def get_center(user_id: int, current_user: int = Depends(get_current_user)):
    u_info = database.users_cache.get(str(user_id), {})
    return {"status": "ok", "center": u_info.get("center", "МійЦентр")}

from bot_setup import bot

# @app.post("/api/user/{user_id}/center") - ВИДАЛЕНО, тепер адмін призначає ЦН


@app.get("/api/user/{user_id}/role")
async def get_user_role(user_id: int, current_user: int = Depends(get_current_user)):
    u_info = database.users_cache.get(str(user_id), {})
    # center_id беремо з кешу, а якщо там порожньо — з БД (кеш міг не оновитися)
    center_id = u_info.get("center_id")
    if not center_id:
        center_id = await database.get_user_center_id(user_id)
    return {
        "status": "ok", 
        "role": u_info.get("role", "user"),
        "name": u_info.get("name", "Невідомо"),
        "center_id": center_id
    }

# ==========================================
# ADMIN PANEL ENDPOINTS
# ==========================================

@app.get("/admin")
@app.get("/admin.html")
async def admin_page(request: Request):
    user_id = None
    try:
        user_id = get_current_user(request)
    except:
        pass
        
    if not user_id or not database.is_admin(user_id):
        return Response(status_code=302, headers={"Location": "/login"})
        
    response = templates.TemplateResponse(request=request, name="admin.html", context={"request": request, "user_id": user_id, "app_version": static_version("admin.js")})
    token = serializer.dumps(user_id)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 60 * 60
    )
    return response

@app.get("/api/admin/users")
async def admin_get_users(current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    users = await database.get_all_users_details()
    return {"status": "ok", "data": users}

@app.put("/api/admin/users/{target_user_id}/center")
async def admin_set_user_center(target_user_id: int, data: UserCenterUpdateData, current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    
    success = await database.admin_set_user_center(target_user_id, data.center_id)
    if success:
        if data.center_id:
            try:
                # Отримуємо назву центру для повідомлення
                centers = await database.get_centers()
                center_name = next((c['name'] for c in centers if c['id'] == data.center_id), "ЦН")
                
                await bot.send_message(
                    target_user_id,
                    f"🎉 Вас призначено до **{center_name}**!\nТепер ви можете вносити витрати. Надішліть чек або натисніть кнопку «Витрати».",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Не вдалося відправити повідомлення користувачу {target_user_id}: {e}")
        return {"status": "ok"}
    raise HTTPException(status_code=400, detail="Помилка оновлення")

@app.get("/api/admin/categories")
async def admin_get_categories(current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    categories = await database.get_all_categories()
    return {"status": "ok", "data": categories}

@app.post("/api/admin/categories")
async def admin_create_category(data: CategoryCreationData, current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    await database.create_category(data.id, data.name, data.sort_order)
    return {"status": "ok"}

@app.put("/api/admin/categories/{category_id}")
async def admin_update_category(category_id: str, data: CategoryUpdateData, current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    await database.update_category(category_id, data.name, data.sort_order, data.is_active)
    return {"status": "ok"}

@app.get("/api/admin/matrix")
async def admin_get_matrix(current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    matrix_data = await database.get_category_matrix()
    return {"status": "ok", "data": matrix_data}

@app.post("/api/admin/matrix/toggle")
async def admin_toggle_matrix(data: MatrixToggleData, current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    await database.set_center_category(data.center_id, data.category_id, data.is_enabled)
    return {"status": "ok"}

@app.get("/api/admin/centers/summary")
async def admin_get_centers_summary(month: Optional[str] = None, current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    summary = await database.get_centers_summary(month, current_user)
    return {"status": "ok", "data": summary}

@app.get("/api/admin/centers")
async def admin_get_centers(current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    centers = await database.get_centers(user_id=current_user)
    return {"status": "ok", "data": centers}

@app.post("/api/admin/centers")
async def admin_create_center(data: CenterCreationData, current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    center_id = await database.create_center(data.name, data.city, data.is_active)
    return {"status": "ok", "center_id": center_id}

@app.put("/api/admin/centers/{center_id}")
async def admin_update_center(center_id: int, data: CenterUpdateData, current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    success = await database.update_center_details(center_id, data.name, data.city, data.is_active)
    return {"status": "ok", "success": success}

# ==========================================
# BUDGETS ENDPOINTS
# ==========================================

@app.get("/api/budgets/center/{center_id}")
async def get_center_budgets_ep(center_id: int, month: str, current_user: int = Depends(get_current_user)):
    budgets = await database.get_center_budgets(center_id, month)
    return {"status": "ok", "data": budgets}

@app.get("/api/budgets/{user_id}")
async def get_budgets(user_id: int, month: str, current_user: int = Depends(get_current_user)):
    """Отримує бюджети користувача на вказаний місяць."""
    budgets = await database.get_user_budgets(user_id, month)
    # Також запускаємо діагностичну функцію
    debug_data = await database.debug_budgets(user_id, month)
    return {"status": "ok", "data": budgets, "_debug": debug_data}

@app.post("/api/admin/budgets")
async def set_budget_admin(admin_id: int, data: BudgetData, current_user: int = Depends(get_current_user)):
    if not database.is_admin(admin_id):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
        
    budget_id = await database.set_center_budget(
        data.target_center_id, 
        data.category_id, 
        data.month, 
        data.amount
    )
    return {"status": "ok", "budget_id": budget_id}


# ==========================================
# AI-МОДЕЛІ (OPENROUTER)
# ==========================================

@app.get("/api/admin/ai")
async def admin_get_ai_models(current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    return {"status": "ok", "data": await database.get_ai_models()}


@app.post("/api/admin/ai")
async def admin_add_ai_model(data: AIModelData, current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    name = (data.name or "").strip()
    model_id = (data.model_id or "").strip()
    api_key = (data.api_key or "").strip()
    if not name or not model_id:
        raise HTTPException(status_code=400, detail="Назва та ID моделі обов'язкові")
    new_id = await database.add_ai_model(name, model_id, api_key, is_active=bool(data.is_active))
    return {"status": "ok", "id": new_id}


@app.put("/api/admin/ai/{model_pk}")
async def admin_update_ai_model(model_pk: int, data: AIModelData, current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    name = (data.name or "").strip()
    model_id = (data.model_id or "").strip()
    if not name or not model_id:
        raise HTTPException(status_code=400, detail="Назва та ID моделі обов'язкові")
    # Порожній ключ = залишити поточний
    api_key = (data.api_key or "").strip() or None
    ok = await database.update_ai_model(model_pk, name, model_id, api_key)
    return {"status": "ok", "success": ok}


@app.delete("/api/admin/ai/{model_pk}")
async def admin_delete_ai_model(model_pk: int, current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    ok = await database.delete_ai_model(model_pk)
    return {"status": "ok", "success": ok}


@app.post("/api/admin/ai/{model_pk}/activate")
async def admin_activate_ai_model(model_pk: int, current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    ok = await database.set_active_ai_model(model_pk)
    return {"status": "ok", "success": ok}


# ==========================================
# 2. ЗАВАНТАЖЕННЯ ЧЕКІВ
# ==========================================

@app.post("/api/upload/{user_id}")
async def upload_receipt(user_id: int, file: UploadFile = File(...), current_user: int = Depends(get_current_user)):
    dt = datetime.now()
    year = dt.strftime("%Y")
    month = dt.strftime("%m")
    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H-%M-%S")
    
    u_info = database.users_cache.get(str(user_id), {'name': 'User', 'center': 'Центр'})
    center_name = u_info.get('center', 'Центр')
    safe_center = "".join(c for c in center_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(" ", "_")
    
    random_suffix = uuid.uuid4().hex[:6]
    ext = os.path.splitext(file.filename)[1].lower() or '.jpg'

    folder_path = f"receipts/{user_id}/{year}/{month}"
    os.makedirs(folder_path, exist_ok=True)
    
    file_name = f"{date_str}_{time_str}-{safe_center}_{random_suffix}{ext}"
    local_path = f"{folder_path}/{file_name}"
    
    with open(local_path, "wb") as buffer:
        buffer.write(await file.read())
        
    file_url = f"{WEBAPP_URL}/{local_path}"
    return {"status": "ok", "file_path": file_url}


# ==========================================
# 3. ЕНДПОЇНТИ ВИ ТРАТ (CRUD)
# ==========================================

@app.get("/api/expenses/{user_id}")
async def get_expenses(user_id: int, center_id: Optional[int] = None, current_user: int = Depends(get_current_user)):
    # Якщо адміністратор запросив витрати конкретного ЦН
    if center_id and database.is_admin(current_user):
        expenses = await database.get_expenses_by_center(center_id)
    # Якщо адміністратор запросив ВСІ витрати (center_id=0 або all)
    elif center_id == 0 and database.is_admin(current_user):
        expenses = await database.get_all_expenses()
    else:
        # Для звичайного юзера (або адміна, який дивиться свій ЦН)
        expenses = await database.get_user_expenses(user_id)
        
    first_exp = expenses[0] if expenses else {}
    return {
        "status": "ok", 
        "data": expenses, 
        "_debug_sample": {
            "total_count": len(expenses),
            "first_record": first_exp,
            "keys": list(first_exp.keys()) if first_exp else []
        }
    }

@app.post("/api/expenses/{user_id}")
async def create_expense(user_id: int, data: ExpenseData, current_user: int = Depends(get_current_user)):
    # Очікується рядок: [date, user_id, amount, expense_name, category, file_path]
    row_data = [data.date, str(user_id), data.amount, data.expense_name, data.category, data.file_path]
    expense_id = await database.add_expense(row_data)
    
    # Видалення повідомлення в боті після швидкого збереження чернетки
    if data.msg_id:
        try:
            from bot_setup import bot, dp
            from aiogram.fsm.context import FSMContext
            from aiogram.fsm.storage.base import StorageKey
            await bot.delete_message(chat_id=user_id, message_id=data.msg_id)
            await bot.send_message(chat_id=user_id, text=f"✅ Витрату «{data.expense_name}» на {data.amount} грн успішно збережено!")
            state = FSMContext(storage=dp.storage, key=StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id))
            await state.clear()
        except Exception as e:
            logging.error(f"Error updating bot message: {e}")

    return {"status": "ok", "expense_id": expense_id}

@app.put("/api/expenses/{user_id}/{expense_id}")
async def edit_expense(user_id: int, expense_id: str, data: ExpenseData, current_user: int = Depends(get_current_user)):
    row_data = [data.date, str(user_id), data.amount, data.expense_name, data.category, data.file_path]
    success = await database.update_expense(expense_id, user_id, row_data)
    if not success:
        raise HTTPException(status_code=404, detail="Запис не знайдено або немає доступу")
    return {"status": "ok"}

@app.delete("/api/expenses/{user_id}/{expense_id}")
async def remove_expense(user_id: int, expense_id: str, current_user: int = Depends(get_current_user)):
    success = await database.delete_expense(expense_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Запис не знайдено або немає доступу")
    return {"status": "ok"}


# ==========================================
# J. КОШТИ ЦН (КАСА) — ПЕРЕГЛЯД ДЛЯ КОРИСТУВАЧА (етап 2)
# ==========================================
# Юзер бачить лише кошти свого ЦН; адмін — будь-якого (у нього є й адмінка).
# Ендпоінти лише читають: жодних операцій зі зміни залишку тут немає.

async def _cash_center_for(user_id: int, center_id: Optional[int] = None) -> int:
    """ЦН для перегляду коштів: явно вказаний (адмін) або власний ЦН користувача."""
    u_info = database.users_cache.get(str(user_id), {})
    own = u_info.get("center_id")
    if not own:
        own = await database.get_user_center_id(user_id)
    try:
        own = int(own) if own not in (None, "", 0) else None
    except (TypeError, ValueError):
        own = None

    if center_id is None:
        if own is None:
            raise HTTPException(status_code=404, detail="Центр не призначено")
        return own

    try:
        center_id = int(center_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Некоректний center_id")

    if own is not None and center_id == own:
        return own
    if database.is_admin(user_id):
        return center_id
    raise HTTPException(status_code=403, detail="Доступ лише до коштів свого ЦН")


def _check_month(month: Optional[str]) -> None:
    if month and not database.is_valid_month(month):
        raise HTTPException(status_code=400, detail="Місяць має бути у форматі YYYY-MM")


@app.get("/api/cash/summary")
async def cash_summary_user(center_id: Optional[int] = None, month: Optional[str] = None,
                            current_user: int = Depends(get_current_user)):
    """Залишки коштів ЦН за місяць (read-only, вкладка «💰 Кошти»)."""
    cid = await _cash_center_for(current_user, center_id)
    _check_month(month)
    data = await database.get_cash_summary(cid, month)
    return {"status": "ok", "data": data}


@app.get("/api/cash/ledger")
async def cash_ledger_user(center_id: Optional[int] = None, month: Optional[str] = None,
                           limit: int = 200,
                           current_user: int = Depends(get_current_user)):
    """Рух коштів ЦН за місяць із наростаючим залишком (read-only)."""
    cid = await _cash_center_for(current_user, center_id)
    _check_month(month)
    limit = max(1, min(int(limit), 500))
    data = await database.get_cash_ledger(cid, month, limit=limit)
    return {"status": "ok", "data": data}


# ==========================================
# J. КОШТИ ЦН (КАСА) — АДМІНСЬКІ ОПЕРАЦІЇ (етап 3)
# ==========================================

CASH_OP_KINDS = ('funding', 'return', 'adjustment')
CASH_METHODS = ('cash', 'bank')


class CashSettingsData(BaseModel):
    center_id: int
    start_month: str
    opening_balance: float = 0.0
    note: Optional[str] = None


class CashOperationData(BaseModel):
    center_id: int
    op_date: str
    kind: str
    amount: float
    method: str = 'cash'
    counterparty: Optional[str] = None
    comment: Optional[str] = None


class CashBatchItem(BaseModel):
    center_id: int
    amount: float


class CashBatchFundingData(BaseModel):
    op_date: str
    method: str = 'cash'
    counterparty: Optional[str] = None
    comment: Optional[str] = None
    amounts: List[CashBatchItem] = []


def _require_admin(current_user: int):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")


async def _cash_notify_after(op: dict):
    """Підсумок за місяцем операції + фонові сповіщення (не валять запит)."""
    try:
        summary = await database.get_cash_summary(op['center_id'], op['month'])
        import cash_notify
        cash_notify.after_operation(op, summary)
        return summary
    except Exception as e:
        logging.error(f"cash notify ({op.get('id')}): {e}")
        return None


@app.get("/api/admin/cash/overview")
async def admin_cash_overview(month: Optional[str] = None,
                              current_user: int = Depends(get_current_user)):
    """Стан коштів по всіх ЦН за місяць (таблиця адмінки)."""
    _require_admin(current_user)
    try:
        data = await database.get_cash_admin_table(month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "data": data}


@app.get("/api/admin/cash/ledger")
async def admin_cash_ledger(center_id: int, month: Optional[str] = None,
                            limit: int = 300,
                            current_user: int = Depends(get_current_user)):
    """Журнал руху коштів одного ЦН за місяць."""
    _require_admin(current_user)
    try:
        data = await database.get_cash_ledger(center_id, month, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    centers = await database.get_centers()
    data['center_name'] = next(
        (c['name'] for c in centers if c['id'] == center_id), f"ЦН #{center_id}"
    )
    return {"status": "ok", "data": data}


@app.post("/api/admin/cash/settings")
async def admin_cash_settings(data: CashSettingsData,
                              current_user: int = Depends(get_current_user)):
    """Початок обліку та реальний залишок на 1-ше число місяця."""
    _require_admin(current_user)
    try:
        settings = await database.set_cash_settings(
            data.center_id, data.start_month, data.opening_balance,
            note=(data.note or '').strip() or None, actor_id=current_user,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "data": settings}


@app.post("/api/admin/cash/operation")
async def admin_cash_operation(data: CashOperationData,
                               current_user: int = Depends(get_current_user)):
    """Рух коштів: funding (+), return (−), adjustment (±)."""
    _require_admin(current_user)
    if data.kind not in CASH_OP_KINDS:
        raise HTTPException(status_code=400, detail="Невідомий тип операції")
    method = (data.method or 'cash').strip().lower()
    if method not in CASH_METHODS:
        raise HTTPException(status_code=400, detail="Спосіб має бути cash або bank")
    try:
        op = await database.add_cash_operation(
            data.center_id, data.op_date, data.kind, data.amount,
            method=method,
            counterparty=(data.counterparty or '').strip() or None,
            comment=(data.comment or '').strip() or None,
            actor_id=current_user,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    summary = await _cash_notify_after(op)
    return {"status": "ok", "data": op, "summary": summary}


@app.post("/api/admin/cash/funding-batch")
async def admin_cash_funding_batch(data: CashBatchFundingData,
                                   current_user: int = Depends(get_current_user)):
    """Масова видача коштів по кількох ЦН одним batch_id."""
    _require_admin(current_user)
    amounts = {}
    for item in data.amounts or []:
        value = float(item.amount or 0)
        if value > 0:
            amounts[int(item.center_id)] = amounts.get(int(item.center_id), 0.0) + value
    if not amounts:
        raise HTTPException(status_code=400, detail="Не вказано жодної суми")
    method = (data.method or 'cash').strip().lower()
    if method not in CASH_METHODS:
        raise HTTPException(status_code=400, detail="Спосіб має бути cash або bank")
        result = await database.add_funding_batch(
        amounts, data.op_date, method=method,
        counterparty=(data.counterparty or '').strip() or None,
        comment=(data.comment or '').strip() or None,
        actor_id=current_user,
    )
    for op in result['created']:
        await _cash_notify_after(op)
    return {"status": "ok", "data": result}


# ==========================================
# J. КОШТИ ЦН — ЗВІТИ (етап 4)
# ==========================================
# Річний огляд 20 ЦН × 12 місяців, закриття / відкриття місяця, звірка залишків, CSV.
# Розрахунки живуть у database.py (агрегатні запити) — тут лише доступ і формат.

class CashMonthActionData(BaseModel):
    month: str
    reason: Optional[str] = None


CASH_STATUS_LABELS = {
    'open': 'відкритий',
    'closed': 'закритий',
    'unconfigured': 'не налаштовано',
    'not_started': 'облік ще не почався',
}


def _parse_year(year: Optional[int]) -> int:
    year = int(year or datetime.now().year)
    if year < 2000 or year > 2100:
        raise HTTPException(status_code=400, detail="Рік має бути в межах 2000–2100")
    return year


def _require_month(month: Optional[str]) -> str:
    if not month:
        raise HTTPException(status_code=400, detail="Вкажіть місяць у форматі YYYY-MM")
    _check_month(month)
    return month


def _csv_money(value) -> str:
    """Число для Excel: десяткова кома, без роздільника тисяч."""
    if value is None or value == '':
        return ''
    try:
        return f"{float(value):.2f}".replace('.', ',')
    except (TypeError, ValueError):
        return str(value)


def _csv_response(rows: List[List], filename: str) -> Response:
    """CSV, який Excel відкриває без «кракозябр»: UTF-8 BOM + роздільник ';'."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=';', lineterminator='\r\n')
    for row in rows:
        writer.writerow(['' if v is None else v for v in row])
    return Response(
        content='\ufeff' + buf.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@app.get("/api/admin/cash/year")
async def admin_cash_year(year: Optional[int] = None,
                          current_user: int = Depends(get_current_user)):
    """Річний огляд коштів: 12 місяців × усі ЦН + підсумки за рік."""
    _require_admin(current_user)
    try:
        data = await database.get_cash_overview(_parse_year(year))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "data": data}


@app.get("/api/admin/cash/reconcile")
async def admin_cash_reconcile(month: Optional[str] = None,
                               current_user: int = Depends(get_current_user)):
    """Звірка: неперервність ланцюжка залишків і збіг розрахунку зі знімками."""
    _require_admin(current_user)
    _check_month(month)
    try:
        data = await database.reconcile_month(month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    centers = await database.get_centers()
    names = {c['id']: c['name'] for c in centers}
    for issue in data.get('issues') or []:
        issue['center_name'] = names.get(issue['center_id'], f"ЦН #{issue['center_id']}")
    return {"status": "ok", "data": data}


@app.post("/api/admin/cash/close-month")
async def admin_cash_close_month(data: CashMonthActionData,
                                 current_user: int = Depends(get_current_user)):
    """Закриває місяць: залишки всіх ЦН фіксуються знімками (status='closed')."""
    _require_admin(current_user)
    month = _require_month(data.month)
    if month > database.current_month():
        raise HTTPException(status_code=400, detail="Не можна закрити майбутній місяць")
    try:
        result = await database.close_month(month, actor_id=current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "data": result}


@app.post("/api/admin/cash/reopen-month")
async def admin_cash_reopen_month(data: CashMonthActionData,
                                  current_user: int = Depends(get_current_user)):
    """Знімає фіксацію місяця (причина пишеться в cash_audit)."""
    _require_admin(current_user)
    month = _require_month(data.month)
    try:
        result = await database.reopen_month(
            month, actor_id=current_user, reason=(data.reason or '').strip() or None
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "data": result}


@app.get("/api/admin/cash/export.csv")
async def admin_cash_export(center_id: Optional[int] = None, month: Optional[str] = None,
                            year: Optional[int] = None,
                            current_user: int = Depends(get_current_user)):
    """CSV-звіт: журнал ЦН за місяць / місяць по всіх ЦН / рік по всіх ЦН."""
    _require_admin(current_user)
    centers = await database.get_centers()
    names = {c['id']: c['name'] for c in centers}

    # 1) Журнал одного ЦН за місяць
    if center_id is not None and month:
        _require_month(month)
        data = await database.get_cash_ledger(center_id, month, limit=5000)
        name = names.get(center_id, f"ЦН #{center_id}")
        rows: List[List] = [['Журнал коштів ЦН'], ['ЦН', name], ['Місяць', month]]
        summary = data.get('summary') or {}
        if data.get('configured'):
            rows += [
                ['Облік з', summary.get('start_month') or ''],
                ['На початок', _csv_money(summary.get('opening_balance'))],
                ['Надійшло', _csv_money(summary.get('received'))],
                ['Витрачено', _csv_money(summary.get('spent'))],
                ['Залишок', _csv_money(summary.get('closing_balance'))],
                ['Стан', CASH_STATUS_LABELS.get(summary.get('status'), summary.get('status') or '')],
            ]
        else:
            rows.append(['Увага', 'Облік коштів для цього ЦН не налаштовано'])
        rows += [[], ['Дата', 'Операція', 'Сума', 'Залишок', 'Стаття', 'Коментар']]
        for r in data.get('rows') or []:
            rows.append([
                r.get('date'), r.get('title'), _csv_money(r.get('amount')),
                _csv_money(r.get('balance')), r.get('category_name') or '',
                r.get('comment') or '',
            ])
        safe_name = ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in name)
        return _csv_response(rows, f"cash-{month}-{safe_name}.csv")

    # 2) Місяць по всіх ЦН
    if month:
        month = _require_month(month)
        table = await database.get_cash_admin_table(month)
        totals = table.get('totals') or {}
        rows = [
            ['Кошти ЦН за місяць'], ['Місяць', month],
            ['Надійшло', _csv_money(totals.get('received'))],
            ['Витрачено', _csv_money(totals.get('spent'))],
            ['Залишок', _csv_money(totals.get('closing_balance'))],
            [], ['ЦН', 'Місто', 'Облік з', 'На початок', 'Надійшло', 'Витрачено', 'Залишок', 'Стан'],
        ]
        for r in table.get('rows') or []:
            status = CASH_STATUS_LABELS.get(r.get('status'), r.get('status') or '')
            if r.get('matches') is False:
                status += ' (розбіжність зі знімком)'
            rows.append([
                r.get('name'), r.get('city') or '', r.get('start_month') or '',
                _csv_money(r.get('month_opening')), _csv_money(r.get('received')),
                _csv_money(r.get('spent')), _csv_money(r.get('closing_balance')), status,
            ])
        if table.get('negative'):
            rows += [[], ['Мінусовий залишок']]
            for n in table['negative']:
                rows.append([n.get('name'), _csv_money(n.get('closing_balance'))])
        return _csv_response(rows, f"cash-{month}.csv")

    # 3) Рік по всіх ЦН
    year = _parse_year(year)
    overview = await database.get_cash_overview(year)
    city_of = {c['id']: (c.get('city') or '') for c in overview.get('centers') or []}
    totals = overview.get('totals') or {}
    rows = [
        ['Звіт про кошти ЦН за рік'], ['Рік', year],
        ['Надійшло за рік', _csv_money(totals.get('received'))],
        ['Витрачено за рік', _csv_money(totals.get('spent'))],
        [], ['Місяць', 'ЦН', 'Місто', 'Облік з', 'На початок', 'Надійшло', 'Витрачено', 'Залишок', 'Стан'],
    ]
    for month_data in overview.get('months') or []:
        for r in month_data.get('rows') or []:
            status = CASH_STATUS_LABELS.get(r.get('status'), r.get('status') or '')
            if r.get('matches') is False:
                status += ' (розбіжність зі знімком)'
            rows.append([
                month_data.get('month'), r.get('name'), city_of.get(r.get('center_id'), ''),
                r.get('start_month') or '', _csv_money(r.get('opening_balance')),
                _csv_money(r.get('received')), _csv_money(r.get('spent')),
                _csv_money(r.get('closing_balance')), status,
            ])
    rows += [[], ['Підсумки по ЦН за рік'],
             ['ЦН', 'Місто', 'Облік з', 'Надійшло', 'Витрачено', 'Залишок на кінець року']]
    for c in overview.get('centers') or []:
        if not c.get('configured'):
            continue
        rows.append([
            c.get('name'), c.get('city') or '', c.get('start_month') or '',
            _csv_money(c.get('received')), _csv_money(c.get('spent')),
            _csv_money(c.get('closing_balance')),
        ])
    return _csv_response(rows, f"cash-{year}.csv")
