import os
import sqlite3
import threading
import time
import logging
from telebot import TeleBot, types

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Конфигурация (задайте свои значения через переменные окружения или прямо в коде)
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
GROUP_ID = os.getenv('TELEGRAM_GROUP_ID')  # ID группы, где бот будет обрабатывать команды

if not TOKEN:
    raise ValueError("Не задан TELEGRAM_BOT_TOKEN")
if not GROUP_ID:
    raise ValueError("Не задан TELEGRAM_GROUP_ID")

bot = TeleBot(TOKEN)

# Имя бота для упоминаний (заполнится автоматически при запуске)
BOT_USERNAME = None

# Словарь для хранения состояний рассылки по пользователям группы
# Ключ: id пользователя в группе, значение: dict с полями:
#   - step: 'waiting_text' или 'waiting_confirm'
#   - targets: список целевых адресов (например, ['all'] или ['Нижний Новгород', 'Россия'])
#   - text: текст рассылки
#   - last_message_id: id последнего сообщения, на которое нужно ответить для подтверждения
broadcast_data = {}

# Словарь для сигналов остановки рассылки (по id инициатора)
stop_events = {}

# ================== Работа с базой данных ==================
DB_PATH = 'user_list.db'  # путь к файлу базы данных

def get_db_connection():
    """Возвращает соединение с БД."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Создаёт таблицу user_list, если её нет (для полноты)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER,
            chat INTEGER,
            f_name TEXT,
            s_name TEXT,
            u_name TEXT,
            addr TEXT,
            comment TEXT
        )
    ''')
    conn.commit()
    conn.close()
    logging.info("База данных инициализирована")

def get_users_by_addr(addr_list):
    """
    Возвращает список chat_id пользователей, у которых addr совпадает с одним из значений в addr_list.
    Если addr_list содержит 'all', возвращает всех пользователей.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if 'all' in addr_list:
        cursor.execute("SELECT chat FROM user_list WHERE chat IS NOT NULL")
    else:
        # Создаём плейсхолдеры для SQL-запроса
        placeholders = ','.join(['?'] * len(addr_list))
        query = f"SELECT chat FROM user_list WHERE addr IN ({placeholders}) AND chat IS NOT NULL"
        cursor.execute(query, addr_list)
    
    rows = cursor.fetchall()
    conn.close()
    # Возвращаем список chat_id (уникальные)
    return list(set(row['chat'] for row in rows))

# ================== Функции рассылки ==================
def send_broadcast(sender_id, targets, text):
    """
    Выполняет рассылку текста text пользователям, соответствующим targets.
    Ограничение: не более 5 сообщений в секунду.
    """
    stop_event = threading.Event()
    stop_events[sender_id] = stop_event

    try:
        # Получаем список получателей
        recipients = get_users_by_addr(targets)
        total = len(recipients)
        logging.info(f"Начало рассылки для {total} пользователей (цели: {targets})")

        if total == 0:
            bot.send_message(GROUP_ID, "⚠️ Нет пользователей для рассылки.")
            return

        sent = 0
        failed = 0

        for i, chat_id in enumerate(recipients):
            if stop_event.is_set():
                logging.info(f"Рассылка остановлена пользователем {sender_id}")
                bot.send_message(GROUP_ID, f"⏹️ Рассылка остановлена. Отправлено {sent} из {total}.")
                return

            try:
                bot.send_message(chat_id, f"📢 Сообщение от координаторов:\n\n{text}")
                sent += 1
            except Exception as e:
                failed += 1
                logging.error(f"Ошибка отправки пользователю {chat_id}: {e}")

            # Ограничение: 5 сообщений в секунду
            if (i + 1) % 5 == 0:
                time.sleep(1)

        # Итог
        bot.send_message(GROUP_ID, f"✅ Рассылка завершена. Успешно: {sent}, ошибок: {failed}.")
        logging.info(f"Рассылка завершена. Успешно: {sent}, ошибок: {failed}")

    except Exception as e:
        logging.error(f"Ошибка в процессе рассылки: {e}")
        bot.send_message(GROUP_ID, f"❌ Ошибка при рассылке: {e}")
    finally:
        if sender_id in stop_events:
            del stop_events[sender_id]

# ================== Обработчики сообщений в группе ==================
@bot.message_handler(func=lambda message: str(message.chat.id) == GROUP_ID)
def handle_group_message(message):
    global BOT_USERNAME
    if BOT_USERNAME is None:
        BOT_USERNAME = bot.get_me().username

    # 1. Обработка команд, начинающихся с упоминания бота
    if message.text and f"@{BOT_USERNAME}" in message.text:
        # Извлекаем часть после упоминания
        parts = message.text.split()
        # Ищем первое слово после упоминания (может быть несколько)
        # Удаляем упоминание из текста
        text_without_mention = message.text.replace(f"@{BOT_USERNAME}", "").strip()
        # Разбиваем на слова
        command_parts = text_without_mention.lower().split()

        # Определяем цели
        targets = []
        for part in command_parts:
            if part == "всем":
                targets.append("all")
            elif part == "нн":
                targets.append("Нижний Новгород")
            elif part == "россия":
                targets.append("Россия")
            elif part == "не" and "россия" in command_parts:  # обработка "не россия"
                # мы уже учтём ниже
                pass

        # Специальная обработка "не россия"
        if "не" in command_parts and "россия" in command_parts:
            targets.append("За рубежом")

        # Если есть "не" без "россия" – игнорируем, но можно выдать ошибку
        # Удаляем дубликаты
        targets = list(set(targets))

        if not targets:
            bot.reply_to(message, "❌ Не распознана команда. Используйте:\n"
                                   f"@{BOT_USERNAME} всем\n"
                                   f"@{BOT_USERNAME} НН\n"
                                   f"@{BOT_USERNAME} Россия\n"
                                   f"@{BOT_USERNAME} не Россия\n"
                                   "Команды можно комбинировать, например: @bot НН Россия")
            return

        # Сохраняем состояние: ожидаем текст для рассылки
        broadcast_data[message.from_user.id] = {
            'step': 'waiting_text',
            'targets': targets,
            'text': None,
            'last_message_id': None
        }

        target_desc = [('всех' if t == 'all' else t) for t in targets]
        bot.reply_to(message, f"✅ Принято. Теперь отправьте текст для рассылки (следующим сообщением).\nЦелевая аудитория: {', '.join(target_desc)}")
        logging.info(f"Пользователь {message.from_user.id} инициировал рассылку для {targets}")

    # 2. Если пользователь в состоянии ожидания текста
    elif message.from_user.id in broadcast_data and broadcast_data[message.from_user.id]['step'] == 'waiting_text':
        state = broadcast_data[message.from_user.id]
        # Сохраняем текст
        text = message.text
        if not text:
            bot.reply_to(message, "Пожалуйста, отправьте текст сообщения.")
            return

        state['text'] = text
        state['step'] = 'waiting_confirm'

        # Отправляем подтверждение и сохраняем id этого сообщения, чтобы позже проверить ответ
        confirm_msg = bot.reply_to(message,
                                   f"📝 Текст для рассылки:\n\n{text}\n\n"
                                   f"Получатели: {', '.join([('всех' if t=='all' else t) for t in state['targets']])}\n\n"
                                   f"Ответьте на это сообщение «верно» для начала рассылки или «стоп» для отмены.")
        state['last_message_id'] = confirm_msg.message_id
        logging.info(f"Пользователь {message.from_user.id} отправил текст, ожидается подтверждение")

    # 3. Обработка ответов на сообщение с подтверждением
    elif message.reply_to_message and message.reply_to_message.from_user.id == bot.get_me().id:
        # Проверяем, есть ли у нас состояние для этого пользователя и совпадает ли id сообщения
        if message.from_user.id in broadcast_data:
            state = broadcast_data[message.from_user.id]
            if state['step'] == 'waiting_confirm' and state['last_message_id'] == message.reply_to_message.message_id:
                if message.text.lower() == 'верно':
                    # Запускаем рассылку в отдельном потоке
                    thread = threading.Thread(
                        target=send_broadcast,
                        args=(message.from_user.id, state['targets'], state['text'])
                    )
                    thread.start()
                    bot.reply_to(message, "🚀 Рассылка начата...")
                    # Удаляем состояние после запуска (чтобы не было повторных подтверждений)
                    del broadcast_data[message.from_user.id]
                elif message.text.lower() == 'стоп':
                    bot.reply_to(message, "⏹️ Рассылка отменена.")
                    del broadcast_data[message.from_user.id]
                else:
                    bot.reply_to(message, "Пожалуйста, ответьте «верно» или «стоп».")
            # else: не совпадает состояние или сообщение – игнорируем
        else:
            # Возможно, это ответ на какое-то другое сообщение бота – игнорируем
            pass

    # 4. Если пользователь в процессе рассылки и хочет её остановить (команда стоп без ответа?)
    #    Но согласно ТС, остановка происходит через ответ "стоп" на сообщение с подтверждением.
    #    Для остановки уже запущенной рассылки другой команды нет, но можно предусмотреть:
    elif message.text and message.text.lower() == 'стоп' and message.from_user.id in stop_events:
        # Пользователь может написать просто "стоп" во время активной рассылки
        stop_events[message.from_user.id].set()
        bot.reply_to(message, "⏹️ Сигнал остановки отправлен.")
    else:
        # Любое другое сообщение в группе игнорируем (или можно добавить свою логику)
        pass

# ================== Запуск бота ==================
if __name__ == '__main__':
    init_db()
    # Убедимся, что бот может получить информацию о себе
    try:
        me = bot.get_me()
        BOT_USERNAME = me.username
        logging.info(f"Бот @{BOT_USERNAME} запущен, группа: {GROUP_ID}")
    except Exception as e:
        logging.error(f"Ошибка подключения: {e}")
        exit(1)

    bot.infinity_polling()
