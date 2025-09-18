# bot.py
# Telegram bot: Daily Word Learner + Translator + Premium + Admin
# Requirements:
# python-telegram-bot==20.3
# googletrans==4.0.0-rc1
# aiohttp

import os
import json
import logging
import datetime
import random
from typing import Any, Dict, List, Optional

import aiohttp
from googletrans import Translator
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
)

# ----------------- CONFIG -----------------
BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN"
ADMIN_ID_STR = os.getenv("ADMIN_ID") or "0"
try:
    ADMIN_ID = int(ADMIN_ID_STR)
except Exception:
    ADMIN_ID = 0

USERS_FILE = "users.json"
WORDS_FILE = "words.json"
LOG_FILE = "bot.log"

# ----------------- LOGGING -----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# ----------------- TRANSLATOR -----------------
translator = Translator()

# ----------------- JSON HELPERS -----------------
def load_json(path: str) -> Any:
    try:
        if not os.path.exists(path):
            return {} if path == USERS_FILE else []
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.exception("Failed to load %s: %s", path, e)
        return {} if path == USERS_FILE else []

def save_json(path: str, data: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Failed to save %s: %s", path, e)

# ----------------- DATA ACCESS -----------------
def get_users() -> Dict[str, Dict[str, Any]]:
    data = load_json(USERS_FILE)
    if isinstance(data, dict):
        return data
    return {}

def save_users(users: Dict[str, Dict[str, Any]]) -> None:
    save_json(USERS_FILE, users)

def get_words() -> List[Dict[str, Any]]:
    data = load_json(WORDS_FILE)
    if isinstance(data, list):
        return data
    return []

def save_words(words: List[Dict[str, Any]]) -> None:
    save_json(WORDS_FILE, words)

def ensure_user(user_id: int, username: Optional[str] = None) -> Dict[str, Any]:
    users = get_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {
            "username": username or "",
            "level": "Beginner",
            "words_per_day": 5,
            "time": "09:00",
            "is_premium": False,
            "learned_words": [],
            "translations_today": 0,
            "target_lang": "ru",
            "pending_premium": False,
        }
        save_users(users)
    return users[uid]

# ----------------- WORDS -----------------
SAMPLE_WORDS_POOL = [
    "apple","book","computer","school","water","friend","language","beautiful","music","travel",
    "work","future","happiness","family","dream","power","light","energy","nature","health",
    "success","challenge","brave","kind","learn","practice","study","create","build","improve"
]

async def fetch_word_info(word: str, target_lang: str = "ru") -> Optional[Dict[str, str]]:
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    try:
                        definition = data[0]["meanings"][0]["definitions"][0].get("definition","")
                    except Exception:
                        definition = ""
                    try:
                        translated = translator.translate(word, dest=target_lang).text
                    except Exception:
                        translated = ""
                    return {"word": word, "translation": translated, "definition": definition, "level": "Beginner"}
    except Exception as e:
        logger.debug("fetch_word_info error for %s: %s", word, e)
    return None

async def ensure_words(min_total: int = 200) -> None:
    words = get_words()
    if len(words) >= min_total:
        return
    logger.info("Need more words. Current=%d", len(words))
    needed = max(min_total - len(words), 50)
    candidates = SAMPLE_WORDS_POOL * ((needed // len(SAMPLE_WORDS_POOL)) + 2)
    random.shuffle(candidates)
    new_added = []
    async with aiohttp.ClientSession() as session:
        for w in candidates:
            if len(new_added) >= needed:
                break
            if any(item["word"] == w for item in words) or any(item["word"] == w for item in new_added):
                continue
            try:
                async with session.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{w}", timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        try:
                            definition = data[0]["meanings"][0]["definitions"][0].get("definition","")
                        except Exception:
                            definition = ""
                        try:
                            translated = translator.translate(w, dest="ru").text
                        except Exception:
                            translated = ""
                        new_added.append({"word": w, "translation": translated, "definition": definition, "level":"Beginner"})
            except Exception as e:
                logger.debug("Skipping %s: %s", w, e)
    if new_added:
        words.extend(new_added)
        save_words(words)
        logger.info("Added %d new words.", len(new_added))

# ----------------- BOT HANDLERS -----------------
REG_LEVEL, REG_COUNT, REG_TIME = range(3)

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

# (остальные хендлеры остаются без изменений из твоего файла)
# Я заменил только CommandHandler("menu", ...) на нормальную функцию cmd_menu

# ----------------- START -----------------
def build_app() -> Application:
    return Application.builder().token(BOT_TOKEN).build()

def main() -> None:
    app = build_app()

    # Registration
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            REG_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_level)],
            REG_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_count)],
            REG_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_time)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Admin
    app.add_handler(CommandHandler("makepremium", cmd_makepremium))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("ping", cmd_ping))

    # Jobs
    app.job_queue.run_repeating(check_and_send, interval=60, first=10)
    midnight = datetime.time(hour=0, minute=0, second=0)
    app.job_queue.run_daily(reset_translations, time=midnight)

    logger.info("Bot started.")
    app.run_polling()

if __name__ == "__main__":
    main()
