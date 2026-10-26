from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from database import update_user_center
from handlers.states import SettingsState

router = Router()

@router.message(Command("settings"))
async def cmd_settings(message: types.Message, state: FSMContext):
    """Запит на зміну центру"""
    await message.answer("Введіть нову назву центру:")
    await state.set_state(SettingsState.waiting_for_new_center)

@router.message(SettingsState.waiting_for_new_center)
async def process_new_center(message: types.Message, state: FSMContext):
    """Збереження оновленої назви центру"""
    if not message.text:
        await message.answer("Будь ласка, надішліть назву центру текстом.")
        return
        
    new_center = message.text.strip()
    await update_user_center(message.from_user.id, new_center)
    await state.clear()
    await message.answer(f"✅ Назву центру змінено на «{new_center}».")
