import logging
import sqlite3
from datetime import datetime
import telebot

# ===== Конфигурация =====
TELEGRAM_BOT_TOKEN = 'YOUR_BOT_TOKEN'
LOG_CHAT_ID = '@your_channel_or_group_id'  # например, '123456789' или '@mychannel'
DB_PATH = 'app_data.db'

# Создаем телеграм-бота
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Настроим логгер локально (для внутренних логов функции)
logger = logging.getLogger('db_logger')
logger.setLevel(logging.INFO)
logger_handler = logging.StreamHandler()  # можно убрать, если нужна только телеграм-вывод
logger.addHandler(logger_handler)

# ===== Функция логирования в Telegram =====
def log_to_telegram(message: str):
    """
    Отправляет сообщение в указанный чат/канал Telegram.
    """
    try:
        bot.send_message(LOG_CHAT_ID, message)
    except Exception as e:
        # Фоновая обработка ошибок отправки лога
        logger.error(f"Failed to send log to Telegram: {e}")

# ===== Контекстная обвязка работы с SQLite =====
def run_query_and_log(sql_query: str, params: tuple = ()):
    """
    Выполняет SQL-запрос к sqlite3, возвращает результат и отправляет лог
    о соединении и выполнении запроса в Telegram.
    """
    conn = sqlite3.connect('user_list.sql')
    cursor = None
    start_time = datetime.utcnow()
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(sql_query, params)
        # Если это SELECT, вернем результат
        if sql_query.strip().lower().startswith('select'):
            rows = cursor.fetchall()
            rowcount = len(rows)
        else:
            conn.commit()
            rows = []
            rowcount = cursor.rowcount

        duration = (datetime.utcnow() - start_time).total_seconds()
        # Лог об успешном выполнении
        log_message = (
            f"DB_LOG | time={start_time.isoformat()}Z | "
            f"query='{sql_query}' | params={params} | "
            f"rows={rowcount} | duration={duration:.3f}s"
        )
        log_to_telegram(log_message)
        return rows
    except Exception as e:
        duration = (datetime.utcnow() - start_time).total_seconds()
        log_message = (
            f"DB_LOG_ERROR | time={start_time.isoformat()}Z | "
            f"query='{sql_query}' | params={params} | "
            f"error={e} | duration={duration:.3f}s"
        )
        log_to_telegram(log_message)
        raise
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

# ===== Пример использования =====
if __name__ == '__main__':
    # Пример: создание таблицы
    run_query_and_log("""
        CREATE TABLE IF NOT EXISTS logs_example (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
"""
    # Пример: вставка
    run_query_and_log("INSERT INTO logs_example (message) VALUES (?)", ("Пример сообщения",))

    # Пример: выборка
    rows = run_query_and_log("SELECT * FROM logs_example")
    print("Query rows:", rows)
"""