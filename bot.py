
import os
import sqlite3
import hashlib
import asyncio
from datetime import datetime, timezone

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
)
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

# ---------------- DATABASE ----------------

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

    # Safe migrations: never recreate or delete the existing DB.
    for table, column, definition in [
        ("users", "username", "TEXT"),
        ("users", "first_name", "TEXT"),
        ("users", "blocked", "INTEGER DEFAULT 0"),
        ("users", "pin_hash", "TEXT"),
        ("files", "folder_id", "INTEGER"),
        ("files", "hidden", "INTEGER DEFAULT 0"),
        ("files", "deleted", "INTEGER DEFAULT 0"),
        ("files", "favorite", "INTEGER DEFAULT 0"),
        ("files", "title", "TEXT"),
    ]:
        ensure_column(con, table, column, definition)

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


# ---------------- UI HELPERS ----------------

def main_menu(uid):
    rows = [
        [InlineKeyboardButton("➕ Добавить файл", callback_data="add")],
        [
            InlineKeyboardButton("📸 Галерея", callback_data="gallery"),
            InlineKeyboardButton("📁 Папки", callback_data="folders"),
        ],
        [
            InlineKeyboardButton("⭐ Избранное", callback_data="favorites"),
            InlineKeyboardButton("🕘 Недавние", callback_data="recent"),
        ],
        [
            InlineKeyboardButton("🔎 Поиск", callback_data="search"),
            InlineKeyboardButton("🙈 Скрытые", callback_data="hidden"),
        ],
        [
            InlineKeyboardButton("🗑 Корзина", callback_data="trash"),
            InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
        ],
    ]
    if uid == ADMIN_ID:
        rows.append([InlineKeyboardButton("👑 Админ-панель", callback_data="admin")])
    return InlineKeyboardMarkup(rows)


def back_home():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="home")]
    ])


def gallery_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Все фотографии", callback_data="allphotos")],
        [InlineKeyboardButton("🖼 Фото по одной", callback_data="photo_view")],
        [
            InlineKeyboardButton("🎥 Видео", callback_data="videos"),
            InlineKeyboardButton("📄 Документы", callback_data="documents"),
        ],
        [InlineKeyboardButton("📝 Тексты", callback_data="texts")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="home")],
    ])


def icon_for(kind):
    return {"photo": "📸", "video": "🎥", "document": "📄", "text": "📝"}.get(kind, "📦")


def display_title(row):
    title = (row["title"] or "").strip()
    if title:
        return title[:40]
    if row["kind"] == "text":
        text = (row["text"] or "").replace("\n", " ").strip()
        return (text[:37] + "...") if len(text) > 40 else (text or f"Текст #{row['id']}")
    return f"Файл #{row['id']}"


def short_date(value):
    if not value:
        return ""
    return str(value)[:16]


def file_buttons(row, back_callback="gallery"):
    fid = row["id"]
    fav = "☆ В избранное" if not row["favorite"] else "⭐ Убрать из избранного"
    buttons = [
        [
            InlineKeyboardButton("👁 Показать", callback_data=f"show:{fid}"),
            InlineKeyboardButton(fav, callback_data=f"fav:{fid}"),
        ],
        [
            InlineKeyboardButton("✏️ Переименовать", callback_data=f"rename:{fid}"),
            InlineKeyboardButton("📁 Переместить", callback_data=f"move:{fid}"),
        ],
        [
            InlineKeyboardButton(
                "🙈 Скрыть" if not row["hidden"] else "👁 Сделать обычным",
                callback_data=f"hide:{fid}" if not row["hidden"] else f"unhide:{fid}",
            ),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{fid}"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)],
    ]
    return InlineKeyboardMarkup(buttons)


async def safe_delete(message):
    try:
        await message.delete()
    except Exception:
        pass


async def replace_callback_message(query):
    await query.answer()
    await safe_delete(query.message)


async def send_home(chat_id, context, uid):
    await context.bot.send_message(
        chat_id,
        "☁️ MONNEY\n\nТвоё личное хранилище.\n\nВыбери действие 👇",
        reply_markup=main_menu(uid),
    )


def get_rows(uid, where="deleted=0 AND hidden=0", params=(), order="id DESC"):
    con = db()
    rows = con.execute(
        f"SELECT * FROM files WHERE user_id=? AND {where} ORDER BY {order}",
        (uid, *params),
    ).fetchall()
    con.close()
    return rows


def get_file(uid, fid):
    con = db()
    row = con.execute(
        "SELECT * FROM files WHERE id=? AND user_id=?", (fid, uid)
    ).fetchone()
    con.close()
    return row


# ---------------- START / HOME ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    context.user_data.clear()
    if is_blocked(user.id) and user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        "☁️ MONNEY\n\n"
        "Личное хранилище внутри Telegram.\n\n"
        "📸 Фото • 🎥 Видео • 📄 Документы\n"
        "📁 Папки • ⭐ Избранное • 🙈 Скрытые\n\n"
        "Выбери действие 👇",
        reply_markup=main_menu(user.id),
    )


async def home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if is_blocked(uid) and uid != ADMIN_ID:
        await q.answer("Доступ заблокирован.", show_alert=True)
        return
    context.user_data.clear()
    await replace_callback_message(q)
    await send_home(q.message.chat_id, context, uid)


# ---------------- ADD / HIDDEN ----------------

async def add_screen(query, context):
    uid = query.from_user.id
    await replace_callback_message(query)
    context.user_data["add_mode"] = True
    context.user_data["hidden_mode"] = False
    await context.bot.send_message(
        query.message.chat_id,
        "➕ Добавление файлов\n\n"
        "Отправляй фото, видео, документы или текст.\n"
        "Можно отправлять несколько фотографий альбомом — MONNEY сохранит все.\n\n"
        "Режим сохранения: ☁️ обычный",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🙈 Включить скрытый режим", callback_data="hidden_upload")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="home")],
        ]),
    )


async def hidden_screen(query, context):
    uid = query.from_user.id
    con = db()
    pin = con.execute("SELECT pin_hash FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    if not pin or not pin["pin_hash"]:
        await query.answer("Сначала установи PIN в настройках.", show_alert=True)
        return

    await replace_callback_message(query)
    context.user_data.clear()
    await context.bot.send_message(
        query.message.chat_id,
        "🙈 Скрытые файлы\n\nВыбери действие:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🙈 Открыть скрытые файлы", callback_data="hidden_list")],
            [InlineKeyboardButton("➕ Сохранить новое скрыто", callback_data="hidden_upload")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="home")],
        ]),
    )


async def hidden_upload(query, context):
    uid = query.from_user.id
    con = db()
    pin = con.execute("SELECT pin_hash FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    if not pin or not pin["pin_hash"]:
        await query.answer("Сначала установи PIN в настройках.", show_alert=True)
        return
    await replace_callback_message(query)
    context.user_data["add_mode"] = True
    context.user_data["hidden_mode"] = True
    await context.bot.send_message(
        query.message.chat_id,
        "🙈 Скрытый режим включён.\n\n"
        "Отправляй один или несколько файлов. Все новые файлы будут скрыты.\n"
        "Когда закончишь, нажми «Готово».",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Готово", callback_data="home")],
        ]),
    )


async def hidden_list(query, context):
    uid = query.from_user.id
    await replace_callback_message(query)
    rows = get_rows(uid, "deleted=0 AND hidden=1")
    if not rows:
        await context.bot.send_message(
            query.message.chat_id,
            "🙈 Скрытых файлов пока нет.",
            reply_markup=back_home(),
        )
        return
    buttons = []
    for r in rows[:100]:
        buttons.append([InlineKeyboardButton(
            f"{icon_for(r['kind'])} {display_title(r)}",
            callback_data=f"file:{r['id']}"
        )])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    await context.bot.send_message(
        query.message.chat_id,
        f"🙈 Скрытые файлы\n\nВсего: {len(rows)}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ---------------- GALLERY ----------------

async def gallery(query, context):
    uid = query.from_user.id
    await replace_callback_message(query)
    rows = get_rows(uid)
    if not rows:
        await context.bot.send_message(
            query.message.chat_id,
            "📸 Галерея пока пуста.",
            reply_markup=back_home(),
        )
        return
    await context.bot.send_message(
        query.message.chat_id,
        f"📸 Галерея\n\n"
        f"Всего файлов: {len(rows)}\n"
        f"Фото: {sum(r['kind']=='photo' for r in rows)}\n"
        f"Видео: {sum(r['kind']=='video' for r in rows)}\n"
        f"Документы: {sum(r['kind']=='document' for r in rows)}\n\n"
        "Выбери режим просмотра:",
        reply_markup=gallery_menu(),
    )


async def all_photos(query, context):
    uid = query.from_user.id
    await replace_callback_message(query)
    rows = get_rows(uid, "deleted=0 AND hidden=0 AND kind='photo'", order="id ASC")
    if not rows:
        await context.bot.send_message(
            query.message.chat_id, "📸 Фотографий пока нет.", reply_markup=back_home()
        )
        return

    await context.bot.send_message(
        query.message.chat_id,
        f"📸 Все фотографии\n\n{len(rows)} фото.\n"
        "Они отправляются альбомами по 10, чтобы их можно было сразу листать.",
    )
    for start in range(0, len(rows), 10):
        chunk = rows[start:start+10]
        media = [
            InputMediaPhoto(
                r["file_id"],
                caption=(
                    f"📸 {display_title(r)}\n"
                    f"{start+i+1}/{len(rows)}"
                ) if i == 0 else None,
            )
            for i, r in enumerate(chunk)
        ]
        try:
            await context.bot.send_media_group(query.message.chat_id, media=media)
        except Exception as exc:
            # Fallback: send individually if a media group contains an invalid item.
            print("MEDIA GROUP ERROR:", repr(exc))
            for r in chunk:
                try:
                    await context.bot.send_photo(
                        query.message.chat_id,
                        r["file_id"],
                        caption=f"📸 {display_title(r)}",
                    )
                except Exception as one_exc:
                    print("PHOTO ERROR:", repr(one_exc))
    await context.bot.send_message(
        query.message.chat_id,
        "Готово. Все фотографии отправлены.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 Галерея", callback_data="gallery")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="home")],
        ]),
    )


# ---------------- SINGLE VIEWER ----------------

async def photo_view(query, context, offset=0):
    uid = query.from_user.id
    rows = get_rows(uid, "deleted=0 AND hidden=0 AND kind='photo'", order="id ASC")
    if not rows:
        await replace_callback_message(query)
        await context.bot.send_message(query.message.chat_id, "📸 Фото нет.", reply_markup=back_home())
        return

    offset = max(0, min(offset, len(rows)-1))
    row = rows[offset]
    await query.answer()

    # For a callback from a text control message, delete it and render a clean viewer.
    await safe_delete(query.message)

    caption = (
        f"📸 {display_title(row)}\n"
        f"{offset+1} / {len(rows)}\n"
        f"Сохранено: {short_date(row['created_at'])}"
    )
    await context.bot.send_photo(
        query.message.chat_id,
        row["file_id"],
        caption=caption,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⬅️", callback_data=f"pv:{offset-1}"),
                InlineKeyboardButton("➡️", callback_data=f"pv:{offset+1}"),
            ],
            [
                InlineKeyboardButton("👁 Показать", callback_data=f"show:{row['id']}"),
                InlineKeyboardButton(
                    "⭐" if not row["favorite"] else "⭐✓",
                    callback_data=f"fav:{row['id']}",
                ),
            ],
            [
                InlineKeyboardButton("✏️", callback_data=f"rename:{row['id']}"),
                InlineKeyboardButton("📁", callback_data=f"move:{row['id']}"),
                InlineKeyboardButton("🗑", callback_data=f"delete:{row['id']}"),
            ],
            [InlineKeyboardButton("⬅️ Галерея", callback_data="gallery")],
        ]),
    )


async def open_file(query, context, fid):
    uid = query.from_user.id
    row = get_file(uid, fid)
    if not row or row["deleted"]:
        await query.answer("Файл не найден.", show_alert=True)
        return
    await query.answer()
    await safe_delete(query.message)
    await send_file_preview(query.message.chat_id, context, row)


async def send_file_preview(chat_id, context, row):
    fid = row["id"]
    caption = (
        f"{icon_for(row['kind'])} {display_title(row)}\n"
        f"#{fid} • {short_date(row['created_at'])}"
    )
    markup = file_buttons(row, "gallery" if not row["hidden"] else "hidden_list")

    if row["kind"] == "photo":
        await context.bot.send_photo(chat_id, row["file_id"], caption=caption, reply_markup=markup)
    elif row["kind"] == "video":
        await context.bot.send_video(chat_id, row["file_id"], caption=caption, reply_markup=markup)
    elif row["kind"] == "document":
        await context.bot.send_document(chat_id, row["file_id"], caption=caption, reply_markup=markup)
    else:
        await context.bot.send_message(chat_id, caption + "\n\n" + (row["text"] or ""), reply_markup=markup)


async def show_original(query, context, fid):
    uid = query.from_user.id
    row = get_file(uid, fid)
    if not row:
        await query.answer("Файл не найден.", show_alert=True)
        return
    await query.answer("Отправляю оригинал…")
    if row["kind"] == "photo":
        await context.bot.send_photo(query.message.chat_id, row["file_id"])
    elif row["kind"] == "video":
        await context.bot.send_video(query.message.chat_id, row["file_id"])
    elif row["kind"] == "document":
        await context.bot.send_document(query.message.chat_id, row["file_id"])
    else:
        await context.bot.send_message(query.message.chat_id, row["text"] or "")


# ---------------- FAVORITES / RECENT ----------------

async def favorites(query, context):
    uid = query.from_user.id
    await replace_callback_message(query)
    rows = get_rows(uid, "deleted=0 AND hidden=0 AND favorite=1")
    if not rows:
        await context.bot.send_message(
            query.message.chat_id, "⭐ Избранное пока пустое.", reply_markup=back_home()
        )
        return
    buttons = [[InlineKeyboardButton(
        f"{icon_for(r['kind'])} {display_title(r)}",
        callback_data=f"file:{r['id']}"
    )] for r in rows[:100]]
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    await context.bot.send_message(
        query.message.chat_id,
        f"⭐ Избранное\n\n{len(rows)} файлов",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def recent(query, context):
    uid = query.from_user.id
    await replace_callback_message(query)
    rows = get_rows(uid, "deleted=0 AND hidden=0", order="id DESC")[:50]
    if not rows:
        await context.bot.send_message(
            query.message.chat_id, "🕘 Здесь пока ничего нет.", reply_markup=back_home()
        )
        return
    buttons = [[InlineKeyboardButton(
        f"{icon_for(r['kind'])} {display_title(r)}",
        callback_data=f"file:{r['id']}"
    )] for r in rows]
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    await context.bot.send_message(
        query.message.chat_id,
        f"🕘 Недавние\n\nПоследние {len(rows)} файлов",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ---------------- SEARCH ----------------

async def search_start(query, context):
    uid = query.from_user.id
    await replace_callback_message(query)
    context.user_data.clear()
    context.user_data["search_mode"] = True
    await context.bot.send_message(
        query.message.chat_id,
        "🔎 Поиск\n\nНапиши название файла, текст или часть подписи.",
        reply_markup=back_home(),
    )


async def search_results(update, context, text):
    uid = update.effective_user.id
    q = f"%{text}%"
    con = db()
    rows = con.execute("""
        SELECT * FROM files
        WHERE user_id=? AND deleted=0 AND hidden=0
          AND (
            COALESCE(title,'') LIKE ?
            OR COALESCE(text,'') LIKE ?
          )
        ORDER BY id DESC
        LIMIT 100
    """, (uid, q, q)).fetchall()
    con.close()
    context.user_data["search_mode"] = False
    if not rows:
        await update.message.reply_text(
            f"🔎 Ничего не найдено по запросу: «{text}»",
            reply_markup=main_menu(uid),
        )
        return
    buttons = [[InlineKeyboardButton(
        f"{icon_for(r['kind'])} {display_title(r)}",
        callback_data=f"file:{r['id']}"
    )] for r in rows]
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    await update.message.reply_text(
        f"🔎 Результаты: «{text}»\n\nНайдено: {len(rows)}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ---------------- RENAME / MOVE ----------------

async def rename_start(query, context, fid):
    uid = query.from_user.id
    row = get_file(uid, fid)
    if not row:
        await query.answer("Файл не найден.", show_alert=True)
        return
    await replace_callback_message(query)
    context.user_data.clear()
    context.user_data["rename_id"] = fid
    await context.bot.send_message(
        query.message.chat_id,
        f"✏️ Новое название для «{display_title(row)}»\n\n"
        "Напиши новое название:",
        reply_markup=back_home(),
    )


async def move_start(query, context, fid):
    uid = query.from_user.id
    row = get_file(uid, fid)
    if not row:
        await query.answer("Файл не найден.", show_alert=True)
        return
    await replace_callback_message(query)
    con = db()
    folders = con.execute("SELECT * FROM folders WHERE user_id=? ORDER BY name", (uid,)).fetchall()
    con.close()
    buttons = []
    for f in folders:
        buttons.append([InlineKeyboardButton(
            f"📁 {f['name']}", callback_data=f"move_to:{fid}:{f['id']}"
        )])
    buttons.append([InlineKeyboardButton("📦 Без папки", callback_data=f"move_to:{fid}:0")])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"file:{fid}")])
    await context.bot.send_message(
        query.message.chat_id,
        f"📁 Куда переместить: «{display_title(row)}»?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ---------------- DELETE / HIDE / FAVORITE ----------------

async def toggle_favorite(query, context, fid):
    uid = query.from_user.id
    con = db()
    row = con.execute("SELECT favorite FROM files WHERE id=? AND user_id=?", (fid, uid)).fetchone()
    if not row:
        con.close()
        await query.answer("Файл не найден.", show_alert=True)
        return
    new = 0 if row["favorite"] else 1
    con.execute("UPDATE files SET favorite=? WHERE id=? AND user_id=?", (new, fid, uid))
    con.commit()
    con.close()
    await query.answer("⭐ Добавлено" if new else "☆ Убрано")
    row = get_file(uid, fid)
    await safe_delete(query.message)
    await send_file_preview(query.message.chat_id, context, row)


async def toggle_hidden(query, context, fid, value):
    uid = query.from_user.id
    if value == 1:
        con = db()
        pin = con.execute("SELECT pin_hash FROM users WHERE user_id=?", (uid,)).fetchone()
        con.close()
        if not pin or not pin["pin_hash"]:
            await query.answer("Сначала установи PIN.", show_alert=True)
            return
    con = db()
    con.execute("UPDATE files SET hidden=? WHERE id=? AND user_id=?", (value, fid, uid))
    con.commit()
    con.close()
    await query.answer("🙈 Файл скрыт" if value else "👁 Файл открыт")
    row = get_file(uid, fid)
    await safe_delete(query.message)
    await send_file_preview(query.message.chat_id, context, row)


async def delete_file(query, context, fid):
    uid = query.from_user.id
    con = db()
    cur = con.execute(
        "UPDATE files SET deleted=1 WHERE id=? AND user_id=? AND deleted=0",
        (fid, uid)
    )
    con.commit()
    con.close()
    if not cur.rowcount:
        await query.answer("Файл не найден.", show_alert=True)
        return
    await query.answer("🗑 Перемещено в корзину")
    await safe_delete(query.message)
    await context.bot.send_message(
        query.message.chat_id,
        "🗑 Файл перемещён в корзину.",
        reply_markup=main_menu(uid),
    )


async def restore_file(query, context, fid):
    uid = query.from_user.id
    con = db()
    cur = con.execute(
        "UPDATE files SET deleted=0 WHERE id=? AND user_id=? AND deleted=1",
        (fid, uid)
    )
    con.commit()
    con.close()
    if not cur.rowcount:
        await query.answer("Файл не найден.", show_alert=True)
        return
    await query.answer("♻️ Восстановлено")
    await safe_delete(query.message)
    await context.bot.send_message(
        query.message.chat_id,
        "♻️ Файл восстановлен.",
        reply_markup=main_menu(uid),
    )


async def trash(query, context):
    uid = query.from_user.id
    await replace_callback_message(query)
    rows = get_rows(uid, "deleted=1", order="id DESC")
    if not rows:
        await context.bot.send_message(
            query.message.chat_id, "🗑 Корзина пуста.", reply_markup=back_home()
        )
        return
    buttons = []
    for r in rows[:100]:
        buttons.append([InlineKeyboardButton(
            f"♻️ {display_title(r)}",
            callback_data=f"restore:{r['id']}"
        )])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    await context.bot.send_message(
        query.message.chat_id,
        f"🗑 Корзина\n\nФайлов: {len(rows)}\nНажми, чтобы восстановить.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ---------------- FOLDERS ----------------

async def folders(query, context):
    uid = query.from_user.id
    await replace_callback_message(query)
    con = db()
    rows = con.execute("SELECT * FROM folders WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
    con.close()
    buttons = [[InlineKeyboardButton("➕ Создать папку", callback_data="folder_new")]]
    for r in rows:
        buttons.append([InlineKeyboardButton(
            f"📁 {r['name']}", callback_data=f"folder:{r['id']}"
        )])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    await context.bot.send_message(
        query.message.chat_id,
        f"📁 Папки\n\nПапок: {len(rows)}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def new_folder(query, context):
    uid = query.from_user.id
    await replace_callback_message(query)
    context.user_data.clear()
    context.user_data["folder_mode"] = True
    await context.bot.send_message(
        query.message.chat_id,
        "📁 Напиши название новой папки:",
        reply_markup=back_home(),
    )


async def open_folder(query, context, folder_id):
    uid = query.from_user.id
    await replace_callback_message(query)
    con = db()
    folder = con.execute(
        "SELECT * FROM folders WHERE id=? AND user_id=?", (folder_id, uid)
    ).fetchone()
    rows = con.execute(
        "SELECT * FROM files WHERE folder_id=? AND user_id=? AND deleted=0 ORDER BY id DESC",
        (folder_id, uid)
    ).fetchall()
    con.close()
    if not folder:
        await context.bot.send_message(query.message.chat_id, "❌ Папка не найдена.", reply_markup=back_home())
        return
    buttons = [[InlineKeyboardButton(
        f"{icon_for(r['kind'])} {display_title(r)}",
        callback_data=f"file:{r['id']}"
    )] for r in rows[:100]]
    buttons.append([InlineKeyboardButton("⬅️ Папки", callback_data="folders")])
    await context.bot.send_message(
        query.message.chat_id,
        f"📁 {folder['name']}\n\nФайлов: {len(rows)}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def move_to(query, context, fid, folder_id):
    uid = query.from_user.id
    con = db()
    # Validate destination folder belongs to this user.
    if folder_id:
        folder = con.execute(
            "SELECT id FROM folders WHERE id=? AND user_id=?", (folder_id, uid)
        ).fetchone()
        if not folder:
            con.close()
            await query.answer("Папка не найдена.", show_alert=True)
            return
    cur = con.execute(
        "UPDATE files SET folder_id=? WHERE id=? AND user_id=?",
        (folder_id or None, fid, uid)
    )
    con.commit()
    con.close()
    if not cur.rowcount:
        await query.answer("Файл не найден.", show_alert=True)
        return
    await query.answer("📁 Перемещено")
    await safe_delete(query.message)
    await context.bot.send_message(
        query.message.chat_id,
        "📁 Файл перемещён.",
        reply_markup=main_menu(uid),
    )


# ---------------- TEXTS / MEDIA TYPES ----------------

async def list_kind(query, context, kind):
    uid = query.from_user.id
    await replace_callback_message(query)
    rows = get_rows(uid, f"deleted=0 AND hidden=0 AND kind='{kind}'")
    if not rows:
        await context.bot.send_message(
            query.message.chat_id,
            f"{icon_for(kind)} Здесь пока пусто.",
            reply_markup=back_home(),
        )
        return
    buttons = [[InlineKeyboardButton(
        f"{icon_for(r['kind'])} {display_title(r)}",
        callback_data=f"file:{r['id']}"
    )] for r in rows[:100]]
    buttons.append([InlineKeyboardButton("⬅️ Галерея", callback_data="gallery")])
    await context.bot.send_message(
        query.message.chat_id,
        f"{icon_for(kind)} {kind.capitalize()}\n\nФайлов: {len(rows)}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ---------------- SETTINGS / PIN ----------------

async def settings(query, context):
    uid = query.from_user.id
    await replace_callback_message(query)
    con = db()
    row = con.execute("SELECT pin_hash FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    status = "🟢 установлен" if row and row["pin_hash"] else "⚪ не установлен"
    await context.bot.send_message(
        query.message.chat_id,
        f"⚙️ Настройки\n\n🔐 PIN: {status}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 Установить PIN", callback_data="pin_set")],
            [InlineKeyboardButton("🔄 Изменить PIN", callback_data="pin_change")],
            [InlineKeyboardButton("❌ Удалить PIN", callback_data="pin_remove")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="home")],
        ]),
    )


async def pin_start(query, context, action):
    uid = query.from_user.id
    if action == "remove":
        con = db()
        con.execute("UPDATE users SET pin_hash=NULL WHERE user_id=?", (uid,))
        con.commit()
        con.close()
        await query.answer("PIN удалён")
        await safe_delete(query.message)
        await send_home(query.message.chat_id, context, uid)
        return
    await replace_callback_message(query)
    context.user_data.clear()
    context.user_data["pin_mode"] = action
    await context.bot.send_message(
        query.message.chat_id,
        "🔐 Введи PIN от 4 до 8 цифр:",
        reply_markup=back_home(),
    )


# ---------------- ADMIN ----------------

async def admin(query, context):
    uid = query.from_user.id
    if uid != ADMIN_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    await replace_callback_message(query)
    con = db()
    users = con.execute("SELECT * FROM users ORDER BY user_id DESC").fetchall()
    total = con.execute("SELECT COUNT(*) n FROM files WHERE deleted=0").fetchone()["n"]
    hidden = con.execute("SELECT COUNT(*) n FROM files WHERE hidden=1 AND deleted=0").fetchone()["n"]
    con.close()
    buttons = []
    for u in users[:50]:
        name = u["username"] or u["first_name"] or str(u["user_id"])
        buttons.append([InlineKeyboardButton(
            f"{'🚫' if u['blocked'] else '🟢'} {name}",
            callback_data=f"adminuser:{u['user_id']}"
        )])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="home")])
    await context.bot.send_message(
        query.message.chat_id,
        f"👑 Админ-панель\n\n"
        f"👤 Пользователей: {len(users)}\n"
        f"📦 Файлов: {total}\n"
        f"🙈 Скрытых: {hidden}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def admin_user(query, context, target):
    uid = query.from_user.id
    if uid != ADMIN_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    await replace_callback_message(query)
    con = db()
    u = con.execute("SELECT * FROM users WHERE user_id=?", (target,)).fetchone()
    files = con.execute("SELECT COUNT(*) n FROM files WHERE user_id=?", (target,)).fetchone()["n"]
    folders_n = con.execute("SELECT COUNT(*) n FROM folders WHERE user_id=?", (target,)).fetchone()["n"]
    con.close()
    if not u:
        await context.bot.send_message(query.message.chat_id, "Пользователь не найден.", reply_markup=back_home())
        return
    await context.bot.send_message(
        query.message.chat_id,
        f"👤 Пользователь\n\n"
        f"ID: {target}\n"
        f"Username: @{u['username'] or 'нет'}\n"
        f"Файлов: {files}\n"
        f"Папок: {folders_n}\n"
        f"Статус: {'🚫 заблокирован' if u['blocked'] else '🟢 активен'}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🚫 Заблокировать" if not u["blocked"] else "✅ Разблокировать",
                callback_data=f"toggleblock:{target}"
            )],
            [InlineKeyboardButton("📂 Файлы пользователя", callback_data=f"adminfiles:{target}")],
            [InlineKeyboardButton("📁 Папки пользователя", callback_data=f"adminfolders:{target}")],
            [InlineKeyboardButton("⬅️ Админ-панель", callback_data="admin")],
        ]),
    )


# ---------------- MESSAGE HANDLER ----------------

async def save_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    user = update.effective_user
    uid = user.id
    register_user(user)
    if is_blocked(uid) and uid != ADMIN_ID:
        return

    # Text workflow states.
    if context.user_data.get("folder_mode"):
        text = (message.text or "").strip()
        if text:
            con = db()
            con.execute("INSERT INTO folders(user_id,name) VALUES(?,?)", (uid, text[:100]))
            con.commit()
            con.close()
            context.user_data.clear()
            await message.reply_text(f"📁 Папка «{text[:100]}» создана.", reply_markup=main_menu(uid))
        return

    if context.user_data.get("rename_id"):
        title = (message.text or "").strip()
        if not title:
            await message.reply_text("❌ Название не может быть пустым.")
            return
        fid = context.user_data.pop("rename_id")
        con = db()
        con.execute("UPDATE files SET title=? WHERE id=? AND user_id=?", (title[:100], fid, uid))
        con.commit()
        con.close()
        await message.reply_text("✏️ Название сохранено.", reply_markup=main_menu(uid))
        return

    if context.user_data.get("pin_mode"):
        pin = (message.text or "").strip()
        if not pin.isdigit() or not 4 <= len(pin) <= 8:
            await message.reply_text("❌ PIN: от 4 до 8 цифр.")
            return
        action = context.user_data.pop("pin_mode")
        con = db()
        con.execute("UPDATE users SET pin_hash=? WHERE user_id=?", (hash_pin(pin), uid))
        con.commit()
        con.close()
        await message.reply_text("✅ PIN сохранён.", reply_markup=main_menu(uid))
        return

    if context.user_data.get("search_mode"):
        text = (message.text or "").strip()
        if text:
            await search_results(update, context, text)
        return

    if message.text and message.text.startswith("/"):
        return

    # If there is no media/text, ignore.
    kind = None
    file_id = None
    text = None
    if message.photo:
        kind = "photo"
        file_id = message.photo[-1].file_id
    elif message.video:
        kind = "video"
        file_id = message.video.file_id
    elif message.document:
        kind = "document"
        file_id = message.document.file_id
    elif message.text:
        text = message.text.strip()
        if text:
            kind = "text"

    if not kind:
        return

    hidden = bool(context.user_data.get("hidden_mode"))
    con = db()
    cur = con.execute(
        "INSERT INTO files(user_id,kind,file_id,text,hidden) VALUES(?,?,?,?,?)",
        (uid, kind, file_id, text, int(hidden)),
    )
    item_id = cur.lastrowid
    con.commit()
    con.close()

    # Keep hidden mode active so every file in a Telegram album is hidden.
    if hidden:
        await message.reply_text(f"🙈 Скрыто сохранено #{item_id}")
    else:
        await message.reply_text(f"✅ Сохранено #{item_id}")


# ---------------- CALLBACK ROUTER ----------------

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    uid = q.from_user.id

    if is_blocked(uid) and uid != ADMIN_ID:
        await q.answer("Доступ заблокирован.", show_alert=True)
        return

    if data == "home":
        await home(update, context)
    elif data == "add":
        await add_screen(q, context)
    elif data == "hidden":
        await hidden_screen(q, context)
    elif data == "hidden_upload":
        await hidden_upload(q, context)
    elif data == "hidden_list":
        await hidden_list(q, context)
    elif data == "gallery":
        await gallery(q, context)
    elif data == "allphotos":
        await all_photos(q, context)
    elif data == "photo_view":
        await photo_view(q, context, 0)
    elif data.startswith("pv:"):
        try:
            await photo_view(q, context, int(data.split(":")[1]))
        except ValueError:
            await q.answer("Ошибка навигации.", show_alert=True)
    elif data.startswith("file:"):
        await open_file(q, context, int(data.split(":")[1]))
    elif data.startswith("show:"):
        await show_original(q, context, int(data.split(":")[1]))
    elif data.startswith("fav:"):
        await toggle_favorite(q, context, int(data.split(":")[1]))
    elif data.startswith("rename:"):
        await rename_start(q, context, int(data.split(":")[1]))
    elif data.startswith("move:"):
        await move_start(q, context, int(data.split(":")[1]))
    elif data.startswith("move_to:"):
        parts = data.split(":")
        await move_to(q, context, int(parts[1]), int(parts[2]))
    elif data.startswith("hide:"):
        await toggle_hidden(q, context, int(data.split(":")[1]), 1)
    elif data.startswith("unhide:"):
        await toggle_hidden(q, context, int(data.split(":")[1]), 0)
    elif data.startswith("delete:"):
        await delete_file(q, context, int(data.split(":")[1]))
    elif data.startswith("restore:"):
        await restore_file(q, context, int(data.split(":")[1]))
    elif data == "favorites":
        await favorites(q, context)
    elif data == "recent":
        await recent(q, context)
    elif data == "search":
        await search_start(q, context)
    elif data == "videos":
        await list_kind(q, context, "video")
    elif data == "documents":
        await list_kind(q, context, "document")
    elif data == "texts":
        await list_kind(q, context, "text")
    elif data == "folders":
        await folders(q, context)
    elif data == "folder_new":
        await new_folder(q, context)
    elif data.startswith("folder:"):
        await open_folder(q, context, int(data.split(":")[1]))
    elif data == "settings":
        await settings(q, context)
    elif data in ("pin_set", "pin_change", "pin_remove"):
        await pin_start(q, context, {
            "pin_set": "set",
            "pin_change": "change",
            "pin_remove": "remove",
        }[data])
    elif data == "trash":
        await trash(q, context)
    elif data == "admin":
        await admin(q, context)
    elif data.startswith("adminuser:"):
        await admin_user(q, context, int(data.split(":")[1]))
    elif data.startswith("toggleblock:"):
        if uid != ADMIN_ID:
            await q.answer("Нет доступа.", show_alert=True)
            return
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
        await q.answer("Готово")
        await safe_delete(q.message)
        await context.bot.send_message(
            q.message.chat_id,
            "🚫 Пользователь заблокирован." if new_value else "✅ Пользователь разблокирован.",
            reply_markup=main_menu(ADMIN_ID),
        )
    elif data.startswith("adminfiles:"):
        if uid != ADMIN_ID:
            await q.answer("Нет доступа.", show_alert=True)
            return
        target = int(data.split(":")[1])
        await replace_callback_message(q)
        con = db()
        rows = con.execute("SELECT * FROM files WHERE user_id=? ORDER BY id DESC", (target,)).fetchall()
        con.close()
        await context.bot.send_message(q.message.chat_id, f"📂 Файлы пользователя: {len(rows)}")
        for r in rows[:50]:
            mark = "🗑" if r["deleted"] else ("🙈" if r["hidden"] else "📦")
            if r["kind"] == "photo":
                await context.bot.send_photo(q.message.chat_id, r["file_id"], caption=f"{mark} {display_title(r)}")
            elif r["kind"] == "video":
                await context.bot.send_video(q.message.chat_id, r["file_id"], caption=f"{mark} {display_title(r)}")
            elif r["kind"] == "document":
                await context.bot.send_document(q.message.chat_id, r["file_id"], caption=f"{mark} {display_title(r)}")
            else:
                await context.bot.send_message(q.message.chat_id, f"{mark} {display_title(r)}\n\n{r['text'] or ''}")
        await context.bot.send_message(q.message.chat_id, "👑 Админ-панель", reply_markup=main_menu(ADMIN_ID))
    elif data.startswith("adminfolders:"):
        if uid != ADMIN_ID:
            await q.answer("Нет доступа.", show_alert=True)
            return
        target = int(data.split(":")[1])
        await replace_callback_message(q)
        con = db()
        rows = con.execute("SELECT * FROM folders WHERE user_id=? ORDER BY id DESC", (target,)).fetchall()
        con.close()
        text = "📁 Папки пользователя:\n\n" + (
            "\n".join(f"#{r['id']} — {r['name']}" for r in rows) if rows else "Папок нет."
        )
        await context.bot.send_message(q.message.chat_id, text, reply_markup=main_menu(ADMIN_ID))
    else:
        await q.answer("Эта кнопка пока недоступна.", show_alert=True)


async def error_handler(update, context):
    print("MONNEY ERROR:", repr(context.error))


def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN или MONNEY_TOKEN не задан.")
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.Document.ALL | (filters.TEXT & ~filters.COMMAND),
        save_message,
    ))
    app.add_error_handler(error_handler)
    print("MONNEY v10 запущен.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
