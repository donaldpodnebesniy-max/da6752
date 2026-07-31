"""
Проверка Telegram.WebApp.initData по алгоритму из документации Telegram:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import config


class AuthError(Exception):
    pass


def validate_init_data(init_data: str, max_age_seconds: int = 86400):
    """Возвращает dict пользователя {id, username, first_name, ...} или бросает AuthError."""
    if not init_data:
        raise AuthError("initData отсутствует")

    pairs = dict(parse_qsl(init_data, strict_parsing=False))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise AuthError("В initData нет hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))

    secret_key = hmac.new(b"WebAppData", config.TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise AuthError("Неверная подпись initData")

    auth_date = int(pairs.get("auth_date", "0"))
    if max_age_seconds and time.time() - auth_date > max_age_seconds:
        raise AuthError("initData устарела")

    user_raw = pairs.get("user")
    if not user_raw:
        raise AuthError("В initData нет пользователя")

    return json.loads(user_raw)


def get_request_user(flask_request):
    """Достаёт и проверяет пользователя из заголовка X-Telegram-Init-Data.
    В dev-режиме (ALLOW_DEV_NOVALIDATE=1) — подставляет тестового пользователя,
    ТОЛЬКО если реальной initData нет (позволяет тестировать вне Telegram)."""
    init_data = flask_request.headers.get("X-Telegram-Init-Data", "")

    if init_data:
        user = validate_init_data(init_data)
        return {
            "id": user["id"],
            "username": user.get("username") or "без username",
        }

    if config.ALLOW_DEV_NOVALIDATE:
        return {"id": config.DEV_USER_ID, "username": config.DEV_USERNAME}

    raise AuthError("Отсутствует initData (открой Mini App через Telegram)")
