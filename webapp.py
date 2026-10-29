from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import database
import asyncio  
import os
import uuid
import logging
from datetime import datetime
from itsdangerous import URLSafeSerializer, BadSignature
from config import WEBAPP_URL, SECRET_KEY

app = FastAPI(title="Expense Tracker WebApp")
templates = Jinja2Templates(directory="templates")
serializer = URLSafeSerializer(SECRET_KEY)

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


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={"request": request})

@app.get("/")
async def read_root(request: Request):
    # Спробуємо отримати user_id з кукі або параметрів
    user_id = None
    try:
        user_id = get_current_user(request)
    except:
        pass
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request, "user_id": user_id})


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
    return {
        "status": "ok", 
        "role": u_info.get("role", "user"),
        "name": u_info.get("name", "Невідомо"),
        "center_id": u_info.get("center_id")
    }

# ==========================================
# ADMIN PANEL ENDPOINTS
# ==========================================

@app.get("/admin")
async def admin_page(request: Request, current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    return templates.TemplateResponse(request=request, name="admin.html", context={"request": request})

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
    summary = await database.get_centers_summary(month)
    return {"status": "ok", "data": summary}

@app.get("/api/admin/centers")
async def admin_get_centers(current_user: int = Depends(get_current_user)):
    if not database.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    centers = await database.get_centers()
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
