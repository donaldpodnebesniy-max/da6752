import sqlite3
from config import (
    DB_FILE, DEFAULT_SHOP_NAME, DEFAULT_PAYMENT_USERNAME, DEFAULT_SUPPORT_USERNAME,
    DEFAULT_CARD_BANK, DEFAULT_CARD_NUMBER, DEFAULT_CARD_HOLDER,
)


def _conn():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ============================================
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ
# ============================================
def init_db():
    conn = _conn()
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            rub_price INTEGER NOT NULL,
            star_price INTEGER NOT NULL,
            description TEXT,
            category_id INTEGER,
            delivery_text TEXT,        -- текст, который бот выдаёт автоматически после оплаты
            delivery_file_id TEXT,     -- file_id файла для авто-выдачи (см. delivery_file_type)
            delivery_file_type TEXT,   -- 'document' | 'photo' | 'video' | 'audio' | 'voice' | 'animation'
            FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE SET NULL
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance_rub INTEGER DEFAULT 0,
            balance_star INTEGER DEFAULT 0,
            greeted INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0
        )
    ''')

    # Единая таблица заявок: и покупки, и пополнения баланса
    cur.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            type TEXT NOT NULL,             -- 'purchase' | 'topup'
            product_id INTEGER,             -- заполнено только для purchase
            payment_method TEXT NOT NULL,   -- 'rub' | 'star'
            amount INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',  -- 'pending' | 'confirmed' | 'cancelled'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            proof_file_id TEXT              -- file_id скриншота оплаты (для payment_method='rub')
        )
    ''')

    # Отзывы о магазине (привязаны к подтверждённой покупке)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            request_id INTEGER,
            product_id INTEGER,
            rating INTEGER NOT NULL,
            text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (request_id) REFERENCES requests (id) ON DELETE SET NULL,
            FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE SET NULL
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # Дополнительные админы, добавленные через админ-панель (в дополнение
    # к "постоянным" ADMIN_IDS из config.py, которых нельзя удалить из бота).
    cur.execute('''
        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            added_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Корзина пользователя: один товар — одна строка (с количеством).
    cur.execute('''
        CREATE TABLE IF NOT EXISTS cart_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, product_id),
            FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
        )
    ''')

    # Снимок товаров, из которых состояла заявка на оформление корзины
    # (requests.type = 'cart'). Хранится отдельно от cart_items, чтобы
    # заявка не менялась, даже если пользователь после оформления снова
    # наполнит корзину или товар изменится/удалится.
    cur.execute('''
        CREATE TABLE IF NOT EXISTS request_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            product_id INTEGER,
            product_name TEXT,
            quantity INTEGER NOT NULL,
            unit_price INTEGER NOT NULL,
            FOREIGN KEY (request_id) REFERENCES requests (id) ON DELETE CASCADE
        )
    ''')

    defaults = [
        ("shop_name", DEFAULT_SHOP_NAME),
        ("payment_username", DEFAULT_PAYMENT_USERNAME),
        ("support_username", DEFAULT_SUPPORT_USERNAME),
        ("card_bank", DEFAULT_CARD_BANK),
        ("card_number", DEFAULT_CARD_NUMBER),
        ("card_holder", DEFAULT_CARD_HOLDER),
    ]
    for key, value in defaults:
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    conn.commit()
    conn.close()

    _self_heal_schema()


def _table_columns(cur, table):
    cur.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _self_heal_schema():
    """
    Если рядом лежит shop.db от старой версии бота (например, скопирован
    вручную, без запуска migrate_old_db.py), таблицы users/products могут
    не содержать новых колонок. CREATE TABLE IF NOT EXISTS их не добавляет,
    поэтому здесь мы дозаполняем схему, чтобы бот не падал молча.
    """
    conn = _conn()
    cur = conn.cursor()

    user_cols = _table_columns(cur, "users")
    if "balance_rub" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN balance_rub INTEGER DEFAULT 0")
        if "balance" in user_cols:
            cur.execute("UPDATE users SET balance_rub = balance")
    if "balance_star" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN balance_star INTEGER DEFAULT 0")
    if "greeted" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN greeted INTEGER DEFAULT 0")
    if "banned" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")

    product_cols = _table_columns(cur, "products")
    if "category_id" not in product_cols:
        cur.execute("ALTER TABLE products ADD COLUMN category_id INTEGER")
    if "delivery_text" not in product_cols:
        cur.execute("ALTER TABLE products ADD COLUMN delivery_text TEXT")
    if "delivery_file_id" not in product_cols:
        cur.execute("ALTER TABLE products ADD COLUMN delivery_file_id TEXT")
    if "delivery_file_type" not in product_cols:
        cur.execute("ALTER TABLE products ADD COLUMN delivery_file_type TEXT")

    request_cols = _table_columns(cur, "requests")
    if "proof_file_id" not in request_cols:
        cur.execute("ALTER TABLE requests ADD COLUMN proof_file_id TEXT")

    conn.commit()
    conn.close()


# ============================================
# НАСТРОЙКИ
# ============================================
def get_setting(key):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    result = cur.fetchone()
    conn.close()
    return result[0] if result else None


def set_setting(key, value):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


# ============================================
# ПОЛЬЗОВАТЕЛИ
# ============================================
def create_user(user_id, username):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    cur.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
    conn.commit()
    conn.close()


def is_greeted(user_id):
    """Было ли пользователю уже отправлено 1-е приветственное сообщение (которое не удаляется)."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT greeted FROM users WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return bool(result and result[0])


def mark_greeted(user_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET greeted = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def reset_greeted(user_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET greeted = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def reset_balance_rub(user_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance_rub = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def reset_balance_star(user_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance_star = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def reset_balance_all(user_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance_rub = 0, balance_star = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def ban_user(user_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET banned = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def unban_user(user_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET banned = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def is_banned(user_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT banned FROM users WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return bool(result and result[0])


def get_banned_users():
    """Список (user_id, username) забаненных пользователей."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username FROM users WHERE banned = 1")
    result = cur.fetchall()
    conn.close()
    return result


def get_all_user_ids():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    result = [row[0] for row in cur.fetchall()]
    conn.close()
    return result


def get_user_id_by_username(username):
    """Ищет пользователя, который уже писал боту, по username (без @, регистр не важен)."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)", (username,))
    result = cur.fetchone()
    conn.close()
    return result[0] if result else None


def get_username(user_id):
    """Возвращает сохранённый username пользователя (без @), если он писал боту."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    if not result or not result[0] or result[0] == "без username":
        return None
    return result[0]


def get_balances(user_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT balance_rub, balance_star FROM users WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return result if result else (0, 0)


def update_balance_rub(user_id, amount):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance_rub = balance_rub + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()


def update_balance_star(user_id, amount):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance_star = balance_star + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()


# ============================================
# КАТЕГОРИИ
# ============================================
def add_category(name):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO categories (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()


def get_categories():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM categories ORDER BY name")
    result = cur.fetchall()
    conn.close()
    return result


def get_category(category_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM categories WHERE id = ?", (category_id,))
    result = cur.fetchone()
    conn.close()
    return result


def rename_category(category_id, new_name):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE categories SET name = ? WHERE id = ?", (new_name, category_id))
    conn.commit()
    conn.close()


def delete_category(category_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE products SET category_id = NULL WHERE category_id = ?", (category_id,))
    cur.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    conn.commit()
    conn.close()


# ============================================
# ТОВАРЫ
# ============================================
def add_product(name, rub_price, star_price, description="", category_id=None,
                 delivery_text=None, delivery_file_id=None, delivery_file_type=None):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO products
           (name, rub_price, star_price, description, category_id,
            delivery_text, delivery_file_id, delivery_file_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (name, rub_price, star_price, description, category_id,
         delivery_text, delivery_file_id, delivery_file_type)
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def update_product(product_id, name, star_price, description, category_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE products SET name = ?, star_price = ?, description = ?, category_id = ? WHERE id = ?",
        (name, star_price, description, category_id, product_id)
    )
    conn.commit()
    conn.close()


def update_product_delivery(product_id, delivery_text=None, delivery_file_id=None, delivery_file_type=None):
    """Задаёт (или сбрасывает, если все аргументы None) содержимое авто-выдачи для товара."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE products SET delivery_text = ?, delivery_file_id = ?, delivery_file_type = ? WHERE id = ?",
        (delivery_text, delivery_file_id, delivery_file_type, product_id)
    )
    conn.commit()
    conn.close()


def count_products_with_delivery():
    conn = _conn()
    cur = conn.cursor()
    cur.execute('''
        SELECT COUNT(*) FROM products
        WHERE (delivery_text IS NOT NULL AND delivery_text != '') OR delivery_file_id IS NOT NULL
    ''')
    result = cur.fetchone()
    conn.close()
    return result[0] if result else 0


def get_products(category_id=None):
    conn = _conn()
    cur = conn.cursor()
    if category_id is None:
        cur.execute("SELECT * FROM products")
    else:
        cur.execute("SELECT * FROM products WHERE category_id = ?", (category_id,))
    result = cur.fetchall()
    conn.close()
    return result


def get_product(product_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    result = cur.fetchone()
    conn.close()
    return result


def delete_product(product_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()


# ============================================
# КОРЗИНА
# ============================================
def add_to_cart(user_id, product_id, qty=1):
    """Добавляет товар в корзину. Если товар уже там — увеличивает количество."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO cart_items (user_id, product_id, quantity)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, product_id) DO UPDATE SET quantity = quantity + excluded.quantity
    ''', (user_id, product_id, qty))
    conn.commit()
    conn.close()


def get_cart_items(user_id):
    """Возвращает строки: (cart_id, product_id, quantity, name, rub_price, star_price,
    delivery_text, delivery_file_id, delivery_file_type)."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute('''
        SELECT c.id, c.product_id, c.quantity, p.name, p.rub_price, p.star_price,
               p.delivery_text, p.delivery_file_id, p.delivery_file_type
        FROM cart_items c
        JOIN products p ON p.id = c.product_id
        WHERE c.user_id = ?
        ORDER BY c.added_at
    ''', (user_id,))
    result = cur.fetchall()
    conn.close()
    return result


def get_cart_count(user_id):
    """Суммарное количество единиц товара в корзине (для счётчика в меню)."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(quantity), 0) FROM cart_items WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return result[0] if result else 0


def update_cart_quantity(user_id, product_id, delta):
    """Изменяет количество товара в корзине на delta (может быть отрицательным).
    Если количество опускается до 0 или ниже — товар удаляется из корзины."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT quantity FROM cart_items WHERE user_id = ? AND product_id = ?", (user_id, product_id))
    row = cur.fetchone()
    if row:
        new_qty = row[0] + delta
        if new_qty <= 0:
            cur.execute("DELETE FROM cart_items WHERE user_id = ? AND product_id = ?", (user_id, product_id))
        else:
            cur.execute("UPDATE cart_items SET quantity = ? WHERE user_id = ? AND product_id = ?", (new_qty, user_id, product_id))
        conn.commit()
    conn.close()


def remove_cart_item(user_id, product_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM cart_items WHERE user_id = ? AND product_id = ?", (user_id, product_id))
    conn.commit()
    conn.close()


def clear_cart(user_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# ============================================
# ЗАЯВКИ (покупки и пополнения)
# ============================================
def create_request(user_id, username, req_type, product_id, payment_method, amount, proof_file_id=None):
    conn = _conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO requests (user_id, username, type, product_id, payment_method, amount, status, proof_file_id)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
    ''', (user_id, username, req_type, product_id, payment_method, amount, proof_file_id))
    req_id = cur.lastrowid
    conn.commit()
    conn.close()
    return req_id


def set_request_proof(request_id, proof_file_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE requests SET proof_file_id = ? WHERE id = ?", (proof_file_id, request_id))
    conn.commit()
    conn.close()


def get_request(request_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
    result = cur.fetchone()
    conn.close()
    return result


def get_pending_requests():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM requests WHERE status = 'pending' ORDER BY created_at DESC")
    result = cur.fetchall()
    conn.close()
    return result


def set_request_status(request_id, status):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE requests SET status = ? WHERE id = ?", (status, request_id))
    conn.commit()
    conn.close()


def create_cart_request(user_id, username, payment_method, amount, items, proof_file_id=None):
    """Оформляет заявку из корзины: одна строка в requests (type='cart', product_id=NULL)
    плюс снимок товаров в request_items.
    items — список кортежей (product_id, product_name, quantity, unit_price).
    Возвращает id созданной заявки."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO requests (user_id, username, type, product_id, payment_method, amount, status, proof_file_id)
        VALUES (?, ?, 'cart', NULL, ?, ?, 'pending', ?)
    ''', (user_id, username, payment_method, amount, proof_file_id))
    request_id = cur.lastrowid
    for product_id, product_name, quantity, unit_price in items:
        cur.execute('''
            INSERT INTO request_items (request_id, product_id, product_name, quantity, unit_price)
            VALUES (?, ?, ?, ?, ?)
        ''', (request_id, product_id, product_name, quantity, unit_price))
    conn.commit()
    conn.close()
    return request_id


def get_request_items(request_id):
    """Возвращает строки: (id, request_id, product_id, product_name, quantity, unit_price)."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM request_items WHERE request_id = ?", (request_id,))
    result = cur.fetchall()
    conn.close()
    return result


def get_confirmed_purchases_by_user(user_id):
    """Подтверждённые покупки пользователя (заявки type='purchase', status='confirmed')."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute('''
        SELECT * FROM requests
        WHERE user_id = ? AND type = 'purchase' AND status = 'confirmed'
        ORDER BY created_at DESC
    ''', (user_id,))
    result = cur.fetchall()
    conn.close()
    return result


# ============================================
# ОТЗЫВЫ
# ============================================
def get_reviewable_purchases(user_id):
    """Подтверждённые покупки пользователя, на которые ещё не оставлен отзыв.
    Каждая строка — это requests.* плюс дополнительное поле с названием товара в конце."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute('''
        SELECT r.*, p.name FROM requests r
        LEFT JOIN products p ON p.id = r.product_id
        LEFT JOIN reviews rv ON rv.request_id = r.id
        WHERE r.user_id = ? AND r.type = 'purchase' AND r.status = 'confirmed' AND rv.id IS NULL
        ORDER BY r.created_at DESC
    ''', (user_id,))
    result = cur.fetchall()
    conn.close()
    return result


def add_review(user_id, username, request_id, product_id, rating, text):
    conn = _conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO reviews (user_id, username, request_id, product_id, rating, text)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, username, request_id, product_id, rating, text))
    review_id = cur.lastrowid
    conn.commit()
    conn.close()
    return review_id


def get_reviews(limit=None):
    conn = _conn()
    cur = conn.cursor()
    if limit:
        cur.execute("SELECT * FROM reviews ORDER BY created_at DESC LIMIT ?", (limit,))
    else:
        cur.execute("SELECT * FROM reviews ORDER BY created_at DESC")
    result = cur.fetchall()
    conn.close()
    return result


def count_reviews():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM reviews")
    result = cur.fetchone()
    conn.close()
    return result[0] if result else 0


def average_rating():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT AVG(rating) FROM reviews")
    result = cur.fetchone()
    conn.close()
    return result[0] if result and result[0] is not None else None


def rating_distribution():
    """Возвращает {1: n, 2: n, 3: n, 4: n, 5: n}."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT rating, COUNT(*) FROM reviews GROUP BY rating")
    rows = cur.fetchall()
    conn.close()
    dist = {i: 0 for i in range(1, 6)}
    for rating, cnt in rows:
        if rating in dist:
            dist[rating] = cnt
    return dist


# ============================================
# СТАТИСТИКА (используется в разделе "О магазине")
# ============================================
def count_users():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    result = cur.fetchone()
    conn.close()
    return result[0] if result else 0


def count_categories():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM categories")
    result = cur.fetchone()
    conn.close()
    return result[0] if result else 0


def count_products():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM products")
    result = cur.fetchone()
    conn.close()
    return result[0] if result else 0


def count_confirmed_purchases():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM requests WHERE type = 'purchase' AND status = 'confirmed'")
    result = cur.fetchone()
    conn.close()
    return result[0] if result else 0


def count_pending_requests():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM requests WHERE status = 'pending'")
    result = cur.fetchone()
    conn.close()
    return result[0] if result else 0


# ============================================
# АДМИНЫ (добавленные через админ-панель)
# ============================================
def add_admin(user_id, username, added_by):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO bot_admins (user_id, username, added_by) VALUES (?, ?, ?)",
        (user_id, username, added_by)
    )
    conn.commit()
    conn.close()


def remove_admin(user_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM bot_admins WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_admins():
    """Список админов, добавленных через панель (не включает ADMIN_IDS из config.py)."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, added_by, created_at FROM bot_admins ORDER BY created_at")
    result = cur.fetchall()
    conn.close()
    return result


def is_db_admin(user_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bot_admins WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return bool(result)


# ============================================
# ДОПОЛНИТЕЛЬНЫЕ ВЫБОРКИ ДЛЯ WEB-АДМИНКИ
# ============================================
def get_all_users_full():
    """(user_id, username, balance_star, banned) для админ-панели."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, balance_star, banned FROM users ORDER BY user_id DESC")
    result = cur.fetchall()
    conn.close()
    return result


def get_requests_with_names(limit=200):
    """Заявки вместе с названием товара (для покупок) — под нужды UI."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute('''
        SELECT r.id, r.user_id, r.username, r.type, r.product_id, r.payment_method,
               r.amount, r.status, r.created_at, p.name
        FROM requests r
        LEFT JOIN products p ON p.id = r.product_id
        ORDER BY r.created_at DESC
        LIMIT ?
    ''', (limit,))
    result = cur.fetchall()
    conn.close()
    return result
