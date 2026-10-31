import asyncio
import base64
import io
import json
import logging

import aiohttp
from PIL import Image

from config import OPENROUTER_BASE_URL, WEBAPP_URL

OPENROUTER_URL = f"{OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"


class AIServiceError(Exception):
    """Помилка під час звернення до AI-провайдера (OpenRouter)."""

    def __init__(self, message: str, status: int = None, is_credit_error: bool = False):
        super().__init__(message)
        self.message = message
        self.status = status
        self.is_credit_error = is_credit_error


def _is_credit_error(status, text: str) -> bool:
    """Визначає, чи помилка пов'язана з вичерпанням коштів/квоти або недійсним ключем."""
    if status in (401, 402, 403):
        return True
    t = (text or "").lower()
    markers = (
        "insufficient credit",
        "credits are depleted",
        "credit balance",
        "payment required",
        "resource_exhausted",
        "quota exceeded",
        "exceeded your current quota",
        "billing",
        "no credits",
        "not enough credits",
    )
    return any(m in t for m in markers)


MAX_IMAGE_SIDE = 1568  # більші зображення не дають приросту якості, лише витрачають токени


def _image_to_data_url(image) -> str:
    """PIL.Image -> data URL (base64 JPEG) у форматі, який очікує OpenRouter (image_url)."""
    img = image
    # JPEG не підтримує альфа-канал та палітри -> конвертуємо у RGB
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # Зменшуємо завеликі фото (менше токенів при тій самій якості розпізнавання)
    if max(img.size) > MAX_IMAGE_SIDE:
        resample = getattr(Image, "Resampling", Image).LANCZOS
        img = img.copy()
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), resample)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _build_prompt(valid_categories) -> str:
    """Формує промпт для розпізнавання чека з урахуванням доступних категорій."""
    cat_names = []
    for c in valid_categories:
        if isinstance(c, dict):
            cat_names.append(c.get("name", ""))
        else:
            cat_names.append(str(c))

    categories_str = ", ".join([name for name in cat_names if name])

    return f"""
    Ти - фінансовий асистент. Проаналізуй це зображення (Україна).

    СПОЧАТКУ визнач тип документа:
    - Чи це фіскальний чек (чек, виданий РРО/ПРРО: є фіскальний номер, сума, перелік товарів)?
    - Якщо це НЕ фіскальний чек (наприклад: папірець про грошовий переказ, квитанція про оплату,
      скріншот банківського переказу, рукописна записка, інший документ) — постав "is_receipt": false,
      у полі "document_type" вкажи, що це насправді, і НЕ намагайся вгадати суму/категорію.
    - Якщо це справжній фіскальний чек — постав "is_receipt": true.

    ЯКЩО ЦЕ ФІСКАЛЬНИЙ ЧЕК:
    Знайди підсумкову суму, визнач категорію витрат, сформулюй коротку назву витрати,
    а також знайди дату та час покупки на чеку.

    ВАЖЛИВО:
    1. Ти повинен обрати категорію ТІЛЬКИ з цього переліку: {categories_str}.
       Якщо ЖОДНА з цих категорій не підходить за змістом, поверни порожній рядок "" для поля category.
    2. Якщо дату на чеку знайти неможливо або вона нечітка, поверни порожній рядок "" для поля receipt_date.
    3. Якщо час на чеку знайти неможливо або він нечіткий, поверни порожній рядок "" для поля receipt_time.

    Поверни ЛИШЕ валідний JSON (без пояснень та без markdown) з ключами:
    "is_receipt" (boolean),
    "document_type" (рядок: короткий опис типу документа, напр. "фіскальний чек", "переказ", "квитанція", "скріншот"),
    "amount" (число типу float, 0 якщо це не чек),
    "expense_name" (рядок),
    "category" (рядок),
    "receipt_date" (рядок у форматі "YYYY-MM-DD" або порожній рядок ""),
    "receipt_time" (рядок у форматі "HH:MM" або "HH:MM:SS" або порожній рядок "").
    """


def _parse_json_response(raw_text: str) -> dict:
    """Парсить JSON-відповідь моделі, стійко до markdown та зайвого тексту навколо."""
    text = (raw_text or "").strip()

    # Прибираємо обгортку ```json ... ```
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # На випадок, якщо модель додала текст навколо JSON
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


async def parse_receipt_image(image, valid_categories: list, model_config: dict) -> dict:
    """
    Аналізує зображення чека через OpenRouter (OpenAI-сумісний API).

    Параметри:
        image: Об'єкт PIL.Image зображення чека.
        valid_categories: Список допустимих категорій користувача (рядки або словники).
        model_config: Словник {'name', 'model_id', 'api_key'} обраної AI-моделі.

    Повертає:
        dict з розпізнаними даними + службове поле "_usage"
        (input_tokens, output_tokens, model_id).

    Підіймає AIServiceError у разі помилки провайдера.
    """
    model_config = model_config or {}
    model_id = (model_config.get("model_id") or "").strip()
    api_key = (model_config.get("api_key") or "").strip()

    if not model_id or not api_key:
        raise AIServiceError(
            "AI-модель не налаштована: відсутній ID моделі або API-ключ OpenRouter. "
            "Додайте модель у панелі адміністратора (розділ «ШІ-моделі»).",
            is_credit_error=True,
        )

    prompt = _build_prompt(valid_categories)
    data_url = await asyncio.to_thread(_image_to_data_url, image)

    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # OpenRouter рекомендує ці заголовки для статистики застосунку в кабінеті
        "HTTP-Referer": WEBAPP_URL or "https://localhost",
        "X-Title": "Expense Tracker CoHBot",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload) as resp:
                status = resp.status
                raw_body = await resp.text()
    except Exception as e:
        raise AIServiceError(f"Не вдалося з'єднатися з OpenRouter: {e}") from e

    if status != 200:
        message = raw_body
        try:
            err = json.loads(raw_body)
            message = (err.get("error") or {}).get("message") or raw_body
        except Exception:
            pass
        logging.error(f"OpenRouter повернув помилку {status}: {message}")
        raise AIServiceError(
            f"OpenRouter {status}: {message}",
            status=status,
            is_credit_error=_is_credit_error(status, raw_body),
        )

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        raise AIServiceError("OpenRouter повернув невалідний JSON.")

    choices = body.get("choices") or []
    if not choices:
        raise AIServiceError("OpenRouter повернув порожню відповідь (немає choices).")

    content = (choices[0].get("message") or {}).get("content") or ""
    try:
        result = _parse_json_response(content)
    except Exception:
        logging.error(f"Не вдалося розпарсити JSON від модель: {content[:500]}")
        raise AIServiceError("Не вдалося розпарсити JSON-відповідь AI.")

    usage = body.get("usage") or {}
    result["_usage"] = {
        "input_tokens": usage.get("prompt_tokens", 0) or 0,
        "output_tokens": usage.get("completion_tokens", 0) or 0,
        "model_id": model_id,
    }

    return result
