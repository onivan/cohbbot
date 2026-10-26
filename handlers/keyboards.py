from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
# from config import WEBAPP_URL # Uncomment if you want to restore Web App button

# Головне меню з кнопками відкриття Web App та інструкції
webapp_kb = ReplyKeyboardMarkup(
    keyboard=[
        #[KeyboardButton(text="📊 Мої витрати", web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton(text="📖 Інструкція")]
    ],
    resize_keyboard=True
)
