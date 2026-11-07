import os
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("MONNEY_TOKEN")
DATA_DIR = os.getenv("DATA_DIR", "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "monney.db")
ADMIN_ID = 8976178026

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
    # Миграция старой базы: добавляем новые поля, не удаляя старые данные.
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

def menu(uid):
    rows = [
        [InlineKeyboardButton("➕ Добавить файл", callback_data="add"),
         InlineKeyboardButton("🗂 Галерея", callback_data="gallery")],
        [InlineKeyboardButton("📁 Папки", callback_data="folders"),
         InlineKeyboardButton("📝 Тексты и ссылки", callback_data="texts")],
        [InlineKeyboardButton("🗑 Корзина", callback_data="trash"),
         InlineKeyboardButton("⚙️ Настройки", callback_data="settings")]
    ]
    if uid == ADMIN_ID:
        rows.append([InlineKeyboardButton("👑 Админ-панель", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

def home_button(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="home")]
    ])

async def send_home(chat_id, context):
    await context.bot.send_message(
        chat_id,
        "💰 MONNEY\n\nВыбери действие:",
        reply_markup=menu(chat_id)
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    await update.message.reply_text(
        "💰 MONNEY\n\nТвоё личное хранилище.\nФото, видео, тексты и ссылки сохраняются здесь.",
        reply_markup=menu(update.effective_user.id)
    )

async def remove_old_button_message(q):
    # Кнопки старого экрана исчезают полностью.
    try:
        await q.message.delete()
    except Exception:
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

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
            "➕ Отправь фото, видео или текст.\nЯ сохраню его автоматически.",
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
                q.message.chat_id, "🗂 Галерея пока пустая.",
                reply_markup=home_button(uid)
            )
            return

        photos = [r for r in rows if r["kind"] == "photo"]
        videos = [r for r in rows if r["kind"] == "video"]
        texts = [r for r in rows if r["kind"] == "text"]

        # Telegram позволяет до 10 элементов в одном media group.
        for i in range(0, len(photos), 10):
            batch = photos[i:i+10]
            await context.bot.send_media_group(
                q.message.chat_id,
                [InputMediaPhoto(r["file_id"]) for r in batch]
            )

        for r in videos:
            await context.bot.send_video(q.message.chat_id, r["file_id"])

        for r in texts:
            await context.bot.send_message(q.message.chat_id, f"📝 #{r['id']}\n{r['text']}")

        await context.bot.send_message(
            q.message.chat_id,
            f"🗂 Галерея открыта\nВсего файлов: {len(rows)}",
            reply_markup=home_button(uid)
        )
        return

    if data == "texts":
        await remove_old_button_message(q)
        con = db()
        rows = con.execute(
            "SELECT * FROM files WHERE user_id=? AND kind='text' AND deleted=0 AND hidden=0 ORDER BY id DESC",
            (uid,)
        ).fetchall()
        con.close()
        if not rows:
            await context.bot.send_message(
                q.message.chat_id, "📝 Тексты и ссылки пока пустые.",
                reply_markup=home_button(uid)
            )
            return
        for r in rows:
            await context.bot.send_message(q.message.chat_id, f"📝 #{r['id']}\n{r['text']}")
        await send_home(q.message.chat_id, context)
        return

    if data == "folders":
        await remove_old_button_message(q)
        con = db()
        rows = con.execute(
            "SELECT * FROM folders WHERE user_id=? ORDER BY id DESC", (uid,)
        ).fetchall()
        con.close()
        buttons = [[InlineKeyboardButton("➕ Создать папку", callback_data="folder_new")]]
        for r in rows:
            buttons.append([InlineKeyboardButton(
                f"📁 {r['name']}", callback_data=f"folder:{r['id']}"
            )])
        buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
        await context.bot.send_message(
            q.message.chat_id, "📁 Твои папки:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data == "folder_new":
        await remove_old_button_message(q)
        context.user_data["waiting_folder"] = True
        await context.bot.send_message(
            q.message.chat_id, "📁 Напиши название новой папки:",
            reply_markup=home_button(uid)
        )
        return

    if data.startswith("folder:"):
        await remove_old_button_message(q)
        folder_id = int(data.split(":")[1])
        con = db()
        folder = con.execute(
            "SELECT * FROM folders WHERE id=? AND user_id=?", (folder_id, uid)
        ).fetchone()
        rows = con.execute(
            "SELECT * FROM files WHERE folder_id=? AND user_id=? AND deleted=0 AND hidden=0 ORDER BY id DESC",
            (folder_id, uid)
        ).fetchall()
        con.close()
        if not folder:
            await context.bot.send_message(q.message.chat_id, "Папка не найдена.", reply_markup=home_button(uid))
            return
        await context.bot.send_message(q.message.chat_id, f"📁 {folder['name']}\nФайлов: {len(rows)}")
        for r in rows:
            if r["kind"] == "photo":
                await context.bot.send_photo(q.message.chat_id, r["file_id"])
            elif r["kind"] == "video":
                await context.bot.send_video(q.message.chat_id, r["file_id"])
            else:
                await context.bot.send_message(q.message.chat_id, f"📝 {r['text']}")
        await send_home(q.message.chat_id, context)
        return

    if data == "trash":
        await remove_old_button_message(q)
        con = db()
        rows = con.execute(
            "SELECT * FROM files WHERE user_id=? AND deleted=1 ORDER BY id DESC", (uid,)
        ).fetchall()
        con.close()
        if not rows:
            await context.bot.send_message(q.message.chat_id, "🗑 Корзина пустая.", reply_markup=home_button(uid))
            return
        buttons = [[InlineKeyboardButton(
            f"♻️ Восстановить #{r['id']}", callback_data=f"restore:{r['id']}"
        )] for r in rows[:50]]
        buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
        await context.bot.send_message(
            q.message.chat_id, "🗑 Корзина:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("restore:"):
        await remove_old_button_message(q)
        fid = int(data.split(":")[1])
        con = db()
        con.execute("UPDATE files SET deleted=0 WHERE id=? AND user_id=?", (fid, uid))
        con.commit()
        con.close()
        await context.bot.send_message(
            q.message.chat_id, f"♻️ Файл #{fid} восстановлен.",
            reply_markup=menu(uid)
        )
        return

    if data == "settings":
        await remove_old_button_message(q)
        await context.bot.send_message(
            q.message.chat_id,
            "⚙️ Настройки\n\nPIN и отдельное защищённое хранилище добавим следующим этапом.",
            reply_markup=home_button(uid)
        )
        return

    # АДМИН
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
            buttons.append([InlineKeyboardButton(
                f"{status} {name}", callback_data=f"adminuser:{u['user_id']}"
            )])
        buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
        await context.bot.send_message(
            q.message.chat_id,
            f"👑 АДМИН-ПАНЕЛЬ\n\nПользователей: {len(users)}\nФайлов: {total}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("adminuser:"):
        if uid != ADMIN_ID:
            return
        await remove_old_button_message(q)
        target = int(data.split(":")[1])
        con = db()
        u = con.execute("SELECT * FROM users WHERE user_id=?", (target,)).fetchone()
        files = con.execute("SELECT * FROM files WHERE user_id=?", (target,)).fetchall()
        folders = con.execute("SELECT * FROM folders WHERE user_id=?", (target,)).fetchall()
        con.close()
        if not u:
            await context.bot.send_message(q.message.chat_id, "Пользователь не найден.", reply_markup=home_button(uid))
            return
        buttons = [
            [InlineKeyboardButton(
                "🚫 Заблокировать" if not u["blocked"] else "✅ Разблокировать",
                callback_data=f"toggleblock:{target}"
            )],
            [InlineKeyboardButton("📂 Показать файлы", callback_data=f"adminfiles:{target}")],
            [InlineKeyboardButton("📁 Показать папки", callback_data=f"adminfolders:{target}")],
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
            await context.bot.send_message(q.message.chat_id, "Себя блокировать нельзя.", reply_markup=home_button(uid))
            return
        con = db()
        row = con.execute("SELECT blocked FROM users WHERE user_id=?", (target,)).fetchone()
        new_value = 0 if row and row["blocked"] else 1
        con.execute("UPDATE users SET blocked=? WHERE user_id=?", (new_value, target))
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
        rows = con.execute("SELECT * FROM files WHERE user_id=? ORDER BY id DESC", (target,)).fetchall()
        con.close()
        await context.bot.send_message(q.message.chat_id, f"📂 Файлы пользователя {target}: {len(rows)}")
        for r in rows[:50]:
            mark = "🗑" if r["deleted"] else ("🙈" if r["hidden"] else "📄")
            if r["kind"] == "photo":
                await context.bot.send_photo(q.message.chat_id, r["file_id"], caption=f"{mark} #{r['id']}")
            elif r["kind"] == "video":
                await context.bot.send_video(q.message.chat_id, r["file_id"], caption=f"{mark} #{r['id']}")
            else:
                await context.bot.send_message(q.message.chat_id, f"{mark} #{r['id']}\n{r['text']}")
        await send_home(q.message.chat_id, context)
        return

    if data.startswith("adminfolders:"):
        if uid != ADMIN_ID:
            return
        await remove_old_button_message(q)
        target = int(data.split(":")[1])
        con = db()
        rows = con.execute("SELECT * FROM folders WHERE user_id=? ORDER BY id DESC", (target,)).fetchall()
        con.close()
        if rows:
            await context.bot.send_message(
                q.message.chat_id,
                "📁 Папки:\n" + "\n".join(f"#{r['id']} — {r['name']}" for r in rows)
            )
        else:
            await context.bot.send_message(q.message.chat_id, "📁 Папок нет.")
        await send_home(q.message.chat_id, context)
        return

async def save_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    register_user(update.effective_user)

    con = db()
    row = con.execute("SELECT blocked FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    if row and row["blocked"] and uid != ADMIN_ID:
        return

    if context.user_data.get("waiting_folder") and update.message.text:
        name = update.message.text.strip()
        if name:
            con = db()
            con.execute("INSERT INTO folders(user_id,name) VALUES(?,?)", (uid, name))
            con.commit()
            con.close()
            context.user_data["waiting_folder"] = False
            await update.message.reply_text(
                f"📁 Папка «{name}» создана.",
                reply_markup=menu(uid)
            )
        return

    kind = None
    file_id = None
    text = None

    if update.message.photo:
        kind = "photo"
        file_id = update.message.photo[-1].file_id
    elif update.message.video:
        kind = "video"
        file_id = update.message.video.file_id
    elif update.message.text and not update.message.text.startswith("/"):
        kind = "text"
        text = update.message.text
    else:
        return

    con = db()
    cur = con.execute(
        "INSERT INTO files(user_id,kind,file_id,text) VALUES(?,?,?,?)",
        (uid, kind, file_id, text)
    )
    item_id = cur.lastrowid
    con.commit()
    con.close()

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
        filters.PHOTO | filters.VIDEO | (filters.TEXT & ~filters.COMMAND),
        save_message
    ))
    app.add_error_handler(error_handler)
    print("MONNEY запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()
