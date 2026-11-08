import os
import sqlite3
import hashlib
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
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


# ---------------- DB ----------------

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def ensure_column(con, table, column, definition):
    cols = [r["name"] for r in con.execute(f"PRAGMA table_info({table})")]
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
            pin_hash TEXT
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

    # Migration for older MONNEY databases
    ensure_column(con, "users", "username", "TEXT")
    ensure_column(con, "users", "first_name", "TEXT")
    ensure_column(con, "users", "blocked", "INTEGER DEFAULT 0")
    ensure_column(con, "users", "pin_hash", "TEXT")

    ensure_column(con, "files", "folder_id", "INTEGER")
    ensure_column(con, "files", "hidden", "INTEGER DEFAULT 0")
    ensure_column(con, "files", "deleted", "INTEGER DEFAULT 0")

    con.commit()
    con.close()


def register_user(user):
    con = db()
    con.execute("""
        INSERT INTO users(user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
    """, (user.id, user.username, user.first_name))
    con.commit()
    con.close()


def is_blocked(uid):
    con = db()
    row = con.execute(
        "SELECT blocked FROM users WHERE user_id=?", (uid,)
    ).fetchone()
    con.close()
    return bool(row and row["blocked"])


def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()


OLD_BUTTON_TEXTS = {
    "➕ Добавить файл", "📦 Галерея", "🗂 Галерея",
    "📁 Папки", "📝 Тексты и ссылки", "🙈 Скрытые файлы",
    "🗑 Корзина", "⚙️ Настройки", "👑 Админ-панель",
    "Добавить файл", "Галерея", "Папки", "Тексты и ссылки",
    "Скрытые файлы", "Корзина", "Настройки", "Админ-панель",
}

async def remove_old_reply_keyboard(context, chat_id):
    # Removes any persistent ReplyKeyboardMarkup left by an older MONNEY version.
    await context.bot.send_message(
        chat_id,
        " ",
        reply_markup=ReplyKeyboardRemove()
    )


# ---------------- KEYBOARDS ----------------

def main_menu(uid):
    rows = [
        [
            InlineKeyboardButton("➕ Добавить файл", callback_data="add"),
            InlineKeyboardButton("🗂 Галерея", callback_data="gallery"),
        ],
        [
            InlineKeyboardButton("📁 Папки", callback_data="folders"),
            InlineKeyboardButton("📝 Тексты и ссылки", callback_data="texts"),
        ],
        [
            InlineKeyboardButton("🙈 Скрытые файлы", callback_data="hidden"),
            InlineKeyboardButton("🗑 Корзина", callback_data="trash"),
        ],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
        ],
    ]

    if uid == ADMIN_ID:
        rows.append([
            InlineKeyboardButton("👑 Админ-панель", callback_data="admin")
        ])

    return InlineKeyboardMarkup(rows)


def back_menu(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="home")]
    ])


def files_menu(uid, rows, prefix="file"):
    buttons = []

    for r in rows:
        icon = {
            "photo": "🖼",
            "video": "🎥",
            "text": "📝",
            "document": "📄",
        }.get(r["kind"], "📄")

        title = r["text"][:25] if r["kind"] == "text" and r["text"] else f"Файл #{r['id']}"
        buttons.append([
            InlineKeyboardButton(
                f"{icon} {title}",
                callback_data=f"{prefix}:{r['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton("🏠 Главное меню", callback_data="home")
    ])

    return InlineKeyboardMarkup(buttons)


# ---------------- START ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)

    await remove_old_reply_keyboard(context, update.effective_chat.id)
    await update.message.reply_text(
        "💰 MONNEY\n\n"
        "Твоё личное хранилище.\n\n"
        "📸 Фото и видео\n"
        "📄 Документы\n"
        "📝 Тексты и ссылки\n"
        "📁 Папки\n"
        "🙈 Скрытые файлы\n"
        "🗑 Корзина с восстановлением\n\n"
        "Выбери нужное действие 👇",
        reply_markup=main_menu(user.id)
    )


# ---------------- NAVIGATION ----------------

async def delete_old_message(query):
    try:
        await query.message.delete()
    except Exception:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass


async def home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await delete_old_message(q)
        chat_id = q.message.chat_id
    else:
        chat_id = update.effective_chat.id

    await remove_old_reply_keyboard(context, chat_id)
    await context.bot.send_message(
        chat_id,
        "💰 MONNEY\n\nВыбери действие 👇",
        reply_markup=main_menu(uid)
    )


# ---------------- ADD FILE ----------------

async def add_screen(query, context):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    context.user_data["add_mode"] = True
    context.user_data["hidden_mode"] = False

    await context.bot.send_message(
        query.message.chat_id,
        "➕ Добавить файл\n\n"
        "Отправь сюда фото, видео, документ или текст.\n"
        "Я сохраню его автоматически.\n\n"
        "Для скрытого файла сначала нажми «🙈 Скрытые файлы».",
        reply_markup=back_menu(uid)
    )


# ---------------- HIDDEN FILES ----------------

async def hidden_screen(query, context):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    context.user_data["hidden_mode"] = True
    context.user_data["add_mode"] = True

    await context.bot.send_message(
        query.message.chat_id,
        "🙈 Скрытый режим включён.\n\n"
        "Следующий отправленный файл будет скрытым "
        "и не появится в обычной галерее.\n\n"
        "Отправь файл сейчас.",
        reply_markup=back_menu(uid)
    )


async def show_hidden(query, context):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    con = db()
    rows = con.execute("""
        SELECT * FROM files
        WHERE user_id=? AND hidden=1 AND deleted=0
        ORDER BY id DESC
    """, (uid,)).fetchall()
    con.close()

    if not rows:
        await context.bot.send_message(
            query.message.chat_id,
            "🙈 Скрытых файлов пока нет.",
            reply_markup=back_menu(uid)
        )
        return

    await context.bot.send_message(
        query.message.chat_id,
        f"🙈 Скрытые файлы: {len(rows)}\n\n"
        "Нажми на файл, чтобы открыть меню управления.",
        reply_markup=files_menu(uid, rows, "hiddenfile")
    )


# ---------------- GALLERY ----------------

async def gallery(query, context):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    con = db()
    rows = con.execute("""
        SELECT * FROM files
        WHERE user_id=? AND deleted=0 AND hidden=0
        ORDER BY id DESC
    """, (uid,)).fetchall()
    con.close()

    if not rows:
        await context.bot.send_message(
            query.message.chat_id,
            "🗂 Галерея пока пустая.",
            reply_markup=back_menu(uid)
        )
        return

    await context.bot.send_message(
        query.message.chat_id,
        f"🗂 Галерея\n\nВсего файлов: {len(rows)}\n\n"
        "Нажми на нужный файл для просмотра и управления.",
        reply_markup=files_menu(uid, rows, "file")
    )


async def open_file(query, context, file_id, hidden=False):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    con = db()
    row = con.execute(
        "SELECT * FROM files WHERE id=? AND user_id=?",
        (file_id, uid)
    ).fetchone()
    con.close()

    if not row:
        await context.bot.send_message(
            query.message.chat_id,
            "❌ Файл не найден.",
            reply_markup=back_menu(uid)
        )
        return

    if row["kind"] == "photo":
        await context.bot.send_photo(
            query.message.chat_id,
            row["file_id"],
            caption=f"🖼 Файл #{row['id']}"
        )
    elif row["kind"] == "video":
        await context.bot.send_video(
            query.message.chat_id,
            row["file_id"],
            caption=f"🎥 Файл #{row['id']}"
        )
    elif row["kind"] == "document":
        await context.bot.send_document(
            query.message.chat_id,
            row["file_id"],
            caption=f"📄 Файл #{row['id']}"
        )
    else:
        await context.bot.send_message(
            query.message.chat_id,
            f"📝 Файл #{row['id']}\n\n{row['text']}"
        )

    buttons = [
        [InlineKeyboardButton(
            "🗑 Удалить",
            callback_data=f"delete:{row['id']}"
        )]
    ]

    if row["hidden"]:
        buttons.append([
            InlineKeyboardButton(
                "👁 Сделать обычным",
                callback_data=f"unhide:{row['id']}"
            )
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                "🙈 Скрыть файл",
                callback_data=f"hide:{row['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton("🏠 Главное меню", callback_data="home")
    ])

    await context.bot.send_message(
        query.message.chat_id,
        "⚙️ Управление файлом:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ---------------- DELETE / RESTORE ----------------

async def delete_file(query, context, file_id):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    con = db()
    cur = con.execute(
        "UPDATE files SET deleted=1 WHERE id=? AND user_id=?",
        (file_id, uid)
    )
    con.commit()
    con.close()

    if cur.rowcount:
        text = f"🗑 Файл #{file_id} перемещён в корзину.\n\nЕго можно восстановить."
    else:
        text = "❌ Файл не найден."

    await context.bot.send_message(
        query.message.chat_id,
        text,
        reply_markup=main_menu(uid)
    )


async def restore_file(query, context, file_id):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    con = db()
    cur = con.execute(
        "UPDATE files SET deleted=0 WHERE id=? AND user_id=?",
        (file_id, uid)
    )
    con.commit()
    con.close()

    await context.bot.send_message(
        query.message.chat_id,
        f"♻️ Файл #{file_id} восстановлен.",
        reply_markup=main_menu(uid)
    )


async def trash(query, context):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    con = db()
    rows = con.execute("""
        SELECT * FROM files
        WHERE user_id=? AND deleted=1
        ORDER BY id DESC
    """, (uid,)).fetchall()
    con.close()

    if not rows:
        await context.bot.send_message(
            query.message.chat_id,
            "🗑 Корзина пустая.",
            reply_markup=back_menu(uid)
        )
        return

    buttons = []

    for r in rows:
        buttons.append([
            InlineKeyboardButton(
                f"♻️ Восстановить #{r['id']}",
                callback_data=f"restore:{r['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton("🏠 Главное меню", callback_data="home")
    ])

    await context.bot.send_message(
        query.message.chat_id,
        f"🗑 Корзина\n\nФайлов: {len(rows)}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ---------------- HIDE / UNHIDE ----------------

async def hide_file(query, context, file_id, hidden_value):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    con = db()
    con.execute(
        "UPDATE files SET hidden=? WHERE id=? AND user_id=?",
        (hidden_value, file_id, uid)
    )
    con.commit()
    con.close()

    text = (
        "🙈 Файл скрыт.\nОн больше не отображается в обычной галерее."
        if hidden_value
        else
        "👁 Файл снова обычный.\nОн будет отображаться в галерее."
    )

    await context.bot.send_message(
        query.message.chat_id,
        text,
        reply_markup=main_menu(uid)
    )


# ---------------- TEXTS ----------------

async def texts(query, context):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    con = db()
    rows = con.execute("""
        SELECT * FROM files
        WHERE user_id=? AND kind='text' AND deleted=0 AND hidden=0
        ORDER BY id DESC
    """, (uid,)).fetchall()
    con.close()

    if not rows:
        await context.bot.send_message(
            query.message.chat_id,
            "📝 Тексты и ссылки пока пустые.",
            reply_markup=back_menu(uid)
        )
        return

    for r in rows:
        await context.bot.send_message(
            query.message.chat_id,
            f"📝 #{r['id']}\n\n{r['text']}"
        )

    await context.bot.send_message(
        query.message.chat_id,
        "Что дальше?",
        reply_markup=main_menu(uid)
    )


# ---------------- FOLDERS ----------------

async def folders(query, context):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    con = db()
    rows = con.execute(
        "SELECT * FROM folders WHERE user_id=? ORDER BY id DESC",
        (uid,)
    ).fetchall()
    con.close()

    buttons = [
        [InlineKeyboardButton("➕ Создать папку", callback_data="folder_new")]
    ]

    for r in rows:
        buttons.append([
            InlineKeyboardButton(
                f"📁 {r['name']}",
                callback_data=f"folder:{r['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton("🏠 Главное меню", callback_data="home")
    ])

    await context.bot.send_message(
        query.message.chat_id,
        "📁 Папки",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def new_folder(query, context):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    context.user_data["waiting_folder"] = True

    await context.bot.send_message(
        query.message.chat_id,
        "📁 Напиши название новой папки:",
        reply_markup=back_menu(uid)
    )


async def open_folder(query, context, folder_id):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    con = db()
    folder = con.execute(
        "SELECT * FROM folders WHERE id=? AND user_id=?",
        (folder_id, uid)
    ).fetchone()

    rows = con.execute("""
        SELECT * FROM files
        WHERE folder_id=? AND user_id=? AND deleted=0
        ORDER BY id DESC
    """, (folder_id, uid)).fetchall()

    con.close()

    if not folder:
        await context.bot.send_message(
            query.message.chat_id,
            "❌ Папка не найдена.",
            reply_markup=back_menu(uid)
        )
        return

    await context.bot.send_message(
        query.message.chat_id,
        f"📁 {folder['name']}\n\nФайлов: {len(rows)}",
        reply_markup=files_menu(uid, rows, "file")
        if rows else back_menu(uid)
    )


# ---------------- SETTINGS ----------------

async def settings(query, context):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    con = db()
    row = con.execute(
        "SELECT pin_hash FROM users WHERE user_id=?",
        (uid,)
    ).fetchone()
    con.close()

    pin_status = "🟢 установлен" if row and row["pin_hash"] else "⚪ не установлен"

    buttons = [
        [InlineKeyboardButton(
            "🔐 Установить PIN",
            callback_data="pin_set"
        )],
        [InlineKeyboardButton(
            "🔄 Изменить PIN",
            callback_data="pin_change"
        )],
        [InlineKeyboardButton(
            "❌ Удалить PIN",
            callback_data="pin_remove"
        )],
        [InlineKeyboardButton(
            "🏠 Главное меню",
            callback_data="home"
        )],
    ]

    await context.bot.send_message(
        query.message.chat_id,
        f"⚙️ Настройки\n\n"
        f"🔐 PIN: {pin_status}\n\n"
        f"PIN защищает доступ к настройкам и скрытым файлам.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def pin_start(query, context, action):
    uid = query.from_user.id
    await query.answer()
    await delete_old_message(query)

    if action == "remove":
        con = db()
        con.execute(
            "UPDATE users SET pin_hash=NULL WHERE user_id=?",
            (uid,)
        )
        con.commit()
        con.close()

        await context.bot.send_message(
            query.message.chat_id,
            "❌ PIN удалён.",
            reply_markup=main_menu(uid)
        )
        return

    context.user_data["pin_action"] = action

    if action == "change":
        text = "🔐 Введи новый PIN-код (4–8 цифр):"
    else:
        text = "🔐 Придумай PIN-код (4–8 цифр):"

    await context.bot.send_message(
        query.message.chat_id,
        text,
        reply_markup=back_menu(uid)
    )


# ---------------- MESSAGE SAVE ----------------

async def save_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    register_user(user)

    if is_blocked(uid) and uid != ADMIN_ID:
        return

    # Folder creation
    if context.user_data.get("waiting_folder"):
        if update.message.text:
            name = update.message.text.strip()

            if not name:
                return

            con = db()
            con.execute(
                "INSERT INTO folders(user_id, name) VALUES (?, ?)",
                (uid, name)
            )
            con.commit()
            con.close()

            context.user_data["waiting_folder"] = False

            await update.message.reply_text(
                f"📁 Папка «{name}» создана.",
                reply_markup=main_menu(uid)
            )
        return

    # PIN
    if context.user_data.get("pin_action") and update.message.text:
        pin = update.message.text.strip()

        if not pin.isdigit() or not (4 <= len(pin) <= 8):
            await update.message.reply_text(
                "❌ PIN должен содержать от 4 до 8 цифр."
            )
            return

        action = context.user_data.pop("pin_action")

        con = db()

        if action in ("set", "change"):
            con.execute(
                "UPDATE users SET pin_hash=? WHERE user_id=?",
                (hash_pin(pin), uid)
            )
            con.commit()
            con.close()

            await update.message.reply_text(
                "✅ PIN сохранён.",
                reply_markup=main_menu(uid)
            )
        return

    # Ignore commands
    if not update.message:
        return

    if update.message.text and update.message.text.startswith("/"):
        return

    # Old MONNEY versions used a persistent reply keyboard.
    # Never save its button labels as user files.
    if update.message.text and update.message.text.strip() in OLD_BUTTON_TEXTS:
        return

    hidden = bool(context.user_data.get("hidden_mode"))
    add_mode = context.user_data.get("add_mode", False)

    kind = None
    file_id = None
    text = None

    if update.message.photo:
        kind = "photo"
        file_id = update.message.photo[-1].file_id
    elif update.message.video:
        kind = "video"
        file_id = update.message.video.file_id
    elif update.message.document:
        kind = "document"
        file_id = update.message.document.file_id
    elif update.message.text:
        kind = "text"
        text = update.message.text.strip()

    if not kind:
        return

    con = db()

    cur = con.execute("""
        INSERT INTO files(user_id, kind, file_id, text, hidden)
        VALUES (?, ?, ?, ?, ?)
    """, (uid, kind, file_id, text, int(hidden)))

    item_id = cur.lastrowid
    con.commit()
    con.close()

    context.user_data["add_mode"] = False
    context.user_data["hidden_mode"] = False

    if hidden:
        label = "🙈 Скрыто сохранено"
    else:
        label = "✅ Сохранено"

    await update.message.reply_text(
        f"{label} — #{item_id}",
        reply_markup=main_menu(uid)
    )


# ---------------- ADMIN ----------------

async def admin(query, context):
    uid = query.from_user.id

    if uid != ADMIN_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return

    await query.answer()
    await delete_old_message(query)

    con = db()
    users = con.execute("SELECT * FROM users ORDER BY user_id DESC").fetchall()
    total_files = con.execute(
        "SELECT COUNT(*) AS n FROM files WHERE deleted=0"
    ).fetchone()["n"]
    hidden = con.execute(
        "SELECT COUNT(*) AS n FROM files WHERE hidden=1 AND deleted=0"
    ).fetchone()["n"]
    con.close()

    buttons = []

    for u in users[:50]:
        name = u["username"] or u["first_name"] or str(u["user_id"])
        status = "🚫" if u["blocked"] else "🟢"

        buttons.append([
            InlineKeyboardButton(
                f"{status} {name}",
                callback_data=f"adminuser:{u['user_id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton("🏠 Главное меню", callback_data="home")
    ])

    await context.bot.send_message(
        query.message.chat_id,
        f"👑 АДМИН-ПАНЕЛЬ\n\n"
        f"👤 Пользователей: {len(users)}\n"
        f"📦 Файлов: {total_files}\n"
        f"🙈 Скрытых: {hidden}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def admin_user(query, context, target):
    uid = query.from_user.id

    if uid != ADMIN_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return

    await query.answer()
    await delete_old_message(query)

    con = db()
    user = con.execute(
        "SELECT * FROM users WHERE user_id=?",
        (target,)
    ).fetchone()
    files = con.execute(
        "SELECT COUNT(*) AS n FROM files WHERE user_id=?",
        (target,)
    ).fetchone()["n"]
    folders_count = con.execute(
        "SELECT COUNT(*) AS n FROM folders WHERE user_id=?",
        (target,)
    ).fetchone()["n"]
    con.close()

    if not user:
        await context.bot.send_message(
            query.message.chat_id,
            "Пользователь не найден.",
            reply_markup=back_menu(uid)
        )
        return

    buttons = [
        [InlineKeyboardButton(
            "🚫 Заблокировать" if not user["blocked"] else "✅ Разблокировать",
            callback_data=f"toggleblock:{target}"
        )],
        [InlineKeyboardButton(
            "📂 Файлы пользователя",
            callback_data=f"adminfiles:{target}"
        )],
        [InlineKeyboardButton(
            "📁 Папки пользователя",
            callback_data=f"adminfolders:{target}"
        )],
        [InlineKeyboardButton(
            "👑 Админ-панель",
            callback_data="admin"
        )],
    ]

    await context.bot.send_message(
        query.message.chat_id,
        f"👤 Пользователь\n\n"
        f"ID: {target}\n"
        f"Username: @{user['username'] or 'нет'}\n"
        f"Файлов: {files}\n"
        f"Папок: {folders_count}\n"
        f"Статус: {'🚫 заблокирован' if user['blocked'] else '🟢 активен'}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ---------------- CALLBACK ROUTER ----------------

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data

    if data == "home":
        await home(update, context)

    elif data == "add":
        await add_screen(q, context)

    elif data == "hidden":
        # First tap = enter hidden upload mode.
        # The actual hidden files list is available through the same screen.
        await hidden_screen(q, context)

    elif data == "gallery":
        await gallery(q, context)

    elif data.startswith("file:"):
        await open_file(
            q, context,
            int(data.split(":")[1]),
            hidden=False
        )

    elif data.startswith("hiddenfile:"):
        await open_file(
            q, context,
            int(data.split(":")[1]),
            hidden=True
        )

    elif data.startswith("delete:"):
        await delete_file(
            q, context,
            int(data.split(":")[1])
        )

    elif data.startswith("restore:"):
        await restore_file(
            q, context,
            int(data.split(":")[1])
        )

    elif data.startswith("hide:"):
        await hide_file(
            q, context,
            int(data.split(":")[1]),
            1
        )

    elif data.startswith("unhide:"):
        await hide_file(
            q, context,
            int(data.split(":")[1]),
            0
        )

    elif data == "texts":
        await texts(q, context)

    elif data == "folders":
        await folders(q, context)

    elif data == "folder_new":
        await new_folder(q, context)

    elif data.startswith("folder:"):
        await open_folder(
            q, context,
            int(data.split(":")[1])
        )

    elif data == "trash":
        await trash(q, context)

    elif data == "settings":
        await settings(q, context)

    elif data in ("pin_set", "pin_change", "pin_remove"):
        action = {
            "pin_set": "set",
            "pin_change": "change",
            "pin_remove": "remove",
        }[data]
        await pin_start(q, context, action)

    elif data == "admin":
        await admin(q, context)

    elif data.startswith("adminuser:"):
        await admin_user(
            q, context,
            int(data.split(":")[1])
        )

    elif data.startswith("toggleblock:"):
        if q.from_user.id != ADMIN_ID:
            await q.answer("Нет доступа.", show_alert=True)
            return

        target = int(data.split(":")[1])

        if target == ADMIN_ID:
            await q.answer("Себя блокировать нельзя.", show_alert=True)
            return

        await q.answer()
        await delete_old_message(q)

        con = db()
        row = con.execute(
            "SELECT blocked FROM users WHERE user_id=?",
            (target,)
        ).fetchone()

        new_value = 0 if row and row["blocked"] else 1

        con.execute(
            "UPDATE users SET blocked=? WHERE user_id=?",
            (new_value, target)
        )
        con.commit()
        con.close()

        await context.bot.send_message(
            q.message.chat_id,
            "🚫 Пользователь заблокирован."
            if new_value
            else "✅ Пользователь разблокирован.",
            reply_markup=main_menu(ADMIN_ID)
        )

    elif data.startswith("adminfiles:"):
        if q.from_user.id != ADMIN_ID:
            await q.answer("Нет доступа.", show_alert=True)
            return

        await q.answer()
        await delete_old_message(q)

        target = int(data.split(":")[1])

        con = db()
        rows = con.execute(
            "SELECT * FROM files WHERE user_id=? ORDER BY id DESC",
            (target,)
        ).fetchall()
        con.close()

        await context.bot.send_message(
            q.message.chat_id,
            f"📂 Файлы пользователя {target}: {len(rows)}"
        )

        for r in rows[:50]:
            mark = "🗑" if r["deleted"] else ("🙈" if r["hidden"] else "📄")

            if r["kind"] == "photo":
                await context.bot.send_photo(
                    q.message.chat_id,
                    r["file_id"],
                    caption=f"{mark} #{r['id']}"
                )
            elif r["kind"] == "video":
                await context.bot.send_video(
                    q.message.chat_id,
                    r["file_id"],
                    caption=f"{mark} #{r['id']}"
                )
            elif r["kind"] == "document":
                await context.bot.send_document(
                    q.message.chat_id,
                    r["file_id"],
                    caption=f"{mark} #{r['id']}"
                )
            else:
                await context.bot.send_message(
                    q.message.chat_id,
                    f"{mark} #{r['id']}\n\n{r['text']}"
                )

        await context.bot.send_message(
            q.message.chat_id,
            "👑 Админ-панель",
            reply_markup=main_menu(ADMIN_ID)
        )

    elif data.startswith("adminfolders:"):
        if q.from_user.id != ADMIN_ID:
            await q.answer("Нет доступа.", show_alert=True)
            return

        await q.answer()
        await delete_old_message(q)

        target = int(data.split(":")[1])

        con = db()
        rows = con.execute(
            "SELECT * FROM folders WHERE user_id=? ORDER BY id DESC",
            (target,)
        ).fetchall()
        con.close()

        if rows:
            text = "📁 Папки пользователя:\n\n"
            text += "\n".join(
                f"#{r['id']} — {r['name']}" for r in rows
            )
        else:
            text = "📁 Папок нет."

        await context.bot.send_message(
            q.message.chat_id,
            text,
            reply_markup=main_menu(ADMIN_ID)
        )


# ---------------- ERROR / MAIN ----------------

async def error_handler(update, context):
    print("ERROR:", repr(context.error))


def main():
    if not TOKEN:
        raise SystemExit(
            "BOT_TOKEN или MONNEY_TOKEN не задан."
        )

    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_router))

    app.add_handler(MessageHandler(
        filters.PHOTO
        | filters.VIDEO
        | filters.Document.ALL
        | (filters.TEXT & ~filters.COMMAND),
        save_message
    ))

    app.add_error_handler(error_handler)

    print("MONNEY v8 запущен.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
