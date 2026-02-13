import os
import telebot

# Токен бота и ID целевого чата (можно задать через переменные окружения)
TOKEN = os.getenv('BOT_TOKEN')
TARGET_CHAT_ID = int(os.getenv('TARGET_CHAT_ID'))  # ID должен быть целым числом

bot = telebot.TeleBot(TOKEN)

# Хранилище связей: (id_целевого_чата, id_сообщения_бота) → id_пользователя
message_owner = {}

@bot.message_handler(func=lambda message: message.chat.type == 'private' and not message.from_user.is_bot)
def handle_private(message):
    """Копирует любое сообщение из лички в целевой чат и запоминает отправителя."""
    try:
        sent = bot.copy_message(
            chat_id=TARGET_CHAT_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
        # Сохраняем, что это сообщение в целевом чате принадлежит данному пользователю
        message_owner[(TARGET_CHAT_ID, sent.message_id)] = message.from_user.id
    except Exception as e:
        bot.reply_to(message, f"Не удалось переслать сообщение: {e}")

@bot.message_handler(func=lambda message: message.chat.id == TARGET_CHAT_ID and not message.from_user.is_bot)
def handle_target_chat(message):
    """Обрабатывает ответы на сообщения бота в целевом чате и пересылает их исходному пользователю."""
    if message.reply_to_message:
        key = (TARGET_CHAT_ID, message.reply_to_message.message_id)
        if key in message_owner:
            user_id = message_owner[key]
            try:
                bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id
                )
            except Exception as e:
                bot.reply_to(message, f"Не удалось отправить ответ пользователю: {e}")
        # Если ответ не на сообщение бота — игнорируем

@bot.message_handler(commands=['start'])
def send_welcome(message):
    """Приветственное сообщение при команде /start."""
    bot.reply_to(message, "Привет! Я бот-пересыльщик. Все твои сообщения будут пересылаться в сторонний чат.")

bot.infinity_polling()
