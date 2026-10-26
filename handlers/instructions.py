import os
import asyncio
import logging
from aiogram import Router, types, F
from aiogram.filters import Command

router = Router()

def load_instruction_md(file_path: str = "instruction.md") -> str:
    """Зчитує текст інструкції у форматі Markdown з файлу на диску"""
    if not os.path.exists(file_path):
        return "⚠️ Файл інструкції (`instruction.md`) не знайдено."
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logging.error(f"Помилка зчитування {file_path}: {e}")
        return "❌ Не вдалося завантажити інструкцію."

@router.message(Command("help", "instruction", "guide"))
@router.message(F.text.in_(["📖 Інструкція", "❓ Допомога", "Інструкція"]))
async def cmd_instruction(message: types.Message):
    """
    Обробник виклику інструкції з файлу .md:
    Спрацьовує на команди /help, /instruction, /guide
    та на натискання кнопки «📖 Інструкція».
    """
    instruction_text = await asyncio.to_thread(load_instruction_md, "instruction.md")
    await message.answer(instruction_text, parse_mode="Markdown")
