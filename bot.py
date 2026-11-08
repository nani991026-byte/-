import os
import sqlite3
import hashlib
import threading

from webapp import start_server
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("MONNEY_TOKEN")
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "monney.db")
ADMIN_ID = 8976178026
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://bot-1794054439-1767-bakha.bothost.tech")

if not TOKEN:
    raise SystemExit("BOT_TOKEN не задан. Укажи BOT_TOKEN в переменных окружения Bothost.")


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def ensure_column(con, table, column, definition):
    cols = [r["name"] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    con = db()

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
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
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
        VALUES(?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
    """, (user.id, user.username, user.first_name))
    con.commit()
    con.close()


def hash_pin(pin):
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def get_pin_hash(uid):
    con = db()
    row = con.execute("SELECT pin_hash FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    return row["pin_hash"] if row else None


def set_pin(uid, pin):
    con = db()
    con.execute("UPDATE users SET pin_hash=? WHERE user_id=?", (hash_pin(pin), uid))
    con.commit()
    con.close()


def remove_pin(uid):
    con = db()
    con.execute("UPDATE users SET pin_hash=NULL WHERE user_id=?", (uid,))
    con.commit()
    con.close()


def menu(uid):
    rows = [
        [InlineKeyboardButton("📱 Открыть MONNEY", web_app=WebAppInfo(url=WEBAPP_URL))],
        [
            InlineKeyboardButton("➕ Добавить", callback_data="add"),
            InlineKeyboardButton("🖼 Галерея", callback_data="gallery")
        ],
        [
            InlineKeyboardButton("📁 Папки", callback_data="folders"),
            InlineKeyboardButton("📝 Тексты", callback_data="texts")
        ],
        [
            InlineKeyboardButton("🔒 Скрытое", callback_data="hidden"),
            InlineKeyboardButton("🗑 Корзина", callback_data="trash")
        ],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data="settings")
        ]
    ]

    if uid == ADMIN_ID:
        rows.append([InlineKeyboardButton("👑 Админ-панель", callback_data="admin")])

    return InlineKeyboardMarkup(rows)


def home_button(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="home")]
    ])


def add_menu(uid):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📸 Фото / видео", callback_data="add_normal"),
            InlineKeyboardButton("🔒 Скрытое", callback_data="add_hidden")
        ],
        [InlineKeyboardButton("📝 Текст", callback_data="add_text")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="home")]
    ])


def settings_menu(uid):
    pin_exists = get_pin_hash(uid) is not None
    rows = [
        [InlineKeyboardButton(
            "🔐 Изменить PIN" if pin_exists else "🔐 Установить PIN",
            callback_data="pin_set"
        )],
    ]

    if pin_exists:
        rows.append([InlineKeyboardButton("🗑 Удалить PIN", callback_data="pin_remove")])

    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    return InlineKeyboardMarkup(rows)


async def remove_old_button_message(q):
    try:
        await q.message.delete()
    except Exception:
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass


async def send_home(chat_id, context):
    await context.bot.send_message(
        chat_id,
        "💰 MONNEY\n\nТвоё личное хранилище.\nВыбери действие:",
        reply_markup=menu(chat_id)
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    await update.message.reply_text(
        "💰 MONNEY\n\n"
        "Твоё личное хранилище.\n"
        "Фото, видео, тексты и ссылки сохраняются здесь.\n\n"
        "🔒 Скрытые файлы защищаются PIN-кодом.",
        reply_markup=menu(update.effective_user.id)
    )


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    register_user(q.from_user)
    data = q.data

    if data == "home":
        await remove_old_button_message(q)
        await send_home(q.message.chat_id, context)
        return

    if data == "add":
        await remove_old_button_message(q)
        await context.bot.send_message(
            q.message.chat_id,
            "➕ Что хочешь сохранить?",
            reply_markup=add_menu(uid)
        )
        return

    if data in ("add_normal", "add_hidden", "add_text"):
        await remove_old_button_message(q)

        if data == "add_hidden":
            context.user_data["save_hidden"] = True
            await context.bot.send_message(
                q.message.chat_id,
                "🔒 Скрытое сохранение включено.\n\n"
                "Отправь фото или видео — оно будет скрыто из обычной галереи.\n"
                "Для просмотра понадобится PIN.",
                reply_markup=home_button(uid)
            )
            return

        if data == "add_text":
            context.user_data["save_hidden"] = False
            context.user_data["waiting_text"] = True
            await context.bot.send_message(
                q.message.chat_id,
                "📝 Отправь текст или ссылку:",
                reply_markup=home_button(uid)
            )
            return

        context.user_data["save_hidden"] = False
        await context.bot.send_message(
            q.message.chat_id,
            "📸 Отправь фото или видео — я сохраню его автоматически.",
            reply_markup=home_button(uid)
        )
        return

    if data == "gallery":
        await remove_old_button_message(q)

        con = db()
        rows = con.execute(
            "SELECT * FROM files WHERE user_id=? AND deleted=0 AND hidden=0 ORDER BY id ASC",
            (uid,)
        ).fetchall()
        con.close()

        if not rows:
            await context.bot.send_message(
                q.message.chat_id,
                "🖼 Галерея пока пустая.",
                reply_markup=home_button(uid)
            )
            return

        photos = [r for r in rows if r["kind"] == "photo"]
        videos = [r for r in rows if r["kind"] == "video"]
        texts = [r for r in rows if r["kind"] == "text"]

        for i in range(0, len(photos), 10):
            batch = photos[i:i + 10]
            await context.bot.send_media_group(
                q.message.chat_id,
                [InputMediaPhoto(r["file_id"]) for r in batch]
            )

        for r in videos:
            await context.bot.send_video(q.message.chat_id, r["file_id"])

        for r in texts:
            await context.bot.send_message(
                q.message.chat_id,
                f"📝 #{r['id']}\n{r['text']}"
            )

        await context.bot.send_message(
            q.message.chat_id,
            f"🖼 Галерея\nВсего открытых файлов: {len(rows)}",
            reply_markup=home_button(uid)
        )
        return

    if data == "hidden":
        await remove_old_button_message(q)

        if not get_pin_hash(uid):
            await context.bot.send_message(
                q.message.chat_id,
                "🔒 Скрытое хранилище ещё не настроено.\n\n"
                "Сначала установи PIN в настройках.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔐 Установить PIN", callback_data="pin_set")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="home")]
                ])
            )
            return

        context.user_data["waiting_hidden_pin"] = True
        await context.bot.send_message(
            q.message.chat_id,
            "🔐 Введи PIN-код для доступа к скрытым файлам:",
            reply_markup=home_button(uid)
        )
        return

    if data == "settings":
        await remove_old_button_message(q)
        await context.bot.send_message(
            q.message.chat_id,
            "⚙️ Настройки\n\n"
            "PIN нужен для доступа к скрытым фото и видео.",
            reply_markup=settings_menu(uid)
        )
        return

    if data == "pin_set":
        await remove_old_button_message(q)
        context.user_data["waiting_new_pin"] = True
        await context.bot.send_message(
            q.message.chat_id,
            "🔐 Придумай PIN-код из 4–6 цифр.\n\n"
            "Например: 4821\n\n"
            "Отправь только цифры.",
            reply_markup=home_button(uid)
        )
        return

    if data == "pin_remove":
        await remove_old_button_message(q)

        if not get_pin_hash(uid):
            await context.bot.send_message(
                q.message.chat_id,
                "PIN не установлен.",
                reply_markup=settings_menu(uid)
            )
            return

        context.user_data["waiting_remove_pin"] = True
        await context.bot.send_message(
            q.message.chat_id,
            "🔐 Введи текущий PIN, чтобы удалить его:",
            reply_markup=home_button(uid)
        )
        return

    if data == "trash":
        await remove_old_button_message(q)

        con = db()
        rows = con.execute(
            "SELECT * FROM files WHERE user_id=? AND deleted=1 ORDER BY id DESC",
            (uid,)
        ).fetchall()
        con.close()

        if not rows:
            await context.bot.send_message(
                q.message.chat_id,
                "🗑 Корзина пустая.",
                reply_markup=home_button(uid)
            )
            return

        buttons = [[
            InlineKeyboardButton(
                f"♻️ Восстановить #{r['id']}",
                callback_data=f"restore:{r['id']}"
            )
        ] for r in rows[:50]]

        buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])

        await context.bot.send_message(
            q.message.chat_id,
            "🗑 Корзина:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("restore:"):
        await remove_old_button_message(q)

        fid = int(data.split(":")[1])

        con = db()
        con.execute(
            "UPDATE files SET deleted=0 WHERE id=? AND user_id=?",
            (fid, uid)
        )
        con.commit()
        con.close()

        await context.bot.send_message(
            q.message.chat_id,
            f"♻️ Файл #{fid} восстановлен.",
            reply_markup=menu(uid)
        )
        return

    if data == "folders":
        await remove_old_button_message(q)

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

        buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])

        await context.bot.send_message(
            q.message.chat_id,
            "📁 Твои папки:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data == "folder_new":
        await remove_old_button_message(q)
        context.user_data["waiting_folder"] = True

        await context.bot.send_message(
            q.message.chat_id,
            "📁 Напиши название новой папки:",
            reply_markup=home_button(uid)
        )
        return

    if data.startswith("folder:"):
        await remove_old_button_message(q)

        folder_id = int(data.split(":")[1])

        con = db()
        folder = con.execute(
            "SELECT * FROM folders WHERE id=? AND user_id=?",
            (folder_id, uid)
        ).fetchone()

        rows = con.execute(
            """
            SELECT * FROM files
            WHERE folder_id=? AND user_id=? AND deleted=0 AND hidden=0
            ORDER BY id DESC
            """,
            (folder_id, uid)
        ).fetchall()
        con.close()

        if not folder:
            await context.bot.send_message(
                q.message.chat_id,
                "Папка не найдена.",
                reply_markup=home_button(uid)
            )
            return

        await context.bot.send_message(
            q.message.chat_id,
            f"📁 {folder['name']}\nФайлов: {len(rows)}"
        )

        for r in rows:
            if r["kind"] == "photo":
                await context.bot.send_photo(q.message.chat_id, r["file_id"])
            elif r["kind"] == "video":
                await context.bot.send_video(q.message.chat_id, r["file_id"])
            else:
                await context.bot.send_message(
                    q.message.chat_id,
                    f"📝 {r['text']}"
                )

        await send_home(q.message.chat_id, context)
        return

    # АДМИН-ПАНЕЛЬ
    if data == "admin":
        if uid != ADMIN_ID:
            return

        await remove_old_button_message(q)

        con = db()
        users = con.execute("SELECT * FROM users ORDER BY user_id").fetchall()
        total = con.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
        con.close()

        buttons = []

        for u in users[:50]:
            status = "🚫" if u["blocked"] else "🟢"
            name = u["username"] or u["first_name"] or str(u["user_id"])

            buttons.append([
                InlineKeyboardButton(
                    f"{status} {name}",
                    callback_data=f"adminuser:{u['user_id']}"
                )
            ])

        buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])

        await context.bot.send_message(
            q.message.chat_id,
            f"👑 АДМИН-ПАНЕЛЬ\n\n"
            f"Пользователей: {len(users)}\n"
            f"Файлов: {total}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("adminuser:"):
        if uid != ADMIN_ID:
            return

        await remove_old_button_message(q)

        target = int(data.split(":")[1])

        con = db()
        u = con.execute(
            "SELECT * FROM users WHERE user_id=?",
            (target,)
        ).fetchone()
        files = con.execute(
            "SELECT * FROM files WHERE user_id=?",
            (target,)
        ).fetchall()
        folders = con.execute(
            "SELECT * FROM folders WHERE user_id=?",
            (target,)
        ).fetchall()
        con.close()

        if not u:
            await context.bot.send_message(
                q.message.chat_id,
                "Пользователь не найден.",
                reply_markup=home_button(uid)
            )
            return

        buttons = [
            [InlineKeyboardButton(
                "🚫 Заблокировать" if not u["blocked"] else "✅ Разблокировать",
                callback_data=f"toggleblock:{target}"
            )],
            [InlineKeyboardButton(
                "📂 Показать файлы",
                callback_data=f"adminfiles:{target}"
            )],
            [InlineKeyboardButton(
                "📁 Показать папки",
                callback_data=f"adminfolders:{target}"
            )],
            [InlineKeyboardButton("👑 Админ-панель", callback_data="admin")]
        ]

        await context.bot.send_message(
            q.message.chat_id,
            f"👤 ID: {target}\n"
            f"Username: @{u['username'] or 'нет'}\n"
            f"Файлов: {len(files)}\n"
            f"Папок: {len(folders)}\n"
            f"Статус: {'🚫 заблокирован' if u['blocked'] else '🟢 активен'}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("toggleblock:"):
        if uid != ADMIN_ID:
            return

        await remove_old_button_message(q)

        target = int(data.split(":")[1])

        if target == ADMIN_ID:
            await context.bot.send_message(
                q.message.chat_id,
                "Себя блокировать нельзя.",
                reply_markup=home_button(uid)
            )
            return

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
            "🚫 Пользователь заблокирован." if new_value else "✅ Пользователь разблокирован.",
            reply_markup=menu(uid)
        )
        return

    if data.startswith("adminfiles:"):
        if uid != ADMIN_ID:
            return

        await remove_old_button_message(q)

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
            else:
                await context.bot.send_message(
                    q.message.chat_id,
                    f"{mark} #{r['id']}\n{r['text']}"
                )

        await send_home(q.message.chat_id, context)
        return

    if data.startswith("adminfolders:"):
        if uid != ADMIN_ID:
            return

        await remove_old_button_message(q)

        target = int(data.split(":")[1])

        con = db()
        rows = con.execute(
            "SELECT * FROM folders WHERE user_id=? ORDER BY id DESC",
            (target,)
        ).fetchall()
        con.close()

        if rows:
            await context.bot.send_message(
                q.message.chat_id,
                "📁 Папки:\n" +
                "\n".join(f"#{r['id']} — {r['name']}" for r in rows)
            )
        else:
            await context.bot.send_message(
                q.message.chat_id,
                "📁 Папок нет."
            )

        await send_home(q.message.chat_id, context)
        return


async def save_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    register_user(update.effective_user)

    con = db()
    row = con.execute(
        "SELECT blocked FROM users WHERE user_id=?",
        (uid,)
    ).fetchone()
    con.close()

    if row and row["blocked"] and uid != ADMIN_ID:
        return

    text = update.message.text.strip() if update.message.text else ""

    # Установка нового PIN
    if context.user_data.get("waiting_new_pin"):
        if not text.isdigit() or not 4 <= len(text) <= 6:
            await update.message.reply_text(
                "❌ PIN должен состоять только из 4–6 цифр.\nПопробуй ещё раз.",
                reply_markup=home_button(uid)
            )
            return

        set_pin(uid, text)
        context.user_data["waiting_new_pin"] = False

        await update.message.reply_text(
            "✅ PIN установлен.\n\n"
            "Теперь скрытые фото и видео будут защищены этим PIN.",
            reply_markup=settings_menu(uid)
        )
        return

    # Удаление PIN
    if context.user_data.get("waiting_remove_pin"):
        saved = get_pin_hash(uid)

        if not saved or saved != hash_pin(text):
            await update.message.reply_text(
                "❌ Неверный PIN.",
                reply_markup=home_button(uid)
            )
            return

        remove_pin(uid)
        context.user_data["waiting_remove_pin"] = False

        await update.message.reply_text(
            "✅ PIN удалён.",
            reply_markup=settings_menu(uid)
        )
        return

    # Вход в скрытое хранилище
    if context.user_data.get("waiting_hidden_pin"):
        saved = get_pin_hash(uid)

        if not saved or saved != hash_pin(text):
            await update.message.reply_text(
                "❌ Неверный PIN. Попробуй ещё раз.",
                reply_markup=home_button(uid)
            )
            return

        context.user_data["waiting_hidden_pin"] = False

        con = db()
        rows = con.execute(
            """
            SELECT * FROM files
            WHERE user_id=? AND hidden=1 AND deleted=0
            ORDER BY id DESC
            """,
            (uid,)
        ).fetchall()
        con.close()

        if not rows:
            await update.message.reply_text(
                "🔒 Скрытое хранилище пустое.",
                reply_markup=home_button(uid)
            )
            return

        await update.message.reply_text(
            f"🔒 Скрытые файлы: {len(rows)}"
        )

        for r in rows:
            if r["kind"] == "photo":
                await context.bot.send_photo(
                    uid,
                    r["file_id"],
                    caption=f"🔒 #{r['id']}"
                )
            elif r["kind"] == "video":
                await context.bot.send_video(
                    uid,
                    r["file_id"],
                    caption=f"🔒 #{r['id']}"
                )
            else:
                await context.bot.send_message(
                    uid,
                    f"🔒 #{r['id']}\n{r['text']}"
                )

        await context.bot.send_message(
            uid,
            "🔒 Скрытое хранилище открыто.",
            reply_markup=home_button(uid)
        )
        return

    # Создание папки
    if context.user_data.get("waiting_folder") and text:
        con = db()
        con.execute(
            "INSERT INTO folders(user_id,name) VALUES(?,?)",
            (uid, text)
        )
        con.commit()
        con.close()

        context.user_data["waiting_folder"] = False

        await update.message.reply_text(
            f"📁 Папка «{text}» создана.",
            reply_markup=menu(uid)
        )
        return

    # Обычное сохранение
    kind = None
    file_id = None
    save_text = None

    if update.message.photo:
        kind = "photo"
        file_id = update.message.photo[-1].file_id
    elif update.message.video:
        kind = "video"
        file_id = update.message.video.file_id
    elif update.message.text and not update.message.text.startswith("/"):
        kind = "text"
        save_text = update.message.text
    else:
        return

    hidden = 1 if context.user_data.get("save_hidden") else 0
    context.user_data["save_hidden"] = False
    context.user_data["waiting_text"] = False

    # Если пользователь выбрал скрытое, но отправил текст — тоже сохраняем скрытым.
    con = db()
    cur = con.execute(
        """
        INSERT INTO files(user_id,kind,file_id,text,hidden)
        VALUES(?,?,?,?,?)
        """,
        (uid, kind, file_id, save_text, hidden)
    )
    item_id = cur.lastrowid
    con.commit()
    con.close()

    if hidden:
        await update.message.reply_text(
            f"🔒 Скрыто сохранено — #{item_id}",
            reply_markup=menu(uid)
        )
    else:
        await update.message.reply_text(
            f"✅ Сохранено — #{item_id}",
            reply_markup=menu(uid)
        )


async def error_handler(update, context):
    print("ERROR:", context.error)


def main():
    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(
        filters.PHOTO |
        filters.VIDEO |
        (filters.TEXT & ~filters.COMMAND),
        save_message
    ))

    app.add_error_handler(error_handler)

    threading.Thread(target=start_server, daemon=True).start()
    print("MONNEY v5 + Mini App запущен.")
    app.run_polling()


if __name__ == "__main__":
    main()
