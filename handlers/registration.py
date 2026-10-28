import asyncio
from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

# Внутрішні модулі проєкту
from database import users_cache, add_user, load_users, get_all_users
from handlers.states import UserState
from handlers.keyboards import webapp_kb
from bot_setup import bot

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Обробка команди /start: вітання або запуск реєстрації"""
    user_id_str = str(message.from_user.id)
    
    if user_id_str not in users_cache:
        await load_users()
        
    if user_id_str in users_cache:
        user_info = users_cache[user_id_str]
        user_name = user_info.get('name', 'Користувач')
        user_status = user_info.get('status', 'pending')
        
        if user_status == 'pending':
            await message.answer(
                f"Привіт, {user_name}! Вашу заявку зареєстровано. Очікуйте, поки адміністратор призначить вас до Центру Надії."
            )
        elif user_status == 'blocked':
            await message.answer(
                f"Привіт, {user_name}. Ваш обліковий запис заблоковано. Зверніться до адміністратора."
            )
        else:
            await message.answer(
                f"Привіт, {user_name}! Надішліть чек або перегляньте статистику.\n(Переглянути інструкцію — /help)",
                reply_markup=webapp_kb
            )
    else:
        await message.answer("Привіт! Я бот для обліку витрат. Введіть своє ім'я:")
        await state.set_state(UserState.waiting_for_name)

@router.message(UserState.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    """Крок 1 реєстрації: отримання імені"""
    if not message.text:
        await message.answer("Будь ласка, надішліть своє ім'я текстом.")
        return
        
    await state.update_data(name=message.text.strip())
    await message.answer("Тепер введіть ваше місто проживання (наприклад: Київ):")
    await state.set_state(UserState.waiting_for_city)

@router.message(UserState.waiting_for_city)
async def process_city(message: types.Message, state: FSMContext):
    """Крок 2 реєстрації: отримання міста та збереження в базу"""
    if not message.text:
        await message.answer("Будь ласка, надішліть назву міста текстом.")
        return
        
    city = message.text.strip()
    data = await state.get_data()
    name = data['name']
    user_id = message.from_user.id
    
    await add_user(user_id=user_id, name=name, city=city, status='pending')
    await state.clear()
    await message.answer(
        f"Приємно познайомитись, {name}! Вашу заявку зареєстровано. Очікуйте, поки адміністратор призначить вас до Центру Надії."
    )
    
    # Сповіщення адмінів
    admins = [u for u in get_all_users() if str(users_cache.get(str(u['user_id']), {}).get('role', '')).strip().lower() == 'admin']
    for admin in admins:
        try:
            await bot.send_message(
                admin['user_id'],
                f"🔔 **Нова реєстрація**\n\nКористувач: {name}\nМісто: {city}\nTelegram ID: `{user_id}`\n\nПризначте користувачу Центр Надії у веб-панелі адміна.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
