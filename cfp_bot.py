import logging
import sqlite3
import asyncio
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from telegram.ext import MessageHandler, ApplicationBuilder, CommandHandler, CallbackQueryHandler
from telegram.ext import filters  # Новый импорт для фильтров
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext

with open("config.json") as f:
    config = json.load(f)

for key in ("spreadsheet_id", "range_name", "bot_token"):
    if not config.get(key):
        raise ValueError(f"{key} не найден в config.json!")

SPREADSHEET_ID, RANGE_NAME, TOKEN = config["spreadsheet_id"], config["range_name"], config["bot_token"]

ADMIN_IDS = config.get("admin_ids", [])

logging.basicConfig(level=logging.INFO)
scheduler = BackgroundScheduler()

CREDENTIALS_FILE = 'credentials.json'

# Подписки пользователей
user_subscriptions = {}

# Список доступных категорий
CATEGORIES = [
    "Frontend", "Backend", "DevOps", "Mobile", "Data Science", 
    "Analytics", "TeamLead / Management", "QA", 
    "Cybersecurity", "HR", "Marketing", "Product", "Design", 
]

# Добавьте эти глобальные переменные в начале файла (например, сразу после импорта модулей)
BOT_APP = None   # Будет хранить экземпляр приложения (бота)
BOT_LOOP = None  # Будет хранить event loop приложения

def init_db():
    conn = sqlite3.connect("subscriptions.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            stacks TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_subscription(user_id: int, stack: str):
    conn = sqlite3.connect("subscriptions.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT stacks FROM subscriptions WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row:
        stacks = set(row[0].split(","))
        stacks.add(stack)
        cursor.execute("UPDATE subscriptions SET stacks = ? WHERE user_id = ?", (",".join(stacks), user_id))
    else:
        cursor.execute("INSERT INTO subscriptions (user_id, stacks) VALUES (?, ?)", (user_id, stack))
    
    conn.commit()
    conn.close()

def get_user_subscriptions(user_id: int):
    conn = sqlite3.connect("subscriptions.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT stacks FROM subscriptions WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    conn.close()
    return set(row[0].split(",")) if row else set()

def get_users_for_category(category: str):
    conn = sqlite3.connect("subscriptions.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id FROM subscriptions WHERE stacks LIKE ?", (f"%{category}%",))
    users = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    return users

def get_all_users():
    """Возвращает список всех подписчиков (user_id) из базы данных."""
    conn = sqlite3.connect("subscriptions.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM subscriptions")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветственное сообщение."""
    await update.message.reply_text("Добро пожаловать! Используйте /subscribe для выбора стека конференций.")

async def subscribe(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_subs = get_user_subscriptions(user_id)  # Получить текущие подписки пользователя
    
    keyboard = [
    [InlineKeyboardButton(f"{'✅ ' if category in user_subs else ''}{category}", callback_data=f"toggle:{category}")]
    for category in CATEGORIES
    ]
    keyboard.append([InlineKeyboardButton("Подтвердить выбор", callback_data="confirm_subscription")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    subscription_info = (
        "Выберите категории для подписки:\n\n"
        "После подписки вы будете получать:\n"
        "- Напоминания о закрытии CFP за неделю и за день до окончания приема заявок.\n"
        "- Уведомления о новых CFP в выбранных вами категориях."
    )
    
    await update.message.reply_text(subscription_info, reply_markup=reply_markup)
    keyboard = [
        [InlineKeyboardButton(f"Отписаться от {category}", callback_data=f"unsubscribe:{category}")]
        for category in user_subs 
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
def remove_subscription(user_id: int, stack: str):
    """Удаляет подписку пользователя от указанной категории."""
    conn = sqlite3.connect("subscriptions.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT stacks FROM subscriptions WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row:
        stacks = set(row[0].split(","))
        if stack in stacks:
            stacks.remove(stack)
            if stacks:
                cursor.execute("UPDATE subscriptions SET stacks = ? WHERE user_id = ?", (",".join(stacks), user_id))
            else:
                cursor.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
    
    conn.commit()
    conn.close()

async def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data.startswith("toggle:"):
        category = query.data.split(":")[1]
        user_subs = get_user_subscriptions(user_id)
        if category in user_subs:
            remove_subscription(user_id, category)
        else:
            add_subscription(user_id, category)
        
        updated_subs = get_user_subscriptions(user_id)
        keyboard = [
            [InlineKeyboardButton(f"{'✅ ' if cat in updated_subs else ''}{cat}", callback_data=f"toggle:{cat}")]
            for cat in CATEGORIES
        ]
        keyboard.append([InlineKeyboardButton("Подтвердить выбор", callback_data="confirm_subscription")])
        await query.edit_message_text("Выберите категории для подписки:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == "confirm_subscription":
        await my_conferences(update, context)

async def list_conferences_by_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет список конференций с открытым CFP по выбранной категории."""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    if data[0] == "subscribe":
        category = data[1]
        conferences = get_conferences_by_category(category)
        if not conferences:
            await query.edit_message_text(f"Нет доступных конференций с открытым CFP для категории: {category}.")
        else:
            conference_list = "\n".join(conferences)
            await query.edit_message_text(f"Конференции с открытым CFP для категории '{category}':\n{conference_list}")

def get_conferences_by_category(category):
    credentials = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    service = build('sheets', 'v4', credentials=credentials, cache_discovery=False)
    sheet = service.spreadsheets()
    
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range="A1:E").execute()
    rows = result.get('values', [])
    now = datetime.now().date()
    conferences = []

    for row in rows[1:]:
        if len(row) < 5:
            continue
        name, start_date, cfp_deadline, conf_categories, link = row
        try:
            cfp_date = datetime.strptime(cfp_deadline, "%d.%m.%Y").date()
            if category.lower() in map(str.lower, conf_categories.split(", ")) and cfp_date >= now:
                conferences.append(f"{name} | CFP до {cfp_deadline} | {link}")
        except ValueError:
            continue
    
    return conferences


async def notify_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправка уведомлений подписчикам по категориям с поддержкой текста (с пропусками строк) и медиа.
       Если указана категория 'all' или 'все', сообщение будет отправлено всем подписчикам."""
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав для этой команды.")
        return

    # Извлекаем полный текст сообщения, включая все переносы строк
    full_text = update.message.text
    # Формат: /notify <категория> <сообщение с переносами строк>
    parts = full_text.split(' ', 2)
    if len(parts) < 3:
        await update.message.reply_text("Использование: /notify <категория или 'all'> <сообщение>")
        return

    category = parts[1]
    message = parts[2]

    # Если категория 'all' или 'все', берём всех подписчиков
    if category.lower() in ["all", "все"]:
        user_ids = get_all_users()  # Функция должна возвращать список всех подписчиков
        category_description = "всех категорий"
    else:
        user_ids = get_users_for_category(category)
        category_description = f"категории '{category}'"

    if not user_ids:
        await update.message.reply_text(f"Нет подписчиков для {category_description}.")
        return

    # Проверка на наличие медиа
    media_file_id = None
    media_type = None

    if update.message.photo:
        media_type = "photo"
        media_file_id = update.message.photo[-1].file_id
    elif update.message.video:
        media_type = "video"
        media_file_id = update.message.video.file_id
    elif update.message.document:
        media_type = "document"
        media_file_id = update.message.document.file_id

    sent_count = 0
    for user_id in user_ids:
        try:
            if media_type == "photo":
                await context.bot.send_photo(chat_id=user_id, photo=media_file_id, caption=message)
            elif media_type == "video":
                await context.bot.send_video(chat_id=user_id, video=media_file_id, caption=message)
            elif media_type == "document":
                await context.bot.send_document(chat_id=user_id, document=media_file_id, caption=message)
            else:
                await context.bot.send_message(chat_id=user_id, text=message)
            sent_count += 1
        except Exception as e:
            logging.error(f"Ошибка при отправке для {user_id}: {e}")

    await update.message.reply_text(f"Сообщение отправлено {sent_count} подписчикам {category_description}.")
    
async def my_conferences(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список конференций по подпискам пользователя, включая категории без доступных конференций."""
    user_id = update.effective_user.id
    
    # Отправка временного сообщения о загрузке
    loading_message = await context.bot.send_message(chat_id=user_id, text="Загрузка, пожалуйста, подождите...")
    
    user_subscriptions = get_user_subscriptions(user_id)
    if not user_subscriptions:
        await context.bot.edit_message_text(chat_id=user_id, message_id=loading_message.message_id, text="Вы не подписаны ни на одну категорию. Используйте /subscribe для подписки.")
        return

    all_conferences = []
    for category in user_subscriptions:
        conferences = get_conferences_by_category(category)
        if conferences:
            conference_list = "\n".join(conferences)
            all_conferences.append(f"Категория: {category}\n{conference_list}")
        else:
            all_conferences.append(f"Категория: {category}\nНет доступных конференций с открытым CFP.")
    
    result_text = "\n\n".join(all_conferences)
    await context.bot.edit_message_text(chat_id=user_id, message_id=loading_message.message_id, text=f"Ваши подписки и конференции с открытым CFP:\n\n{result_text}",disable_web_page_preview=True)

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет сообщение об ошибке при неизвестной команде."""
    await update.message.reply_text("Извините, я не понимаю эту команду. Используйте /help для списка доступных команд.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет список доступных команд и их описание."""
    help_text = (
        "DevRel CFP Bot — это удобный бот, который поможет вам быть в курсе актуальных CFP (Call for Papers) русскоязычных ИТ-конференций.\n"
        "\n"
        "Команды:\n"
        "\n"
        "• /subscribe — Подписаться на выбранные категории конференций или изменить существующие подписки. После подписки вы будете получать:.\n"
        "- Напоминания о закрытии CFP за неделю и за день до окончания приема заявок.\n"
        "- Уведомления о новых CFP в выбранных вами категориях.\n"
        "\n"
        "• /my_conferences — Просмотреть список конференций по вашим подпискам.\n"
        "\n"
        "Если у вас есть вопросы, вы заметили ошибку или у вас есть предложения по улучшению бота, пожалуйста, пишите @m3rlyn.\n"
    )
    await update.message.reply_text(help_text)

def get_subscriber_counts():
    """Возвращает количество подписчиков по каждой категории и общее число уникальных подписчиков."""
    conn = sqlite3.connect("subscriptions.db")
    cursor = conn.cursor()
    
    counts = {}
    # Подсчет подписчиков по каждой категории
    for category in CATEGORIES:
        cursor.execute("SELECT COUNT(user_id) FROM subscriptions WHERE stacks LIKE ?", (f"%{category}%",))
        count = cursor.fetchone()[0]
        counts[category] = count

    # Подсчет общего числа уникальных подписчиков (по строкам в таблице)
    cursor.execute("SELECT COUNT(user_id) FROM subscriptions")
    total_unique = cursor.fetchone()[0]

    conn.close()
    return counts, total_unique

async def subscribers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает количество подписчиков по категориям (только для админов), включая общее число уникальных подписчиков."""
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав для этой команды.")
        return

    category_counts, total_unique = get_subscriber_counts()
    message_lines = [f"{category}: {count} подписчиков" for category, count in category_counts.items()]
    message_lines.append(f"\nВсего уникальных подписчиков: {total_unique}")

    message = "\n".join(message_lines)
    await update.message.reply_text(f"Количество подписчиков по категориям:\n\n{message}")

def get_users_for_category(category: str):
    conn = sqlite3.connect("subscriptions.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM subscriptions WHERE stacks LIKE ?", (f"%{category}%",))
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_all_conferences():
    """
    Получает все конференции из Google Sheets.
    Предполагается, что таблица имеет следующие столбцы:
      [Название, Дата начала, CFP дедлайн (в формате dd.mm.yyyy), Категории, Ссылка]
    """
    try:
        credentials = Credentials.from_service_account_file(
            CREDENTIALS_FILE,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )
        service = build('sheets', 'v4', credentials=credentials, cache_discovery=False)
        sheet = service.spreadsheets()
        # Используем диапазон A1:E (заголовок в первой строке)
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range="A1:E").execute()
        rows = result.get('values', [])
    except Exception as e:
        logging.error(f"Ошибка при получении данных из Google Sheets: {e}")
        return []

    conferences = []
    # Пропускаем первую строку (заголовки)
    for row in rows[1:]:
        if len(row) < 5:
            continue
        name, start_date, cfp_deadline, categories_str, link = row
        try:
            cfp_date = datetime.strptime(cfp_deadline, "%d.%m.%Y").date()
        except ValueError:
            logging.warning(f"Неверный формат даты для конференции '{name}': {cfp_deadline}")
            continue
        # Разбиваем строку с категориями по запятой
        categories = [cat.strip() for cat in categories_str.split(",")]
        conferences.append({
            'name': name,
            'start_date': start_date,
            'cfp_deadline': cfp_deadline,
            'cfp_date': cfp_date,
            'categories': categories,
            'link': link
        })
    return conferences

def notify_cfp_deadlines():
    """
    Проверяет все конференции и, если до дедлайна CFP осталось ровно 7 или 1 день,
    отправляет уведомление подписанным пользователям.
    """
    logging.info("Запуск проверки дедлайнов CFP...")
    today = datetime.now().date()
    conferences = get_all_conferences()
    for conf in conferences:
        days_left = (conf['cfp_date'] - today).days
        if days_left in (7, 1):
            # Формируем текст уведомления
            day_text = "1 день" if days_left == 1 else f"{days_left} дней"
            message = (
                f"Напоминаем!\nДо дедлайна CFP конференции «{conf['name']}» осталось {day_text}.\n"
                f"Подробности: {conf['link']}"
            )
            notified_users = set()  # Чтобы не отправлять одному пользователю несколько раз
            for category in conf['categories']:
                user_ids = get_users_for_category(category)
                for user_id in user_ids:
                    if user_id in notified_users:
                        continue
                    notified_users.add(user_id)
                    # Отправка сообщения через бот; BOT_APP и BOT_LOOP должны быть определены (см. ниже)
                    future = asyncio.run_coroutine_threadsafe(
                        BOT_APP.bot.send_message(chat_id=user_id, text=message),
                        BOT_LOOP
                    )
                    try:
                        future.result(timeout=10)
                    except Exception as e:
                        logging.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")
    logging.info("Проверка дедлайнов CFP завершена.")

def main():
    global BOT_APP, BOT_LOOP

    # Инициализация базы данных
    # init_db()

    # Инициализация приложения Telegram Bot
    app = ApplicationBuilder().token(TOKEN).build()
    BOT_APP = app
    BOT_LOOP = asyncio.get_event_loop()


    # Регистрация обработчиков команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("notify", notify_category))
    app.add_handler(CommandHandler("my_conferences", my_conferences))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("subscribers", subscribers))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))


    scheduler.add_job(notify_cfp_deadlines, trigger='cron', hour=9, minute=0)
    scheduler.start()


    # Запуск бота
    app.run_polling()

if __name__ == '__main__':
    main()