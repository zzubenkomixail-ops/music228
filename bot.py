import os
import re
import requests
import asyncio
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")  # Установи эту переменную окружения на Render / локально

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MusicBot/1.0)"}

# --- Поиск ссылок на rus.hitmotop через DuckDuckGo HTML интерфейс ---
def search_hitmotop(query, max_results=5):
    """
    Ищем страницы вида https://rus.hitmotop.com/song/<id> через DuckDuckGo HTML.
    Возвращаем список URL'ов (максимум max_results).
    """
    ddg_url = "https://html.duckduckgo.com/html/"
    params = {"q": f"site:rus.hitmotop.com/song {query}"}
    try:
        resp = requests.post(ddg_url, data=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print("Search request failed:", e)
        return []

    links = []
    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # DuckDuckGo returns direct links or redirects; try to extract real rus.hitmotop links
        if "rus.hitmotop.com/song/" in href:
            # Clean up href if it's a redirect
            m = re.search(r"(https?://rus\.hitmotop\.com/song/\d+)", href)
            if m:
                url = m.group(1)
            else:
                url = href.split("&uddg=")[-1] if "uddg=" in href else href
            if url not in links:
                links.append(url)
        if len(links) >= max_results:
            break
    return links

def extract_song_info(song_url):
    """
    Извлекает title/artist и прямую ссылку на mp3 (если есть) со страницы трека.
    Возвращает (title, mp3_url) или (None, None) при неудаче.
    """
    try:
        resp = requests.get(song_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print("Failed to fetch song page:", e)
        return None, None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Попытки получить название трека
    title = None
    # 1) <h1> часто содержит название
    h1 = soup.find("h1")
    if h1 and h1.text.strip():
        title = h1.text.strip()
    # 2) meta og:title
    if not title:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()

    # Ищем mp3 ссылку: <a href="...mp3">, <audio><source src="...">, meta og:audio
    mp3_url = None
    # a tags
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".mp3") or ".mp3?" in href.lower():
            mp3_url = href
            break
        # иногда ссылка внутренняя и ведёт к скачиванию: ищем /download/ или /get/
        if "/get/" in href or "/download" in href:
            if href.lower().endswith(".mp3") or ".mp3" in href:
                mp3_url = href
                break

    # audio/source tags
    if not mp3_url:
        audio = soup.find("audio")
        if audio:
            src = audio.get("src")
            if src and ".mp3" in src:
                mp3_url = src
            else:
                source = audio.find("source")
                if source and source.get("src"):
                    mp3_url = source["src"]

    # meta og:audio
    if not mp3_url:
        og_audio = soup.find("meta", property="og:audio")
        if og_audio and og_audio.get("content"):
            mp3_url = og_audio["content"]

    # Нормализуем относительные URL'ы
    if mp3_url and mp3_url.startswith("/"):
        base = re.match(r"https?://[^/]+", song_url)
        if base:
            mp3_url = base.group(0) + mp3_url

    # Иногда mp3 ссылка может быть в JS — это не покрывается (сложнее)
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
    token = BOT_TOKEN
    if not token:
        print("Error: please set BOT_TOKEN environment variable.")
        return

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))
    app.add_handler(CallbackQueryHandler(handle_choice))
    print("Bot started.")
    app.run_polling()

if __name__ == "__main__":
    main()
