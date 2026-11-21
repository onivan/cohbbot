"""Перевірка автентичності даних Telegram Web App."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def telegram_webapp_user_id(init_data: str, bot_token: str,
                            max_age_seconds: int = 86400,
                            now: int = None) -> int | None:
    """Повертає Telegram user ID лише для коректних і свіжих initData.

    Формат і підпис відповідають алгоритму перевірки Telegram Web Apps.
    """
    if not init_data or not bot_token:
        return None

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        params = dict(pairs)
        if len(params) != len(pairs):
            return None
        received_hash = params.pop("hash", "")
        auth_date = int(params.get("auth_date", ""))
        user = json.loads(params.get("user", "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    if not received_hash or not isinstance(user, dict):
        return None

    timestamp = int(time.time()) if now is None else int(now)
    age = timestamp - auth_date
    if age < -60 or age > max_age_seconds:
        return None

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(params.items())
    )
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
    ).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    user_id = user.get("id")
    if isinstance(user_id, bool) or not isinstance(user_id, (int, str)):
        return None
    try:
        user_id = int(user_id)
    except ValueError:
        return None
    return user_id if user_id > 0 else None
