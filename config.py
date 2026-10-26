import os
from dotenv import load_dotenv

# Завантажуємо .env файл з папки проєкту
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
WEBAPP_URL = os.getenv("WEBAPP_URL")
PORT = int(os.getenv("PORT", 8000))
DEBUG_DIAGNOSTICS = os.getenv("DEBUG_DIAGNOSTICS", "False").lower() == "true"
