import os
import sqlite3
import requests
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

# ========== CONFIG ==========
BOT_TOKEN = "8663479623:AAEmBgQ8cxNymOqxSflOxjypnhFxOd_u8NE"
DEEPSEEK_API_KEY = "sk-d38fc497c0164fc598c28629c573a719"
ADMIN_PASS = "2010"
ADMIN_IDS = []  # Will be filled when admin logs in

DB_PATH = "shekha.db"

SHEKHA_SYSTEM_PROMPT = """Tu ek funny, smart aur thodi naughty ladki hai jiska naam Shekha hai.
Tu hamesha Hindi mein baat karti hai (Hinglish bhi chalega).
Tu group mein sabke messages ka reply karti hai - funny, helpful aur engaging tarike se.
Tu kabhi bhi boring nahi hoti.
Tu short replies deti hai - 1-3 sentences max.
Agar koi serious sawaal pooche toh seedha helpful jawab de.
Agar koi bakwaas kare toh funny roast kar.
Tu apne aap ko AI nahi batati - tu Shekha hai, ek real group member ki tarah behave karti hai."""

# ========== DATABASE ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            is_active INTEGER DEFAULT 1,
            promo_text TEXT DEFAULT NULL,
            promo_interval INTEGER DEFAULT 0,
            message_count INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            telegram_id INTEGER PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()

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
        return row[2]  # Return promo text to send
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

# ========== DEEPSEEK API ==========
def ask_deepseek(user_message, user_name):
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SHEKHA_SYSTEM_PROMPT},
            {"role": "user", "content": f"{user_name} ne kaha: {user_message}"}
        ],
        "max_tokens": 200,
        "temperature": 0.9
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return "Arre yaar, abhi thoda busy hoon! Thodi der baad baat karte hain 😅"

# ========== HANDLERS ==========
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type in ["group", "supergroup"]:
        register_group(chat.id)
        await update.message.reply_text(
            "Heyy! 👋 Main Shekha hoon! Ab is group mein masti shuru! 😄\n"
            "Koi bhi kuch bhi poochho, main hamesha ready hoon! 🔥"
        )
    else:
        await update.message.reply_text(
            "Heyy! Main Shekha hoon! 😊\n"
            "Mujhe kisi group mein add karo aur main wahan sab se baat karungi! 🎉\n\n"
            "Admin login ke liye /admin bhejo."
        )

async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid):
        await show_admin_help(update)
        return
    await update.message.reply_text(
        "🔐 Admin password bhejo:"
    )
    ctx.user_data["waiting_admin_pass"] = True

async def show_admin_help(update):
    await update.message.reply_text(
        "✅ *Admin Panel - Shekha Bot*\n\n"
        "📋 *Commands:*\n\n"
        "▶️ `/on <group_id>` — Group mein Shekha on karo\n"
        "⏹ `/off <group_id>` — Group mein Shekha off karo\n"
        "📢 `/setpromo <group_id> | <interval> | <text>` — Promo ad set karo\n"
        "🗑 `/removepromo <group_id>` — Promo hatao\n"
        "📊 `/groups` — Saare groups dekho\n\n"
        "💡 *Example:*\n"
        "`/setpromo -1001234567890 | 10 | Hamara channel join karo!`\n"
        "_(Har 10 messages ke baad promo send hoga)_",
        parse_mode="Markdown"
    )

async def on_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /on <group_id>")
        return
    chat_id = int(ctx.args[0])
    register_group(chat_id)
    set_group_active(chat_id, 1)
    await update.message.reply_text(f"✅ Shekha group `{chat_id}` mein ON kar di!", parse_mode="Markdown")

async def off_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /off <group_id>")
        return
    chat_id = int(ctx.args[0])
    set_group_active(chat_id, 0)
    await update.message.reply_text(f"⏹ Shekha group `{chat_id}` mein OFF kar di!", parse_mode="Markdown")

async def setpromo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        text = update.message.text.replace("/setpromo", "").strip()
        parts = text.split("|")
        chat_id = int(parts[0].strip())
        interval = int(parts[1].strip())
        promo_text = parts[2].strip()
        set_promo(chat_id, promo_text, interval)
        await update.message.reply_text(
            f"✅ Promo set ho gaya!\n"
            f"Group: `{chat_id}`\n"
            f"Har *{interval} messages* ke baad send hoga:\n"
            f"_{promo_text}_",
            parse_mode="Markdown"
        )
    except:
        await update.message.reply_text(
            "❌ Format galat hai!\nSahi format:\n`/setpromo <group_id> | <interval> | <promo text>`",
            parse_mode="Markdown"
        )

async def removepromo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /removepromo <group_id>")
        return
    chat_id = int(ctx.args[0])
    set_promo(chat_id, None, 0)
    await update.message.reply_text(f"🗑 Group `{chat_id}` ka promo hata diya!", parse_mode="Markdown")

async def groups_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    groups = conn.execute("SELECT * FROM groups").fetchall()
    conn.close()
    if not groups:
        await update.message.reply_text("Koi group nahi hai abhi.")
        return
    text = "📊 *All Groups:*\n\n"
    for g in groups:
        status = "✅ ON" if g["is_active"] else "⏹ OFF"
        promo = f"📢 Promo: every {g['promo_interval']} msgs" if g["promo_interval"] else "No promo"
        text += f"`{g['chat_id']}` — {status} — {promo}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    uid = update.effective_user.id
    chat = update.effective_chat
    text = update.message.text
    user_name = update.effective_user.first_name or "User"

    # Admin password check in private
    if chat.type == "private":
        if ctx.user_data.get("waiting_admin_pass"):
            if text.strip() == ADMIN_PASS:
                add_admin(uid)
                ctx.user_data["waiting_admin_pass"] = False
                await update.message.reply_text("✅ Admin login ho gaya! /admin bhejo commands ke liye.")
            else:
                ctx.user_data["waiting_admin_pass"] = False
                await update.message.reply_text("❌ Wrong password!")
            return

        # Private chat - reply normally
        reply = ask_deepseek(text, user_name)
        await update.message.reply_text(reply)
        return

    # Group chat
    if chat.type in ["group", "supergroup"]:
        register_group(chat.id)
        group = get_group(chat.id)

        if not group or not group["is_active"]:
            return

        # Check promo
        promo = increment_msg_count(chat.id)
        if promo:
            await update.message.reply_text(f"📢 {promo}")
            return

        # Only reply if bot is mentioned or message is a reply to bot
        bot_username = (await ctx.bot.get_me()).username
        is_mentioned = f"@{bot_username}" in text
        is_reply_to_bot = (
            update.message.reply_to_message and
            update.message.reply_to_message.from_user and
            update.message.reply_to_message.from_user.username == bot_username
        )

        # Reply to every message (remove the condition below to reply to all)
        # If you want reply to ALL messages, keep this as is
        # If you want only when mentioned, wrap in: if is_mentioned or is_reply_to_bot:
        reply = ask_deepseek(text, user_name)
        await update.message.reply_text(reply)

# ========== MAIN ==========
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("on", on_cmd))
    app.add_handler(CommandHandler("off", off_cmd))
    app.add_handler(CommandHandler("setpromo", setpromo_cmd))
    app.add_handler(CommandHandler("removepromo", removepromo_cmd))
    app.add_handler(CommandHandler("groups", groups_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Shekha Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
