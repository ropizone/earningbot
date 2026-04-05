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
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{SHEKHA_PROMPT}\n\n{user_name} ne kaha: {user_message}"}
                    ]
                }
            ]
        }
        response = requests.post(url, json=payload, timeout=20)
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"Gemini Error: {e}")
        return "Arre yaar, thoda busy hoon abhi! 😅"

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or ""
    fname = update.effective_user.full_name or "User"
    save_user(uid, uname, fname)

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
        "📨 *Broadcast to ALL users (private):*\n"
        "📣 `/broadcast <message>` — Text bhejo sabko\n"
        "📤 `/forward` — Koi bhi message forward karo sabko\n_(Next message jo bhejoge woh sabko jayega)_\n\n"
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
    await update.message.reply_text("📤 Ab jo bhi message bhejoge woh *sabko forward* ho jayega!\n_(Text, photo, video, kuch bhi)_", parse_mode="Markdown")

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message: return

    uid = update.effective_user.id
    chat = update.effective_chat
    user_name = update.effective_user.first_name or "User"
    uname = update.effective_user.username or ""
    fname = update.effective_user.full_name or "User"

    # Save user
    save_user(uid, uname, fname)

    # ---- PRIVATE CHAT ----
    if chat.type == "private":
        # Admin password check
        if ctx.user_data.get("waiting_admin_pass"):
            if update.message.text and update.message.text.strip() == ADMIN_PASS:
                add_admin(uid)
                ctx.user_data["waiting_admin_pass"] = False
                await update.message.reply_text("✅ Admin login ho gaya! /admin bhejo.")
            else:
                ctx.user_data["waiting_admin_pass"] = False
                await update.message.reply_text("❌ Wrong password!")
            return

        # Forward to all users
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
            await update.message.reply_text(f"✅ Forwarded to *{sent}* users!\n❌ Failed: *{failed}*", parse_mode="Markdown")
            return

        # Normal private chat reply
        if not update.message.text: return
        reply = ask_shekha(update.message.text, user_name)
        await update.message.reply_text(reply)
        return

    # ---- GROUP CHAT ----
    if chat.type in ["group", "supergroup"]:
        register_group(chat.id)
        group = get_group(chat.id)
        if not group or not group["is_active"]: return
        if not update.message.text: return
        promo = increment_msg_count(chat.id)
        if promo:
            await update.message.reply_text(f"📢 {promo}")
            return
        reply = ask_shekha(update.message.text, user_name)
        await update.message.reply_text(reply)

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
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("forward", forward_cmd))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    print("🤖 Shekha Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
