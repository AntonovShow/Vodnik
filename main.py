import sqlite3
import threading
import time
import logging
from asyncio.windows_events import NULL

from telebot import TeleBot, types
import bot_logging
import var

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Конфигурация (задайте свои значения через переменные окружения или прямо в коде)
TOKEN = var.TOKEN
GROUP_ID = var.GROUP_ID  # ID группы, где бот будет обрабатывать команды

bot = TeleBot(TOKEN)

# Имя бота для упоминаний (заполнится автоматически при запуске)
BOT_USERNAME = None

#ID темы в телеграм группе
THREAD_ID = None

# Словарь для хранения состояний рассылки по пользователям группы
# Ключ: id пользователя в группе, значение: dict с полями:
#   - step: 'waiting_text' или 'waiting_confirm'
#   - targets: список целевых адресов (например, ['all'] или ['Нижний Новгород', 'Россия'])
#   - text: текст рассылки
#   - last_message_id: id последнего сообщения, на которое нужно ответить для подтверждения
broadcast_data = {}

# Словарь для сигналов остановки рассылки (по id инициатора)
stop_events = {}

# Хранилище связей: (id_целевого_чата, id_сообщения_бота) → id_пользователя
message_owner = {}


def thread_user(chat_id, first_name, last_name, username):
    """Создает тред, если еще не создан, и записывает его ID в базу данных"""
    save_user(chat_id, first_name, last_name, username)
    global THREAD_ID
    thread_name = f"{username} {first_name} {last_name}"
    row = bot_logging.run_query_and_log("SELECT uid FROM user_list WHERE chat=?", chat_id)
    if not row:
        try:
            created_topic: types.ForumTopic = bot.create_forum_topic(chat_id=var.GROUP_ID, name=thread_name)
            THREAD_ID = created_topic.message_thread_id
            bot_logging.run_query_and_log("INSERT INTO user_list (uid) VALUES (?) WHERE chat=?", (THREAD_ID, chat_id))
        except Exception as e:
            bot_logging.log_to_telegram(f"Не удалось создать тему '{thread_name}' в группе: {e}")

def save_user(chat_id, first_name, last_name, username):
    """Сохраняет или обновляет основные данные пользователя (без addr)."""
    if not bot_logging.run_query_and_log("SELECT * FROM user_list WHERE chat = '%s'" % chat_id):
        bot_logging.run_query_and_log('''INSERT INTO user_list (chat, f_name, s_name, username)
                                         VALUES (?, ?, ?, ?)''', (chat_id, first_name, last_name, username))


def update_user_addr(chat_id, addr):
    """Обновляет поле addr у пользователя."""
    bot_logging.run_query_and_log("UPDATE user_list SET addr = '%s' WHERE chat = '%s'" % (addr, chat_id))


def update_user_comment(chat_id, comment):
    """Обновляет поле comment у пользователя."""
    bot_logging.run_query_and_log("UPDATE user_list SET comment = '%s' WHERE chat = '%s'" % (comment, chat_id))


# ---------- Клавиатуры ----------
def yes_no_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton(var.YN1), types.KeyboardButton(var.YN2))
    return markup


def location_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row(types.KeyboardButton(var.ADDR1))
    markup.row(types.KeyboardButton(var.ADDR2))
    markup.row(types.KeyboardButton(var.ADDR3))
    return markup


def nn_actions_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton(var.HELP1), types.KeyboardButton(var.HELP2))
    markup.row(types.KeyboardButton(var.OTHER_HELP), types.KeyboardButton(var.BACK))
    return markup


def russia_actions_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton(var.HELP3), types.KeyboardButton(var.HELP2))
    markup.row(types.KeyboardButton(var.OTHER_HELP), types.KeyboardButton(var.BACK))
    return markup


def abroad_actions_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton(var.HELP3))
    markup.row(types.KeyboardButton(var.OTHER_HELP), types.KeyboardButton(var.BACK))
    return markup


def back_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton(var.BACK))
    return markup


# ---------- Состояния пользователей ----------
# Простая машина состояний: храним для каждого chat_id текущий шаг
# и, возможно, выбранную локацию.
user_state = {}  # chat_id -> {'step': 'waiting_help' / 'waiting_location' / 'in_menu', 'location': ...}


@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    user_state[chat_id] = {'step': 'waiting_help'}
    bot.send_message(
        chat_id,
        f"Привет, {message.from_user.first_name}! 👋\n\n{var.START}",
        reply_markup=yes_no_keyboard()
    )
    bot_logging.log_to_telegram(f"Пользователь {chat_id} начал диалог.")


def handle_all_messages(message):
    chat_id = message.chat.id
    text = message.text
    state = user_state.get(chat_id)

    # Если состояние не определено (например, после перезапуска бота), предложим /start
    if not state:
        bot.send_message(chat_id, var.NOTSTART)
        return

    step = state['step']

    # ---------- Ожидание ответа на вопрос о помощи ----------
    if step == 'waiting_help':
        if text == var.YN1:
            # Сохраняем пользователя
            thread_user(
                message.chat.id,
                message.from_user.first_name,
                message.from_user.last_name,
                message.from_user.username
            )
            # Переходим к выбору местоположения
            user_state[chat_id]['step'] = 'waiting_location'
            bot.send_message(
                chat_id, var.READY,
                reply_markup=location_keyboard()
            )
        elif text == 'Нет':
            bot.send_message(
                chat_id,
                var.NREADY,
                reply_markup=types.ReplyKeyboardRemove()
            )
            # Сбрасываем состояние
            del user_state[chat_id]
        else:
            bot.send_message(
                chat_id,
                var.BUTTTONS,
                reply_markup=yes_no_keyboard()
            )

    # ---------- Ожидание выбора местоположения ----------
    elif step == 'waiting_location':
        location_map = {
            var.ADDR1: var.LOC1,
            var.ADDR2: var.LOC2,
            var.ADDR3: var.LOC3
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
                var.ACTION_TEXT,
                reply_markup=_get_actions_keyboard(addr)
            )
        else:
            bot.send_message(
                chat_id,
                var.BUTTTONS,
                reply_markup=location_keyboard()
            )

    # ---------- Нахождение в меню действий ----------
    elif step == 'in_menu':
        location = state['location']

        # Обработка кнопки "Назад" (возврат в меню)
        if text == var.BACK:
            bot.send_message(
                chat_id,
                var.ACTION_TEXT2,
                reply_markup=_get_actions_keyboard(location)
            )
            return

        # Обработка конкретных действий
        if location == var.LOC1:
            if text == var.HELP1:
                bot.send_message(
                    chat_id,
                    var.ACT1,
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            elif text == var.HELP2:
                bot.send_message(
                    chat_id,
                    var.ACT2,
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            elif text == var.OTHER_HELP:
                user_state[chat_id]['step'] = 'waiting_custom_help'
                bot.send_message(
                    chat_id,
                    var.OTHER_ACT,
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            else:
                # Неизвестная кнопка — повторяем меню
                bot.send_message(
                    chat_id,
                    var.BUTTTONS,
                    reply_markup=nn_actions_keyboard()
                )

        elif location == var.LOC2:
            if text == var.HELP3:
                bot.send_message(
                    chat_id,
                    var.ACT3,
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            elif text == var.HELP2:
                bot.send_message(
                    chat_id,
                    var.ACT2,
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            elif text == var.OTHER_HELP:
                user_state[chat_id]['step'] = 'waiting_custom_help'
                bot.send_message(
                    chat_id,
                    var.OTHER_ACT,
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            else:
                bot.send_message(
                    chat_id,
                    var.BUTTTONS,
                    reply_markup=russia_actions_keyboard()
                )

        elif location == var.LOC3:
            if text == var.HELP3:
                bot.send_message(
                    chat_id,
                    var.ACT3,
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            elif text == var.OTHER_HELP:
                user_state[chat_id]['step'] = 'waiting_custom_help'
                bot.send_message(
                    chat_id,
                    var.OTHER_ACT,
                    parse_mode='Markdown',
                    reply_markup=back_keyboard()
                )
            else:
                bot.send_message(
                    chat_id,
                    var.BUTTTONS,
                    reply_markup=abroad_actions_keyboard()
                )

    # ---------- Ожидание текста предложения ----------
    elif step == 'waiting_custom_help':
        if text == var.BACK:
            # Возврат в меню
            location = state['location']
            user_state[chat_id]['step'] = 'in_menu'
            bot.send_message(
                chat_id,
                var.ACTION_TEXT2,
                reply_markup=_get_actions_keyboard(location)
            )
        else:
            # Сохраняем предложение в поле comment
            update_user_comment(chat_id, text)
            bot.send_message(
                chat_id,
                var.ANSWER,
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
                var.ACTION_TEXT3,
                reply_markup=_get_actions_keyboard(location)
            )


# Вспомогательная функция для получения клавиатуры по локации
def _get_actions_keyboard(location):
    if location == var.LOC1:
        return nn_actions_keyboard()
    elif location == var.LOC2:
        return russia_actions_keyboard()
    else:
        return abroad_actions_keyboard()


@bot.message_handler(func=lambda message: message.chat.type == 'private' and not message.from_user.is_bot)
def handle_private(message):
    """Копирует любое сообщение из лички в целевой чат и запоминает отправителя."""
    try:
        sent = bot.copy_message(
            chat_id=GROUP_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
        if message.from_user.username:
            bot.send_message(GROUP_ID, f"Сообщение от пользователя @{message.from_user.username}",
                             reply_to_message_id=sent.message_id)
        else:
            bot.send_message(GROUP_ID,
                             f"Сообщение от пользователя {message.from_user.first_name} {message.from_user.first_name}",
                             reply_to_message_id=sent.message_id)
        # Сохраняем, что это сообщение в целевом чате принадлежит данному пользователю
        message_owner[(GROUP_ID, sent.message_id)] = message.from_user.id
    except Exception as e:
        bot_logging.log_to_telegram(message, f"Не удалось переслать сообщение: {e}")
    handle_all_messages(message)


@bot.message_handler(func=lambda message: message.chat.id == GROUP_ID and not message.from_user.is_bot)
def handle_target_chat(message):
    handle_group_message(message)
    """Обрабатывает ответы на сообщения бота в целевом чате и пересылает их исходному пользователю."""
    if message.reply_to_message:
        key = (GROUP_ID, message.reply_to_message.message_id)
        if key in message_owner:
            user_id = message_owner[key]
            try:
                bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id
                )
            except Exception as e:
                bot_logging.log_to_telegram(f"Не удалось отправить ответ пользователю: {e}")
        # Если ответ не на сообщение бота — игнорируем


# ================== Работа с базой данных ==================
DB_PATH = var.DB_PATH  # путь к файлу базы данных


def get_db_connection():
    """Возвращает соединение с БД."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создаёт таблицу user_list, если её нет (для полноты)."""
    query = 'CREATE TABLE IF NOT EXISTS user_list (id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, chat INTEGER, f_name TEXT, s_name TEXT, username TEXT, addr TEXT, comment TEXT)'
    bot_logging.run_query_and_log(query)


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
        bot_logging.log_to_telegram(f"Начало рассылки для {total} пользователей (цели: {targets})")

        if total == 0:
            bot.send_message(GROUP_ID, "⚠️ Нет пользователей для рассылки.")
            return

        sent = 0
        failed = 0

        for i, chat_id in enumerate(recipients):
            if stop_event.is_set():
                bot_logging.log_to_telegram(f"Рассылка остановлена пользователем {sender_id}")
                bot.send_message(GROUP_ID, f"⏹️ Рассылка остановлена. Отправлено {sent} из {total}.")
                return
            try:
                bot.send_message(chat_id, text)
                sent += 1
            except Exception as e:
                failed += 1
                bot_logging.log_to_telegram(f"Ошибка отправки пользователю {chat_id}: {e}")

            # Ограничение: 5 сообщений в секунду
            if (i + 1) % 5 == 0:
                time.sleep(1)

        # Итог
        bot.send_message(GROUP_ID, f"✅ Рассылка завершена. Успешно: {sent}, ошибок: {failed}.")
        bot_logging.log_to_telegram(f"Рассылка завершена. Успешно: {sent}, ошибок: {failed}")

    except Exception as e:
        logging.error(f"Ошибка в процессе рассылки: {e}")
        bot_logging.log_to_telegram(f"Ошибка в процессе рассылки: {e}")
        bot.send_message(GROUP_ID, f"❌ Ошибка при рассылке: {e}")
    finally:
        if sender_id in stop_events:
            del stop_events[sender_id]


# ================== Обработчики сообщений в группе ==================
# @bot.message_handler(func=lambda message: message.chat.id == GROUP_ID)
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
        bot.reply_to(message,
                     f"✅ Принято. Теперь отправьте текст для рассылки (следующим сообщением).\nЦелевая аудитория: {', '.join(target_desc)}")
        bot_logging.log_to_telegram(
            f"Пользователь {message.from_user.first_name} {message.from_user.last_name} @{message.from_user.username} инициировал рассылку для {targets}")

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
                                   f"Получатели: {', '.join([('всех' if t == 'all' else t) for t in state['targets']])}\n\n"
                                   f"Ответьте на это сообщение «верно» для начала рассылки или «стоп» для отмены.")
        state['last_message_id'] = confirm_msg.message_id
        bot_logging.log_to_telegram(f"Пользователь {message.from_user.id} отправил текст, ожидается подтверждение")

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
        bot_logging.log_to_telegram(f"Бот @{BOT_USERNAME} запущен, группа: {GROUP_ID}")
    except Exception as e:
        bot_logging.log_to_telegram(f"Ошибка подключения: {e}")
        exit(1)

    bot.infinity_polling()