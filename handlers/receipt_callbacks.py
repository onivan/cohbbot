import os
import asyncio
from datetime import datetime
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext

from database import users_cache, add_expense, get_category_id_by_name, build_category_formula
from handlers.states import ReceiptState
# Імпортуємо render_summary з receipts, оскільки вони тісно пов'язані
# (в майбутньому це можна винести в окремий сервіс)
from handlers.receipts import render_summary

router = Router()

@router.callback_query(F.data.startswith("selcat_"), ReceiptState.waiting_for_category_selection)
async def process_category_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """Вибір категорії за допомогою інлайн-кнопок"""
    idx = int(callback_query.data.split("_")[1])
    data = await state.get_data()
    valid_categories = data.get('valid_categories', [])
    
    if idx < len(valid_categories):
        selected_category = valid_categories[idx]
        await state.update_data(category=selected_category)
        
    data_fsm = await state.get_data()
    await render_summary(callback_query.message, data_fsm, state)
    await callback_query.answer()

@router.callback_query(F.data.in_(["receipt_save", "receipt_cancel"]), ReceiptState.waiting_for_confirmation)
async def process_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Остаточне збереження в Google Таблицю або скасування запису"""
    data = await state.get_data()
    user_id = callback_query.from_user.id
    
    if callback_query.data == "receipt_save":
        user_id_str = str(user_id)
        user_info = users_cache.get(user_id_str, {})
        user_name = user_info.get('name', 'Невідомо')
        
        receipt_date = data.get('receipt_date')
        if not receipt_date or not str(receipt_date).strip():
            receipt_date = datetime.now().strftime("%Y-%m-%d")
        else:
            receipt_date = str(receipt_date).strip().split(' ')[0]

        category_name = data.get('category', 'Інше')
        
        row_data = [
            receipt_date, 
            user_id, 
            data['amount'], 
            data['expense_name'], 
            category_name,
            data.get('file_path', '')
        ]
        
        await add_expense(row_data)
        await callback_query.message.edit_text(
            f"✅ Збережено: **{data['amount']} грн** за {receipt_date} у «{category_name}».", 
            parse_mode="Markdown"
        )
    
    elif callback_query.data == "receipt_cancel":
        # Видаляємо локальний файл у разі скасування, використовуючи збережений локальний шлях
        local_path = data.get('local_fs_path', '')
        
        if local_path:
            # Асинхронні перевірка та видалення файлу
            file_exists = await asyncio.to_thread(os.path.exists, local_path)
            if file_exists:
                await asyncio.to_thread(os.remove, local_path)
                
        await callback_query.message.edit_text("🚫 Скасовано.")
        
    await state.clear()
    await callback_query.answer()
