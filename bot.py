import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Создаем Flask приложение для работы порта
app = Flask(name)

@app.route('/')
def home():
    return "Music Bot is running!"

def run_web_server():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я бот. Функционал поиска музыки временно отключен.")

def main():
    token = os.environ.get('BOT_TOKEN')
    if not token:
        print("Error: please set BOT_TOKEN environment variable.")
        return

    # Запускаем веб-сервер в отдельном потоке
    web_thread = threading.Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()
    
    # Запускаем бота
    app_bot = ApplicationBuilder().token(token).build()
    app_bot.add_handler(CommandHandler("start", start))
    print("Bot started successfully!")
    app_bot.run_polling()

if name == "main":
    main()
