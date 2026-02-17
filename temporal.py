import sqlite3
import threading
import time
from datetime import datetime
import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Конфигурация
TOKEN = 
SUPERGROUP_ID = 

bot = telebot.TeleBot(TOKEN)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER UNIQUE,
        first_name TEXT,
        last_name TEXT,
        username TEXT,
        addr TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица для хранения topic_id для каждого пользователя
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_topics (
        user_id INTEGER,
        topic_id INTEGER,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# Словари для хранения состояний
user_states = {}
broadcast_states = {}
stop_events = {}

# Класс для хранения состояний пользователя
class UserState:
    def __init__(self):
        self.waiting_for_help_response = False
        self.waiting_for_location = False
        self.waiting_for_action = False
        self.waiting_for_custom_help = False
        self.location = None

# Получение или создание состояния пользователя
def get_user_state(user_id):
    if user_id not in user_states:
        user_states[user_id] = UserState()
    return user_states[user_id]

# Работа с базой данных
def save_user(chat_id, first_name, last_name, username):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        INSERT OR REPLACE INTO users (chat_id, first_name, last_name, username)
        VALUES (?, ?, ?, ?)
        ''', (chat_id, first_name, last_name, username))
        conn.commit()
    except Exception as e:
        print(f"Ошибка сохранения пользователя: {e}")
    finally:
        conn.close()

def update_user_address(chat_id, addr):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('UPDATE users SET addr = ? WHERE chat_id = ?', (addr, chat_id))
        conn.commit()
    except Exception as e:
        print(f"Ошибка обновления адреса: {e}")
    finally:
        conn.close()

def save_user_topic(user_id, topic_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('INSERT OR REPLACE INTO user_topics (user_id, topic_id) VALUES (?, ?)',
                      (user_id, topic_id))
        conn.commit()
    except Exception as e:
        print(f"Ошибка сохранения topic_id: {e}")
    finally:
        conn.close()

def get_user_by_chat_id(chat_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users WHERE chat_id = ?', (chat_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def get_user_id_by_chat_id(chat_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM users WHERE chat_id = ?', (chat_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_topic_id_by_user_id(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT topic_id FROM user_topics WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_users_by_addr(addr=None):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    if addr:
        cursor.execute('SELECT chat_id FROM users WHERE addr = ?', (addr,))
    else:
        cursor.execute('SELECT chat_id FROM users')
    
    users = cursor.fetchall()
    conn.close()
    return [user[0] for user in users]

# Создание темы в супергруппе
def create_forum_topic(user_data):
    try:
        # Создаем тему с именем пользователя
        topic_name = f"{user_data['username'] or ''} {user_data['first_name']} {user_data['last_name']}".strip()
        
        # В Telebot API пока нет прямой поддержки создания тем в форумах
        # Используем альтернативный подход с пересылкой первого сообщения
        
        # Отправляем сообщение в супергруппу с текстом, который станет началом темы
        message = bot.send_message(
            SUPERGROUP_ID,
            f"📝 Новая тема: {topic_name}\n"
            f"Пользователь: {user_data['first_name']} {user_data['last_name']} (@{user_data['username']})\n"
            f"Готов помочь защитить стадион 'Водник'!"
        )
        
        # Сохраняем message_id как идентификатор темы
        topic_id = message.message_id
        
        return topic_id
    except Exception as e:
        print(f"Ошибка создания темы: {e}")
        return None

# Пересылка сообщения в супергруппу
def forward_to_supergroup(user_id, message):
    try:
        user = get_user_by_chat_id(user_id)
        if not user:
            return None
            
        user_db_id = get_user_id_by_chat_id(user_id)
        topic_id = get_topic_id_by_user_id(user_db_id)
        
        if not topic_id:
            # Создаем новую тему
            user_data = {
                'first_name': user[2],
                'last_name': user[3],
                'username': user[4]
            }
            topic_id = create_forum_topic(user_data)
            if topic_id:
                save_user_topic(user_db_id, topic_id)
        
        # Пересылаем сообщение
        if message.content_type == 'text':
            forwarded_msg = bot.send_message(
                SUPERGROUP_ID,
                f"👤 Сообщение от пользователя:\n{message.text}",
                reply_to_message_id=topic_id
            )
        elif message.content_type == 'photo':
            forwarded_msg = bot.send_photo(
                SUPERGROUP_ID,
                message.photo[-1].file_id,
                caption=message.caption or "📸 Фото от пользователя",
                reply_to_message_id=topic_id
            )
        else:
            # Для других типов контента
            forwarded_msg = bot.forward_message(
                SUPERGROUP_ID,
                message.chat.id,
                message.message_id
            )
        
        return forwarded_msg.message_id
    except Exception as e:
        print(f"Ошибка пересылки в супергруппу: {e}")
        return None

# Обработка команды /start
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_state = get_user_state(message.chat.id)
    user_state.waiting_for_help_response = True
    
    bot.send_message(
        message.chat.id,
        f"Привет, {message.from_user.first_name}! 👋\n"
        "Я бот для защиты стадиона «Водник» в Нижнем Новгороде от застройки.\n\n"
        "Хотите помочь в защите стадиона?",
        reply_markup=create_yes_no_keyboard()
    )

# Создание клавиатуры с кнопками Да/Нет
def create_yes_no_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton('Да'), types.KeyboardButton('Нет'))
    return markup

# Создание клавиатуры для выбора местоположения
def create_location_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(
        types.KeyboardButton('Я в Нижнем Новгороде'),
        types.KeyboardButton('Я в России'),
        types.KeyboardButton('Я за рубежом')
    )
    return markup

# Создание клавиатуры для действий в Нижнем Новгороде
def create_nn_actions_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(
        types.KeyboardButton('Расклеить листовки'),
        types.KeyboardButton('Собрать подписи'),
        types.KeyboardButton('Предложить иную помощь'),
        types.KeyboardButton('Назад')
    )
    return markup

# Создание клавиатуры для действий в России
def create_russia_actions_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(
        types.KeyboardButton('Написать в прокуратуру'),
        types.KeyboardButton('Собрать подписи'),
        types.KeyboardButton('Предложить иную помощь'),
        types.KeyboardButton('Назад')
    )
    return markup

# Создание клавиатуры для действий за рубежом
def create_abroad_actions_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(
        types.KeyboardButton('Написать в прокуратуру'),
        types.KeyboardButton('Предложить иную помощь'),
        types.KeyboardButton('Назад')
    )
    return markup

# Создание кнопки "Назад"
def create_back_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton('Назад'))
    return markup

# Основной обработчик сообщений
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_state = get_user_state(message.chat.id)
    
    # Пересылка всех сообщений в супергруппу
    forward_to_supergroup(message.chat.id, message)
    
    # Обработка ответа на вопрос о помощи
    if user_state.waiting_for_help_response:
        if message.text == 'Да':
            # Сохраняем пользователя в БД
            save_user(
                message.chat.id,
                message.from_user.first_name,
                message.from_user.last_name,
                message.from_user.username
            )
            
            user_state.waiting_for_help_response = False
            user_state.waiting_for_location = True
            
            bot.send_message(
                message.chat.id,
                "Отлично! Спасибо за готовность помочь! 🙏\n"
                "Пожалуйста, укажите, где вы находитесь:",
                reply_markup=create_location_keyboard()
            )
        elif message.text == 'Нет':
            bot.send_message(
                message.chat.id,
                "Жаль. Если передумаете - обращайтесь!",
                reply_markup=types.ReplyKeyboardRemove()
            )
            user_state.waiting_for_help_response = False
        else:
            bot.send_message(
                message.chat.id,
                "Пожалуйста, ответьте с помощью кнопок:",
                reply_markup=create_yes_no_keyboard()
            )
    
    # Обработка выбора местоположения
    elif user_state.waiting_for_location:
        if message.text == 'Я в Нижнем Новгороде':
            update_user_address(message.chat.id, "Нижний Новгород")
            user_state.location = "Нижний Новгород"
            user_state.waiting_for_location = False
            user_state.waiting_for_action = True
            
            bot.send_message(
                message.chat.id,
                "Спасибо! Вы можете выбрать один или несколько вариантов помощи:\n\n"
                "Выберите действие:",
                reply_markup=create_nn_actions_keyboard()
            )
            
        elif message.text == 'Я в России':
            update_user_address(message.chat.id, "Россия")
            user_state.location = "Россия"
            user_state.waiting_for_location = False
            user_state.waiting_for_action = True
            
            bot.send_message(
                message.chat.id,
                "Спасибо! Вы можете выбрать один или несколько вариантов помощи:\n\n"
                "Выберите действие:",
                reply_markup=create_russia_actions_keyboard()
            )
            
        elif message.text == 'Я за рубежом':
            update_user_address(message.chat.id, "За рубежом")
            user_state.location = "За рубежом"
            user_state.waiting_for_location = False
            user_state.waiting_for_action = True
            
            bot.send_message(
                message.chat.id,
                "Спасибо! Вы можете выбрать один или несколько вариантов помощи:\n\n"
                "Выберите действие:",
                reply_markup=create_abroad_actions_keyboard()
            )
        else:
            bot.send_message(
                message.chat.id,
                "Пожалуйста, выберите вариант с помощью кнопок:",
                reply_markup=create_location_keyboard()
            )
    
    # Обработка действий для Нижнего Новгорода
    elif user_state.waiting_for_action and user_state.location == "Нижний Новгород":
        if message.text == 'Расклеить листовки':
            bot.send_message(
                message.chat.id,
                "📄 Расклейка листовок:\n\n"
                "1. Скачайте листовки по ссылке: [ссылка на листовки]\n"
                "2. Распечатайте их\n"
                "3. Расклейте в людных местах, особенно рядом со стадионом\n"
                "4. Соблюдайте местные законы о расклейке\n\n"
                "Спасибо за помощь!",
                reply_markup=create_back_keyboard()
            )
        elif message.text == 'Собрать подписи':
            bot.send_message(
                message.chat.id,
                "📋 Сбор подписей:\n\n"
                "1. Скачайте бланк петиции: [ссылка на петицию]\n"
                "2. Распечатайте его\n"
                "3. Собирайте подписи у друзей, родственников, коллег\n"
                "4. Особенно эффективно собирать подписи на мероприятиях\n"
                "5. Отправьте заполненные бланки по адресу: [адрес]\n\n"
                "Спасибо за помощь!",
                reply_markup=create_back_keyboard()
            )
        elif message.text == 'Предложить иную помощь':
            user_state.waiting_for_action = False
            user_state.waiting_for_custom_help = True
            bot.send_message(
                message.chat.id,
                "💡 Предложите свою помощь:\n\n"
                "Кратко опишите, чем вы можете помочь, и оставьте контакты для связи.\n"
                "Например: 'Могу помочь с организацией митинга. Telegram: @username'",
                reply_markup=create_back_keyboard()
            )
        elif message.text == 'Назад':
            user_state.waiting_for_action = True
            bot.send_message(
                message.chat.id,
                "Выберите действие:",
                reply_markup=create_nn_actions_keyboard()
            )
        else:
            bot.send_message(
                message.chat.id,
                "Пожалуйста, выберите действие с помощью кнопок:",
                reply_markup=create_nn_actions_keyboard()
            )
    
    # Обработка действий для России
    elif user_state.waiting_for_action and user_state.location == "Россия":
        if message.text == 'Написать в прокуратуру':
            bot.send_message(
                message.chat.id,
                "📝 Письмо в прокуратуру:\n\n"
                "1. Скачайте образец письма: [ссылка на образец]\n"
                "2. Заполните свои данные\n"
                "3. Отправьте по адресу: прокуратура Нижнего Новгорода, ул. [адрес]\n"
                "4. Или отправьте онлайн через портал: [ссылка]\n\n"
                "Спасибо за помощь!",
                reply_markup=create_back_keyboard()
            )
        elif message.text == 'Собрать подписи':
            bot.send_message(
                message.chat.id,
                "📋 Сбор подписей:\n\n"
                "1. Скачайте бланк петиции: [ссылка на петицию]\n"
                "2. Распечатайте его\n"
                "3. Собирайте подписи у друзей, родственников, коллег\n"
                "4. Особенно эффективно собирать подписи на мероприятиях\n"
                "5. Отправьте заполненные бланки по адресу: [адрес]\n\n"
                "Спасибо за помощь!",
                reply_markup=create_back_keyboard()
            )
        elif message.text == 'Предложить иную помощь':
            user_state.waiting_for_action = False
            user_state.waiting_for_custom_help = True
            bot.send_message(
                message.chat.id,
                "💡 Предложите свою помощь:\n\n"
                "Кратко опишите, чем вы можете помочь, и оставьте контакты для связи.\n"
                "Например: 'Могу помочь с переводом материалов. Email: example@mail.ru'",
                reply_markup=create_back_keyboard()
            )
        elif message.text == 'Назад':
            user_state.waiting_for_action = True
            bot.send_message(
                message.chat.id,
                "Выберите действие:",
                reply_markup=create_russia_actions_keyboard()
            )
        else:
            bot.send_message(
                message.chat.id,
                "Пожалуйста, выберите действие с помощью кнопок:",
                reply_markup=create_russia_actions_keyboard()
            )
    
    # Обработка действий за рубежом
    elif user_state.waiting_for_action and user_state.location == "За рубежом":
        if message.text == 'Написать в прокуратуру':
            bot.send_message(
                message.chat.id,
                "📝 Письмо в прокуратуру:\n\n"
                "1. Скачайте образец письма на английском/русском: [ссылка]\n"
                "2. Заполните свои данные\n"
                "3. Отправьте по email: [email прокуратуры]\n"
                "4. Можно также отправить обычной почтой\n\n"
                "Спасибо за международную поддержку!",
                reply_markup=create_back_keyboard()
            )
        elif message.text == 'Предложить иную помощь':
            user_state.waiting_for_action = False
            user_state.waiting_for_custom_help = True
            bot.send_message(
                message.chat.id,
                "💡 Предложите свою помощь:\n\n"
                "Кратко опишите, чем вы можете помочь, и оставьте контакты для связи.\n"
                "Например: 'Могу помочь с привлечением международных СМИ. WhatsApp: +123456789'",
                reply_markup=create_back_keyboard()
            )
        elif message.text == 'Назад':
            user_state.waiting_for_action = True
            bot.send_message(
                message.chat.id,
                "Выберите действие:",
                reply_markup=create_abroad_actions_keyboard()
            )
        else:
            bot.send_message(
                message.chat.id,
                "Пожалуйста, выберите действие с помощью кнопок:",
                reply_markup=create_abroad_actions_keyboard()
            )
    
    # Обработка предложения иной помощи
    elif user_state.waiting_for_custom_help:
        if message.text == 'Назад':
            user_state.waiting_for_custom_help = False
            user_state.waiting_for_action = True
            
            if user_state.location == "Нижний Новгород":
                bot.send_message(
                    message.chat.id,
                    "Выберите действие:",
                    reply_markup=create_nn_actions_keyboard()
                )
            elif user_state.location == "Россия":
                bot.send_message(
                    message.chat.id,
                    "Выберите действие:",
                    reply_markup=create_russia_actions_keyboard()
                )
            elif user_state.location == "За рубежом":
                bot.send_message(
                    message.chat.id,
                    "Выберите действие:",
                    reply_markup=create_abroad_actions_keyboard()
                )
        else:
            # Пользователь предложил свою помощь
            bot.send_message(
                message.chat.id,
                "Спасибо за ваше предложение! Мы обязательно с вами свяжемся. 🙏",
                reply_markup=types.ReplyKeyboardRemove()
            )
            user_state.waiting_for_custom_help = False

# Обработка сообщений в супергруппе


# Функция рассылки


# Запуск бота
if __name__ == "__main__":
    print("Бот запущен...")
    bot.polling(none_stop=True)
