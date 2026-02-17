import sqlite3
import logging
from telebot import TeleBot, types

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Конфигурация
TOKEN = 'YOUR_BOT_TOKEN'  # замените на реальный токен
bot = TeleBot(TOKEN)

# Имя файла базы данных
DB_NAME = 'vodnik_bot.db'

# ---------- Работа с базой данных ----------
def init_db():
    """Создаёт таблицу users, если её нет."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER UNIQUE,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            addr TEXT,
            comment TEXT
        )
    ''')
    conn.commit()
    conn.close()
    logging.info("База данных инициализирована.")

def save_user(chat_id, first_name, last_name, username):
    """Сохраняет или обновляет основные данные пользователя (без addr)."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO users (chat_id, first_name, last_name, username)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            username = excluded.username
    ''', (chat_id, first_name, last_name, username))
    conn.commit()
    conn.close()

def update_user_addr(chat_id, addr):
    """Обновляет поле addr у пользователя."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('UPDATE users SET addr = ? WHERE chat_id = ?', (addr, chat_id))
    conn.commit()
    conn.close()

def update_user_comment(chat_id, comment):
    """Обновляет поле comment у пользователя."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('UPDATE users SET comment = ? WHERE chat_id = ?', (comment, chat_id))
    conn.commit()
    conn.close()

# ---------- Клавиатуры ----------
def yes_no_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton('Да'), types.KeyboardButton('Нет'))
    return markup

def location_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(
        types.KeyboardButton('Я в Нижнем Новгороде'),
        types.KeyboardButton('Я в России'),
        types.KeyboardButton('Я за рубежом')
    )
    return markup

def nn_actions_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton('Расклеить листовки'), types.KeyboardButton('Собрать подписи'))
    markup.row(types.KeyboardButton('Предложить иную помощь'), types.KeyboardButton('Назад'))
    return markup

def russia_actions_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton('Написать в прокуратуру'), types.KeyboardButton('Собрать подписи'))
    markup.row(types.KeyboardButton('Предложить иную помощь'), types.KeyboardButton('Назад'))
    return markup

def abroad_actions_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton('Написать в прокуратуру'))
    markup.row(types.KeyboardButton('Предложить иную помощь'), types.KeyboardButton('Назад'))
    return markup

def back_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton('Назад'))
    return markup

# ---------- Состояния пользователей ----------
# Простая машина состояний: храним для каждого chat_id текущий шаг
# и, возможно, выбранную локацию.
user_state = {}  # chat_id -> {'step': 'waiting_help' / 'waiting_location' / 'in_menu', 'location': ...}

# ---------- Обработчики ----------
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    user_state[chat_id] = {'step': 'waiting_help'}
    bot.send_message(
        chat_id,
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Я бот для защиты стадиона «Водник» в Нижнем Новгороде от застройки.\n\n"
        "Хотите помочь в защите стадиона?",
        reply_markup=yes_no_keyboard()
    )
    logging.info(f"Пользователь {chat_id} начал диалог.")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    chat_id = message.chat.id
    text = message.text
    state = user_state.get(chat_id)

    # Если состояние не определено (например, после перезапуска бота), предложим /start
    if not state:
        bot.send_message(chat_id, "Нажмите /start, чтобы начать.")
        return

    step = state['step']

    # ---------- Ожидание ответа на вопрос о помощи ----------
    if step == 'waiting_help':
        if text == 'Да':
            # Сохраняем пользователя
            save_user(
                chat_id,
                message.from_user.first_name,
                message.from_user.last_name,
                message.from_user.username
            )
            # Переходим к выбору местоположения
            user_state[chat_id]['step'] = 'waiting_location'
            bot.send_message(
                chat_id,
                "Отлично! Спасибо за готовность помочь! 🙏\n"
                "Пожалуйста, укажите, где вы находитесь:",
                reply_markup=location_keyboard()
            )
        elif text == 'Нет':
            bot.send_message(
                chat_id,
                "Очень жаль. Если передумаете — нажмите /start.",
                reply_markup=types.ReplyKeyboardRemove()
            )
            # Сбрасываем состояние
            del user_state[chat_id]
        else:
            bot.send_message(
                chat_id,
                "Пожалуйста, ответьте с помощью кнопок:",
                reply_markup=yes_no_keyboard()
            )

    # ---------- Ожидание выбора местоположения ----------
    elif step == 'waiting_location':
        location_map = {
            'Я в Нижнем Новгороде': 'Нижний Новгород',
            'Я в России': 'Россия',
            'Я за рубежом': 'За рубежом'
        }
        if text in location_map:
            addr = location_map[text]
            # Обновляем адрес в БД
            update_user_addr(chat_id, addr)
            # Сохраняем локацию в состоянии и переходим в меню
            user_state[chat_id]['location'] = addr
            user_state[chat_id]['step'] = 'in_menu'

            # Показываем соответствующее меню
            bot.send_message(
                chat_id,
                "Спасибо! Вы можете выбрать один или несколько вариантов помощи "
                "(их можно совмещать между собой в любых комбинациях):\n\n"
                "Выберите действие:",
                reply_markup=_get_actions_keyboard(addr)
            )
        else:
            bot.send_message(
                chat_id,
                "Пожалуйста, выберите вариант с помощью кнопок:",
                reply_markup=location_keyboard()
            )

    # ---------- Нахождение в меню действий ----------
    elif step == 'in_menu':
        location = state['location']

        # Обработка кнопки "Назад" (возврат в меню)
        if text == 'Назад':
            bot.send_message(
                chat_id,
                "Выберите действие:",
                reply_markup=_get_actions_keyboard(location)
            )
            return

        # Обработка конкретных действий
        if location == 'Нижний Новгород':
            if text == 'Расклеить листовки':
                bot.send_message(
                    chat_id,
                    "📄 **Расклейка листовок**\n\n"
                    "1. Получите материалы у координаторов.\n"
                    "2. Расклейте в людных местах рядом со стадионом.\n"
                    "3. Не нарушайте правила расклейки.\n\n"
                    "Спасибо за помощь!",
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            elif text == 'Собрать подписи':
                bot.send_message(
                    chat_id,
                    "📋 **Сбор подписей**\n\n"
                    "1. Скачайте бланк петиции у координаторов.\n"
                    "2. Собирайте подписи у друзей, соседей, прохожих.\n"
                    "3. Передайте заполненные бланки координаторам.\n\n"
                    "Спасибо за помощь!",
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            elif text == 'Предложить иную помощь':
                user_state[chat_id]['step'] = 'waiting_custom_help'
                bot.send_message(
                    chat_id,
                    "💡 **Предложить иную помощь**\n\n"
                    "Кратко опишите, чем вы можете помочь, и оставьте контактные данные для связи.\n\n"
                    "Например: «Могу помочь с организацией митинга. Телефон: +7 XXX XXX-XX-XX»",
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            else:
                # Неизвестная кнопка — повторяем меню
                bot.send_message(
                    chat_id,
                    "Пожалуйста, выберите действие с помощью кнопок:",
                    reply_markup=nn_actions_keyboard()
                )

        elif location == 'Россия':
            if text == 'Написать в прокуратуру':
                bot.send_message(
                    chat_id,
                    "📝 **Письмо в прокуратуру**\n\n"
                    "1. Скачайте образец письма у координаторов.\n"
                    "2. Заполните своими данными.\n"
                    "3. Отправьте почтой или через сайт прокуратуры.\n\n"
                    "Спасибо за помощь!",
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            elif text == 'Собрать подписи':
                bot.send_message(
                    chat_id,
                    "📋 **Сбор подписей**\n\n"
                    "1. Скачайте бланк петиции.\n"
                    "2. Собирайте подписи в своём городе.\n"
                    "3. Отправьте скан на email координаторов.\n\n"
                    "Спасибо за помощь!",
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            elif text == 'Предложить иную помощь':
                user_state[chat_id]['step'] = 'waiting_custom_help'
                bot.send_message(
                    chat_id,
                    "💡 **Предложить иную помощь**\n\n"
                    "Кратко опишите, чем вы можете помочь, и оставьте контактные данные для связи.\n\n"
                    "Например: «Могу организовать сбор подписей в своём городе. Телефон: +7 XXX XXX-XX-XX»",
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            else:
                bot.send_message(
                    chat_id,
                    "Пожалуйста, выберите действие с помощью кнопок:",
                    reply_markup=russia_actions_keyboard()
                )

        elif location == 'За рубежом':
            if text == 'Написать в прокуратуру':
                bot.send_message(
                    chat_id,
                    "📝 **Письмо в прокуратуру (международная поддержка)**\n\n"
                    "1. Скачайте образец письма на английском/русском.\n"
                    "2. Заполните и отправьте по email: international@genproc.gov.ru\n"
                    "3. Копию можно отправить в международные организации.\n\n"
                    "Спасибо за международную поддержку!",
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            elif text == 'Предложить иную помощь':
                user_state[chat_id]['step'] = 'waiting_custom_help'
                bot.send_message(
                    chat_id,
                    "💡 **Предложить иную помощь**\n\n"
                    "Кратко опишите, чем вы можете помочь, и оставьте контактные данные для связи.\n\n"
                    "Например: «Могу привлечь внимание международных СМИ. WhatsApp: +XX XXX XXX-XX-XX»",
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            else:
                bot.send_message(
                    chat_id,
                    "Пожалуйста, выберите действие с помощью кнопок:",
                    reply_markup=abroad_actions_keyboard()
                )

    # ---------- Ожидание текста предложения ----------
    elif step == 'waiting_custom_help':
        if text == 'Назад':
            # Возврат в меню
            location = state['location']
            user_state[chat_id]['step'] = 'in_menu'
            bot.send_message(
                chat_id,
                "Выберите действие:",
                reply_markup=_get_actions_keyboard(location)
            )
        else:
            # Сохраняем предложение в поле comment
            update_user_comment(chat_id, text)
            bot.send_message(
                chat_id,
                "🙏 **Спасибо за ваше предложение!**\n\n"
                "Мы обязательно рассмотрим его и свяжемся с вами в ближайшее время.\n"
                "Совместными усилиями мы сможем защитить стадион «Водник»!",
                parse_mode='Markdown',
                reply_markup=types.ReplyKeyboardRemove()
            )
            # После благодарности возвращаемся в меню (или можно завершить диалог)
            # По логике, предложивший помощь может захотеть ещё что-то сделать.
            # Поэтому покажем меню снова.
            location = state['location']
            user_state[chat_id]['step'] = 'in_menu'
            bot.send_message(
                chat_id,
                "Вы можете выбрать другие варианты помощи:",
                reply_markup=_get_actions_keyboard(location)
            )

# Вспомогательная функция для получения клавиатуры по локации
def _get_actions_keyboard(location):
    if location == 'Нижний Новгород':
        return nn_actions_keyboard()
    elif location == 'Россия':
        return russia_actions_keyboard()
    else:  # За рубежом
        return abroad_actions_keyboard()

# ---------- Запуск бота ----------
if __name__ == '__main__':
    init_db()
    logging.info("Бот запущен...")
    bot.infinity_polling()
