import os
import random
from dotenv import load_dotenv

# Завантажуємо .env файл з папки проєкту
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# OpenRouter (розпізнавання чеків через OpenAI-сумісний API)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
WEBAPP_URL = os.getenv("WEBAPP_URL")
PORT = int(os.getenv("PORT", 8000))
DEBUG_DIAGNOSTICS = os.getenv("DEBUG_DIAGNOSTICS", "False").lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY", "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=32))) # Ключ для підпису куків

# MySQL Database Settings
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "expense_tracker")
