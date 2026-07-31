import json
import logging
import os
import uuid
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, abort

import config
import database as db
import telegram_api as tg
from auth import get_request_user, AuthError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static", static_url_path="")

@app.before_request
def debug_request():
    print(f"[REQUEST] {request.method} {request.path}")
    if request.args:
        print("  args:", dict(request.args))
    if request.is_json:
        print("  json:", request.get_json(silent=True))


db.init_db()


# ============================================
# ХЕЛПЕРЫ
# ============================================
def is_admin(user_id):
    return user_id in config.ADMIN_IDS or db.is_db_admin(user_id)


def is_owner(user_id):
    return user_id in config.ADMIN_IDS


def product_to_json(row):
    # id, name, rub_price, star_price, description, category_id,
    # delivery_text, delivery_file_id, delivery_file_type
    return {
        "id": row[0],
        "name": row[1],
        "star_price": row[3],
        "description": row[4],
        "category_id": row[5],
        "auto_delivery": bool(row[6] or row[7]),
    }


def category_to_json(row):
    return {"id": row[0], "name": row[1]}


def review_to_json(row):
    # id, user_id, username, request_id, product_id, rating, text, created_at
    return {"username": f"@{row[2]}" if row[2] and row[2] != "без username" else "Аноним",
            "rating": row[5], "text": row[6]}


def request_to_json(row):
    # id, user_id, username, type, product_id, payment_method, amount, status, created_at, product_name
    return {
        "id": row[0],
        "type": row[3],
        "username": f"@{row[2]}" if row[2] and row[2] != "без username" else f"id{row[1]}",
        "productName": row[9] if row[3] == "purchase" else None,
        "amount": row[6],
        "status": row[7],
    }


def current_user_or_401():
    try:
        return get_request_user(request)
    except AuthError as e:
        abort(401, description=str(e))


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = current_user_or_401()
        if not is_admin(u["id"]):
            abort(403, description="Требуются права администратора")
        request.tg_user = u
        return fn(*args, **kwargs)
    return wrapper


def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = current_user_or_401()
        if db.is_banned(u["id"]):
            abort(403, description="Вы заблокированы")
        request.tg_user = u
        return fn(*args, **kwargs)
    return wrapper


@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(403)
@app.errorhandler(404)
def handle_error(e):
    return jsonify({"ok": False, "error": getattr(e, "description", str(e))}), e.code


# ============================================
# СТАТИКА (сам Mini App)
# ============================================
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/uploads/delivery/<path:filename>")
@admin_required
def delivery_file(filename):
    # доступ к загруженным файлам авто-выдачи — только админам (превью в панели)
    return send_from_directory(config.UPLOAD_DIR, filename)


# ============================================
# BOOTSTRAP (главный экран)
# ============================================
@app.route("/api/bootstrap")
@auth_required
def bootstrap():
    u = request.tg_user
    db.create_user(u["id"], u["username"])

    categories = [category_to_json(c) for c in db.get_categories()]
    products = [product_to_json(p) for p in db.get_products()]
    cart_rows = db.get_cart_items(u["id"])
    cart = {str(r[1]): r[2] for r in cart_rows}  # product_id -> qty
    balances = db.get_balances(u["id"])
    reviews = [review_to_json(r) for r in db.get_reviews(limit=100)]
    my_requests = [request_to_json(r) for r in db.get_requests_with_names(500) if r[1] == u["id"]]

    return jsonify({
        "ok": True,
        "settings": {
            "shop_name": db.get_setting("shop_name") or config.DEFAULT_SHOP_NAME,
            "support_username": db.get_setting("support_username") or config.DEFAULT_SUPPORT_USERNAME,
        },
        "user": {"id": u["id"], "username": u["username"], "balance_star": balances[1]},
        "isAdmin": is_admin(u["id"]),
        "categories": categories,
        "products": products,
        "cart": cart,
        "reviews": reviews,
        "purchasesConfirmed": len(db.get_confirmed_purchases_by_user(u["id"])),
        "myRequests": my_requests,
        "reviewablePurchases": [
            {"request_id": r[0], "product_id": r[4], "productName": r[-1]}
            for r in db.get_reviewable_purchases(u["id"])
        ],
    })


# ============================================
# КОРЗИНА
# ============================================
@app.route("/api/cart/update", methods=["POST"])
@auth_required
def cart_update():
    u = request.tg_user
    data = request.get_json(force=True)
    product_id = int(data["product_id"])
    delta = int(data["delta"])
    if delta > 0:
        db.add_to_cart(u["id"], product_id, delta)
    else:
        db.update_cart_quantity(u["id"], product_id, delta)
    cart_rows = db.get_cart_items(u["id"])
    return jsonify({"ok": True, "cart": {str(r[1]): r[2] for r in cart_rows}})


# ============================================
# ПОКУПКА / ОФОРМЛЕНИЕ КОРЗИНЫ
# ============================================
def _deliver_product(chat_id, product_row):
    """product_row = результат db.get_product(): id,name,rub,star,desc,cat,dtext,dfile,dtype"""
    name, dtext, dfile, dtype = product_row[1], product_row[6], product_row[7], product_row[8]
    if dfile:
        caption = dtext or f"✅ Ваш товар «{name}»"
        tg.send_delivery_file(chat_id, dfile, dtype or "document", caption=caption)
    elif dtext:
        tg.send_message(chat_id, f"✅ Ваш товар «{name}»:\n\n{dtext}")
    else:
        tg.send_message(chat_id, f"✅ Оплата за «{name}» подтверждена! Продавец свяжется с вами для выдачи.")


def _cart_items_or_400(u):
    cart_rows = db.get_cart_items(u["id"])
    if not cart_rows:
        abort(400, description="Корзина пуста")
    return cart_rows


@app.route("/api/checkout/balance", methods=["POST"])
@auth_required
def checkout_balance():
    """Оплата товара(ов) из корзины или единичной покупки с внутреннего баланса ⭐."""
    u = request.tg_user
    data = request.get_json(force=True)
    mode = data.get("mode", "cart")  # 'cart' | 'single'

    if mode == "single":
        product_id = int(data["product_id"])
        qty = max(1, int(data.get("qty", 1)))
        product = db.get_product(product_id)
        if not product:
            abort(404, description="Товар не найден")
        items = [(product_id, product[1], qty, product[3])]
    else:
        cart_rows = _cart_items_or_400(u)
        items = [(r[1], r[3], r[2], r[5]) for r in cart_rows]  # product_id, name, qty, star_price

    total = sum(qty * price for _, _, qty, price in items)
    balances = db.get_balances(u["id"])
    if balances[1] < total:
        abort(400, description="Недостаточно средств на балансе")

    db.update_balance_star(u["id"], -total)
    req_id = db.create_cart_request(u["id"], u["username"], "star", total, items) \
        if mode != "single" else db.create_request(u["id"], u["username"], "purchase", items[0][0], "star", total)
    db.set_request_status(req_id, "confirmed")

    for product_id, _, _, _ in items:
        product = db.get_product(product_id)
        if product:
            _deliver_product(u["id"], product)

    if mode != "single":
        db.clear_cart(u["id"])

    return jsonify({"ok": True, "balance_star": db.get_balances(u["id"])[1]})


@app.route("/api/checkout/stars", methods=["POST"])
@auth_required
def checkout_stars():
    """Создаёт ссылку на оплату Telegram Stars за корзину или один товар."""
    u = request.tg_user
    data = request.get_json(force=True)
    mode = data.get("mode", "cart")

    if mode == "single":
        product_id = int(data["product_id"])
        qty = max(1, int(data.get("qty", 1)))
        product = db.get_product(product_id)
        if not product:
            abort(404, description="Товар не найден")
        total = product[3] * qty
        title = f"{product[1]} × {qty}" if qty > 1 else product[1]
        req_id = db.create_request(u["id"], u["username"], "purchase", product_id, "star", total)
    else:
        cart_rows = _cart_items_or_400(u)
        items = [(r[1], r[3], r[2], r[5]) for r in cart_rows]
        total = sum(qty * price for _, _, qty, price in items)
        title = f"Корзина ({sum(q for _, _, q, _ in items)} шт.)"
        req_id = db.create_cart_request(u["id"], u["username"], "star", total, items)

    payload = json.dumps({"kind": "purchase", "request_id": req_id})
    link = tg.create_invoice_link(title, title, payload, total)
    if not link:
        abort(400, description="Не удалось создать счёт на оплату. Проверьте BOT_TOKEN.")
    return jsonify({"ok": True, "invoice_link": link, "request_id": req_id})


@app.route("/api/topup/stars", methods=["POST"])
@auth_required
def topup_stars():
    u = request.tg_user
    data = request.get_json(force=True)
    amount = int(data.get("amount", 0))
    if amount <= 0:
        abort(400, description="Некорректная сумма")

    req_id = db.create_request(u["id"], u["username"], "topup", None, "star", amount)
    payload = json.dumps({"kind": "topup", "request_id": req_id})
    link = tg.create_invoice_link("Пополнение баланса", f"Пополнение на {amount} ⭐", payload, amount)
    if not link:
        abort(400, description="Не удалось создать счёт на оплату. Проверьте BOT_TOKEN.")
    return jsonify({"ok": True, "invoice_link": link, "request_id": req_id})


@app.route("/api/requests/<int:req_id>")
@auth_required
def request_status(req_id):
    row = db.get_request(req_id)
    if not row or row[1] != request.tg_user["id"]:
        abort(404)
    return jsonify({"ok": True, "status": row[7]})


# ============================================
# ОТЗЫВЫ
# ============================================
@app.route("/api/reviews", methods=["POST"])
@auth_required
def add_review():
    u = request.tg_user
    data = request.get_json(force=True)
    rating = max(1, min(5, int(data.get("rating", 5))))
    text = (data.get("text") or "").strip()[:500]
    request_id = data.get("request_id")
    product_id = data.get("product_id")
    db.add_review(u["id"], u["username"], request_id, product_id, rating, text)
    return jsonify({"ok": True})


# ============================================
# АДМИН: bootstrap
# ============================================
@app.route("/api/admin/bootstrap")
@admin_required
def admin_bootstrap():
    reqs = [request_to_json(r) for r in db.get_requests_with_names(300)]
    categories = [category_to_json(c) for c in db.get_categories()]
    products_full = []
    for p in db.get_products():
        j = product_to_json(p)
        products_full.append(j)
    users = []
    for uid, uname, bal, banned in db.get_all_users_full():
        users.append({"id": uid, "username": uname or "без username", "balance_star": bal, "banned": bool(banned)})
    admins = [{"id": aid, "username": "владелец", "isOwner": True} for aid in config.ADMIN_IDS]
    for uid, uname, added_by, created_at in db.get_admins():
        admins.append({"id": uid, "username": uname or f"id{uid}", "isOwner": False})

    return jsonify({
        "ok": True,
        "requests": reqs,
        "categories": categories,
        "products": products_full,
        "settings": {
            "shop_name": db.get_setting("shop_name") or config.DEFAULT_SHOP_NAME,
            "support_username": db.get_setting("support_username") or config.DEFAULT_SUPPORT_USERNAME,
        },
        "admins": admins,
        "users": users,
    })


# ---- заявки ----
@app.route("/api/admin/requests/<int:req_id>/approve", methods=["POST"])
@admin_required
def admin_request_approve(req_id):
    row = db.get_request(req_id)
    if not row:
        abort(404)
    user_id, req_type, product_id, amount = row[1], row[3], row[4], row[6]
    db.set_request_status(req_id, "confirmed")
    if req_type == "topup":
        db.update_balance_star(user_id, amount)
        tg.send_message(user_id, f"✅ Баланс пополнен на {amount} ⭐")
    elif req_type == "purchase" and product_id:
        product = db.get_product(product_id)
        if product:
            _deliver_product(user_id, product)
    elif req_type == "cart":
        for item in db.get_request_items(req_id):
            # id, request_id, product_id, product_name, quantity, unit_price
            product = db.get_product(item[2]) if item[2] else None
            if product:
                _deliver_product(user_id, product)
    return jsonify({"ok": True})


@app.route("/api/admin/requests/<int:req_id>/reject", methods=["POST"])
@admin_required
def admin_request_reject(req_id):
    row = db.get_request(req_id)
    if not row:
        abort(404)
    db.set_request_status(req_id, "cancelled")
    tg.send_message(row[1], "❌ Ваша заявка отклонена администратором.")
    return jsonify({"ok": True})


# ---- категории ----
@app.route("/api/admin/categories", methods=["POST"])
@admin_required
def admin_category_add():
    name = (request.get_json(force=True).get("name") or "").strip()
    if not name:
        abort(400, description="Введите название")
    db.add_category(name)
    return jsonify({"ok": True})


@app.route("/api/admin/categories/<int:cat_id>", methods=["PUT"])
@admin_required
def admin_category_rename(cat_id):
    name = (request.get_json(force=True).get("name") or "").strip()
    if not name:
        abort(400, description="Введите название")
    db.rename_category(cat_id, name)
    return jsonify({"ok": True})


@app.route("/api/admin/categories/<int:cat_id>", methods=["DELETE"])
@admin_required
def admin_category_delete(cat_id):
    db.delete_category(cat_id)
    return jsonify({"ok": True})


# ---- товары ----
@app.route("/api/admin/products", methods=["POST"])
@admin_required
def admin_product_add():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    star_price = int(data.get("star_price") or 0)
    if not name or star_price <= 0:
        abort(400, description="Заполните название и цену")
    new_id = db.add_product(
        name, 0, star_price, (data.get("description") or "").strip(),
        data.get("category_id"),
    )
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/admin/products/<int:prod_id>", methods=["PUT"])
@admin_required
def admin_product_edit(prod_id):
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    star_price = int(data.get("star_price") or 0)
    if not name or star_price <= 0:
        abort(400, description="Заполните название и цену")
    db.update_product(prod_id, name, star_price, (data.get("description") or "").strip(), data.get("category_id"))
    return jsonify({"ok": True})


@app.route("/api/admin/products/<int:prod_id>", methods=["DELETE"])
@admin_required
def admin_product_delete(prod_id):
    db.delete_product(prod_id)
    return jsonify({"ok": True})


@app.route("/api/admin/products/<int:prod_id>/delivery", methods=["POST"])
@admin_required
def admin_product_delivery(prod_id):
    """multipart/form-data: text (опц.), file (опц.) — задаёт авто-выдачу товара."""
    text = (request.form.get("text") or "").strip() or None
    file_path, file_type = None, None

    f = request.files.get("file")
    if f and f.filename:
        ext = os.path.splitext(f.filename)[1]
        fname = f"{uuid.uuid4().hex}{ext}"
        dest = os.path.join(config.UPLOAD_DIR, fname)
        f.save(dest)
        file_path = dest
        mime = (f.mimetype or "").split("/")[0]
        file_type = {"image": "photo", "video": "video", "audio": "audio"}.get(mime, "document")

    if not text and not file_path:
        db.update_product_delivery(prod_id, None, None, None)
    else:
        db.update_product_delivery(prod_id, text, file_path, file_type)
    return jsonify({"ok": True})


@app.route("/api/admin/products/<int:prod_id>/delivery", methods=["DELETE"])
@admin_required
def admin_product_delivery_clear(prod_id):
    db.update_product_delivery(prod_id, None, None, None)
    return jsonify({"ok": True})


# ---- настройки ----
@app.route("/api/admin/settings", methods=["POST"])
@admin_required
def admin_settings_update():
    data = request.get_json(force=True)
    key = data.get("key")
    value = (data.get("value") or "").strip()
    if key not in ("shop_name", "support_username"):
        abort(400, description="Неизвестная настройка")
    if not value:
        abort(400, description="Значение не может быть пустым")
    db.set_setting(key, value)
    return jsonify({"ok": True})


# ---- админы ----
@app.route("/api/admin/admins", methods=["POST"])
@admin_required
def admin_add_admin():
    if not is_owner(request.tg_user["id"]):
        abort(403, description="Добавлять админов может только владелец")
    data = request.get_json(force=True)
    try:
        target_id = int(data.get("user_id"))
    except (TypeError, ValueError):
        abort(400, description="Некорректный user_id")
    username = db.get_username(target_id) or f"id{target_id}"
    db.add_admin(target_id, username, request.tg_user["id"])
    return jsonify({"ok": True})


@app.route("/api/admin/admins/<int:admin_id>", methods=["DELETE"])
@admin_required
def admin_remove_admin(admin_id):
    if not is_owner(request.tg_user["id"]):
        abort(403, description="Удалять админов может только владелец")
    if admin_id in config.ADMIN_IDS:
        abort(400, description="Нельзя удалить владельца")
    db.remove_admin(admin_id)
    return jsonify({"ok": True})


# ---- пользователи ----
@app.route("/api/admin/users/<int:user_id>/ban", methods=["POST"])
@admin_required
def admin_user_ban(user_id):
    if is_admin(user_id):
        abort(400, description="Нельзя заблокировать администратора")
    db.ban_user(user_id)
    return jsonify({"ok": True})


@app.route("/api/admin/users/<int:user_id>/unban", methods=["POST"])
@admin_required
def admin_user_unban(user_id):
    db.unban_user(user_id)
    return jsonify({"ok": True})


@app.route("/api/admin/users/<int:user_id>/balance", methods=["POST"])
@admin_required
def admin_user_balance(user_id):
    delta = int(request.get_json(force=True).get("delta", 0))
    db.update_balance_star(user_id, delta)
    balances = db.get_balances(user_id)
    if balances[1] < 0:
        db.reset_balance_star(user_id)
    tg.send_message(user_id, f"ℹ️ Администратор изменил ваш баланс на {delta:+d} ⭐")
    return jsonify({"ok": True, "balance_star": db.get_balances(user_id)[1]})


@app.route("/api/admin/users/<int:user_id>/reset-balance", methods=["POST"])
@admin_required
def admin_user_reset_balance(user_id):
    db.reset_balance_star(user_id)
    return jsonify({"ok": True})


# ---- рассылка ----
@app.route("/api/admin/broadcast", methods=["POST"])
@admin_required
def admin_broadcast():
    text = (request.get_json(force=True).get("text") or "").strip()
    if not text:
        abort(400, description="Введите текст рассылки")
    sent, failed = 0, 0
    for user_id in db.get_all_user_ids():
        if db.is_banned(user_id):
            failed += 1
            continue
        result = tg.send_message(user_id, text)
        if result.get("ok"):
            sent += 1
        else:
            failed += 1
    return jsonify({"ok": True, "sent": sent, "failed": failed})


# ============================================
# TELEGRAM WEBHOOK (оплата Stars и т.п.)
# ============================================
@app.route("/api/telegram/webhook", methods=["POST"])
def telegram_webhook():
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if config.WEBHOOK_SECRET and secret != config.WEBHOOK_SECRET:
        abort(403)

    update = request.get_json(silent=True) or {}

    if "pre_checkout_query" in update:
        pcq = update["pre_checkout_query"]
        tg.answer_pre_checkout_query(pcq["id"], ok=True)
        return jsonify({"ok": True})

    message = update.get("message")
    if message and "successful_payment" in message:
        sp = message["successful_payment"]
        chat_id = message["chat"]["id"]
        try:
            payload = json.loads(sp.get("invoice_payload", "{}"))
        except json.JSONDecodeError:
            payload = {}

        req_id = payload.get("request_id")
        kind = payload.get("kind")
        if req_id:
            row = db.get_request(req_id)
            if row and row[7] == "pending":
                db.set_request_status(req_id, "confirmed")
                if kind == "topup":
                    db.update_balance_star(chat_id, row[6])
                    tg.send_message(chat_id, f"✅ Баланс пополнен на {row[6]} ⭐")
                elif row[3] == "purchase" and row[4]:
                    product = db.get_product(row[4])
                    if product:
                        _deliver_product(chat_id, product)
                elif row[3] == "cart":
                    for item in db.get_request_items(req_id):
                        product = db.get_product(item[2]) if item[2] else None
                        if product:
                            _deliver_product(chat_id, product)
                    db.clear_cart(chat_id)
        return jsonify({"ok": True})

    if message and message.get("text") == "/start":
        chat_id = message["chat"]["id"]
        user = message.get("from", {})
        db.create_user(chat_id, user.get("username") or "без username")
        shop_name = db.get_setting("shop_name") or config.DEFAULT_SHOP_NAME
        tg.send_message(chat_id, f"✨ Добро пожаловать в {shop_name}!\n\nНажмите на кнопку меню слева от поля ввода, чтобы открыть магазин.")

    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
