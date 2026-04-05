import sqlite3
import requests
import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8663479623:AAEcaM8MXa28bXqTBBh6y9AyH7PhtRHGUWA"
GEMINI_API_KEY = "AIzaSyCitI8nbNAjtcSbVh4vey9jIOKFo6Zo2PY"
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

# 12 models in order — will cycle through if one fails
GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-pro-exp",
    "gemini-2.0-flash-thinking-exp",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
    "gemini-1.0-pro",
    "gemini-pro",
    "gemini-exp-1206",
    "gemini-exp-1121",
    "gemini-2.0-flash-exp",
]

# Tracks current model index globally (persists during runtime)
current_model_index = 0

BRAIN_SWITCH_MSGS = [
    "Ek sec... apna dimaag badal rahi hoon 🧠⚡",
    "Oops! Naya brain load ho raha hai... 🔄🧠",
    "Yeh wala dimaag kaam nahi kar raha, doosra try karti hoon 😅🔃",
    "Brain switching... thoda wait karo 💫🧠",
    "Ek minute, naya mode on kar rahi hoon ⚙️✨",
    "Purana brain crash ho gaya, naya install kar rahi hoon 😂🔧",
]

import random

# ───────────────────────── DB ─────────────────────────

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
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO users (telegram_id, username, full_name) VALUES (?,?,?)",
                     (telegram_id, username, full_name))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"save_user error: {e}")

def get_all_users():
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT telegram_id FROM users").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except:
        return []

def get_group(chat_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM groups WHERE chat_id=?", (chat_id,)).fetchone()
        conn.close()
        return row
    except:
        return None

def register_group(chat_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR IGNORE INTO groups (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"register_group error: {e}")

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
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE groups SET message_count=message_count+1 WHERE chat_id=?", (chat_id,))
        row = conn.execute("SELECT message_count, promo_interval, promo_text FROM groups WHERE chat_id=?", (chat_id,)).fetchone()
        conn.commit()
        conn.close()
        if row and row[1] and row[1] > 0 and row[0] >= row[1]:
            conn2 = sqlite3.connect(DB_PATH)
            conn2.execute("UPDATE groups SET message_count=0 WHERE chat_id=?", (chat_id,))
            conn2.commit()
            conn2.close()
            return row[2]
    except Exception as e:
        logger.error(f"increment_msg_count error: {e}")
    return None

def is_admin(telegram_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT telegram_id FROM admins WHERE telegram_id=?", (telegram_id,)).fetchone()
        conn.close()
        return row is not None
    except:
        return False

def add_admin(telegram_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (telegram_id,))
    conn.commit()
    conn.close()

# ───────────────────────── GEMINI WITH BRAIN SWITCH ─────────────────────────

async def ask_shekha(user_message, user_name, send_status_func=None):
    global current_model_index

    total_models = len(GEMINI_MODELS)
    tried = 0

    while tried < total_models:
        model = GEMINI_MODELS[current_model_index]
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
            logger.info(f"Gemini [{model}] status={response.status_code}")

            if "error" in data:
                raise Exception(data["error"].get("message", "API error"))

            reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            if reply:
                logger.info(f"Gemini [{model}] success!")
                return reply, None  # reply, no switch message

        except Exception as e:
            logger.warning(f"Gemini [{model}] failed: {e}")
            # Move to next model
            current_model_index = (current_model_index + 1) % total_models
            tried += 1

            if tried < total_models:
                switch_msg = random.choice(BRAIN_SWITCH_MSGS)
                next_model = GEMINI_MODELS[current_model_index]
                switch_msg += f"\n_(Brain #{current_model_index + 1}: {next_model})_"
                # Send brain switch notification
                if send_status_func:
                    await send_status_func(switch_msg)
                continue

    return "Saare dimaag thak gaye! Thodi der baad aana yaar 😴", None


# ───────────────────────── HANDLERS ─────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uid = update.effective_user.id
        uname = update.effective_user.username or ""
        fname = update.effective_user.full_name or "User"
        save_user(uid, uname, fname)
        logger.info(f"/start from uid={uid} name={fname} chat_type={update.effective_chat.type}")

        chat = update.effective_chat
        if chat.type in ["group", "supergroup"]:
            register_group(chat.id)
            await update.message.reply_text("Heyy! 👋 Main Shekha hoon! Ab is group mein masti shuru! 😄🔥")
        else:
            await update.message.reply_text(
                "Heyy! 😊❤️ Main Shekha hoon!\n\n"
                "Kuch bhi poochho, main hamesha ready hoon! 🎉\n"
                "Admin ho toh /admin bhejo. 😉"
            )
    except Exception as e:
        logger.error(f"start error: {e}")

async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid):
        await show_admin_help(update)
        return
    await update.message.reply_text("🔐 Admin password bhejo:")
    ctx.user_data["waiting_admin_pass"] = True

async def show_admin_help(update):
    await update.message.reply_text(
        "✅ *Admin Panel - Shekha Bot* 🛡️\n\n"
        "👥 *Group Controls:*\n"
        "▶️ `/on <group_id>` — Shekha ON karo\n"
        "⏹ `/off <group_id>` — Shekha OFF karo\n"
        "📢 `/setpromo <group_id> | <interval> | <text>`\n"
        "🗑 `/removepromo <group_id>`\n"
        "📊 `/groups` — Saare groups dekho\n\n"
        "📨 *Broadcast:*\n"
        "📣 `/broadcast <message>`\n"
        "📤 `/forward` — Next message sabko forward\n\n"
        "👤 `/users` — Total users count",
        parse_mode="Markdown"
    )

async def on_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args:
        await update.message.reply_text("Usage: /on <group_id>"); return
    chat_id = int(ctx.args[0])
    register_group(chat_id)
    set_group_active(chat_id, 1)
    await update.message.reply_text("✅ Shekha ON!")

async def off_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args:
        await update.message.reply_text("Usage: /off <group_id>"); return
    set_group_active(int(ctx.args[0]), 0)
    await update.message.reply_text("⏹ Shekha OFF!")

async def setpromo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        text = update.message.text.replace("/setpromo", "").strip()
        parts = text.split("|")
        chat_id = int(parts[0].strip())
        interval = int(parts[1].strip())
        promo_text = parts[2].strip()
        set_promo(chat_id, promo_text, interval)
        await update.message.reply_text(
            f"✅ Promo set!\nHar *{interval} msgs* baad:\n_{promo_text}_",
            parse_mode="Markdown"
        )
    except:
        await update.message.reply_text("❌ Format:\n`/setpromo <group_id> | <interval> | <text>`", parse_mode="Markdown")

async def removepromo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args:
        await update.message.reply_text("Usage: /removepromo <group_id>"); return
    set_promo(int(ctx.args[0]), None, 0)
    await update.message.reply_text("🗑 Promo hata diya!")

async def groups_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    groups = conn.execute("SELECT * FROM groups").fetchall()
    conn.close()
    if not groups:
        await update.message.reply_text("Koi group nahi."); return
    text = "📊 *Groups:*\n\n"
    for g in groups:
        status = "✅ ON" if g["is_active"] else "⏹ OFF"
        promo = f"Promo: har {g['promo_interval']} msgs" if g["promo_interval"] else "No promo"
        text += f"`{g['chat_id']}` — {status} — {promo}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def users_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    users = get_all_users()
    await update.message.reply_text(f"👤 Total Users: *{len(users)}*", parse_mode="Markdown")

async def broadcast_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    msg = update.message.text.replace("/broadcast", "").strip()
    if not msg:
        await update.message.reply_text("Usage: /broadcast <message>"); return
    users = get_all_users()
    sent, failed = 0, 0
    for uid in users:
        try:
            await ctx.bot.send_message(chat_id=uid, text=f"📢 *Announcement*\n\n{msg}", parse_mode="Markdown")
            sent += 1
        except:
            failed += 1
    await update.message.reply_text(f"✅ Sent: *{sent}*\n❌ Failed: *{failed}*", parse_mode="Markdown")

async def forward_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    ctx.user_data["waiting_forward"] = True
    await update.message.reply_text(
        "📤 Ab jo bhi message bhejoge woh *sabko forward* ho jayega!\n_(Text, photo, video, kuch bhi)_",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message: return

        uid = update.effective_user.id
        chat = update.effective_chat
        user_name = update.effective_user.first_name or "User"
        uname = update.effective_user.username or ""
        fname = update.effective_user.full_name or "User"

        save_user(uid, uname, fname)
        logger.info(f"MSG uid={uid} chat_type={chat.type} text={update.message.text}")

        # ── PRIVATE CHAT ──
        if chat.type == "private":

            if ctx.user_data.get("waiting_admin_pass"):
                if update.message.text and update.message.text.strip() == ADMIN_PASS:
                    add_admin(uid)
                    ctx.user_data["waiting_admin_pass"] = False
                    await update.message.reply_text("✅ Admin login ho gaya! /admin bhejo.")
                else:
                    ctx.user_data["waiting_admin_pass"] = False
                    await update.message.reply_text("❌ Wrong password!")
                return

            if ctx.user_data.get("waiting_forward"):
                ctx.user_data["waiting_forward"] = False
                users = get_all_users()
                sent, failed = 0, 0
                for user_id in users:
                    try:
                        await update.message.forward(chat_id=user_id)
                        sent += 1
                    except:
                        failed += 1
                await update.message.reply_text(
                    f"✅ Forwarded to *{sent}* users!\n❌ Failed: *{failed}*",
                    parse_mode="Markdown"
                )
                return

            if not update.message.text:
                await update.message.reply_text("Arey kya bheja yeh? Text mein likho na! 😄")
                return

            async def send_status(msg):
                await update.message.reply_text(msg, parse_mode="Markdown")

            reply, _ = await ask_shekha(update.message.text, user_name, send_status)
            await update.message.reply_text(reply)
            return

        # ── GROUP CHAT ──
        if chat.type in ["group", "supergroup"]:
            register_group(chat.id)
            group = get_group(chat.id)
            if not group or not group["is_active"]:
                return
            if not update.message.text:
                return

            bot_username = ctx.bot.username
            is_mentioned = bool(bot_username and f"@{bot_username}" in update.message.text)
            is_reply_to_bot = (
                update.message.reply_to_message is not None and
                update.message.reply_to_message.from_user is not None and
                update.message.reply_to_message.from_user.id == ctx.bot.id
            )

            promo = increment_msg_count(chat.id)
            if promo:
                await update.message.reply_text(f"📢 {promo}")
                return

            if is_mentioned or is_reply_to_bot:
                clean_text = update.message.text.replace(f"@{bot_username}", "").strip() if bot_username else update.message.text

                async def send_status(msg):
                    await update.message.reply_text(msg, parse_mode="Markdown")

                reply, _ = await ask_shekha(clean_text, user_name, send_status)
                await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"handle_message error: {e}")

# ───────────────────────── MAIN ─────────────────────────

def main():
    init_db()
    logger.info("🤖 Shekha Bot starting...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("on", on_cmd))
    app.add_handler(CommandHandler("off", off_cmd))
    app.add_handler(CommandHandler("setpromo", setpromo_cmd))
    app.add_handler(CommandHandler("removepromo", removepromo_cmd))
    app.add_handler(CommandHandler("groups", groups_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("forward", forward_cmd))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    logger.info("🤖 Shekha Bot is LIVE!")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
