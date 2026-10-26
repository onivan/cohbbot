import asyncio
from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

# Внутрішні модулі проєкту
from database import users_cache, add_user, load_users
from handlers.states import UserState
from handlers.keyboards import webapp_kb

router = Router()

@router.message(Command("start"))
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

@router.message(UserState.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    """Крок 1 реєстрації: отримання імені"""
    if not message.text:
        await message.answer("Будь ласка, надішліть своє ім'я текстом.")
        return
        
    await state.update_data(name=message.text.strip())
    await message.answer("Тепер введіть назву вашого центру (наприклад: ЦН Київ):")
    await state.set_state(UserState.waiting_for_center)

@router.message(UserState.waiting_for_center)
async def process_center(message: types.Message, state: FSMContext):
    """Крок 2 реєстрації: отримання центру та збереження в базу"""
    if not message.text:
        await message.answer("Будь ласка, надішліть назву центру текстом.")
        return
        
    center = message.text.strip()
    data = await state.get_data()
    name = data['name']
    user_id = message.from_user.id
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    await add_user(user_id, name, center, date_str)
    await state.clear()
    await message.answer(
        f"Приємно познайомитись, {name} з «{center}»! Тепер ви можете надсилати фото чеків або додавати витрати вручну натиснувши кнопку «Витрати».", 
        reply_markup=webapp_kb
    )
