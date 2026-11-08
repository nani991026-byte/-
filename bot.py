import os
import sqlite3
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("MONNEY_TOKEN")
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "monney.db")
ADMIN_ID = 8976178026

if not TOKEN:
    raise SystemExit("BOT_TOKEN не задан. Добавь BOT_TOKEN в переменные окружения Bothost.")


# ---------- DATABASE ----------

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def ensure_column(con, table, column, definition):
    columns = [r["name"] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
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


def is_blocked(user_id):
    con = db()
    row = con.execute(
        "SELECT blocked FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()
    con.close()
    return bool(row and row["blocked"])


def save_file(user_id, kind, file_id=None, text=None, hidden=0):
    con = db()
    cur = con.execute("""
        INSERT INTO files(user_id, kind, file_id, text, hidden)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, kind, file_id, text, int(hidden)))
    file_number = cur.lastrowid
    con.commit()
    con.close()
    return file_number


# ---------- REPLY KEYBOARD ----------

def main_keyboard(user_id):
    rows = [
        ["➕ Добавить файл", "📦 Галерея"],
        ["📁 Папки", "📝 Тексты и ссылки"],
        ["🙈 Скрытые файлы", "🗑 Корзина"],
        ["⚙️ Настройки", "👑 Админ-панель"],
    ]

    if user_id != ADMIN_ID:
        rows[-1] = ["⚙️ Настройки"]

    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите действие…"
    )


def hidden_keyboard(user_id):
    rows = [
        ["🙈 Добавить в скрытые", "📂 Открыть скрытые"],
        ["⬅️ Главное меню"],
    ]
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Отправь фото или видео…"
    )


async def show_menu(update: Update, text=None):
    user = update.effective_user
    message = text or (
        "💰 MONNEY\n\n"
        "Твоё личное хранилище.\n"
        "Фото, видео, файлы, тексты и ссылки сохраняются здесь.\n\n"
        "Выбери нужное действие 👇"
    )
    await update.effective_message.reply_text(
        message,
        reply_markup=main_keyboard(user.id)
    )


# ---------- START ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["hidden_mode"] = False
    user = update.effective_user
    register_user(user)

    if is_blocked(user.id):
        await update.effective_message.reply_text("🚫 Доступ к MONNEY заблокирован.")
        return

    await show_menu(update)


# ---------- GALLERY ----------

async def gallery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    con = db()
    rows = con.execute("""
        SELECT id, kind, file_id, text, created_at
        FROM files
        WHERE user_id=? AND deleted=0 AND hidden=0
        ORDER BY id DESC
        LIMIT 100
    """, (user.id,)).fetchall()
    con.close()

    if not rows:
        await update.effective_message.reply_text(
            "📦 Галерея пока пустая.",
            reply_markup=main_keyboard(user.id)
        )
        return

    photos = [r for r in rows if r["kind"] == "photo"]
    videos = [r for r in rows if r["kind"] == "video"]
    documents = [r for r in rows if r["kind"] == "document"]
    texts = [r for r in rows if r["kind"] == "text"]

    if photos:
        await update.effective_message.reply_text("📸 Фотографии:")
        for r in photos[:50]:
            await update.effective_message.reply_photo(r["file_id"])

    if videos:
        await update.effective_message.reply_text("🎥 Видео:")
        for r in videos[:20]:
            await update.effective_message.reply_video(r["file_id"])

    if documents:
        await update.effective_message.reply_text("📎 Файлы:")
        for r in documents[:20]:
            await update.effective_message.reply_document(r["file_id"])

    if texts:
        lines = ["📝 Тексты:"]
        for r in texts[:30]:
            lines.append(f"\n#{r['id']} — {r['text']}")
        await update.effective_message.reply_text("\n".join(lines))

    await show_menu(update)


# ---------- HIDDEN FILES ----------

async def hidden_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["hidden_mode"] = False
    user = update.effective_user

    con = db()
    rows = con.execute("""
        SELECT id, kind, file_id, text
        FROM files
        WHERE user_id=? AND hidden=1 AND deleted=0
        ORDER BY id DESC
        LIMIT 100
    """, (user.id,)).fetchall()
    con.close()

    if not rows:
        await update.effective_message.reply_text(
            "🙈 Скрытых файлов пока нет.",
            reply_markup=hidden_keyboard(user.id)
        )
        return

    photos = [r for r in rows if r["kind"] == "photo"]
    videos = [r for r in rows if r["kind"] == "video"]
    documents = [r for r in rows if r["kind"] == "document"]
    texts = [r for r in rows if r["kind"] == "text"]

    await update.effective_message.reply_text(
        "🙈 Скрытые файлы\n\n"
        "Они не отображаются в обычной галерее.",
        reply_markup=hidden_keyboard(user.id)
    )

    if photos:
        await update.effective_message.reply_text("📸 Скрытые фотографии:")
        for r in photos[:50]:
            await update.effective_message.reply_photo(r["file_id"])

    if videos:
        await update.effective_message.reply_text("🎥 Скрытые видео:")
        for r in videos[:20]:
            await update.effective_message.reply_video(r["file_id"])

    if documents:
        await update.effective_message.reply_text("📎 Скрытые файлы:")
        for r in documents[:20]:
            await update.effective_message.reply_document(r["file_id"])

    if texts:
        lines = ["📝 Скрытые тексты:"]
        for r in texts[:30]:
            lines.append(f"\n#{r['id']} — {r['text']}")
        await update.effective_message.reply_text("\n".join(lines))


async def enter_hidden_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["hidden_mode"] = True
    await update.effective_message.reply_text(
        "🙈 Режим скрытого сохранения включён.\n\n"
        "Отправляй сюда одну фотографию или сразу несколько фотографий альбомом — "
        "каждая будет сохранена как скрытая.\n\n"
        "Чтобы выйти, нажми «⬅️ Главное меню».",
        reply_markup=hidden_keyboard(update.effective_user.id)
    )


# ---------- SAVE INCOMING ----------

async def save_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)

    if is_blocked(user.id):
        return

    msg = update.effective_message
    hidden = bool(context.user_data.get("hidden_mode", False))

    if msg.photo:
        file_id = msg.photo[-1].file_id
        num = save_file(user.id, "photo", file_id=file_id, hidden=hidden)
        prefix = "🙈 Скрыто сохранено" if hidden else "✅ Сохранено"
        await msg.reply_text(
            f"{prefix} — #{num}",
            reply_markup=hidden_keyboard(user.id) if hidden else main_keyboard(user.id)
        )
        return

    if msg.video:
        num = save_file(user.id, "video", file_id=msg.video.file_id, hidden=hidden)
        prefix = "🙈 Скрыто сохранено" if hidden else "✅ Видео сохранено"
        await msg.reply_text(
            f"{prefix} — #{num}",
            reply_markup=hidden_keyboard(user.id) if hidden else main_keyboard(user.id)
        )
        return

    if msg.document:
        num = save_file(user.id, "document", file_id=msg.document.file_id, hidden=hidden)
        prefix = "🙈 Скрыто сохранено" if hidden else "✅ Файл сохранён"
        await msg.reply_text(
            f"{prefix} — #{num}",
            reply_markup=hidden_keyboard(user.id) if hidden else main_keyboard(user.id)
        )
        return

    if msg.text and not msg.text.startswith("/"):
        menu_items = {
            "➕ Добавить файл",
            "📦 Галерея",
            "📁 Папки",
            "📝 Тексты и ссылки",
            "🙈 Скрытые файлы",
            "🗑 Корзина",
            "⚙️ Настройки",
            "👑 Админ-панель",
            "🙈 Добавить в скрытые",
            "📂 Открыть скрытые",
            "⬅️ Главное меню",
        }
        if msg.text not in menu_items:
            num = save_file(user.id, "text", text=msg.text, hidden=hidden)
            prefix = "🙈 Скрыто сохранено" if hidden else "✅ Сохранено"
            await msg.reply_text(
                f"{prefix} — #{num}\n📝 Текст",
                reply_markup=hidden_keyboard(user.id) if hidden else main_keyboard(user.id)
            )


# ---------- TEXTS ----------

async def texts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    con = db()
    rows = con.execute("""
        SELECT id, text
        FROM files
        WHERE user_id=? AND kind='text' AND deleted=0 AND hidden=0
        ORDER BY id DESC
        LIMIT 50
    """, (user.id,)).fetchall()
    con.close()

    if not rows:
        await update.effective_message.reply_text(
            "📝 Текстов и ссылок пока нет.",
            reply_markup=main_keyboard(user.id)
        )
        return

    lines = ["📝 Тексты и ссылки:\n"]
    for r in rows:
        lines.append(f"#{r['id']}\n{r['text']}\n")

    await update.effective_message.reply_text(
        "\n".join(lines),
        reply_markup=main_keyboard(user.id)
    )


# ---------- FOLDERS ----------

async def folders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    con = db()
    rows = con.execute("""
        SELECT id, name
        FROM folders
        WHERE user_id=?
        ORDER BY id DESC
    """, (user.id,)).fetchall()
    con.close()

    if not rows:
        await update.effective_message.reply_text(
            "📁 Папок пока нет.\n\n"
            "Чтобы создать папку, напиши:\n"
            "/newfolder Название папки",
            reply_markup=main_keyboard(user.id)
        )
        return

    lines = ["📁 Твои папки:\n"]
    for r in rows:
        lines.append(f"#{r['id']} — {r['name']}")
    lines.append("\nСоздать новую: /newfolder Название")

    await update.effective_message.reply_text(
        "\n".join(lines),
        reply_markup=main_keyboard(user.id)
    )


async def newfolder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = " ".join(context.args).strip()

    if not name:
        await update.effective_message.reply_text(
            "Напиши так:\n/newfolder Личные фото",
            reply_markup=main_keyboard(user.id)
        )
        return

    con = db()
    cur = con.execute(
        "INSERT INTO folders(user_id, name) VALUES (?, ?)",
        (user.id, name)
    )
    folder_id = cur.lastrowid
    con.commit()
    con.close()

    await update.effective_message.reply_text(
        f"📁 Папка создана: {name}\nID: #{folder_id}",
        reply_markup=main_keyboard(user.id)
    )


# ---------- TRASH ----------

async def trash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    con = db()
    rows = con.execute("""
        SELECT id, kind, text
        FROM files
        WHERE user_id=? AND deleted=1
        ORDER BY id DESC
        LIMIT 50
    """, (user.id,)).fetchall()
    con.close()

    if not rows:
        await update.effective_message.reply_text(
            "🗑 Корзина пуста.",
            reply_markup=main_keyboard(user.id)
        )
        return

    lines = ["🗑 Корзина:\n"]
    for r in rows:
        preview = r["text"] if r["text"] else r["kind"]
        lines.append(f"#{r['id']} — {preview}")
    lines.append("\nВосстановить: /restore ID")

    await update.effective_message.reply_text(
        "\n".join(lines),
        reply_markup=main_keyboard(user.id)
    )


async def restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text(
            "Напиши: /restore ID",
            reply_markup=main_keyboard(user.id)
        )
        return

    file_id = int(context.args[0])

    con = db()
    cur = con.execute("""
        UPDATE files
        SET deleted=0
        WHERE id=? AND user_id=?
    """, (file_id, user.id))
    con.commit()
    changed = cur.rowcount
    con.close()

    text = f"♻️ Файл #{file_id} восстановлен." if changed else "❌ Файл не найден в твоей корзине."
    await update.effective_message.reply_text(
        text,
        reply_markup=main_keyboard(user.id)
    )


# ---------- SETTINGS / ADMIN ----------

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "⚙️ Настройки\n\n"
        "Здесь будут настройки безопасности, PIN-код и управление хранилищем.",
        reply_markup=main_keyboard(update.effective_user.id)
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.effective_message.reply_text("🚫 Доступ запрещён.")
        return

    con = db()
    users = con.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    files = con.execute("SELECT COUNT(*) AS c FROM files WHERE deleted=0").fetchone()["c"]
    folders_count = con.execute("SELECT COUNT(*) AS c FROM folders").fetchone()["c"]
    con.close()

    await update.effective_message.reply_text(
        "👑 Админ-панель\n\n"
        f"👤 Пользователей: {users}\n"
        f"📦 Файлов: {files}\n"
        f"📁 Папок: {folders_count}\n\n"
        "Команды:\n"
        "/users — пользователи\n"
        "/stats — статистика",
        reply_markup=main_keyboard(user.id)
    )


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    con = db()
    rows = con.execute("""
        SELECT user_id, username, first_name, blocked
        FROM users
        ORDER BY user_id DESC
        LIMIT 50
    """).fetchall()
    con.close()

    if not rows:
        await update.effective_message.reply_text("Пользователей пока нет.")
        return

    lines = ["👤 Пользователи:\n"]
    for r in rows:
        name = r["first_name"] or "Без имени"
        username = f"@{r['username']}" if r["username"] else "без username"
        status = "🚫 заблокирован" if r["blocked"] else "✅ активен"
        lines.append(f"{r['user_id']} — {name} — {username} — {status}")

    await update.effective_message.reply_text("\n".join(lines))


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    con = db()
    total = con.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]
    photos = con.execute("SELECT COUNT(*) AS c FROM files WHERE kind='photo'").fetchone()["c"]
    videos = con.execute("SELECT COUNT(*) AS c FROM files WHERE kind='video'").fetchone()["c"]
    texts_count = con.execute("SELECT COUNT(*) AS c FROM files WHERE kind='text'").fetchone()["c"]
    docs = con.execute("SELECT COUNT(*) AS c FROM files WHERE kind='document'").fetchone()["c"]
    hidden = con.execute("SELECT COUNT(*) AS c FROM files WHERE hidden=1 AND deleted=0").fetchone()["c"]
    con.close()

    await update.effective_message.reply_text(
        "📊 Статистика MONNEY\n\n"
        f"Всего файлов: {total}\n"
        f"📸 Фото: {photos}\n"
        f"🎥 Видео: {videos}\n"
        f"📝 Тексты: {texts_count}\n"
        f"📎 Документы: {docs}\n"
        f"🙈 Скрытые: {hidden}",
        reply_markup=main_keyboard(update.effective_user.id)
    )


# ---------- BUTTON ROUTER ----------

async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.effective_message.text

    if text == "➕ Добавить файл":
        context.user_data["hidden_mode"] = False
        await update.effective_message.reply_text(
            "➕ Добавить файл\n\n"
            "Просто отправь сюда фотографию, видео или документ.\n"
            "Можно отправить сразу несколько фотографий альбомом — "
            "каждая сохранится отдельно.\n"
            "Тексты и ссылки тоже можно отправлять прямо сюда.",
            reply_markup=main_keyboard(update.effective_user.id)
        )

    elif text == "📦 Галерея":
        context.user_data["hidden_mode"] = False
        await gallery(update, context)

    elif text == "📁 Папки":
        context.user_data["hidden_mode"] = False
        await folders(update, context)

    elif text == "📝 Тексты и ссылки":
        context.user_data["hidden_mode"] = False
        await texts(update, context)

    elif text == "🙈 Скрытые файлы":
        await hidden_files(update, context)

    elif text == "🙈 Добавить в скрытые":
        await enter_hidden_mode(update, context)

    elif text == "📂 Открыть скрытые":
        await hidden_files(update, context)

    elif text == "⬅️ Главное меню":
        context.user_data["hidden_mode"] = False
        await show_menu(update)

    elif text == "🗑 Корзина":
        context.user_data["hidden_mode"] = False
        await trash(update, context)

    elif text == "⚙️ Настройки":
        context.user_data["hidden_mode"] = False
        await settings(update, context)

    elif text == "👑 Админ-панель":
        context.user_data["hidden_mode"] = False
        await admin_panel(update, context)

    else:
        await save_incoming(update, context)


# ---------- MAIN ----------

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newfolder", newfolder))
    app.add_handler(CommandHandler("restore", restore))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))

    # Each photo in a Telegram album arrives as its own update.
    # Because hidden_mode is stored in user_data, ALL album photos
    # are saved hidden instead of only the first one.
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.TEXT,
        button_router
    ))

    print("MONNEY запущен.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
