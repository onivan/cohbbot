import json
import logging
from google import genai
from google.genai.types import GenerateContentConfig, AutomaticFunctionCallingConfig
from config import GEMINI_API_KEY

# Ініціалізація асинхронного клієнта Google Gemini API
client = genai.Client(api_key=GEMINI_API_KEY)

async def parse_receipt_image(image, valid_categories: list) -> dict:
    """
    Аналізує зображення чека за допомогою штучного інтелекту Google Gemini.

    Параметри:
        image: Об'єкт PIL.Image зображення чека.
        valid_categories: Список допустимих категорій користувача (рядки або словники).

    Повертає:
        dict: Словник з розпізнаними даними:
              - "amount" (float)
              - "expense_name" (str)
              - "category" (str)
              - "receipt_date" (str YYYY-MM-DD або "")
              - "receipt_time" (str HH:MM / HH:MM:SS або "")
    """
    # 1. Нормалізація категорій: конвертуємо можливі словники {'id', 'name'} у чисті назви
    cat_names = []
    for c in valid_categories:
        if isinstance(c, dict):
            cat_names.append(c.get('name', ''))
        else:
            cat_names.append(str(c))
            
    # Об'єднуємо назви в єдиний рядок для промпту
    categories_str = ", ".join([name for name in cat_names if name])
    
    # 2. Формування промпту для ШІ
    prompt = f"""
    Ти - фінансовий асистент. Проаналізуй цей чек в Україні. 
    Знайди підсумкову суму, визнач категорію витрат, сформулюй коротку назву витрати, 
    а також знайди дату та час покупки на чеку.
    
    ВАЖЛИВО: 
    1. Ти повинен обрати категорію ТІЛЬКИ з цього переліку: {categories_str}.
       Якщо ЖОДНА з цих категорій не підходить за змістом, поверни порожній рядок "" для поля category.
    2. Якщо дату на чеку знайти неможливо або вона нечітка, поверни порожній рядок "" для поля receipt_date.
    3. Якщо час на чеку знайти неможливо або він нечіткий, поверни порожній рядок "" для поля receipt_time.
    
    Поверни JSON з ключами: 
    "amount" (число типу float), 
    "expense_name" (рядок), 
    "category" (рядок), 
    "receipt_date" (рядок у форматі "YYYY-MM-DD" або порожній рядок ""),
    "receipt_time" (рядок у форматі "HH:MM" або "HH:MM:SS" або порожній рядок "").
    """
    
    # 3. Виклик актуальної моделі gemini-3.8-flash
    response = await client.aio.models.generate_content(
        model='gemini-3.8-flash',
        contents=[prompt, image],
        config=GenerateContentConfig(
            response_mime_type="application/json",
            automatic_function_calling=AutomaticFunctionCallingConfig(disable=True)
        )
    )
    
    model_used = response.model_version
    # Витягуємо токени
    usage = response.usage_metadata
    input_tokens = usage.prompt_token_count or 0
    output_tokens = usage.candidates_token_count or 0
    
    # 4. Очищення відповіді від можливого форматування Markdown (```json ... ```)
    raw_text = response.text.strip()
    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw_text = "\n".join(lines).strip()
    
    result = json.loads(raw_text)
    # Додаємо метадані до результату
    result['_usage'] = {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens
    }
    
    return result

