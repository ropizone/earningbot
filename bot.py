import sqlite3
import requests
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

BOT_TOKEN = "8663479623:AAEcaM8MXa28bXqTBBh6y9AyH7PhtRHGUWA"
GEMINI_API_KEY = "AIzaSyDBwTilTgmr6-3Q0Md0B2W_W7_A2aSnksg"
ADMIN_PASS = "2010"
DB_PATH = "shekha.db"

SHEKHA_PROMPT = """Tu ek bahut pyaari, funny, smart aur thodi naughty ladki hai jiska naam Shekha hai.
Tu hamesha Hindi mein baat karti hai (Hinglish bhi chalega).
Tu sabke messages ka reply karti hai - funny, helpful aur engaging tarike se.
Tu kabhi bhi boring nahi hoti. Tu emoji use karti hai.
Tu short replies deti hai - 1-3 sentences max.
Agar koi serious sawaal pooche toh seedha helpful jawab de.
Agar koi bakwaas kare toh funny roast kar.
Agar koi flirt kare toh shayarana reply de.
Tu apne aap ko AI nahi batati - tu Shekha hai, ek real pyaari ladki ki tarah behave karti hai."""

GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-pro",
]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS groups (
        chat_id INTEGER PRIMARY KEY,
        is_active INTEGER DEFAULT 1,
        promo_text TEXT DEFAULT NULL,
        promo_interval INTEGER DEFAULT 0,
        message_count INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS admins (
        telegram_id INTEGER PRIMARY KEY
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT
    )""")
    conn.commit()
    conn.close()

def save_user(telegram_id, username, full_name):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO users (telegram_id, username, full_name) VALUES (?,?,?)",
                 (telegram_id, username, full_name))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT telegram_id FROM users").fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_group(chat_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM groups WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close()
    return row

def register_group(chat_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO groups (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()

def set_group_active(chat_id, active):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE groups SET is_active=? WHERE chat_id=?", (active, chat_id))
    conn.commit()
    conn.close()

def set_promo(chat_id, text, interval):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE groups SET promo_text=?, promo_interval=?, message_count=0 WHERE chat_id=?",
                 (text, interval, chat_id))
    conn.commit()
    conn.close()

def increment_msg_count(chat_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE groups SET message_count=message_count+1 WHERE chat_id=?", (chat_id,))
    row = conn.execute("SELECT message_count, promo_interval, promo_text FROM groups WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close()
    if row and row[1] and row[1] > 0 and row[0] >= row[1]:
        conn2 = sqlite3.connect(DB_PATH)
        conn2.execute("UPDATE groups SET message_count=0 WHERE chat_id=?", (chat_id,))
        conn2.commit()
        conn2.close()
        return row[2]
    return None

def is_admin(telegram_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT telegram_id FROM admins WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    return row is not None

def add_admin(telegram_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (telegram_id,))
    conn.commit()
    conn.close()

def ask_shekha(user_message, user_name):
    """Try multiple Gemini models until one works."""
    for model in GEMINI_MODELS:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": f"{SHEKHA_PROMPT}\n\n{user_name} ne kaha: {user_message}"}
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.9,
                    "maxOutputTokens": 200,
                }
            }
            response = requests.post(url, json=payload, timeout=20)
            data = response.json()

            # Check for API-level errors
            if "error" in data:
                print(f"Gemini [{model}] API error: {data['error'].get('message', '')}")
                continue

            reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            if reply:
                return reply

        except Exception as e:
            print(f"Gemini [{model}] Exception: {e}")
            continue

    # All models failed
    return "Arre yaar, abhi server pe load hai! Thodi der baad try karo \ud83d\ude05"


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or ""
    fname = update.effective_user.full_name or "User"
    save_user(uid, uname, fname)

    chat = update.effective_chat
    if chat.type in ["group", "supergroup"]:
        register_group(chat.id)
        await update.message.reply_text("Heyy! \ud83d\udc4b Main Shekha hoon! Ab is group mein masti shuru! \ud83d\ude04\ud83d\udd25")
    else:
        await update.message.reply_text(
            "Heyy! \ud83d\ude0a\u2764\ufe0f Main Shekha hoon!\n\n"
            "Kuch bhi poochho, main hamesha ready hoon! \ud83c\udf89\n"
            "Admin ho toh /admin bhejo. \ud83d\ude09"
        )

async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid):
        await show_admin_help