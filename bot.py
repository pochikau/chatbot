import logging
import os
import sqlite3
import sys
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
SUPPORT_GROUP_ID = int(os.environ["SUPPORT_GROUP_ID"]) if os.environ.get("SUPPORT_GROUP_ID") else 0
DATA_DIR = os.environ.get("DATA_DIR", "/app/data").strip() or "/app/data"
SUPER_ADMIN_USER_IDS = {
    int(x.strip())
    for x in os.environ.get("SUPER_ADMIN_USER_IDS", "").split(",")
    if x.strip().isdigit()
}

DB_PATH = os.path.join(DATA_DIR, "tickets.db")
LOG_PATH = os.path.join(DATA_DIR, "bot.log")

os.makedirs(DATA_DIR, exist_ok=True)

_log_handlers = [logging.StreamHandler(sys.stdout)]
try:
    _log_handlers.append(logging.FileHandler(LOG_PATH, encoding="utf-8"))
except OSError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=_log_handlers,
)
logger = logging.getLogger(__name__)

DEFAULT_TEXT = {
    "main_menu_text": """🤖 Привет, давай сейчас все тебе починим 🛠

Выбери категорию проблемы:""",
    "help_connection_text": """⚙️ *Не работает подключение*

Обычно помогают эти действия, попробуй выполнить их по порядку:""",
    "update_menu_text": "🔄 *Скачать/Обновить приложение*\n\nВыбери свою платформу:",
    "reinstall_text": "📖 *Добавить подписку заново*\n\nИнструкция по переустановке подписки:",
    "renew_text": "📩 *Перевыпустить подписку*\n\nИнструкция по перевыпуску подписки:",
    "setup_help_text": "📲 *Как настроить подключение?*\n\nВыбери свою операционную систему:",
    "subscription_help_text": """📩 *Действия с подпиской*

Ты можешь получить новую подписку или ознакомиться с тарифами в нашем основном боте. Перейди по ссылке ниже!""",
    "setup_title_ios": "📱 *Инструкция для iPhone*",
    "setup_title_android": "🤖 *Инструкция для Android*",
    "setup_title_macos": "🍎 *Инструкция для macOS*",
    "setup_title_windows": "🪟 *Инструкция для Windows*",
}

DEFAULT_URLS = {
    "url_store_iphone": "https://apps.apple.com/ru/app/v2raytun/id6476628951",
    "url_store_android": "https://github.com/vladimir-fp/v2client/raw/refs/heads/main/android/v2RayTun_5.18.61.apk",
    "url_store_macos": "https://apps.apple.com/ru/app/v2raytun/id6476628951?l=en-GB",
    "url_store_windows": "https://github.com/vladimir-fp/v2client/raw/refs/heads/main/win/v2RayTun_Setup.exe?download=",
    "url_reinstall": "https://telegra.ph/Kak-zakazat-novyj-klyuch-i-dobavit-v-prilozhenie-10-14",
    "url_renew": "https://telegra.ph/Kak-zakazat-novyj-klyuch-i-dobavit-v-prilozhenie-10-14",
    "url_setup_ios": "https://telegra.ph/Kak-zakazat-novyj-klyuch-i-dobavit-v-prilozhenie-10-14",
    "url_setup_android": "https://telegra.ph/Kak-zakazat-novyj-klyuch-i-dobavit-v-prilozhenie-10-14",
    "url_setup_macos": "https://telegra.ph/Kak-dobavit-podpisku-v-prilozhenie-V2RayTun-v-ruchnuyu-10-18",
    "url_setup_windows": "https://telegra.ph/Kak-dobavit-podpisku-v-prilozhenie-V2RayTun-v-ruchnuyu-10-18",
    "url_subscription_bot": "https://t.me/wgitzbot",
    "url_subscription_how": "https://telegra.ph/Kak-zakazat-novyj-klyuch-i-dobavit-v-prilozhenie-10-14",
    "url_balance": "https://telegra.ph/Kak-popolnit-balans-bota-dlya-oplaty-podpiski-10-25",
    "url_ticket_reinstall": "https://telegra.ph/Instrukciya-kak-udalit-klyuch-dlya-polzovatelej-Android-i-iPhone-07-01",
    "url_ticket_renew": "https://telegra.ph/Kak-zakazat-novyj-klyuch-i-dobavit-v-prilozhenie-10-14",
}

# Ключи файлов инструкций (загрузка админом); если file_id есть — отправляется документ, иначе URL
INSTR_SETUP_KEYS = ("ios", "android", "macos", "windows")


def log_event(level, message, user_id=None, ticket_id=None):
    extra_info = ""
    if user_id:
        extra_info += f" [User: {user_id}]"
    if ticket_id:
        extra_info += f" [Ticket: {ticket_id}]"
    full_message = f"{message}{extra_info}"
    if level == "info":
        logger.info(full_message)
    elif level == "error":
        logger.error(full_message)
    elif level == "warning":
        logger.warning(full_message)


def _conn():
    return sqlite3.connect(DB_PATH)


def is_super_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMIN_USER_IDS


def is_admin_user(user_id: int) -> bool:
    if is_super_admin(user_id):
        return True
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        c.close()
        return row is not None
    except Exception as e:
        log_event("error", f"is_admin_user: {e}", user_id=user_id)
        return False


def seed_super_admins():
    if not SUPER_ADMIN_USER_IDS:
        return
    try:
        c = _conn()
        cur = c.cursor()
        for uid in SUPER_ADMIN_USER_IDS:
            cur.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (uid,))
        c.commit()
        c.close()
    except Exception as e:
        log_event("error", f"seed_super_admins: {e}")


def get_content(key: str, default: str | None = None) -> str:
    d = default
    if d is None:
        d = DEFAULT_TEXT.get(key) or DEFAULT_URLS.get(key) or ""
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute("SELECT value FROM bot_content WHERE key = ?", (key,))
        row = cur.fetchone()
        c.close()
        if row and row[0]:
            return row[0]
    except Exception as e:
        log_event("error", f"get_content {key}: {e}")
    return d


def set_content(key: str, value: str) -> bool:
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            """
            INSERT INTO bot_content (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )
        c.commit()
        c.close()
        return True
    except Exception as e:
        log_event("error", f"set_content {key}: {e}")
        return False


def get_instruction_file(key: str) -> str | None:
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute("SELECT file_id FROM instruction_files WHERE key = ?", (key,))
        row = cur.fetchone()
        c.close()
        if row and row[0]:
            return row[0]
    except Exception as e:
        log_event("error", f"get_instruction_file {key}: {e}")
    return None


def set_instruction_file(key: str, file_id: str) -> bool:
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            """
            INSERT INTO instruction_files (key, file_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET file_id = excluded.file_id, updated_at = CURRENT_TIMESTAMP
            """,
            (key, file_id),
        )
        c.commit()
        c.close()
        return True
    except Exception as e:
        log_event("error", f"set_instruction_file {key}: {e}")
        return False


def list_content_keys() -> list[str]:
    keys = sorted(set(DEFAULT_TEXT.keys()) | set(DEFAULT_URLS.keys()))
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute("SELECT key FROM bot_content")
        keys.extend(k[0] for k in cur.fetchall())
        c.close()
    except Exception:
        pass
    return sorted(set(keys))


def init_db():
    try:
        conn = _conn()
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_name TEXT,
                ticket_id TEXT UNIQUE,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                message_thread_id INTEGER,
                topic_name TEXT,
                device_type TEXT,
                problem_description TEXT
            )
            """
        )

        cursor.execute("PRAGMA table_info(tickets)")
        columns = [column[1] for column in cursor.fetchall()]
        if "device_type" not in columns:
            cursor.execute("ALTER TABLE tickets ADD COLUMN device_type TEXT")
            log_event("info", "Added device_type column to tickets table")
        if "problem_description" not in columns:
            cursor.execute("ALTER TABLE tickets ADD COLUMN problem_description TEXT")
            log_event("info", "Added problem_description column to tickets table")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_forms (
                user_id INTEGER PRIMARY KEY,
                device_type TEXT,
                problem_description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_content (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS instruction_files (
                key TEXT PRIMARY KEY,
                file_id TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        for k, v in {**DEFAULT_TEXT, **DEFAULT_URLS}.items():
            cursor.execute(
                "INSERT OR IGNORE INTO bot_content (key, value) VALUES (?, ?)", (k, v)
            )

        conn.commit()
        conn.close()
        log_event("info", "Database initialized successfully")
    except Exception as e:
        log_event("error", f"Database initialization failed: {e}")
        raise


def generate_ticket_id():
    return f"TICKET-{datetime.now().strftime('%Y%m%d%H%M%S')}"


def generate_topic_name(ticket_id, user_name, status="open"):
    if status == "closed":
        return f"🔒 {ticket_id} - {user_name}"
    return f"🎫 {ticket_id} - {user_name}"


def get_user_ticket(user_id):
    try:
        conn = _conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM tickets WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
        ticket = cursor.fetchone()
        conn.close()
        return ticket
    except Exception as e:
        log_event("error", f"Error getting user ticket: {e}", user_id=user_id)
        return None


def get_user_open_ticket(user_id):
    try:
        conn = _conn()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM tickets WHERE user_id = ? AND status = "open" ORDER BY created_at DESC LIMIT 1',
            (user_id,),
        )
        ticket = cursor.fetchone()
        conn.close()
        return ticket
    except Exception as e:
        log_event("error", f"Error getting user open ticket: {e}", user_id=user_id)
        return None


def save_ticket_form(user_id, device_type=None, problem_description=None):
    try:
        conn = _conn()
        cursor = conn.cursor()
        if device_type:
            cursor.execute(
                """
                INSERT OR REPLACE INTO ticket_forms (user_id, device_type, problem_description)
                VALUES (?, ?, COALESCE(?, (SELECT problem_description FROM ticket_forms WHERE user_id = ?)))
                """,
                (user_id, device_type, problem_description, user_id),
            )
        elif problem_description:
            cursor.execute(
                """
                INSERT OR REPLACE INTO ticket_forms (user_id, device_type, problem_description)
                VALUES (?, COALESCE(?, (SELECT device_type FROM ticket_forms WHERE user_id = ?)), ?)
                """,
                (user_id, device_type, user_id, problem_description),
            )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log_event("error", f"Error saving ticket form: {e}", user_id=user_id)
        return False


def get_ticket_form(user_id):
    try:
        conn = _conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ticket_forms WHERE user_id = ?", (user_id,))
        form = cursor.fetchone()
        conn.close()
        return form
    except Exception as e:
        log_event("error", f"Error getting ticket form: {e}", user_id=user_id)
        return None


def delete_ticket_form(user_id):
    try:
        conn = _conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ticket_forms WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log_event("error", f"Error deleting ticket form: {e}", user_id=user_id)
        return False


def update_ticket_status(ticket_id, status):
    try:
        conn = _conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tickets SET status = ? WHERE ticket_id = ?",
            (status, ticket_id),
        )
        conn.commit()
        conn.close()
        log_event("info", f"Ticket status updated to {status}", ticket_id=ticket_id)
        return True
    except Exception as e:
        log_event("error", f"Error updating ticket status: {e}", ticket_id=ticket_id)
        return False


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text=None):
    if not message_text:
        message_text = get_content("main_menu_text")
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⚙️ Не работает подключение", callback_data="help_connection")],
            [InlineKeyboardButton("📲 Как настроить подключение?", callback_data="help_setup")],
            [InlineKeyboardButton("📩 Действия с подпиской", callback_data="help_subscription")],
            [InlineKeyboardButton("👨‍💻 Ничего не помогло, позвать человеков", callback_data="create_ticket")],
        ]
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(message_text, reply_markup=keyboard)
    else:
        await update.message.reply_text(message_text, reply_markup=keyboard)


async def help_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "help_connection":
        await show_connection_help(query)
    elif query.data == "help_setup":
        await show_setup_help(query)
    elif query.data == "help_subscription":
        await show_subscription_help(query)
    elif query.data == "create_ticket":
        await start_ticket_creation(query, context)


async def show_connection_help(query):
    text = get_content("help_connection_text")
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 Скачать/Обновить приложение", callback_data="connection_update")],
            [InlineKeyboardButton("📖 Добавить подписку заново", callback_data="connection_reinstall")],
            [InlineKeyboardButton("📩 Перевыпустить подписку", callback_data="connection_renew")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")],
            [InlineKeyboardButton("👨‍💻 Ничего не помогло, позвать человеков", callback_data="create_ticket")],
        ]
    )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def show_update_menu(query):
    text = get_content("update_menu_text")
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("iPhone", url=get_content("url_store_iphone"))],
            [InlineKeyboardButton("Android", url=get_content("url_store_android"))],
            [InlineKeyboardButton("macOS", url=get_content("url_store_macos"))],
            [InlineKeyboardButton("Windows", url=get_content("url_store_windows"))],
            [InlineKeyboardButton("◀️ Назад", callback_data="help_connection")],
        ]
    )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def show_reinstall_instructions(query):
    text = get_content("reinstall_text")
    url = get_content("url_reinstall")
    fid = get_instruction_file("reinstall")
    if fid:
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📄 Открыть файл инструкции", callback_data="open_file_reinstall")],
                [InlineKeyboardButton("◀️ Назад", callback_data="help_connection")],
            ]
        )
    else:
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📖 Инструкция по переустановке подписки", url=url)],
                [InlineKeyboardButton("◀️ Назад", callback_data="help_connection")],
            ]
        )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def show_renew_instructions(query):
    text = get_content("renew_text")
    url = get_content("url_renew")
    fid = get_instruction_file("renew")
    if fid:
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📄 Открыть файл инструкции", callback_data="open_file_renew")],
                [InlineKeyboardButton("◀️ Назад", callback_data="help_connection")],
            ]
        )
    else:
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📖 Инструкция по перевыпуску подписки", url=url)],
                [InlineKeyboardButton("◀️ Назад", callback_data="help_connection")],
            ]
        )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def show_setup_help(query):
    text = get_content("setup_help_text")
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📱 iPhone", callback_data="setup_ios")],
            [InlineKeyboardButton("🤖 Android", callback_data="setup_android")],
            [InlineKeyboardButton("🍎 macOS", callback_data="setup_macos")],
            [InlineKeyboardButton("🪟 Windows", callback_data="setup_windows")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")],
        ]
    )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def show_platform_instructions(query, platform):
    title_key = f"setup_title_{platform}"
    text = get_content(title_key)
    url_key = f"url_setup_{platform}"
    url = get_content(url_key)
    fid = get_instruction_file(platform)
    if fid:
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📄 Открыть файл инструкции", callback_data=f"open_file_{platform}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="help_setup")],
            ]
        )
    else:
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📖 Открыть инструкцию", url=url)],
                [InlineKeyboardButton("◀️ Назад", callback_data="help_setup")],
            ]
        )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def show_subscription_help(query):
    text = get_content("subscription_help_text")
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🤖 Перейти в бота", url=get_content("url_subscription_bot"))],
            [
                InlineKeyboardButton(
                    "📩 Как сделать новую подписку",
                    url=get_content("url_subscription_how"),
                )
            ],
            [
                InlineKeyboardButton(
                    "💰 Как пополнить баланс бота для оплаты?",
                    url=get_content("url_balance"),
                )
            ],
            [InlineKeyboardButton("📖 Добавить подписку заново", callback_data="connection_reinstall")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")],
        ]
    )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def start_ticket_creation(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    delete_ticket_form(user_id)
    text = """👨‍💻 *Создание тикета*

Хорошо, я позову специалиста. Чтобы он смог помочь тебе быстрее, ответь, пожалуйста, на несколько вопросов.

*Вопрос 1:* 📱 На каком устройстве у тебя проблема?"""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("iPhone", callback_data="ticket_device_iphone")],
            [InlineKeyboardButton("Android", callback_data="ticket_device_android")],
            [InlineKeyboardButton("macOS", callback_data="ticket_device_macos")],
            [InlineKeyboardButton("Windows", callback_data="ticket_device_windows")],
            [InlineKeyboardButton("Другое (напиши)", callback_data="ticket_device_other")],
            [InlineKeyboardButton("◀️ Отмена", callback_data="back_to_main")],
        ]
    )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def handle_device_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    device_type = query.data.replace("ticket_device_", "").capitalize()
    save_ticket_form(user_id, device_type=device_type)
    text = f"""✅ *Устройство:* {device_type}

*Вопрос 2:* ❓ Опиши свою проблему максимально подробно.

Что ты делал(а), что не получается, какая ошибка?

_Просто напиши сообщение с описанием проблемы..._"""
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="create_ticket")]])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def handle_problem_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    problem_description = update.message.text
    save_ticket_form(user_id, problem_description=problem_description)
    form_data = get_ticket_form(user_id)
    if form_data and form_data[1] and form_data[2]:
        await show_ticket_confirmation(update, context, form_data[1], problem_description)
    else:
        await update.message.reply_text(
            "❌ Что-то пошло не так. Давай начнем заново.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔄 Начать заново", callback_data="create_ticket")]]
            ),
        )


async def show_ticket_confirmation(
    update: Update, context: ContextTypes.DEFAULT_TYPE, device_type, problem_description
):
    text = f"""✅ *Проверь, все ли верно:*

*Устройство:* {device_type}
*Описание проблемы:* {problem_description}

*Всё верно? Создаю тикет для поддержки.*"""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Всё верно, создать тикет", callback_data="confirm_ticket")],
            [InlineKeyboardButton("❌ Заполнить заново", callback_data="create_ticket")],
        ]
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def create_confirmed_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_name = query.from_user.full_name
    form_data = get_ticket_form(user_id)
    if not form_data or not form_data[1] or not form_data[2]:
        await query.edit_message_text(
            "❌ Данные не найдены. Давай начнем заново.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔄 Начать заново", callback_data="create_ticket")]]
            ),
        )
        return
    device_type, problem_description = form_data[1], form_data[2]
    ticket_id = await create_new_ticket(context, user_id, user_name, device_type, problem_description)
    if ticket_id:
        delete_ticket_form(user_id)
        await show_ticket_created_message(query, ticket_id)
    else:
        await query.edit_message_text(
            "❌ Ошибка при создании тикета. Попробуй еще раз.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔄 Попробовать снова", callback_data="create_ticket")]]
            ),
        )


async def show_ticket_created_message(query, ticket_id):
    text = f"""✅ *Отлично! Тикет {ticket_id} создан.* 🔰

Наш специалист свяжется с тобой в ближайшее время. Обычно это занимает до 24 часов в рабочие дни.

Ты можешь в любой момент проверить статус или закрыть тикет, если проблема решилась сама."""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📋 Проверить статус тикета", callback_data=f"status_{ticket_id}")],
            [InlineKeyboardButton("🔒 Закрыть тикет", callback_data=f"close_{ticket_id}")],
            [InlineKeyboardButton("💬 Добавить комментарий к тикету", callback_data=f"comment_{ticket_id}")],
            [
                InlineKeyboardButton(
                    "📖 Инструкция по переустановке подписки",
                    url=get_content("url_ticket_reinstall"),
                )
            ],
            [
                InlineKeyboardButton(
                    "📖 Инструкция по перевыпуску подписки",
                    url=get_content("url_ticket_renew"),
                )
            ],
        ]
    )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def create_new_ticket(context, user_id, user_name, device_type, problem_description):
    ticket_id = generate_ticket_id()
    topic_name = generate_topic_name(ticket_id, user_name)
    try:
        log_event("info", "Creating new ticket with form data", user_id=user_id, ticket_id=ticket_id)
        forum_topic = await context.bot.create_forum_topic(
            chat_id=SUPPORT_GROUP_ID,
            name=topic_name,
        )
        message_thread_id = forum_topic.message_thread_id
        ticket_text = f"""
🎫 **ТИКЕТ СОЗДАН**: {ticket_id}
👤 **Пользователь**: {user_name} (ID: {user_id})
📱 **Устройство**: {device_type}
📅 **Создан**: {datetime.now().strftime('%d.%m.%Y %H:%M')}

📋 **Описание проблемы**:
{problem_description}
        """
        await context.bot.send_message(
            chat_id=SUPPORT_GROUP_ID,
            message_thread_id=message_thread_id,
            text=ticket_text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✅ Закрыть тикет", callback_data=f"admin_close_{ticket_id}")]]
            ),
        )
        conn = _conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO tickets (user_id, user_name, ticket_id, message_thread_id, topic_name, device_type, problem_description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, user_name, ticket_id, message_thread_id, topic_name, device_type, problem_description),
        )
        conn.commit()
        conn.close()
        log_event("info", "New ticket created successfully with form data", user_id=user_id, ticket_id=ticket_id)
        return ticket_id
    except Exception as e:
        log_event("error", f"Error creating ticket: {e}", user_id=user_id, ticket_id=ticket_id)
        return False


async def show_ticket_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    ticket_id = query.data.replace("status_", "")
    user_id = query.from_user.id
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tickets WHERE ticket_id = ? AND user_id = ?", (ticket_id, user_id))
    ticket = cursor.fetchone()
    conn.close()
    if ticket:
        status = "🟢 В работе" if ticket[4] == "open" else "🔒 Закрыт"
        text = f"""📋 *Статус тикета {ticket_id}:*

*Статус:* {status}
*Создан:* {ticket[5]}
*Устройство:* {ticket[8] or 'Не указано'}
*Описание:* {ticket[9] or 'Не указано'}

*Последний комментарий от поддержки:* Специалист уже изучает вашу проблему"""
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔄 Обновить статус", callback_data=f"status_{ticket_id}")],
                [InlineKeyboardButton("🔒 Закрыть тикет", callback_data=f"close_confirm_{ticket_id}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")],
            ]
        )
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await query.edit_message_text(
            "❌ Тикет не найден.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🆕 Создать тикет", callback_data="create_ticket")]]
            ),
        )


async def confirm_close_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    ticket_id = query.data.replace("close_confirm_", "")
    text = f"""🔒 *Закрытие тикета*

Ты уверен, что хочешь закрыть тикет {ticket_id}?

Если ты его закроешь, переписка с поддержкой прекратится."""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Да, закрыть тикет", callback_data=f"close_{ticket_id}")],
            [InlineKeyboardButton("❌ Нет, оставить открытым", callback_data=f"status_{ticket_id}")],
        ]
    )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def close_ticket_simple(context, ticket_id, user_id, user_name, closed_by_user=False):
    try:
        log_event("info", "Closing ticket started", user_id=user_id, ticket_id=ticket_id)
        conn = _conn()
        cursor = conn.cursor()
        cursor.execute("SELECT message_thread_id, topic_name FROM tickets WHERE ticket_id = ?", (ticket_id,))
        ticket = cursor.fetchone()
        if not ticket:
            log_event("error", "Ticket not found in database", user_id=user_id, ticket_id=ticket_id)
            conn.close()
            return False
        message_thread_id, current_topic_name = ticket[0], ticket[1]
        conn.close()
        if not update_ticket_status(ticket_id, "closed"):
            return False
        try:
            new_topic_name = generate_topic_name(ticket_id, user_name, "closed")
            if current_topic_name != new_topic_name:
                await context.bot.edit_forum_topic(
                    chat_id=SUPPORT_GROUP_ID,
                    message_thread_id=message_thread_id,
                    name=new_topic_name,
                )
                log_event("info", "Topic name updated", ticket_id=ticket_id)
        except Exception as e:
            log_event("warning", f"Could not update topic name: {e}", ticket_id=ticket_id)
        try:
            await context.bot.close_forum_topic(
                chat_id=SUPPORT_GROUP_ID,
                message_thread_id=message_thread_id,
            )
            log_event("info", "Forum topic closed", ticket_id=ticket_id)
        except Exception as e:
            log_event("warning", f"Could not close forum topic: {e}", ticket_id=ticket_id)
        try:
            closed_by = "пользователем" if closed_by_user else "администратором"
            close_message = f"💯 Тикет закрыт 🔒\n\nЗакрыт {closed_by}"
            await context.bot.send_message(
                chat_id=SUPPORT_GROUP_ID,
                message_thread_id=message_thread_id,
                text=close_message,
            )
        except Exception as e:
            log_event("warning", f"Could not send close message: {e}", ticket_id=ticket_id)
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎫 Тикет {ticket_id} был закрыт.\n\n"
                f"Если у вас есть новые вопросы, создайте новый тикет.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🆕 Новый тикет", callback_data="create_ticket")]]
                ),
            )
        except Exception as e:
            log_event("warning", f"Could not notify user: {e}", user_id=user_id, ticket_id=ticket_id)
        log_event(
            "info",
            f'Ticket closed successfully by {"user" if closed_by_user else "admin"}',
            user_id=user_id,
            ticket_id=ticket_id,
        )
        return True
    except Exception as e:
        log_event("error", f"Error in close_ticket_simple: {e}", user_id=user_id, ticket_id=ticket_id)
        return False


async def handle_ticket_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    ticket_id = query.data.replace("close_", "")
    user_id = query.from_user.id
    user_name = query.from_user.full_name
    success = await close_ticket_simple(context, ticket_id, user_id, user_name, closed_by_user=True)
    if success:
        text = f"""✅ *Тикет {ticket_id} закрыт.*

Спасибо, что воспользовался нашей помощью! ✨

Если проблема возникнет снова — ты знаешь, где меня найти."""
        await query.edit_message_text(text, parse_mode="Markdown")
        await context.bot.send_message(
            chat_id=user_id,
            text="Чем еще могу помочь?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🆕 Создать новый тикет", callback_data="create_ticket")],
                    [InlineKeyboardButton("📖 Получить помощь", callback_data="back_to_main")],
                ]
            ),
        )
    else:
        await query.edit_message_text(
            "❌ Ошибка при закрытии тикета. Попробуй еще раз.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Попробовать снова",
                            callback_data=f"close_confirm_{ticket_id}",
                        )
                    ]
                ]
            ),
        )


async def handle_add_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    ticket_id = query.data.replace("comment_", "")
    text = f"""💬 *Добавление комментария к тикету {ticket_id}*

Просто напиши сообщение с дополнительной информацией, и оно будет добавлено в тикет."""
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Отмена", callback_data=f"status_{ticket_id}")]])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def forward_message_to_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE, ticket):
    user_id = update.message.from_user.id
    ticket_id = ticket[3]
    message_thread_id = ticket[6]
    try:
        log_event("info", "Adding message to existing ticket", user_id=user_id, ticket_id=ticket_id)
        if update.message.text:
            user_message_text = f"💬 **Дополнительный комментарий от пользователя**:\n{update.message.text}"
            await context.bot.send_message(
                chat_id=SUPPORT_GROUP_ID,
                message_thread_id=message_thread_id,
                text=user_message_text,
            )
            await update.message.reply_text("✅ Ваше сообщение добавлено в тикет.")
        elif update.message.photo:
            photo = update.message.photo[-1]
            caption = f"📷 **Фото от пользователя**\n{update.message.caption or ''}"
            await context.bot.send_photo(
                chat_id=SUPPORT_GROUP_ID,
                message_thread_id=message_thread_id,
                photo=photo.file_id,
                caption=caption,
            )
            await update.message.reply_text("✅ Ваше фото добавлено в тикет.")
    except Exception as e:
        log_event("error", f"Error adding message to ticket: {e}", user_id=user_id, ticket_id=ticket_id)
        await update.message.reply_text("❌ Ошибка при отправке сообщения в тикет.")


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if update.message.text and update.message.text.startswith("/"):
        return

    if context.user_data.get("awaiting_upload_instruction"):
        if not is_admin_user(user_id):
            context.user_data.pop("awaiting_upload_instruction", None)
        elif update.message.document:
            key = context.user_data.pop("awaiting_upload_instruction")
            fid = update.message.document.file_id
            if set_instruction_file(key, fid):
                await update.message.reply_text(f"✅ Файл для ключа `{key}` сохранён.", parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Не удалось сохранить файл.")
            return
        else:
            await update.message.reply_text("Пришлите документ (файл) одним сообщением.")
            return

    if context.user_data.get("awaiting_content_key"):
        if not is_admin_user(user_id):
            context.user_data.pop("awaiting_content_key", None)
            return
        key = context.user_data.pop("awaiting_content_key")
        set_content(key, update.message.text or "")
        await update.message.reply_text(f"✅ Ключ `{key}` обновлён.", parse_mode="Markdown")
        return

    existing_ticket = get_user_open_ticket(user_id)
    if existing_ticket:
        await forward_message_to_ticket(update, context, existing_ticket)
        return
    form_data = get_ticket_form(user_id)
    if form_data and form_data[1] and not form_data[2]:
        await handle_problem_description(update, context)
    else:
        await show_main_menu(update, context)


async def show_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.id != SUPPORT_GROUP_ID:
        return
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tickets WHERE status = "open" ORDER BY created_at DESC')
    open_tickets = cursor.fetchall()
    conn.close()
    if not open_tickets:
        await update.message.reply_text("✅ Нет открытых тикетов.")
        return
    tickets_text = "📋 **ОТКРЫТЫЕ ТИКЕТЫ**:\n\n"
    for ticket in open_tickets:
        tickets_text += f"🎫 {ticket[3]} - {ticket[2]} - {ticket[5]}\n"
    await update.message.reply_text(tickets_text)


async def show_closed_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.id != SUPPORT_GROUP_ID:
        return
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tickets WHERE status = "closed" ORDER BY created_at DESC LIMIT 10')
    closed_tickets = cursor.fetchall()
    conn.close()
    if not closed_tickets:
        await update.message.reply_text("🔒 Нет закрытых тикетов.")
        return
    tickets_text = "🔒 **ПОСЛЕДНИЕ ЗАКРЫТЫЕ ТИКЕТЫ**:\n\n"
    for ticket in closed_tickets:
        tickets_text += f"🔒 {ticket[3]} - {ticket[2]} - {ticket[5]}\n"
    await update.message.reply_text(tickets_text)


async def reopen_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.id != SUPPORT_GROUP_ID:
        return
    if not context.args:
        await update.message.reply_text("Использование: /reopen TICKET-ID")
        return
    ticket_id = context.args[0]
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
    ticket = cursor.fetchone()
    if not ticket:
        await update.message.reply_text("❌ Тикет не найден.")
        return
    cursor.execute("UPDATE tickets SET status = ? WHERE ticket_id = ?", ("open", ticket_id))
    conn.commit()
    conn.close()
    try:
        await context.bot.reopen_forum_topic(chat_id=SUPPORT_GROUP_ID, message_thread_id=ticket[6])
        new_topic_name = generate_topic_name(ticket_id, ticket[2], "open")
        await context.bot.edit_forum_topic(
            chat_id=SUPPORT_GROUP_ID,
            message_thread_id=ticket[6],
            name=new_topic_name,
        )
        await update.message.reply_text(f"✅ Тикет {ticket_id} переоткрыт.")
    except Exception as e:
        logger.error(f"Ошибка переоткрытия топика: {e}")
        await update.message.reply_text(f"✅ Статус тикета обновлен, но не удалось переоткрыть топик: {e}")


async def new_ticket_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    existing_ticket = get_user_open_ticket(user_id)
    if existing_ticket:
        ticket_id = existing_ticket[3]
        await update.message.reply_text(
            f"⚠️ У вас уже есть открытый тикет: {ticket_id}\n\n"
            f"Продолжайте общение в существующем тикете.\n"
            f"Если хотите создать новый тикет, сначала закройте текущий командой /closeticket",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("📋 Статус тикета", callback_data=f"status_{ticket_id}")],
                    [InlineKeyboardButton("🔒 Закрыть тикет", callback_data=f"close_{ticket_id}")],
                ]
            ),
        )
        return
    await start_ticket_creation_from_command(update, context)


async def start_ticket_creation_from_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    delete_ticket_form(user_id)
    text = """👨‍💻 *Создание тикета*

Хорошо, я позову специалиста. Чтобы он смог помочь тебе быстрее, ответь, пожалуйста, на несколько вопросов.

*Вопрос 1:* 📱 На каком устройстве у тебя проблема?"""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("iPhone", callback_data="ticket_device_iphone")],
            [InlineKeyboardButton("Android", callback_data="ticket_device_android")],
            [InlineKeyboardButton("macOS", callback_data="ticket_device_macos")],
            [InlineKeyboardButton("Windows", callback_data="ticket_device_windows")],
            [InlineKeyboardButton("Другое (напиши)", callback_data="ticket_device_other")],
            [InlineKeyboardButton("◀️ Отмена", callback_data="back_to_main")],
        ]
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def close_ticket_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    existing_ticket = get_user_open_ticket(user_id)
    if not existing_ticket:
        await update.message.reply_text(
            "❌ У вас нет открытых тикетов.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🆕 Новый тикет", callback_data="create_ticket")]]
            ),
        )
        return
    ticket_id = existing_ticket[3]
    text = f"""🔒 *Закрытие тикета*

Ты уверен, что хочешь закрыть тикет {ticket_id}?

Если ты его закроешь, переписка с поддержкой прекратится."""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Да, закрыть тикет", callback_data=f"close_{ticket_id}")],
            [InlineKeyboardButton("❌ Нет, оставить открытым", callback_data=f"status_{ticket_id}")],
        ]
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def my_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    existing_ticket = get_user_open_ticket(user_id)
    if not existing_ticket:
        await update.message.reply_text(
            "📋 У вас нет активных тикетов.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🆕 Создать тикет", callback_data="create_ticket")]]
            ),
        )
        return
    ticket_id = existing_ticket[3]
    created_at = existing_ticket[5]
    await update.message.reply_text(
        f"📋 **Ваш активный тикет**\n\n"
        f"🎫 **Номер**: {ticket_id}\n"
        f"👤 **Пользователь**: {update.message.from_user.full_name}\n"
        f"📅 **Создан**: {created_at}\n"
        f"🟢 **Статус**: Открыт\n\n"
        f"💬 Все ваши сообщения будут добавляться в этот тикет",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔒 Закрыть тикет", callback_data=f"close_{ticket_id}")],
                [InlineKeyboardButton("🆕 Новый тикет", callback_data="new_ticket")],
            ]
        ),
    )


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(f"Ваш Telegram user id: `{u.id}`", parse_mode="Markdown")


async def cmd_admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin_user(uid):
        await update.message.reply_text("Нет доступа.")
        return
    lines = [
        "*Админ-команды* (в личке с ботом):",
        "/admin\\_help — это сообщение",
        "/listcontent — ключи текстов и URL",
        "/getcontent \\<key\\>",
        "/setcontent \\<key\\> — затем одним сообщением пришлите новое значение",
        "/seturl \\<key\\> \\<url\\> — установить URL",
        "/upload\\_instruction \\<key\\> — затем пришлите *документ*",
        "",
        "*Ключи файлов инструкций:* `ios`, `android`, `macos`, `windows`, `reinstall`, `renew`",
    ]
    if is_super_admin(uid):
        lines.extend(
            [
                "",
                "*Только супер-админ* (SUPER\\_ADMIN\\_USER\\_IDS в .env):",
                "/addadmin \\<user\\_id\\>",
                "/removeadmin \\<user\\_id\\>",
                "/listadmins",
            ]
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_listcontent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    keys = list_content_keys()
    chunk = "\n".join(keys[:80])
    await update.message.reply_text(f"Ключи (фрагмент):\n`{chunk}`", parse_mode="Markdown")


async def cmd_getcontent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /getcontent <key>")
        return
    key = context.args[0]
    val = get_content(key)
    await update.message.reply_text(f"`{key}`:\n{val[:3500]}", parse_mode="Markdown")


async def cmd_setcontent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /setcontent <key> — затем следующим сообщением текст.")
        return
    key = context.args[0]
    context.user_data["awaiting_content_key"] = key
    await update.message.reply_text(f"Пришлите новое значение для `{key}` одним сообщением.", parse_mode="Markdown")


async def cmd_seturl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /seturl <key> <url>")
        return
    key = context.args[0]
    url = " ".join(context.args[1:]).strip()
    if set_content(key, url):
        await update.message.reply_text(f"✅ `{key}` обновлён.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Ошибка записи.")


async def cmd_upload_instruction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    if not context.args:
        await update.message.reply_text(
            "Использование: /upload_instruction <key>\n"
            "Ключи: ios, android, macos, windows, reinstall, renew\n"
            "Затем пришлите документ."
        )
        return
    key = context.args[0].lower()
    allowed = set(INSTR_SETUP_KEYS) | {"reinstall", "renew"}
    if key not in allowed:
        await update.message.reply_text(f"Неизвестный ключ. Допустимо: {', '.join(sorted(allowed))}")
        return
    context.user_data["awaiting_upload_instruction"] = key
    await update.message.reply_text(f"Пришлите файл инструкции для `{key}` (как документ).", parse_mode="Markdown")


async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_super_admin(uid):
        await update.message.reply_text("Только супер-админ может добавлять администраторов.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Использование: /addadmin <user_id>")
        return
    new_id = int(context.args[0])
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_id,))
        c.commit()
        c.close()
        await update.message.reply_text(f"✅ Админ `{new_id}` добавлен (или уже был).", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def cmd_removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super_admin(update.effective_user.id):
        await update.message.reply_text("Только супер-админ может удалять администраторов.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Использование: /removeadmin <user_id>")
        return
    rid = int(context.args[0])
    if rid in SUPER_ADMIN_USER_IDS:
        await update.message.reply_text("Нельзя удалить супер-админа из .env таким способом.")
        return
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute("DELETE FROM admins WHERE user_id = ?", (rid,))
        c.commit()
        c.close()
        await update.message.reply_text(f"✅ Запись `{rid}` удалена из admins (если была).", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def cmd_listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super_admin(update.effective_user.id):
        await update.message.reply_text("Только супер-админ.")
        return
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute("SELECT user_id FROM admins ORDER BY user_id")
        rows = [str(r[0]) for r in cur.fetchall()]
        c.close()
        sup = ", ".join(str(x) for x in sorted(SUPER_ADMIN_USER_IDS)) or "—"
        await update.message.reply_text(
            f"*Супер-админы (.env):* `{sup}`\n*Все админы (БД):* `{', '.join(rows) or '—'}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (
        update.message.chat.id != SUPPORT_GROUP_ID
        or not update.message.message_thread_id
        or update.message.message_thread_id == 1
    ):
        return
    message_thread_id = update.message.message_thread_id
    admin_name = update.message.from_user.full_name
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM tickets WHERE message_thread_id = ? AND status = "open"',
        (message_thread_id,),
    )
    ticket = cursor.fetchone()
    conn.close()
    if ticket:
        ticket_id = ticket[3]
        user_id = ticket[1]
        user_name = ticket[2]
        try:
            if update.message.text:
                response_text = f"""
📨 **Ответ от поддержки** (Тикет: {ticket_id})

💬 {update.message.text}

👨‍💼 **Администратор**: {admin_name}
                """
                await context.bot.send_message(chat_id=user_id, text=response_text)
            elif update.message.photo:
                photo = update.message.photo[-1]
                caption = f"📨 **Ответ от поддержки** (Тикет: {ticket_id})\n\n{update.message.caption or ''}\n\n👨‍💼 Администратор: {admin_name}"
                await context.bot.send_photo(chat_id=user_id, photo=photo.file_id, caption=caption)
            elif update.message.document:
                caption = f"📨 **Ответ от поддержки** (Тикет: {ticket_id})\n\n{update.message.caption or ''}\n\n👨‍💼 Администратор: {admin_name}"
                await context.bot.send_document(
                    chat_id=user_id,
                    document=update.message.document.file_id,
                    caption=caption,
                )
            elif update.message.video:
                caption = f"📨 **Ответ от поддержки** (Тикет: {ticket_id})\n\n{update.message.caption or ''}\n\n👨‍💼 Администратор: {admin_name}"
                await context.bot.send_video(chat_id=user_id, video=update.message.video.file_id, caption=caption)
            elif update.message.audio:
                caption = f"📨 **Ответ от поддержки** (Тикет: {ticket_id})\n\n{update.message.caption or ''}\n\n👨‍💼 Администратор: {admin_name}"
                await context.bot.send_audio(chat_id=user_id, audio=update.message.audio.file_id, caption=caption)
            elif update.message.voice:
                await context.bot.send_voice(
                    chat_id=user_id,
                    voice=update.message.voice.file_id,
                    caption=f"📨 **Голосовой ответ от поддержки** (Тикет: {ticket_id})\n\n👨‍💼 Администратор: {admin_name}",
                )
            elif update.message.sticker:
                await context.bot.send_sticker(chat_id=user_id, sticker=update.message.sticker.file_id)
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📨 **Ответ от поддержки** (Тикет: {ticket_id})\n\n👨‍💼 Администратор отправил стикер: {admin_name}",
                )
            await update.message.reply_text(f"✅ Ответ отправлен пользователю {user_name}")
        except Exception as e:
            log_event("error", f"Error sending reply to user: {e}", user_id=user_id, ticket_id=ticket_id)
            await update.message.reply_text(
                "❌ Не удалось отправить ответ пользователю. Возможно, он заблокировал бота."
            )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data.startswith("open_file_"):
        key = data.replace("open_file_", "")
        fid = get_instruction_file(key)
        if not fid:
            await query.answer("Файл не загружен", show_alert=True)
            return
        await query.answer()
        try:
            await context.bot.send_document(chat_id=query.from_user.id, document=fid)
        except Exception as e:
            log_event("error", f"open_instruction_file: {e}", user_id=query.from_user.id)
        return

    await query.answer()

    if data == "back_to_main":
        await show_main_menu(update, context)
    elif data == "new_ticket":
        await start_ticket_creation(query, context)
    elif data.startswith("help_"):
        await help_menu_handler(update, context)
    elif data == "connection_update":
        await show_update_menu(query)
    elif data == "connection_reinstall":
        await show_reinstall_instructions(query)
    elif data == "connection_renew":
        await show_renew_instructions(query)
    elif data.startswith("setup_"):
        platform = data.replace("setup_", "")
        await show_platform_instructions(query, platform)
    elif data == "create_ticket":
        await start_ticket_creation(query, context)
    elif data.startswith("ticket_device_"):
        await handle_device_selection(update, context)
    elif data == "confirm_ticket":
        await create_confirmed_ticket(update, context)
    elif data.startswith("status_"):
        await show_ticket_status(update, context)
    elif data.startswith("close_confirm_"):
        await confirm_close_ticket(update, context)
    elif data.startswith("close_"):
        await handle_ticket_close(update, context)
    elif data.startswith("comment_"):
        await handle_add_comment(update, context)
    elif data.startswith("admin_close_"):
        ticket_id = data.replace("admin_close_", "")
        conn = _conn()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, user_name FROM tickets WHERE ticket_id = ?", (ticket_id,))
        ticket = cursor.fetchone()
        conn.close()
        if ticket:
            user_id_ticket, user_name_ticket = ticket
            success = await close_ticket_simple(
                context, ticket_id, user_id_ticket, user_name_ticket, closed_by_user=False
            )
            if success:
                await query.edit_message_reply_markup(
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔒 Тикет закрыт", callback_data="already_closed")]]
                    )
                )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    log_event("info", "User started bot", user_id=user_id)
    existing_ticket = get_user_open_ticket(user_id)
    if existing_ticket:
        ticket_id = existing_ticket[3]
        await update.message.reply_text(
            f"🟢 У вас есть активный тикет: {ticket_id}\n\n"
            f"Вы можете управлять им через меню ниже:",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("📋 Статус тикета", callback_data=f"status_{ticket_id}")],
                    [InlineKeyboardButton("🔒 Закрыть тикет", callback_data=f"close_confirm_{ticket_id}")],
                    [InlineKeyboardButton("💬 Добавить комментарий", callback_data=f"comment_{ticket_id}")],
                    [InlineKeyboardButton("📖 Получить быструю помощь", callback_data="back_to_main")],
                ]
            ),
        )
    else:
        await show_main_menu(update, context)


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан. Укажите его в .env")
        sys.exit(1)
    if not SUPPORT_GROUP_ID:
        logger.error("SUPPORT_GROUP_ID не задан. Укажите его в .env")
        sys.exit(1)
    if not SUPER_ADMIN_USER_IDS:
        logger.warning(
            "SUPER_ADMIN_USER_IDS пуст — добавление админов через /addadmin будет недоступно, "
            "пока не зададите хотя бы один id в .env"
        )

    try:
        log_event("info", "Starting Telegram Ticket Bot...")
        init_db()
        seed_super_admins()

        application = Application.builder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("myid", cmd_myid))
        application.add_handler(CommandHandler("admin_help", cmd_admin_help))
        application.add_handler(CommandHandler("listcontent", cmd_listcontent))
        application.add_handler(CommandHandler("getcontent", cmd_getcontent))
        application.add_handler(CommandHandler("setcontent", cmd_setcontent))
        application.add_handler(CommandHandler("seturl", cmd_seturl))
        application.add_handler(CommandHandler("upload_instruction", cmd_upload_instruction))
        application.add_handler(CommandHandler("addadmin", cmd_addadmin))
        application.add_handler(CommandHandler("removeadmin", cmd_removeadmin))
        application.add_handler(CommandHandler("listadmins", cmd_listadmins))

        application.add_handler(CommandHandler("tickets", show_tickets))
        application.add_handler(CommandHandler("closed", show_closed_tickets))
        application.add_handler(CommandHandler("reopen", reopen_ticket))
        application.add_handler(CommandHandler("newticket", new_ticket_command))
        application.add_handler(CommandHandler("closeticket", close_ticket_user))
        application.add_handler(CommandHandler("myticket", my_ticket))

        application.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, handle_user_message))
        application.add_handler(
            MessageHandler(filters.ChatType.GROUPS & filters.REPLY & ~filters.COMMAND, handle_admin_reply)
        )
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_error_handler(error_handler)

        log_event("info", "Bot started successfully")
        print("Бот запущен. DATA_DIR=", DATA_DIR)
        application.run_polling()
    except Exception as e:
        log_event("error", f"Bot crashed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
