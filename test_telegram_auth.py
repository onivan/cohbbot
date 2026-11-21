"""Unit tests for Telegram Web App initData validation."""
import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

from telegram_auth import telegram_webapp_user_id


BOT_TOKEN = "123456:unit-test-token"
NOW = 1_800_000_000


def make_init_data(user_id=987654321, auth_date=NOW):
    params = {
        "auth_date": str(auth_date),
        "query_id": "AAE-unit-test",
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(params.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)


class TelegramWebAppAuthTests(unittest.TestCase):
    def test_accepts_valid_signed_user(self):
        self.assertEqual(
            telegram_webapp_user_id(make_init_data(), BOT_TOKEN, now=NOW),
            987654321,
        )

    def test_rejects_tampered_user(self):
        data = make_init_data().replace("987654321", "123456789")
        self.assertIsNone(telegram_webapp_user_id(data, BOT_TOKEN, now=NOW))

    def test_rejects_expired_data(self):
        data = make_init_data(auth_date=NOW - 86401)
        self.assertIsNone(telegram_webapp_user_id(data, BOT_TOKEN, now=NOW))

    def test_rejects_data_from_far_future(self):
        data = make_init_data(auth_date=NOW + 61)
        self.assertIsNone(telegram_webapp_user_id(data, BOT_TOKEN, now=NOW))

    def test_rejects_duplicate_parameters(self):
        data = make_init_data() + "&auth_date=" + str(NOW)
        self.assertIsNone(telegram_webapp_user_id(data, BOT_TOKEN, now=NOW))

    def test_rejects_missing_token_or_malformed_data(self):
        self.assertIsNone(telegram_webapp_user_id(make_init_data(), "", now=NOW))
        self.assertIsNone(telegram_webapp_user_id("not-init-data", BOT_TOKEN, now=NOW))


if __name__ == "__main__":
    unittest.main()
