import os
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("MONNEY_TOKEN")
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "monney.db")
ADMIN_ID = 8976178026

if not TOKEN:
    raise SystemExit("BOT_TOKEN или MONNEY_TOKEN не задан.")


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def ensure_column(con, table, column, definition):
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    con = db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            blocked INTEGER DEFAULT 0,
            pin_hash TEXT,
            vault_owner_id INTEGER
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            folder_id INTEGER,
            kind TEXT NOT NULL,
            file_id TEXT,
            text TEXT,
            hidden INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS link_codes (
            code TEXT PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0
        )
    """)

    # Compatibility with all previous MONNEY versions.
    ensure_column(con, "users", "username", "TEXT")
    ensure_column(con, "users", "first_name", "TEXT")
    ensure_column(con, "users", "blocked", "INTEGER DEFAULT 0")
    ensure_column(con, "users", "pin_hash", "TEXT")
    ensure_column(con, "users", "vault_owner_id", "INTEGER")
    ensure_column(con, "files", "folder_id", "INTEGER")
    ensure_column(con, "files", "hidden", "INTEGER DEFAULT 0")
    ensure_column(con, "files", "deleted", "INTEGER DEFAULT 0")

    # Existing users keep their old personal storage as their own vault.
    con.execute("UPDATE users SET vault_owner_id=user_id WHERE vault_owner_id IS NULL")
    con.commit()
    con.close()


def register_user(user):
    con = db()
    row = con.execute("SELECT vault_owner_id FROM users WHERE user_id=?", (user.id,)).fetchone()
    if row:
        owner = row["vault_owner_id"] or user.id
        con.execute("""
            UPDATE users SET username=?, first_name=?, vault_owner_id=? WHERE user_id=?
        """, (user.username, user.first_name, owner, user.id))
    else:
        con.execute("""
            INSERT INTO users(user_id, username, first_name, vault_owner_id)
            VALUES (?, ?, ?, ?)
        """, (user.id, user.username, user.first_name, user.id))
    con.commit()
    con.close()


def owner_id(uid):
    con = db()
    row = con.execute("SELECT vault_owner_id FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    return (row["vault_owner_id"] if row and row["vault_owner_id"] else uid)


def is_blocked(uid):
    con = db()
    row = con.execute("SELECT blocked FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    return bool(row and row["blocked"])


def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()


async def safe_delete(message):
    try:
        await message.delete()
    except Exception:
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


def main_menu(uid):
    rows = [
        [InlineKeyboardButton("➕ Добавить файл", callback_data="add"),
         InlineKeyboardButton("🗂 Галерея", callback_data="gallery")],
        [InlineKeyboardButton("📁 Папки", callback_data="folders"),
         InlineKeyboardButton("📝 Тексты и ссылки", callback_data="texts")],
        [InlineKeyboardButton("🙈 Скрытые файлы", callback_data="hidden"),
         InlineKeyboardButton("🗑 Корзина", callback_data="trash")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
    ]
    if uid == ADMIN_ID:
        rows.append([InlineKeyboardButton("👑 Админ-панель", callback_data="admin")])
    return InlineKeyboardMarkup(rows)


def back_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="home")]])


def file_buttons(rows, prefix="file"):
    buttons = []
    for r in rows:
        icon = {"photo": "🖼", "video": "🎥", "text": "📝", "document": "📄"}.get(r["kind"], "📄")
        title = (r["text"] or "")[:25] if r["kind"] == "text" else f"Файл #{r['id']}"
        buttons.append([InlineKeyboardButton(f"{icon} {title}", callback_data=f"{prefix}:{r['id']}")])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    context.user_data.clear()

    # Support /start link_CODE for future deep-link linking.
    args = context.args
    if args and args[0].startswith("link_"):
        await link_by_code(update, context, args[0][5:])
        return

    await update.message.reply_text(
        "💰 MONNEY\n\n"
        "Твоё личное хранилище в Telegram.\n\n"
        "📸 Фото и видео\n"
        "📄 Документы\n"
        "📝 Тексты и ссылки\n"
        "📁 Папки\n"
        "🙈 Скрытые файлы\n"
        "🗑 Корзина с восстановлением\n"
        "🔗 Можно подключить второй Telegram-аккаунт к тому же хранилищу.\n\n"
        "Выбери действие 👇",
        reply_markup=main_menu(user.id),
    )


async def home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await safe_delete(q.message)
    context.user_data.clear()
    await context.bot.send_message(
        q.message.chat_id,
        "💰 MONNEY\n\nВыбери действие 👇",
        reply_markup=main_menu(q.from_user.id),
    )


async def add_screen(q, context):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    context.user_data["add_mode"] = True
    context.user_data["hidden_mode"] = False
    await context.bot.send_message(
        q.message.chat_id,
        "➕ Добавить файл\n\n"
        "Отправь сюда фото, видео, документ или текст — я сохраню его автоматически.",
        reply_markup=back_menu(),
    )


async def hidden_screen(q, context):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    owner = owner_id(uid)
    con = db()
    rows = con.execute("""
        SELECT * FROM files WHERE user_id=? AND hidden=1 AND deleted=0 ORDER BY id DESC
    """, (owner,)).fetchall()
    con.close()
    buttons = [[InlineKeyboardButton("➕ Добавить скрытый файл", callback_data="hidden_add")]]
    for r in rows:
        icon = {"photo": "🖼", "video": "🎥", "document": "📄", "text": "📝"}.get(r["kind"], "📄")
        buttons.append([InlineKeyboardButton(f"{icon} Файл #{r['id']}", callback_data=f"hiddenfile:{r['id']}")])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    text = f"🙈 Скрытые файлы\n\nВсего: {len(rows)}\n\nВыбери файл или добавь новый."
    await context.bot.send_message(q.message.chat_id, text, reply_markup=InlineKeyboardMarkup(buttons))


async def hidden_add(q, context):
    await q.answer()
    await safe_delete(q.message)
    context.user_data["add_mode"] = True
    context.user_data["hidden_mode"] = True
    await context.bot.send_message(
        q.message.chat_id,
        "🙈 Скрытая загрузка включена.\n\nСледующий отправленный файл будет скрытым.",
        reply_markup=back_menu(),
    )


async def gallery(q, context):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    owner = owner_id(uid)
    con = db()
    rows = con.execute("""
        SELECT * FROM files WHERE user_id=? AND deleted=0 AND hidden=0 ORDER BY id DESC
    """, (owner,)).fetchall()
    con.close()
    if not rows:
        await context.bot.send_message(q.message.chat_id, "🗂 Галерея пока пустая.", reply_markup=back_menu())
        return
    await context.bot.send_message(
        q.message.chat_id,
        f"🗂 Галерея\n\nВсего файлов: {len(rows)}\n\nНажми на файл для просмотра и управления.",
        reply_markup=file_buttons(rows),
    )


async def open_file(q, context, file_id):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    owner = owner_id(uid)
    con = db()
    row = con.execute("SELECT * FROM files WHERE id=? AND user_id=?", (file_id, owner)).fetchone()
    con.close()
    if not row:
        await context.bot.send_message(q.message.chat_id, "❌ Файл не найден.", reply_markup=back_menu())
        return

    if row["kind"] == "photo":
        await context.bot.send_photo(q.message.chat_id, row["file_id"], caption=f"🖼 Файл #{row['id']}")
    elif row["kind"] == "video":
        await context.bot.send_video(q.message.chat_id, row["file_id"], caption=f"🎥 Файл #{row['id']}")
    elif row["kind"] == "document":
        await context.bot.send_document(q.message.chat_id, row["file_id"], caption=f"📄 Файл #{row['id']}")
    else:
        await context.bot.send_message(q.message.chat_id, f"📝 Файл #{row['id']}\n\n{row['text'] or ''}")

    buttons = [[InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{row['id']}")]]
    buttons.append([InlineKeyboardButton("👁 Сделать обычным", callback_data=f"unhide:{row['id']}")]
                    if row["hidden"] else [InlineKeyboardButton("🙈 Скрыть файл", callback_data=f"hide:{row['id']}")])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    await context.bot.send_message(q.message.chat_id, "⚙️ Управление файлом:", reply_markup=InlineKeyboardMarkup(buttons))


async def delete_file(q, context, file_id):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    owner = owner_id(uid)
    con = db()
    cur = con.execute("UPDATE files SET deleted=1 WHERE id=? AND user_id=?", (file_id, owner))
    con.commit()
    con.close()
    text = f"🗑 Файл #{file_id} перемещён в корзину.\n\nЕго можно восстановить." if cur.rowcount else "❌ Файл не найден."
    await context.bot.send_message(q.message.chat_id, text, reply_markup=main_menu(uid))


async def restore_file(q, context, file_id):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    owner = owner_id(uid)
    con = db()
    cur = con.execute("UPDATE files SET deleted=0 WHERE id=? AND user_id=?", (file_id, owner))
    con.commit()
    con.close()
    await context.bot.send_message(q.message.chat_id, "♻️ Файл восстановлен." if cur.rowcount else "❌ Файл не найден.", reply_markup=main_menu(uid))


async def trash(q, context):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    owner = owner_id(uid)
    con = db()
    rows = con.execute("SELECT * FROM files WHERE user_id=? AND deleted=1 ORDER BY id DESC", (owner,)).fetchall()
    con.close()
    if not rows:
        await context.bot.send_message(q.message.chat_id, "🗑 Корзина пустая.", reply_markup=back_menu())
        return
    buttons = [[InlineKeyboardButton(f"♻️ Восстановить #{r['id']}", callback_data=f"restore:{r['id']}")] for r in rows]
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    await context.bot.send_message(q.message.chat_id, f"🗑 Корзина\n\nФайлов: {len(rows)}", reply_markup=InlineKeyboardMarkup(buttons))


async def hide_file(q, context, file_id, hidden):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    owner = owner_id(uid)
    con = db()
    con.execute("UPDATE files SET hidden=? WHERE id=? AND user_id=?", (hidden, file_id, owner))
    con.commit()
    con.close()
    await context.bot.send_message(q.message.chat_id, "🙈 Файл скрыт." if hidden else "👁 Файл снова обычный.", reply_markup=main_menu(uid))


async def texts(q, context):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    owner = owner_id(uid)
    con = db()
    rows = con.execute("SELECT * FROM files WHERE user_id=? AND kind='text' AND deleted=0 AND hidden=0 ORDER BY id DESC", (owner,)).fetchall()
    con.close()
    if not rows:
        await context.bot.send_message(q.message.chat_id, "📝 Тексты и ссылки пока пустые.", reply_markup=back_menu())
        return
    buttons = []
    for r in rows:
        title = (r["text"] or "")[:35].replace("\n", " ")
        buttons.append([InlineKeyboardButton(f"📝 {title}", callback_data=f"file:{r['id']}")])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    await context.bot.send_message(q.message.chat_id, f"📝 Тексты и ссылки\n\nВсего: {len(rows)}", reply_markup=InlineKeyboardMarkup(buttons))


async def folders(q, context):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    owner = owner_id(uid)
    con = db()
    rows = con.execute("SELECT * FROM folders WHERE user_id=? ORDER BY id DESC", (owner,)).fetchall()
    con.close()
    buttons = [[InlineKeyboardButton("➕ Создать папку", callback_data="folder_new")]]
    for r in rows:
        buttons.append([InlineKeyboardButton(f"📁 {r['name']}", callback_data=f"folder:{r['id']}")])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    await context.bot.send_message(q.message.chat_id, "📁 Папки", reply_markup=InlineKeyboardMarkup(buttons))


async def new_folder(q, context):
    await q.answer()
    await safe_delete(q.message)
    context.user_data["waiting_folder"] = True
    await context.bot.send_message(q.message.chat_id, "📁 Напиши название новой папки:", reply_markup=back_menu())


async def open_folder(q, context, folder_id):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    owner = owner_id(uid)
    con = db()
    folder = con.execute("SELECT * FROM folders WHERE id=? AND user_id=?", (folder_id, owner)).fetchone()
    rows = con.execute("SELECT * FROM files WHERE folder_id=? AND user_id=? AND deleted=0 ORDER BY id DESC", (folder_id, owner)).fetchall()
    con.close()
    if not folder:
        await context.bot.send_message(q.message.chat_id, "❌ Папка не найдена.", reply_markup=back_menu())
        return
    await context.bot.send_message(q.message.chat_id, f"📁 {folder['name']}\n\nФайлов: {len(rows)}", reply_markup=file_buttons(rows) if rows else back_menu())


async def settings(q, context):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    con = db()
    row = con.execute("SELECT pin_hash FROM users WHERE user_id=?", (uid,)).fetchone()
    linked = con.execute("SELECT COUNT(*) AS n FROM users WHERE vault_owner_id=? AND user_id<>?", (owner_id(uid), owner_id(uid))).fetchone()["n"]
    con.close()
    pin_status = "🟢 установлен" if row and row["pin_hash"] else "⚪ не установлен"
    buttons = [
        [InlineKeyboardButton("🔐 Установить / изменить PIN", callback_data="pin_set")],
        [InlineKeyboardButton("❌ Удалить PIN", callback_data="pin_remove")],
        [InlineKeyboardButton("🔗 Подключить другой аккаунт", callback_data="link_create")],
        [InlineKeyboardButton("👥 Подключённые аккаунты", callback_data="link_list")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="home")],
    ]
    await context.bot.send_message(q.message.chat_id,
        f"⚙️ Настройки\n\n🔐 PIN: {pin_status}\n👥 Доп. аккаунтов: {linked}\n\n"
        "🔗 Один и тот же MONNEY можно использовать с двух Telegram-аккаунтов.",
        reply_markup=InlineKeyboardMarkup(buttons))


async def pin_start(q, context, action):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    if action == "remove":
        con = db(); con.execute("UPDATE users SET pin_hash=NULL WHERE user_id=?", (uid,)); con.commit(); con.close()
        await context.bot.send_message(q.message.chat_id, "❌ PIN удалён.", reply_markup=main_menu(uid)); return
    context.user_data["pin_action"] = "set"
    await context.bot.send_message(q.message.chat_id, "🔐 Введи PIN-код от 4 до 8 цифр:", reply_markup=back_menu())


async def link_create(q, context):
    uid = q.from_user.id
    await q.answer()
    await safe_delete(q.message)
    code = str(secrets.randbelow(90000000) + 10000000)
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    con = db()
    con.execute("DELETE FROM link_codes WHERE owner_id=? OR expires_at < ?", (owner_id(uid), datetime.now(timezone.utc).isoformat()))
    con.execute("INSERT INTO link_codes(code, owner_id, expires_at) VALUES (?, ?, ?)", (code, owner_id(uid), expires))
    con.commit(); con.close()
    await context.bot.send_message(q.message.chat_id,
        "🔗 Подключение второго аккаунта\n\n"
        f"Код: <code>{code}</code>\n\n"
        "1. Открой MONNEY со второго Telegram-аккаунта.\n"
        "2. Нажми ⚙️ Настройки → «Подключить другой аккаунт».\n"
        "3. Введи этот код.\n\n"
        "Код действует 10 минут.", parse_mode="HTML", reply_markup=back_menu())


async def link_prompt(q, context):
    await q.answer(); await safe_delete(q.message)
    context.user_data["waiting_link_code"] = True
    await context.bot.send_message(q.message.chat_id, "🔗 Введи код подключения второго аккаунта:", reply_markup=back_menu())


async def link_by_code(update, context, code):
    uid = update.effective_user.id
    register_user(update.effective_user)
    if not code.isdigit():
        await update.message.reply_text("❌ Неверный код.", reply_markup=main_menu(uid)); return
    con = db()
    row = con.execute("SELECT * FROM link_codes WHERE code=? AND used=0", (code,)).fetchone()
    if not row:
        con.close(); await update.message.reply_text("❌ Код не найден или уже использован.", reply_markup=main_menu(uid)); return
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        con.execute("DELETE FROM link_codes WHERE code=?", (code,)); con.commit(); con.close()
        await update.message.reply_text("⌛ Код истёк. Создай новый код на основном аккаунте.", reply_markup=main_menu(uid)); return
    owner = row["owner_id"]
    if owner == uid:
        con.close(); await update.message.reply_text("ℹ️ Это уже основной аккаунт.", reply_markup=main_menu(uid)); return
    con.execute("UPDATE users SET vault_owner_id=? WHERE user_id=?", (owner, uid))
    con.execute("UPDATE link_codes SET used=1 WHERE code=?", (code,))
    con.commit(); con.close()
    context.user_data.clear()
    await update.message.reply_text("✅ Аккаунт подключён. Теперь ты видишь то же хранилище MONNEY.", reply_markup=main_menu(uid))


async def link_list(q, context):
    uid = q.from_user.id
    await q.answer(); await safe_delete(q.message)
    owner = owner_id(uid)
    con = db()
    rows = con.execute("SELECT * FROM users WHERE vault_owner_id=? ORDER BY user_id", (owner,)).fetchall()
    con.close()
    buttons = []
    for r in rows:
        if r["user_id"] == owner: continue
        name = r["username"] or r["first_name"] or str(r["user_id"])
        buttons.append([InlineKeyboardButton(f"❌ Отключить {name}", callback_data=f"unlink:{r['user_id']}")])
    if not buttons:
        text = "👥 Подключённых аккаунтов нет."
    else:
        text = "👥 Подключённые аккаунты\n\nНажми на аккаунт, чтобы отключить его."
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    await context.bot.send_message(q.message.chat_id, text, reply_markup=InlineKeyboardMarkup(buttons))


async def unlink(q, context, target):
    uid = q.from_user.id
    await q.answer(); await safe_delete(q.message)
    owner = owner_id(uid)
    if owner != uid:
        await context.bot.send_message(q.message.chat_id, "❌ Отключать аккаунты может только основной аккаунт.", reply_markup=main_menu(uid)); return
    con = db()
    con.execute("UPDATE users SET vault_owner_id=user_id WHERE user_id=? AND vault_owner_id=?", (target, owner))
    con.commit(); con.close()
    await context.bot.send_message(q.message.chat_id, "✅ Аккаунт отключён. Его новые файлы снова будут храниться отдельно.", reply_markup=main_menu(uid))


async def save_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    register_user(user)
    if is_blocked(uid) and uid != ADMIN_ID:
        return

    if context.user_data.get("waiting_link_code") and update.message.text:
        context.user_data.pop("waiting_link_code", None)
        await link_by_code(update, context, update.message.text.strip())
        return

    if context.user_data.get("waiting_folder") and update.message.text:
        name = update.message.text.strip()
        if not name: return
        owner = owner_id(uid)
        con = db(); con.execute("INSERT INTO folders(user_id,name) VALUES (?,?)", (owner,name)); con.commit(); con.close()
        context.user_data.pop("waiting_folder", None)
        await update.message.reply_text(f"📁 Папка «{name}» создана.", reply_markup=main_menu(uid)); return

    if context.user_data.get("pin_action") and update.message.text:
        pin = update.message.text.strip()
        if not pin.isdigit() or not 4 <= len(pin) <= 8:
            await update.message.reply_text("❌ PIN должен содержать от 4 до 8 цифр."); return
        context.user_data.pop("pin_action", None)
        con = db(); con.execute("UPDATE users SET pin_hash=? WHERE user_id=?", (hash_pin(pin),uid)); con.commit(); con.close()
        await update.message.reply_text("✅ PIN сохранён.", reply_markup=main_menu(uid)); return

    if not update.message or not (context.user_data.get("add_mode") or update.message.photo or update.message.video or update.message.document):
        # Plain text is saved only when Add File mode is active.
        if not context.user_data.get("add_mode"):
            return

    if update.message.text and update.message.text.startswith("/"):
        return

    hidden = bool(context.user_data.get("hidden_mode"))
    owner = owner_id(uid)
    kind = file_id = text = None
    if update.message.photo:
        kind, file_id = "photo", update.message.photo[-1].file_id
    elif update.message.video:
        kind, file_id = "video", update.message.video.file_id
    elif update.message.document:
        kind, file_id = "document", update.message.document.file_id
    elif update.message.text:
        text = update.message.text.strip()
        if not text: return
        kind = "text"
    if not kind: return

    con = db()
    cur = con.execute("INSERT INTO files(user_id,kind,file_id,text,hidden) VALUES (?,?,?,?,?)", (owner,kind,file_id,text,int(hidden)))
    item_id = cur.lastrowid
    con.commit(); con.close()
    context.user_data["add_mode"] = False
    context.user_data["hidden_mode"] = False
    await update.message.reply_text(
        f"{'🙈 Скрыто сохранено' if hidden else '✅ Сохранено'} — #{item_id}",
        reply_markup=main_menu(uid))


async def admin(q, context):
    if q.from_user.id != ADMIN_ID:
        await q.answer("Нет доступа.", show_alert=True); return
    await q.answer(); await safe_delete(q.message)
    con = db()
    users = con.execute("SELECT * FROM users ORDER BY user_id DESC").fetchall()
    total = con.execute("SELECT COUNT(*) n FROM files WHERE deleted=0").fetchone()["n"]
    hidden = con.execute("SELECT COUNT(*) n FROM files WHERE hidden=1 AND deleted=0").fetchone()["n"]
    con.close()
    buttons=[]
    for u in users[:50]:
        name=u["username"] or u["first_name"] or str(u["user_id"])
        buttons.append([InlineKeyboardButton(f"{'🚫' if u['blocked'] else '🟢'} {name}", callback_data=f"adminuser:{u['user_id']}")])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    await context.bot.send_message(q.message.chat_id, f"👑 АДМИН-ПАНЕЛЬ\n\n👤 Пользователей: {len(users)}\n📦 Файлов: {total}\n🙈 Скрытых: {hidden}", reply_markup=InlineKeyboardMarkup(buttons))


async def admin_user(q, context, target):
    if q.from_user.id != ADMIN_ID:
        await q.answer("Нет доступа.", show_alert=True); return
    await q.answer(); await safe_delete(q.message)
    con=db(); user=con.execute("SELECT * FROM users WHERE user_id=?",(target,)).fetchone(); files=con.execute("SELECT COUNT(*) n FROM files WHERE user_id=?",(owner_id(target),)).fetchone()["n"]; folders_count=con.execute("SELECT COUNT(*) n FROM folders WHERE user_id=?",(owner_id(target),)).fetchone()["n"]; con.close()
    if not user:
        await context.bot.send_message(q.message.chat_id,"Пользователь не найден.",reply_markup=back_menu()); return
    buttons=[[InlineKeyboardButton("🚫 Заблокировать" if not user["blocked"] else "✅ Разблокировать",callback_data=f"toggleblock:{target}")],[InlineKeyboardButton("📂 Файлы пользователя",callback_data=f"adminfiles:{target}")],[InlineKeyboardButton("📁 Папки пользователя",callback_data=f"adminfolders:{target}")],[InlineKeyboardButton("👑 Админ-панель",callback_data="admin")]]
    await context.bot.send_message(q.message.chat_id,f"👤 Пользователь\n\nID: {target}\nUsername: @{user['username'] or 'нет'}\nФайлов: {files}\nПапок: {folders_count}\nСтатус: {'🚫 заблокирован' if user['blocked'] else '🟢 активен'}",reply_markup=InlineKeyboardMarkup(buttons))


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; data=q.data
    if data=="home": await home(update,context)
    elif data=="add": await add_screen(q,context)
    elif data=="hidden": await hidden_screen(q,context)
    elif data=="hidden_add": await hidden_add(q,context)
    elif data=="gallery": await gallery(q,context)
    elif data.startswith("file:") or data.startswith("hiddenfile:"): await open_file(q,context,int(data.split(":")[1]))
    elif data.startswith("delete:"): await delete_file(q,context,int(data.split(":")[1]))
    elif data.startswith("restore:"): await restore_file(q,context,int(data.split(":")[1]))
    elif data.startswith("hide:"): await hide_file(q,context,int(data.split(":")[1]),1)
    elif data.startswith("unhide:"): await hide_file(q,context,int(data.split(":")[1]),0)
    elif data=="texts": await texts(q,context)
    elif data=="folders": await folders(q,context)
    elif data=="folder_new": await new_folder(q,context)
    elif data.startswith("folder:"): await open_folder(q,context,int(data.split(":")[1]))
    elif data=="trash": await trash(q,context)
    elif data=="settings": await settings(q,context)
    elif data in ("pin_set","pin_remove"): await pin_start(q,context,"set" if data=="pin_set" else "remove")
    elif data=="link_create": await link_create(q,context)
    elif data=="link_prompt": await link_prompt(q,context)
    elif data=="link_list": await link_list(q,context)
    elif data.startswith("unlink:"): await unlink(q,context,int(data.split(":")[1]))
    elif data=="admin": await admin(q,context)
    elif data.startswith("adminuser:"): await admin_user(q,context,int(data.split(":")[1]))
    elif data.startswith("toggleblock:"):
        if q.from_user.id != ADMIN_ID: await q.answer("Нет доступа.",show_alert=True); return
        target=int(data.split(":")[1])
        if target==ADMIN_ID: await q.answer("Себя блокировать нельзя.",show_alert=True); return
        await q.answer(); await safe_delete(q.message)
        con=db(); row=con.execute("SELECT blocked FROM users WHERE user_id=?",(target,)).fetchone(); new=0 if row and row["blocked"] else 1; con.execute("UPDATE users SET blocked=? WHERE user_id=?",(new,target)); con.commit(); con.close()
        await context.bot.send_message(q.message.chat_id,"🚫 Пользователь заблокирован." if new else "✅ Пользователь разблокирован.",reply_markup=main_menu(ADMIN_ID))
    elif data.startswith("adminfiles:"):
        if q.from_user.id != ADMIN_ID: await q.answer("Нет доступа.",show_alert=True); return
        await q.answer(); await safe_delete(q.message); target=int(data.split(":")[1]); owner=owner_id(target)
        con=db(); rows=con.execute("SELECT * FROM files WHERE user_id=? ORDER BY id DESC",(owner,)).fetchall(); con.close()
        await context.bot.send_message(q.message.chat_id,f"📂 Файлы пользователя: {len(rows)}")
        for r in rows[:50]:
            mark="🗑" if r["deleted"] else ("🙈" if r["hidden"] else "📄")
            if r["kind"]=="photo": await context.bot.send_photo(q.message.chat_id,r["file_id"],caption=f"{mark} #{r['id']}")
            elif r["kind"]=="video": await context.bot.send_video(q.message.chat_id,r["file_id"],caption=f"{mark} #{r['id']}")
            elif r["kind"]=="document": await context.bot.send_document(q.message.chat_id,r["file_id"],caption=f"{mark} #{r['id']}")
            else: await context.bot.send_message(q.message.chat_id,f"{mark} #{r['id']}\n\n{r['text'] or ''}")
        await context.bot.send_message(q.message.chat_id,"👑 Админ-панель",reply_markup=main_menu(ADMIN_ID))
    elif data.startswith("adminfolders:"):
        if q.from_user.id != ADMIN_ID: await q.answer("Нет доступа.",show_alert=True); return
        await q.answer(); await safe_delete(q.message); target=int(data.split(":")[1]); owner=owner_id(target)
        con=db(); rows=con.execute("SELECT * FROM folders WHERE user_id=? ORDER BY id DESC",(owner,)).fetchall(); con.close()
        text="📁 Папки пользователя:\n\n"+"\n".join(f"#{r['id']} — {r['name']}" for r in rows) if rows else "📁 Папок нет."
        await context.bot.send_message(q.message.chat_id,text,reply_markup=main_menu(ADMIN_ID))


async def error_handler(update, context):
    print("ERROR:", repr(context.error))


def main():
    init_db()
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("link",lambda update,context: update.message.reply_text("🔗 Открой настройки MONNEY и создай код подключения на основном аккаунте.")))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.PHOTO|filters.VIDEO|filters.Document.ALL|(filters.TEXT & ~filters.COMMAND),save_message))
    app.add_error_handler(error_handler)
    print("MONNEY v9 запущен.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
