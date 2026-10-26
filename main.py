import asyncio
import logging
import uvicorn

import database
from webapp import app as fastapi_app
from bot_setup import bot, dp
from handlers.registration import router as registration_router
from handlers.settings import router as settings_router
from handlers.instructions import router as instructions_router
from handlers.receipts import router as receipts_router
from handlers.receipt_callbacks import router as callbacks_router
from webapp import app        # Імпортуємо наш FastAPI додаток
from config import PORT

# Підключаємо всі роутери
dp.include_router(registration_router)
dp.include_router(settings_router)
dp.include_router(instructions_router)
dp.include_router(receipts_router)
dp.include_router(callbacks_router)

async def start_uvicorn():
    # Налаштовуємо Uvicorn програмно
    config = uvicorn.Config(app=app, host="127.0.0.1", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
    
async def start_bot():
    logging.info("Bot is starting...")
    await dp.start_polling(bot)

async def main():
    # 1. Завантажуємо користувачів із Sheets
    await asyncio.to_thread(database.load_users)
    
    # Запускаємо одночасно FastAPI (uvicorn) та Telegram Polling
    await asyncio.gather(
        start_uvicorn(),
        start_bot()
    )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
