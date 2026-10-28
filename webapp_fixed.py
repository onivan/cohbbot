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

def get_current_user(request: Request) -> int:
    """Р’РёС‚СЏРіСѓС” user_id Р· РєСѓРєС– СЃРµСЃС–С— (РґР»СЏ Р±СЂР°СѓР·РµСЂР°) Р°Р±Рѕ Р· query params (СЏРєС‰Рѕ Р· Р±РѕС‚Р°)"""
    # 1. РЎРїСЂРѕР±Р° РѕС‚СЂРёРјР°С‚Рё Р· РєСѓРєС–
    session_cookie = request.cookies.get("session_token")
    if session_cookie:
        try:
            return serializer.loads(session_cookie)
        except BadSignature:
            pass
            
    # 2. РЎРїСЂРѕР±Р° РѕС‚СЂРёРјР°С‚Рё Р· query parameters (СЏРєС‰Рѕ РІС–РґРєСЂРёС‚Рѕ Р· Telegram Web App)
    tg_user_id = request.query_params.get("user_id")
    if tg_user_id and tg_user_id.isdigit():
        return int(tg_user_id)
        
    return None

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
            max_age=30 * 24 * 60 * 60 # 30 РґРЅС–РІ
        )
        return {"status": "ok", "user_id": user_id}
    else:
        raise HTTPException(status_code=401, detail="РќРµРІС–СЂРЅРёР№ Р°Р±Рѕ РїСЂРѕСЃС‚СЂРѕС‡РµРЅРёР№ РєРѕРґ")

@app.post("/api/auth/logout")
async def logout_api(response: Response):
    response.delete_cookie("session_token")
    return {"status": "ok"}

# РњРѕРЅС‚СѓРІР°РЅРЅСЏ РїР°РїРєРё Р· С„РѕС‚РѕРіСЂР°С„С–СЏРјРё С‡РµРєС–РІ
os.makedirs("receipts", exist_ok=True)
app.mount("/receipts", StaticFiles(directory="receipts"), name="receipts")

# РњРѕРЅС‚СѓРІР°РЅРЅСЏ СЃС‚Р°С‚РёРєРё (CSS, JS)
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Pydantic РјРѕРґРµР»С– РІР°Р»С–РґР°С†С–С—
class ExpenseData(BaseModel):
    date: str
    amount: float
    expense_name: str
    category: str  # Р—Р±РµСЂС–РіР°С” category_id Р°Р±Рѕ РЅР°Р·РІСѓ
    file_path: Optional[str] = ""
    msg_id: Optional[int] = None

class CenterData(BaseModel):
    center: str

class CategoriesData(BaseModel):
    categories: List[str]

class CategoryActionData(BaseModel):
    category: str
    old_category: Optional[str] = None
    category_id: Optional[str] = None
    sort_order: Optional[int] = 999

class BudgetData(BaseModel):
    target_user_id: int
    month: str
    category_id: str
    amount: float


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={"request": request})

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request})


# ==========================================
# 1. Р•РќР”РџРћР‡РќРўР РљРђРўР•Р“РћР Р†Р™ РўРђ РќРђР›РђРЁРўРЈР’РђРќР¬
# ==========================================

@app.get("/api/categories")
async def fetch_categories():
    categories = await database.get_categories()
    return {"status": "ok", "data": categories}

@app.get("/api/categories/{user_id}")
async def fetch_user_categories(user_id: int):
    categories = await database.get_categories(user_id)
    return {"status": "ok", "data": categories}

@app.post("/api/categories/{user_id}")
async def update_user_categories(user_id: int, data: CategoriesData, admin_id: int):
    if not database.is_admin(admin_id):
        raise HTTPException(status_code=403, detail="Р”РѕСЃС‚СѓРї Р·Р°Р±РѕСЂРѕРЅРµРЅРѕ")
    await database.save_user_categories(user_id, data.categories)
    return {"status": "ok"}

@app.post("/api/categories/{user_id}/add")
async def add_category_endpoint(user_id: int, data: CategoryActionData, admin_id: int):
    if not database.is_admin(admin_id):
        raise HTTPException(status_code=403, detail="Р”РѕСЃС‚СѓРї Р·Р°Р±РѕСЂРѕРЅРµРЅРѕ")
    await database.add_user_category(user_id, data.category, data.sort_order)
    return {"status": "ok"}

@app.post("/api/categories/{user_id}/delete")
async def delete_category_endpoint(user_id: int, data: CategoryActionData, admin_id: int):
    if not database.is_admin(admin_id):
        raise HTTPException(status_code=403, detail="Р”РѕСЃС‚СѓРї Р·Р°Р±РѕСЂРѕРЅРµРЅРѕ")
    await database.delete_user_category(user_id, data.category)
    return {"status": "ok"}

@app.post("/api/categories/{user_id}/rename")
async def rename_category_endpoint(user_id: int, data: CategoryActionData, admin_id: int):
    if not database.is_admin(admin_id):
        raise HTTPException(status_code=403, detail="Р”РѕСЃС‚СѓРї Р·Р°Р±РѕСЂРѕРЅРµРЅРѕ")
    if data.old_category:
        await database.rename_user_category(user_id, data.old_category, data.category)
    return {"status": "ok"}

@app.get("/api/user/{user_id}/center")
async def get_center(user_id: int):
    u_info = database.users_cache.get(str(user_id), {})
    return {"status": "ok", "center": u_info.get("center", "РњС–Р№Р¦РµРЅС‚СЂ")}

from bot_setup import bot

from bot_setup import bot

@app.post("/api/user/{user_id}/center")
async def set_center(user_id: int, data: CenterData):
    await database.update_user_center(user_id, data.center)
    try:
        await bot.send_message(
            user_id,
            f"вњ… Р’Р°СЃ РїСЂРёР·РЅР°С‡РµРЅРѕ РґРѕ **{data.center}**! РўРµРїРµСЂ РІРё РјРѕР¶РµС‚Рµ РІРЅРѕСЃРёС‚Рё РІРёС‚СЂР°С‚Рё.",
            parse_mode="Markdown"
        )
    except Exception:
        pass
    return {"status": "ok"}
    try:
        await bot.send_message(
            user_id,
            f"рџЋ‰ Р’Р°СЃ РїСЂРёР·РЅР°С‡РµРЅРѕ РґРѕ **{data.center}**!\nРўРµРїРµСЂ РІРё РјРѕР¶РµС‚Рµ РІРЅРѕСЃРёС‚Рё РІРёС‚СЂР°С‚Рё. РќР°РґС–С€Р»С–С‚СЊ С‡РµРє Р°Р±Рѕ РЅР°С‚РёСЃРЅС–С‚СЊ РєРЅРѕРїРєСѓ В«Р’РёС‚СЂР°С‚РёВ».",
            parse_mode="Markdown"
        )
    except Exception:
        pass
        
    return {"status": "ok"}


@app.get("/api/user/{user_id}/role")
async def get_user_role(user_id: int):
    u_info = database.users_cache.get(str(user_id), {})
    return {
        "status": "ok", 
        "role": u_info.get("role", "user"),
        "name": u_info.get("name", "РќРµРІС–РґРѕРјРѕ")
    }

@app.get("/api/admin/users")
async def get_all_users_admin(admin_id: int):
    if not database.is_admin(admin_id):
        raise HTTPException(status_code=403, detail="Р”РѕСЃС‚СѓРї Р·Р°Р±РѕСЂРѕРЅРµРЅРѕ")
    users = database.get_all_users()
    return {"status": "ok", "data": users}

@app.get("/api/budgets/{user_id}")
async def get_budgets(user_id: int, month: str):
    """РћС‚СЂРёРјСѓС” Р±СЋРґР¶РµС‚Рё РєРѕСЂРёСЃС‚СѓРІР°С‡Р° РЅР° РІРєР°Р·Р°РЅРёР№ РјС–СЃСЏС†СЊ."""
    budgets = await database.get_user_budgets(user_id, month)
    # РўР°РєРѕР¶ Р·Р°РїСѓСЃРєР°С”РјРѕ РґС–Р°РіРЅРѕСЃС‚РёС‡РЅСѓ С„СѓРЅРєС†С–СЋ
    debug_data = await database.debug_budgets(user_id, month)
    return {"status": "ok", "data": budgets, "_debug": debug_data}

@app.post("/api/admin/budgets")
async def set_budget_admin(admin_id: int, data: BudgetData):
    if not database.is_admin(admin_id):
        raise HTTPException(status_code=403, detail="Р”РѕСЃС‚СѓРї Р·Р°Р±РѕСЂРѕРЅРµРЅРѕ")
        
    budget_id = await database.set_user_budget(
        data.target_user_id, 
        data.category_id, 
        data.month, 
        data.amount
    )
    return {"status": "ok", "budget_id": budget_id}


# ==========================================
# 2. Р—РђР’РђРќРўРђР–Р•РќРќРЇ Р§Р•РљР†Р’
# ==========================================

@app.post("/api/upload/{user_id}")
async def upload_receipt(user_id: int, file: UploadFile = File(...)):
    dt = datetime.now()
    year = dt.strftime("%Y")
    month = dt.strftime("%m")
    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H-%M-%S")
    
    u_info = database.users_cache.get(str(user_id), {'name': 'User', 'center': 'Р¦РµРЅС‚СЂ'})
    center_name = u_info.get('center', 'Р¦РµРЅС‚СЂ')
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
# 3. Р•РќР”РџРћР‡РќРўР Р’Р РўР РђРў (CRUD)
# ==========================================

@app.get("/api/expenses/{user_id}")
async def get_expenses(user_id: int):
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
async def create_expense(user_id: int, data: ExpenseData):
    # РћС‡С–РєСѓС”С‚СЊСЃСЏ СЂСЏРґРѕРє: [date, user_id, amount, expense_name, category, file_path]
    row_data = [data.date, str(user_id), data.amount, data.expense_name, data.category, data.file_path]
    expense_id = await database.add_expense(row_data)
    
    # Р’РёРґР°Р»РµРЅРЅСЏ РїРѕРІС–РґРѕРјР»РµРЅРЅСЏ РІ Р±РѕС‚С– РїС–СЃР»СЏ С€РІРёРґРєРѕРіРѕ Р·Р±РµСЂРµР¶РµРЅРЅСЏ С‡РµСЂРЅРµС‚РєРё
    if data.msg_id:
        try:
            from bot_setup import bot, dp
            from aiogram.fsm.context import FSMContext
            from aiogram.fsm.storage.base import StorageKey
            await bot.delete_message(chat_id=user_id, message_id=data.msg_id)
            await bot.send_message(chat_id=user_id, text=f"вњ… Р’РёС‚СЂР°С‚Сѓ В«{data.expense_name}В» РЅР° {data.amount} РіСЂРЅ СѓСЃРїС–С€РЅРѕ Р·Р±РµСЂРµР¶РµРЅРѕ!")
            state = FSMContext(storage=dp.storage, key=StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id))
            await state.clear()
        except Exception as e:
            logging.error(f"Error updating bot message: {e}")

    return {"status": "ok", "expense_id": expense_id}

@app.put("/api/expenses/{user_id}/{expense_id}")
async def edit_expense(user_id: int, expense_id: str, data: ExpenseData):
    row_data = [data.date, str(user_id), data.amount, data.expense_name, data.category, data.file_path]
    success = await database.update_expense(expense_id, user_id, row_data)
    if not success:
        raise HTTPException(status_code=404, detail="Р—Р°РїРёСЃ РЅРµ Р·РЅР°Р№РґРµРЅРѕ Р°Р±Рѕ РЅРµРјР°С” РґРѕСЃС‚СѓРїСѓ")
    return {"status": "ok"}

@app.delete("/api/expenses/{user_id}/{expense_id}")
async def remove_expense(user_id: int, expense_id: str):
    success = await database.delete_expense(expense_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Р—Р°РїРёСЃ РЅРµ Р·РЅР°Р№РґРµРЅРѕ Р°Р±Рѕ РЅРµРјР°С” РґРѕСЃС‚СѓРїСѓ")
    return {"status": "ok"}
