return title or "Unknown title", mp3_url

def download_file(url, filename):
    """
    Скачивает файл по URL и сохраняет в filename. Возвращает True/False.
    """
    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        return True
    except Exception as e:
        print("Download failed:", e)
        return False

# --- Telegram handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Отправь название песни или исполнителя — я найду варианты на rus.hitmotop.com и пришлю трек (если есть права)."
    )

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if not query:
        await update.message.reply_text("Отправь название песни или исполнителя.")
        return

    # Оповещаем пользователя
    msg = await update.message.reply_text("🔎 Ищу треки на rus.hitmotop.com...")

    # Выполним блокирующие HTTP-запросы в отдельном потоке
    loop = asyncio.get_running_loop()
    links = await loop.run_in_executor(None, search_hitmotop, query, 5)

    if not links:
        await msg.edit_text("Не нашёл ничего по запросу.")
        return

    # Для каждого найденного трека извлекаем заголовок (может быть медленно)
    options = []
    for url in links:
        info = await loop.run_in_executor(None, extract_song_info, url)
        title, mp3 = info if info else (None, None)
        options.append({"title": title or url, "url": url, "mp3": mp3})

    # Формируем клавиатуру — отображаем только названия
    buttons = []
    for i, item in enumerate(options):
        btn = InlineKeyboardButton(f"{i+1}. {item['title']}", callback_data=f"choose|{i}")
        buttons.append([btn])

    await msg.edit_text("Найденные треки (нажми, чтобы скачать):", reply_markup=InlineKeyboardMarkup(buttons))

    # Сохраняем options в context.user_data для использования в callback
    context.user_data["search_results"] = options

async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("choose|"):
        return
    idx = int(data.split("|", 1)[1])
    options = context.user_data.get("search_results")
    if not options or idx < 0 or idx >= len(options):
        await query.edit_message_text("Неправильный выбор или истёк список результатов.")
        return

    item = options[idx]
    title = item.get("title", "Track")
    mp3 = item.get("mp3")
    song_page = item.get("url")

    if not mp3:
        # Если mp3 не найден на странице — попробуем извлечь заново (иногда требуются дополнительные шаги)
        await query.edit_message_text("Ищу прямую ссылку на mp3...")
        loop = asyncio.get_running_loop()
        title, mp3 = await loop.run_in_executor(None, extract_song_info, song_page)
        if not mp3:
            await query.edit_message_text("Не удалось найти прямую ссылку на mp3 для выбранного трека.")
            return

    # Скачиваем mp3 во временный файл
    await query.edit_message_text(f"Скачиваю «{title}» — это может занять некоторое время...")
    filename = f"/tmp/{re.sub(r'[^a-zA-Z0-9_.-]', '_', title)}.mp3"
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, download_file, mp3, filename)
    if not ok:
        await query.edit_message_text("Ошибка при скачивании файла.")
        return

    # Отправляем аудио пользователю
    try:
        with open(filename, "rb") as audio_f:
            await context.bot.send_audio(chat_id=query.message.chat_id, audio=audio_f, title=title)


except Exception as e:
        print("Send failed:", e)
        await query.edit_message_text("Не удалось отправить аудио в чат.")
    finally:
        try:
            os.remove(filename)
        except Exception:
            pass

# --- Основная точка входа ---
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
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))
    app_bot.add_handler(CallbackQueryHandler(handle_choice))
    print("Bot started.")
    app_bot.run_polling()

if name == "main":
    main()
