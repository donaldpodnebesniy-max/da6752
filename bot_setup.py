"""
Запускается один раз (и после каждого изменения WEBAPP_URL / домена),
чтобы:
  1) сказать Telegram, куда слать обновления (вебхук) — платежи Stars,
  2) поставить кнопку меню бота, которая открывает Mini App.

Использование:
    python bot_setup.py
"""
import config
import telegram_api as tg


def main():
    if not config.TOKEN:
        print("❌ BOT_TOKEN не задан в .env")
        return
    if not config.WEBAPP_URL:
        print("❌ WEBAPP_URL не задан в .env (нужен публичный https-адрес)")
        return

    me = tg.get_me()
    if not me.get("ok"):
        print("❌ Не удалось подключиться к Telegram API:", me)
        return
    print(f"✅ Бот: @{me['result']['username']}")

    webhook_url = config.WEBAPP_URL.rstrip("/") + "/api/telegram/webhook"
    res = tg.set_webhook(webhook_url, secret_token=config.WEBHOOK_SECRET)
    print("Webhook:", "✅ установлен" if res.get("ok") else f"❌ {res}")

    res = tg.set_chat_menu_button(config.WEBAPP_URL, text="Открыть магазин")
    print("Menu button:", "✅ установлена" if res.get("ok") else f"❌ {res}")

    res = tg.set_my_commands()
    print("Commands:", "✅ установлены" if res.get("ok") else f"❌ {res}")


if __name__ == "__main__":
    main()
