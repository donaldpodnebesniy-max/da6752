import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Токен бота (получить у @BotFather). Обязателен — без него не работают
# ни платежи Stars, ни доставка товаров, ни авторизация Mini App.
TOKEN = os.getenv("BOT_TOKEN", "8989047643:AAFcrHULu0I56Pie9LmVpzzHYPVn1LYVG98")

# ID владельцев (их нельзя удалить из админ-панели). Через запятую в .env.
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "7319791603").split(",") if x.strip()]

# Публичный HTTPS-адрес, на котором будет открываться Mini App
# (например https://shop.example.com). Обязателен для запуска бота:
# используется и как web_app.url в кнопке меню, и как base для вебхука.
WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")

# Файл базы данных — тот же формат, что и у исходного бота (shop.db).
DB_FILE = os.path.join(BASE_DIR, "shop.db")

# Папка для файлов, которые админ загружает для авто-выдачи товаров
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads", "delivery")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Значения по умолчанию (меняются в админ-панели -> Настройки)
DEFAULT_SHOP_NAME = "Магазин"
DEFAULT_PAYMENT_USERNAME = "@"
DEFAULT_SUPPORT_USERNAME = "@"
DEFAULT_CARD_BANK = "СберБанк"
DEFAULT_CARD_NUMBER = "0000 0000 0000 0000"
DEFAULT_CARD_HOLDER = "Иван И."

# ТОЛЬКО для локальной разработки без Telegram (открытие index.html в
# обычном браузере): пропускает проверку initData и подставляет тестового
# пользователя. На проде ОБЯЗАТЕЛЬНО должно быть выключено (0/не задано).
ALLOW_DEV_NOVALIDATE = os.getenv("ALLOW_DEV_NOVALIDATE", "0") == "1"
DEV_USER_ID = int(os.getenv("DEV_USER_ID", "111111111"))
DEV_USERNAME = os.getenv("DEV_USERNAME", "dev_user")

# Секрет для проверки, что вебхук действительно шлёт Telegram
# (используется как X-Telegram-Bot-Api-Secret-Token)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change-me-webhook-secret")
