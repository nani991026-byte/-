import os
import sqlite3
import hashlib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("MONNEY_TOKEN")
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "monney.db")
ADMIN_ID = 8976178026

if not TOKEN:
    raise SystemExit("BOT_TOKEN не задан.")

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
    con.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        blocked INTEGER DEFAULT 0,
        pin_hash TEXT
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        folder_id INTEGER,
        kind TEXT NOT NULL,
        file_id TEXT,
        text TEXT,
        hidden INTEGER DEFAULT 0,
        deleted INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
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
    con.execute("""INSERT INTO users(user_id, username, first_name)
                   VALUES(?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                   username=excluded.username, first_name=excluded.first_name""",
                (user.id, user.username, user.first_name))
    con.commit()
    con.close()

def pin_hash(pin):
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()

def has_pin(uid):
    con = db()
    row = con.execute("SELECT pin_hash FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    return bool(row and row["pin_hash"])

def set_pin(uid, pin):
    con = db()
    con.execute("UPDATE users SET pin_hash=? WHERE user_id=?", (pin_hash(pin), uid))
    con.commit()
    con.close()

def remove_pin(uid):
    con = db()
    con.execute("UPDATE users SET pin_hash=NULL WHERE user_id=?", (uid,))
    con.commit()
    con.close()

def check_pin(uid, pin):
    con = db()
    row = con.execute("SELECT pin_hash FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    return bool(row and row["pin_hash"] == pin_hash(pin))

def main_menu(uid):
    rows = [
        [InlineKeyboardButton("➕ Добавить файл", callback_data="add"),
         InlineKeyboardButton("🗂 Галерея", callback_data="gallery")],
        [InlineKeyboardButton("📁 Папки", callback_data="folders"),
         InlineKeyboardButton("📝 Тексты и ссылки", callback_data="texts")],
        [InlineKeyboardButton("🙈 Скрытые файлы", callback_data="hidden"),
         InlineKeyboardButton("🗑 Корзина", callback_data="trash")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")]
    ]
    if uid == ADMIN_ID:
        rows.append([InlineKeyboardButton("👑 Админ-панель", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

def back_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="home")]])

async def delete_button_message(q):
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
        "💰 MONNEY\n\nТвоё личное хранилище.\nВыбери действие 👇",
        reply_markup=main_menu(chat_id)
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    await update.message.reply_text(
        "💰 MONNEY\n\n"
        "Твоё личное хранилище.\n"
        "Фото, видео, документы, тексты и ссылки можно хранить здесь.\n\n"
        "Файлы можно удалять, восстанавливать и прятать.\n"
        "В настройках можно установить PIN-код.",
        reply_markup=main_menu(update.effective_user.id)
    )

async def show_file(q, context, row, include_delete=True):
    uid = q.from_user.id
    mark = "🙈" if row["hidden"] else "📄"
    buttons = []
    if include_delete:
        buttons.append([
            InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{row['id']}")
        ])
    if row["kind"] == "photo":
        await context.bot.send_photo(q.message.chat_id, row["file_id"], caption=f"{mark} Файл #{row['id']}",
                                      reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)
    elif row["kind"] == "video":
        await context.bot.send_video(q.message.chat_id, row["file_id"], caption=f"{mark} Файл #{row['id']}",
                                     reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)
    else:
        text = row["text"] or ""
        await context.bot.send_message(q.message.chat_id, f"{mark} Файл #{row['id']}\n\n{text}",
                                       reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    register_user(q.from_user)
    data = q.data

    if data == "home":
        await delete_button_message(q)
        await send_home(q.message.chat_id, context)
        return

    if data == "add":
        await delete_button_message(q)
        context.user_data["upload_hidden"] = False
        await context.bot.send_message(
            q.message.chat_id,
            "➕ Добавление файла\n\n"
            "Отправь сюда фото, видео, документ или обычный текст.\n"
            "Файл сохранится автоматически.",
            reply_markup=back_menu()
        )
        return

    if data == "hidden":
        await delete_button_message(q)
        buttons = [
            [InlineKeyboardButton("➕ Добавить скрытый файл", callback_data="hidden_add")],
            [InlineKeyboardButton("👁 Показать скрытые", callback_data="hidden_list")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="home")]
        ]
        await context.bot.send_message(
            q.message.chat_id,
            "🙈 Скрытые файлы\n\n"
            "Скрытые файлы не показываются в обычной галерее.\n"
            "Они находятся только в этом разделе.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data == "hidden_add":
        await delete_button_message(q)
        context.user_data["upload_hidden"] = True
        await context.bot.send_message(
            q.message.chat_id,
            "🙈 Режим скрытой загрузки включён.\n\n"
            "Теперь отправь фото, видео, документ или текст.\n"
            "Он сохранится как скрытый.",
            reply_markup=back_menu()
        )
        return

    if data == "hidden_list":
        if not has_pin(uid):
            await delete_button_message(q)
            await context.bot.send_message(
                q.message.chat_id,
                "🔐 Сначала установи PIN-код в разделе «Настройки».",
                reply_markup=back_menu()
            )
            return
        await delete_button_message(q)
        context.user_data["awaiting_hidden_pin"] = True
        await context.bot.send_message(
            q.message.chat_id,
            "🔐 Введи PIN-код для просмотра скрытых файлов.",
            reply_markup=back_menu()
        )
        return

    if data == "gallery":
        await delete_button_message(q)
        con = db()
        rows = con.execute(
            "SELECT * FROM files WHERE user_id=? AND deleted=0 AND hidden=0 ORDER BY id DESC",
            (uid,)
        ).fetchall()
        con.close()
        if not rows:
            await context.bot.send_message(q.message.chat_id, "🗂 Галерея пока пустая.", reply_markup=back_menu())
            return
        await context.bot.send_message(q.message.chat_id, f"🗂 Галерея\nФайлов: {len(rows)}")
        for r in rows[:50]:
            await show_file(q, context, r)
        await context.bot.send_message(q.message.chat_id, "Готово.", reply_markup=back_menu())
        return

    if data == "texts":
        await delete_button_message(q)
        con = db()
        rows = con.execute(
            "SELECT * FROM files WHERE user_id=? AND kind='text' AND deleted=0 AND hidden=0 ORDER BY id DESC",
            (uid,)
        ).fetchall()
        con.close()
        if not rows:
            await context.bot.send_message(q.message.chat_id, "📝 Тексты и ссылки пока пустые.", reply_markup=back_menu())
            return
        for r in rows[:50]:
            await show_file(q, context, r)
        await context.bot.send_message(q.message.chat_id, "📝 Раздел открыт.", reply_markup=back_menu())
        return

    if data == "folders":
        await delete_button_message(q)
        con = db()
        rows = con.execute("SELECT * FROM folders WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
        con.close()
        buttons = [[InlineKeyboardButton("➕ Создать папку", callback_data="folder_new")]]
        for r in rows:
            buttons.append([InlineKeyboardButton(f"📁 {r['name']}", callback_data=f"folder:{r['id']}")])
        buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
        await context.bot.send_message(q.message.chat_id, "📁 Твои папки:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data == "folder_new":
        await delete_button_message(q)
        context.user_data["waiting_folder"] = True
        await context.bot.send_message(q.message.chat_id, "📁 Напиши название новой папки:", reply_markup=back_menu())
        return

    if data.startswith("folder:"):
        await delete_button_message(q)
        folder_id = int(data.split(":")[1])
        con = db()
        folder = con.execute("SELECT * FROM folders WHERE id=? AND user_id=?", (folder_id, uid)).fetchone()
        rows = con.execute(
            "SELECT * FROM files WHERE folder_id=? AND user_id=? AND deleted=0 ORDER BY id DESC",
            (folder_id, uid)
        ).fetchall()
        con.close()
        if not folder:
            await context.bot.send_message(q.message.chat_id, "Папка не найдена.", reply_markup=back_menu())
            return
        await context.bot.send_message(q.message.chat_id, f"📁 {folder['name']}\nФайлов: {len(rows)}")
        for r in rows[:50]:
            await show_file(q, context, r)
        await context.bot.send_message(q.message.chat_id, "Готово.", reply_markup=back_menu())
        return

    if data.startswith("delete:"):
        fid = int(data.split(":")[1])
        con = db()
        row = con.execute("SELECT * FROM files WHERE id=? AND user_id=? AND deleted=0", (fid, uid)).fetchone()
        if row:
            con.execute("UPDATE files SET deleted=1 WHERE id=? AND user_id=?", (fid, uid))
            con.commit()
        con.close()
        await delete_button_message(q)
        await context.bot.send_message(
            q.message.chat_id,
            f"🗑 Файл #{fid} перемещён в корзину.\nЕго можно восстановить.",
            reply_markup=main_menu(uid)
        )
        return

    if data == "trash":
        await delete_button_message(q)
        con = db()
        rows = con.execute("SELECT * FROM files WHERE user_id=? AND deleted=1 ORDER BY id DESC", (uid,)).fetchall()
        con.close()
        if not rows:
            await context.bot.send_message(q.message.chat_id, "🗑 Корзина пустая.", reply_markup=back_menu())
            return
        buttons = []
        for r in rows[:50]:
            buttons.append([
                InlineKeyboardButton(f"♻️ Восстановить #{r['id']}", callback_data=f"restore:{r['id']}")
            ])
        buttons.append([InlineKeyboardButton("🧹 Очистить корзину", callback_data="trash_clear")])
        buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
        await context.bot.send_message(q.message.chat_id, "🗑 Корзина:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("restore:"):
        fid = int(data.split(":")[1])
        con = db()
        con.execute("UPDATE files SET deleted=0 WHERE id=? AND user_id=?", (fid, uid))
        con.commit()
        con.close()
        await delete_button_message(q)
        await context.bot.send_message(q.message.chat_id, f"♻️ Файл #{fid} восстановлен.", reply_markup=main_menu(uid))
        return

    if data == "trash_clear":
        await delete_button_message(q)
        con = db()
        con.execute("DELETE FROM files WHERE user_id=? AND deleted=1", (uid,))
        con.commit()
        con.close()
        await context.bot.send_message(q.message.chat_id, "🧹 Корзина очищена окончательно.", reply_markup=main_menu(uid))
        return

    if data == "settings":
        await delete_button_message(q)
        pin_status = "✅ PIN установлен" if has_pin(uid) else "❌ PIN не установлен"
        buttons = [
            [InlineKeyboardButton("🔐 Установить / изменить PIN", callback_data="pin_set")],
            [InlineKeyboardButton("🔓 Удалить PIN", callback_data="pin_remove")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="home")]
        ]
        await context.bot.send_message(
            q.message.chat_id,
            f"⚙️ Настройки\n\n{pin_status}\n\n"
            "PIN используется для доступа к скрытым файлам.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data == "pin_set":
        await delete_button_message(q)
        context.user_data["awaiting_pin"] = True
        await context.bot.send_message(q.message.chat_id, "🔐 Введи новый PIN (4–8 цифр):", reply_markup=back_menu())
        return

    if data == "pin_remove":
        await delete_button_message(q)
        if not has_pin(uid):
            await context.bot.send_message(q.message.chat_id, "PIN ещё не установлен.", reply_markup=main_menu(uid))
            return
        context.user_data["awaiting_remove_pin"] = True
        await context.bot.send_message(q.message.chat_id, "🔓 Введи текущий PIN для удаления:", reply_markup=back_menu())
        return

    # Админ
    if data == "admin":
        if uid != ADMIN_ID:
            return
        await delete_button_message(q)
        con = db()
        users = con.execute("SELECT * FROM users ORDER BY user_id").fetchall()
        total = con.execute("SELECT COUNT(*) n FROM files").fetchone()["n"]
        con.close()
        buttons = []
        for u in users[:50]:
            status = "🚫" if u["blocked"] else "🟢"
            name = u["username"] or u["first_name"] or str(u["user_id"])
            buttons.append([InlineKeyboardButton(f"{status} {name}", callback_data=f"adminuser:{u['user_id']}")])
        buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
        await context.bot.send_message(
            q.message.chat_id,
            f"👑 АДМИН-ПАНЕЛЬ\n\nПользователей: {len(users)}\nФайлов: {total}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("adminuser:") and uid == ADMIN_ID:
        await delete_button_message(q)
        target = int(data.split(":")[1])
        con = db()
        u = con.execute("SELECT * FROM users WHERE user_id=?", (target,)).fetchone()
        files = con.execute("SELECT COUNT(*) n FROM files WHERE user_id=?", (target,)).fetchone()["n"]
        folders = con.execute("SELECT COUNT(*) n FROM folders WHERE user_id=?", (target,)).fetchone()["n"]
        con.close()
        if not u:
            await context.bot.send_message(q.message.chat_id, "Пользователь не найден.", reply_markup=main_menu(uid))
            return
        buttons = [
            [InlineKeyboardButton("🚫 Заблокировать" if not u["blocked"] else "✅ Разблокировать",
                                  callback_data=f"toggleblock:{target}")],
            [InlineKeyboardButton("📂 Показать файлы", callback_data=f"adminfiles:{target}")],
            [InlineKeyboardButton("📁 Показать папки", callback_data=f"adminfolders:{target}")],
            [InlineKeyboardButton("👑 Назад", callback_data="admin")]
        ]
        await context.bot.send_message(
            q.message.chat_id,
            f"👤 ID: {target}\nUsername: @{u['username'] or 'нет'}\n"
            f"Файлов: {files}\nПапок: {folders}\n"
            f"Статус: {'🚫 заблокирован' if u['blocked'] else '🟢 активен'}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("toggleblock:") and uid == ADMIN_ID:
        target = int(data.split(":")[1])
        if target == ADMIN_ID:
            await q.answer("Себя блокировать нельзя.", show_alert=True)
            return
        con = db()
        row = con.execute("SELECT blocked FROM users WHERE user_id=?", (target,)).fetchone()
        new_value = 0 if row and row["blocked"] else 1
        con.execute("UPDATE users SET blocked=? WHERE user_id=?", (new_value, target))
        con.commit()
        con.close()
        await delete_button_message(q)
        await context.bot.send_message(
            q.message.chat_id,
            "🚫 Пользователь заблокирован." if new_value else "✅ Пользователь разблокирован.",
            reply_markup=main_menu(uid)
        )
        return

    if data.startswith("adminfiles:") and uid == ADMIN_ID:
        await delete_button_message(q)
        target = int(data.split(":")[1])
        con = db()
        rows = con.execute("SELECT * FROM files WHERE user_id=? ORDER BY id DESC", (target,)).fetchall()
        con.close()
        await context.bot.send_message(q.message.chat_id, f"📂 Файлы пользователя {target}: {len(rows)}")
        for r in rows[:50]:
            await show_file(q, context, r, include_delete=False)
        await context.bot.send_message(q.message.chat_id, "Готово.", reply_markup=main_menu(uid))
        return

    if data.startswith("adminfolders:") and uid == ADMIN_ID:
        await delete_button_message(q)
        target = int(data.split(":")[1])
        con = db()
        rows = con.execute("SELECT * FROM folders WHERE user_id=? ORDER BY id DESC", (target,)).fetchall()
        con.close()
        text = "📁 Папки:\n" + ("\n".join(f"#{r['id']} — {r['name']}" for r in rows) if rows else "Папок нет.")
        await context.bot.send_message(q.message.chat_id, text, reply_markup=main_menu(uid))
        return

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    register_user(update.effective_user)

    con = db()
    row = con.execute("SELECT blocked FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    if row and row["blocked"] and uid != ADMIN_ID:
        return

    text = update.message.text or ""

    if context.user_data.pop("awaiting_hidden_pin", False):
        if check_pin(uid, text.strip()):
            con = db()
            rows = con.execute(
                "SELECT * FROM files WHERE user_id=? AND hidden=1 AND deleted=0 ORDER BY id DESC",
                (uid,)
            ).fetchall()
            con.close()
            if not rows:
                await update.message.reply_text("🙈 Скрытых файлов пока нет.", reply_markup=main_menu(uid))
            else:
                await update.message.reply_text(f"🙈 Скрытых файлов: {len(rows)}")
                # Скрытые файлы показываем только после правильного PIN.
                for r in rows[:50]:
                    buttons = [[InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{r['id']}")]]
                    if r["kind"] == "photo":
                        await update.message.reply_photo(r["file_id"], caption=f"🙈 #{r['id']}",
                                                         reply_markup=InlineKeyboardMarkup(buttons))
                    elif r["kind"] == "video":
                        await update.message.reply_video(r["file_id"], caption=f"🙈 #{r['id']}",
                                                        reply_markup=InlineKeyboardMarkup(buttons))
                    else:
                        await update.message.reply_text(f"🙈 #{r['id']}\n\n{r['text']}",
                                                        reply_markup=InlineKeyboardMarkup(buttons))
                await update.message.reply_text("Готово.", reply_markup=main_menu(uid))
        else:
            await update.message.reply_text("❌ Неверный PIN.", reply_markup=back_menu())
        return

    if context.user_data.pop("awaiting_pin", False):
        if text.isdigit() and 4 <= len(text) <= 8:
            set_pin(uid, text)
            await update.message.reply_text("✅ PIN установлен.", reply_markup=main_menu(uid))
        else:
            context.user_data["awaiting_pin"] = True
            await update.message.reply_text("❌ PIN должен содержать 4–8 цифр. Попробуй ещё раз.", reply_markup=back_menu())
        return

    if context.user_data.pop("awaiting_remove_pin", False):
        if check_pin(uid, text.strip()):
            remove_pin(uid)
            await update.message.reply_text("🔓 PIN удалён.", reply_markup=main_menu(uid))
        else:
            context.user_data["awaiting_remove_pin"] = True
            await update.message.reply_text("❌ Неверный PIN.", reply_markup=back_menu())
        return

    if context.user_data.pop("waiting_folder", False):
        name = text.strip()
        if name:
            con = db()
            con.execute("INSERT INTO folders(user_id,name) VALUES(?,?)", (uid, name))
            con.commit()
            con.close()
            await update.message.reply_text(f"📁 Папка «{name}» создана.", reply_markup=main_menu(uid))
        else:
            await update.message.reply_text("Название пустое.", reply_markup=back_menu())
        return

    if text.startswith("/"):
        return

    hidden = bool(context.user_data.pop("upload_hidden", False))
    con = db()
    cur = con.execute(
        "INSERT INTO files(user_id, kind, text, hidden) VALUES(?,?,?,?)",
        (uid, "text", text, 1 if hidden else 0)
    )
    fid = cur.lastrowid
    con.commit()
    con.close()
    await update.message.reply_text(
        f"{'🙈 Скрыто сохранено' if hidden else '✅ Сохранено'} — #{fid}",
        reply_markup=main_menu(uid)
    )

async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    register_user(update.effective_user)

    con = db()
    row = con.execute("SELECT blocked FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    if row and row["blocked"] and uid != ADMIN_ID:
        return

    hidden = bool(context.user_data.pop("upload_hidden", False))
    kind = None
    file_id = None

    if update.message.photo:
        kind, file_id = "photo", update.message.photo[-1].file_id
    elif update.message.video:
        kind, file_id = "video", update.message.video.file_id
    elif update.message.document:
        kind, file_id = "document", update.message.document.file_id
    else:
        return

    con = db()
    cur = con.execute(
        "INSERT INTO files(user_id, kind, file_id, hidden) VALUES(?,?,?,?)",
        (uid, kind, file_id, 1 if hidden else 0)
    )
    fid = cur.lastrowid
    con.commit()
    con.close()
    await update.message.reply_text(
        f"{'🙈 Скрыто сохранено' if hidden else '✅ Сохранено'} — #{fid}",
        reply_markup=main_menu(uid)
    )

async def error_handler(update, context):
    print("ERROR:", repr(context.error))

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, file_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error_handler)
    print("MONNEY v7 запущен.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
