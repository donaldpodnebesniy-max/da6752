"""
Тонкая обёртка над Telegram Bot API поверх requests — без aiogram/PTB,
чтобы backend оставался простым синхронным Flask-приложением.
"""
import logging
import requests

import config

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _url(method):
    return API_BASE.format(token=config.TOKEN, method=method)


def _call(method, data=None, files=None):
    if not config.TOKEN:
        logger.error("BOT_TOKEN не задан — вызов %s пропущен", method)
        return {"ok": False, "description": "BOT_TOKEN не задан"}
    try:
        resp = requests.post(_url(method), data=data or {}, files=files, timeout=15)
        result = resp.json()
        if not result.get("ok"):
            logger.warning("Telegram API %s error: %s", method, result)
        return result
    except requests.RequestException:
        logger.exception("Ошибка запроса к Telegram API (%s)", method)
        return {"ok": False, "description": "network error"}


def send_message(chat_id, text, parse_mode="HTML"):
    return _call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode})


# Соответствие file_type -> метод API для локальных файлов и старых file_id
_SEND_METHOD = {
    "document": ("sendDocument", "document"),
    "photo": ("sendPhoto", "photo"),
    "video": ("sendVideo", "video"),
    "audio": ("sendAudio", "audio"),
    "voice": ("sendVoice", "voice"),
    "animation": ("sendAnimation", "animation"),
}


def send_delivery_file(chat_id, file_ref, file_type, caption=None):
    """
    file_ref может быть:
      - путём к локальному файлу (загруженному через веб-админку) — начинается с UPLOAD_DIR,
      - либо "старым" Telegram file_id (для БД, унаследованной от bota на aiogram/PTB).
    """
    import os
    method, field = _SEND_METHOD.get(file_type, ("sendDocument", "document"))
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption
        data["parse_mode"] = "HTML"

    if file_ref and os.path.isfile(file_ref):
        with open(file_ref, "rb") as f:
            files = {field: f}
            return _call(method, data=data, files=files)
    else:
        # трактуем как готовый Telegram file_id
        data[field] = file_ref
        return _call(method, data=data)


def create_invoice_link(title, description, payload, amount_stars):
    """Создаёт ссылку на оплату Telegram Stars (валюта XTR, provider_token не требуется)."""
    data = {
        "title": title[:32] or "Покупка",
        "description": (description or title)[:255],
        "payload": payload,
        "provider_token": "",
        "currency": "XTR",
        "prices": _json([{"label": title[:32] or "Товар", "amount": int(amount_stars)}]),
    }
    result = _call("createInvoiceLink", data)
    if result.get("ok"):
        return result["result"]
    return None


def _json(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)


def answer_pre_checkout_query(query_id, ok=True, error_message=None):
    data = {"pre_checkout_query_id": query_id, "ok": ok}
    if error_message:
        data["error_message"] = error_message
    return _call("answerPreCheckoutQuery", data)


def set_webhook(url, secret_token=None):
    data = {
        "url": url,
        "allowed_updates": _json(["message", "pre_checkout_query", "callback_query"]),
    }
    if secret_token:
        data["secret_token"] = secret_token
    return _call("setWebhook", data)


def delete_webhook():
    return _call("deleteWebhook", {})


def set_chat_menu_button(webapp_url, text="Открыть магазин"):
    data = {
        "menu_button": _json({"type": "web_app", "text": text, "web_app": {"url": webapp_url}}),
    }
    return _call("setChatMenuButton", data)


def set_my_commands():
    data = {"commands": _json([{"command": "start", "description": "Открыть магазин"}])}
    return _call("setMyCommands", data)


def get_me():
    return _call("getMe", {})
