import asyncio
import logging
import uvicorn

import database
from webapp import app as fastapi_app
from handlers import dp, bot
from webapp import app        # Імпортуємо наш FastAPI додаток

async def start_uvicorn():
    # Налаштовуємо Uvicorn програмно
    config = uvicorn.Config(app=app, host="127.0.0.1", port=8000, log_level="info")
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
