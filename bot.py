import sqlite3
import logging
import random
from datetime import datetime
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─────────────────────── CONFIG ───────────────────────
BOT_TOKEN     = "8663479623:AAEcaM8MXa28bXqTBBh6y9AyH7PhtRHGUWA"
GROQ_API_KEY  = "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"
ADMIN_PASS    = "2010"
DB_PATH       = "shekha.db"
SUPPORT_USER  = "@earn_karo_pls"
PAYMENT_UPI   = "richaryanbro@fam"
FREE_CREDITS  = 10          # messages per day
RESET_HOUR    = 0           # midnight 12:00 AM reset

GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
    "llama3-70b-8192",
    "llama3-8b-8192",
]

SHEKHA_PROMPT = """Tu ek bahut pyaari, funny, smart aur thodi naughty ladki hai jiska naam Shekha hai.
Tu hamesha Hindi mein baat karti hai (Hinglish bhi chalega).
Tu sabke messages ka reply karti hai - funny, helpful aur engaging tarike se.
Tu kabhi bhi boring nahi hoti. Tu emoji use karti hai.
Tu short replies deti hai - 1-3 sentences max.
Agar koi serious sawaal pooche toh seedha helpful jawab de.
Agar koi bakwaas kare toh funny roast kar.
Agar koi flirt kare toh shayarana reply de.
Tu apne aap ko AI nahi batati - tu Shekha hai, ek real pyaari ladki ki tarah behave karti hai."""

BRAIN_SWITCH_MSGS = [
    "Ek sec... apna dimaag badal rahi hoon 🧠⚡",
    "Oops! Naya brain load ho raha hai... 🔄🧠",
    "Yeh wala dimaag kaam nahi kar raha, doosra try 😅🔃",
    "Brain switching... 💫🧠",
    "Naya mode on kar rahi hoon ⚙️✨",
    "Purana brain crash, naya install kar rahi hoon 😂🔧",
]

groq_client = Groq(api_key=GROQ_API_KEY)

# ─────────────────────── DB SETUP ───────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        telegram_id   INTEGER PRIMARY KEY,
        username      TEXT,
        full_name     TEXT,
        credits       INTEGER DEFAULT 10,
        last_reset    TEXT DEFAULT '',
        extra_credits INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS admins (
        telegram_id INTEGER PRIMARY KEY
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS groups (
        chat_id        INTEGER PRIMARY KEY,
        is_active      INTEGER DEFAULT 1,
        promo_text     TEXT DEFAULT NULL,
        promo_interval INTEGER DEFAULT 0,
        message_count  INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS payments (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER,
        utr        TEXT,
        amount     TEXT,
        status     TEXT DEFAULT 'pending',
        credits    INTEGER DEFAULT 0,
        created_at TEXT
    )""")

    conn.commit()
    conn.close()

# ─────────────────────── USER HELPERS ───────────────────────

def get_today():
    return datetime.now().strftime("%Y-%m-%d")

def get_user(telegram_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    return row

def save_user(telegram_id, username, full_name):
    conn = sqlite3.connect(DB_PATH)
    today = get_today()
    conn.execute("""INSERT INTO users (telegram_id, username, full_name, credits, last_reset, extra_credits)
                    VALUES (?,?,?,?,?,'')
                    ON CONFLICT(telegram_id) DO UPDATE SET
                    username=excluded.username, full_name=excluded.full_name""",
                 (telegram_id, username, full_name, FREE_CREDITS, today))
    conn.commit()
    conn.close()

def reset_credits_if_needed(telegram_id):
    """Reset credits to FREE_CREDITS at midnight every day."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    today = get_today()
    if row and row["last_reset"] != today:
        conn.execute("UPDATE users SET credits=?, last_reset=? WHERE telegram_id=?",
                     (FREE_CREDITS, today, telegram_id))
        conn.commit()
    conn.close()

def get_credits(telegram_id):
    reset_credits_if_needed(telegram_id)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT credits, extra_credits FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    if row:
        return row["credits"] + row["extra_credits"]
    return 0

def use_credit(telegram_id):
    """Returns True if credit used successfully, False if no credits."""
    reset_credits_if_needed(telegram_id)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT credits, extra_credits FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not row:
        conn.close()
        return False
    # Use extra_credits first, then normal credits
    if row["extra_credits"] > 0:
        conn.execute("UPDATE users SET extra_credits=extra_credits-1 WHERE telegram_id=?", (telegram_id,))
        conn.commit()
        conn.close()
        return True
    elif row["credits"] > 0:
        conn.execute("UPDATE users SET credits=credits-1 WHERE telegram_id=?", (telegram_id,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def add_credits(telegram_id, amount):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET extra_credits=extra_credits+? WHERE telegram_id=?", (amount, telegram_id))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT telegram_id FROM users").fetchall()
    conn.close()
    return [r[0] for r in rows]

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

# ─────────────────────── GROUP HELPERS ───────────────────────

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
    conn.commit()
    conn.close()
    if row and row[1] and row[1] > 0 and row[0] >= row[1]:
        conn2 = sqlite3.connect(DB_PATH)
        conn2.execute("UPDATE groups SET message_count=0 WHERE chat_id=?", (chat_id,))
        conn2.commit()
        conn2.close()
        return row[2]
    return None

# ─────────────────────── PAYMENT HELPERS ───────────────────────

def submit_payment(user_id, utr, amount, credits):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO payments (user_id, utr, amount, status, credits, created_at) VALUES (?,?,?,?,?,?)",
                 (user_id, utr, amount, "pending", credits, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def get_pending_payments():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM payments WHERE status='pending' ORDER BY created_at DESC").fetchall()
    conn.close()
    return rows

def get_payment_by_id(pay_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM payments WHERE id=?", (pay_id,)).fetchone()
    conn.close()
    return row

def update_payment_status(pay_id, status):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE payments SET status=? WHERE id=?", (status, pay_id))
    conn.commit()
    conn.close()

# ─────────────────────── GROQ AI ───────────────────────

current_model_index = 0

async def ask_shekha(user_message, user_name, send_status_func=None):
    global current_model_index
    total = len(GROQ_MODELS)
    tried = 0

    while tried < total:
        model = GROQ_MODELS[current_model_index]
        try:
            response = groq_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SHEKHA_PROMPT},
                    {"role": "user", "content": f"{user_name} ne kaha: {user_message}"}
                ],
                max_tokens=200,
                temperature=0.9,
            )
            reply = response.choices[0].message.content.strip()
            if reply:
                logger.info(f"Groq [{model}] success!")
                return reply
        except Exception as e:
            logger.warning(f"Groq [{model}] failed: {e}")
            current_model_index = (current_model_index + 1) % total
            tried += 1
            if tried < total:
                switch_msg = random.choice(BRAIN_SWITCH_MSGS)
                switch_msg += f"\n_(Brain #{current_model_index + 1}: {GROQ_MODELS[current_model_index]})_"
                if send_status_func:
                    await send_status_func(switch_msg)
            continue

    return "Saare dimaag thak gaye! Thodi der baad try karo yaar 😴"

# ─────────────────────── KEYBOARDS ───────────────────────

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💬 Chat with Shekha", callback_data="menu_chat"),
            InlineKeyboardButton("📊 My Credits", callback_data="menu_credits"),
        ],
        [
            InlineKeyboardButton("💳 Buy Credits", callback_data="menu_buy"),
            InlineKeyboardButton("❓ Help", url=f"https://t.me/{SUPPORT_USER.lstrip('@')}"),
        ],
        [
            InlineKeyboardButton("📢 Support Channel", url=f"https://t.me/{SUPPORT_USER.lstrip('@')}"),
        ]
    ])

def buy_credits_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("50 Credits — ₹10", callback_data="buy_50_10"),
            InlineKeyboardButton("100 Credits — ₹18", callback_data="buy_100_18"),
        ],
        [
            InlineKeyboardButton("250 Credits — ₹40", callback_data="buy_250_40"),
            InlineKeyboardButton("500 Credits — ₹75", callback_data="buy_500_75"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_back")],
    ])

def payment_admin_keyboard(pay_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"pay_approve_{pay_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"pay_reject_{pay_id}"),
        ]
    ])

# ─────────────────────── /start ───────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uid   = update.effective_user.id
        uname = update.effective_user.username or ""
        fname = update.effective_user.full_name or "User"
        save_user(uid, uname, fname)

        chat = update.effective_chat
        if chat.type in ["group", "supergroup"]:
            register_group(chat.id)
            await update.message.reply_text("Heyy! 👋 Main Shekha hoon! Ab is group mein masti shuru! 😄🔥")
            return

        credits = get_credits(uid)
        text = (
            f"Heyy! 😊❤️ Main *Shekha* hoon!\n\n"
            f"Kuch bhi poochho, main hamesha ready hoon! 🎉\n"
            f"💰 Aapke paas abhi *{credits} credits* hain.\n"
            f"_(Free: {FREE_CREDITS} credits/day, midnight pe reset)_\n\n"
            f"Neeche se kuch select karo 👇"
        )
        await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"start error: {e}")

# ─────────────────────── BUTTON CALLBACKS ───────────────────────

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    data  = query.data

    # ── Main Menu ──
    if data == "menu_chat":
        await query.edit_message_text(
            "Bas message karo, main reply karungi! 😊\n"
            "_(Credits check karne ke liye /credits bhejo)_",
            parse_mode="Markdown"
        )

    elif data == "menu_credits":
        credits = get_credits(uid)
        reset_credits_if_needed(uid)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT credits, extra_credits, last_reset FROM users WHERE telegram_id=?", (uid,)).fetchone()
        conn.close()
        text = (
            f"📊 *Your Credits*\n\n"
            f"🆓 Daily Credits: *{row['credits']}/{FREE_CREDITS}*\n"
            f"💎 Paid Credits: *{row['extra_credits']}*\n"
            f"📅 Last Reset: *{row['last_reset']}*\n"
            f"🔄 Resets daily at midnight (12:00 AM)\n\n"
            f"Total Available: *{credits}* messages"
        )
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup([
                                          [InlineKeyboardButton("💳 Buy More", callback_data="menu_buy"),
                                           InlineKeyboardButton("🔙 Back", callback_data="menu_back")]
                                      ]))

    elif data == "menu_buy":
        text = (
            f"💳 *Buy Credits*\n\n"
            f"UPI ID: `{PAYMENT_UPI}`\n\n"
            f"Select a pack 👇\n"
            f"_(After payment, send UTR number here)_"
        )
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=buy_credits_keyboard())

    elif data == "menu_back":
        credits = get_credits(uid)
        text = (
            f"Heyy! 😊❤️ Main *Shekha* hoon!\n\n"
            f"Kuch bhi poochho, main hamesha ready hoon! 🎉\n"
            f"💰 Aapke paas abhi *{credits} credits* hain.\n"
            f"_(Free: {FREE_CREDITS} credits/day, midnight pe reset)_\n\n"
            f"Neeche se kuch select karo 👇"
        )
        await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")

    # ── Buy Packs ──
    elif data.startswith("buy_"):
        parts   = data.split("_")
        credits = int(parts[1])
        amount  = parts[2]
        ctx.user_data["pending_purchase"] = {"credits": credits, "amount": amount}
        text = (
            f"💳 *Payment Instructions*\n\n"
            f"Pack: *{credits} Credits*\n"
            f"Amount: *₹{amount}*\n\n"
            f"1️⃣ UPI ID: `{PAYMENT_UPI}`\n"
            f"2️⃣ Pay ₹{amount} karo\n"
            f"3️⃣ UTR/Transaction number yahan bhejo\n\n"
            f"_Admin verify karega aur credits add ho jayenge!_"
        )
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup([
                                          [InlineKeyboardButton("🔙 Back", callback_data="menu_buy")]
                                      ]))
        ctx.user_data["waiting_utr"] = True

    # ── Admin Payment Actions ──
    elif data.startswith("pay_approve_"):
        if not is_admin(uid):
            await query.answer("❌ Admin only!", show_alert=True)
            return
        pay_id  = int(data.split("_")[2])
        payment = get_payment_by_id(pay_id)
        if not payment or payment["status"] != "pending":
            await query.answer("Already processed!", show_alert=True)
            return
        add_credits(payment["user_id"], payment["credits"])
        update_payment_status(pay_id, "approved")
        # Notify user
        try:
            await ctx.bot.send_message(
                chat_id=payment["user_id"],
                text=f"✅ *Payment Approved!*\n\n"
                     f"*{payment['credits']} credits* add ho gaye!\n"
                     f"UTR: `{payment['utr']}`\n\n"
                     f"Enjoy karo Shekha ke saath! 😊",
                parse_mode="Markdown"
            )
        except:
            pass
        await query.edit_message_text(
            query.message.text + f"\n\n✅ *APPROVED by admin*",
            parse_mode="Markdown"
        )

    elif data.startswith("pay_reject_"):
        if not is_admin(uid):
            await query.answer("❌ Admin only!", show_alert=True)
            return
        pay_id  = int(data.split("_")[2])
        payment = get_payment_by_id(pay_id)
        if not payment or payment["status"] != "pending":
            await query.answer("Already processed!", show_alert=True)
            return
        update_payment_status(pay_id, "rejected")
        try:
            await ctx.bot.send_message(
                chat_id=payment["user_id"],
                text=f"❌ *Payment Rejected*\n\n"
                     f"UTR: `{payment['utr']}`\n"
                     f"Agar galti hui hai toh {SUPPORT_USER} se contact karo.",
                parse_mode="Markdown"
            )
        except:
            pass
        await query.edit_message_text(
            query.message.text + f"\n\n❌ *REJECTED by admin*",
            parse_mode="Markdown"
        )

# ─────────────────────── /credits COMMAND ───────────────────────

async def credits_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    credits = get_credits(uid)
    conn    = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT credits, extra_credits FROM users WHERE telegram_id=?", (uid,)).fetchone()
    conn.close()
    text = (
        f"📊 *Your Credits*\n\n"
        f"🆓 Daily Credits: *{row['credits']}/{FREE_CREDITS}*\n"
        f"💎 Paid Credits: *{row['extra_credits']}*\n"
        f"✅ Total: *{credits}* messages available\n\n"
        f"🔄 Daily credits reset at midnight!\n"
        f"💳 More credits? /buy karo"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ─────────────────────── /buy COMMAND ───────────────────────

async def buy_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        f"💳 *Buy Credits*\n\n"
        f"UPI ID: `{PAYMENT_UPI}`\n\n"
        f"📦 *Available Packs:*\n"
        f"• 50 Credits — ₹10\n"
        f"• 100 Credits — ₹18\n"
        f"• 250 Credits — ₹40\n"
        f"• 500 Credits — ₹75\n\n"
        f"1️⃣ Pay karo UPI pe\n"
        f"2️⃣ UTR number yahan bhejo\n"
        f"3️⃣ Admin verify karega\n"
        f"4️⃣ Credits add ho jayenge!\n\n"
        f"Help: {SUPPORT_USER}"
    )
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=buy_credits_keyboard())

# ─────────────────────── /admin COMMAND ───────────────────────

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
        "💳 *Payments:*\n"
        "/payments — Pending payments dekho\n"
        "/addcredits <user_id> <amount> — Manually add credits\n\n"
        "👥 *Group Controls:*\n"
        "/on <group_id> — Shekha ON\n"
        "/off <group_id> — Shekha OFF\n"
        "/setpromo <group_id> | <interval> | <text>\n"
        "/removepromo <group_id>\n"
        "/groups — Saare groups\n\n"
        "📨 *Broadcast:*\n"
        "/broadcast <message>\n"
        "/forward — Next message forward\n\n"
        "👤 /users — Total users",
        parse_mode="Markdown"
    )

# ─────────────────────── /payments COMMAND ───────────────────────

async def payments_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    payments = get_pending_payments()
    if not payments:
        await update.message.reply_text("✅ Koi pending payment nahi!")
        return
    for p in payments:
        try:
            user = await ctx.bot.get_chat(p["user_id"])
            uname = f"@{user.username}" if user.username else user.full_name
        except:
            uname = f"ID: {p['user_id']}"
        text = (
            f"💳 *Payment Request #{p['id']}*\n\n"
            f"👤 User: {uname}\n"
            f"💰 Amount: ₹{p['amount']}\n"
            f"🎁 Credits: {p['credits']}\n"
            f"🔢 UTR: `{p['utr']}`\n"
            f"📅 Time: {p['created_at']}\n"
            f"Status: ⏳ Pending"
        )
        await update.message.reply_text(text, parse_mode="Markdown",
                                        reply_markup=payment_admin_keyboard(p["id"]))

# ─────────────────────── /addcredits COMMAND ───────────────────────

async def addcredits_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        user_id = int(ctx.args[0])
        amount  = int(ctx.args[1])
        add_credits(user_id, amount)
        await update.message.reply_text(f"✅ *{amount} credits* added to user `{user_id}`!", parse_mode="Markdown")
        try:
            await ctx.bot.send_message(
                chat_id=user_id,
                text=f"🎁 Admin ne tumhe *{amount} credits* diye! Enjoy karo 😊",
                parse_mode="Markdown"
            )
        except:
            pass
    except:
        await update.message.reply_text("Usage: /addcredits <user_id> <amount>")

# ─────────────────────── GROUP ADMIN COMMANDS ───────────────────────

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
        text  = update.message.text.replace("/setpromo", "").strip()
        parts = text.split("|")
        chat_id    = int(parts[0].strip())
        interval   = int(parts[1].strip())
        promo_text = parts[2].strip()
        set_promo(chat_id, promo_text, interval)
        await update.message.reply_text(f"✅ Promo set! Har *{interval} msgs* baad.", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Format: `/setpromo <id> | <interval> | <text>`", parse_mode="Markdown")

async def removepromo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args:
        await update.message.reply_text("Usage: /removepromo <group_id>"); return
    set_promo(int(ctx.args[0]), None, 0)
    await update.message.reply_text("🗑 Promo removed!")

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
        promo  = f"har {g['promo_interval']} msgs" if g["promo_interval"] else "No promo"
        text  += f"`{g['chat_id']}` — {status} — {promo}\n"
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
    await update.message.reply_text("📤 Next message sabko forward ho jayega!", parse_mode="Markdown")

# ─────────────────────── MESSAGE HANDLER ───────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message: return

        uid       = update.effective_user.id
        chat      = update.effective_chat
        user_name = update.effective_user.first_name or "User"
        uname     = update.effective_user.username or ""
        fname     = update.effective_user.full_name or "User"

        save_user(uid, uname, fname)

        # ── PRIVATE CHAT ──
        if chat.type == "private":

            # Admin password
            if ctx.user_data.get("waiting_admin_pass"):
                if update.message.text and update.message.text.strip() == ADMIN_PASS:
                    add_admin(uid)
                    ctx.user_data["waiting_admin_pass"] = False
                    await update.message.reply_text("✅ Admin login ho gaya! /admin bhejo.")
                else:
                    ctx.user_data["waiting_admin_pass"] = False
                    await update.message.reply_text("❌ Wrong password!")
                return

            # Forward mode
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
                await update.message.reply_text(f"✅ Forwarded to *{sent}*!\n❌ Failed: *{failed}*", parse_mode="Markdown")
                return

            # UTR submission
            if ctx.user_data.get("waiting_utr") and update.message.text:
                utr = update.message.text.strip()
                purchase = ctx.user_data.get("pending_purchase", {})
                credits  = purchase.get("credits", 0)
                amount   = purchase.get("amount", "?")
                if credits > 0:
                    submit_payment(uid, utr, amount, credits)
                    ctx.user_data["waiting_utr"] = False
                    ctx.user_data["pending_purchase"] = {}

                    # Notify all admins
                    try:
                        uinfo = f"@{uname}" if uname else fname
                        admin_text = (
                            f"💳 *New Payment Request!*\n\n"
                            f"👤 User: {uinfo} (`{uid}`)\n"
                            f"💰 Amount: ₹{amount}\n"
                            f"🎁 Credits: {credits}\n"
                            f"🔢 UTR: `{utr}`\n"
                            f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                        )
                        conn = sqlite3.connect(DB_PATH)
                        admins = conn.execute("SELECT telegram_id FROM admins").fetchall()
                        conn.close()
                        # Get the payment id
                        conn2 = sqlite3.connect(DB_PATH)
                        pay = conn2.execute("SELECT id FROM payments WHERE user_id=? AND utr=? ORDER BY id DESC LIMIT 1",
                                            (uid, utr)).fetchone()
                        conn2.close()
                        pay_id = pay[0] if pay else 0
                        for admin in admins:
                            try:
                                await ctx.bot.send_message(
                                    chat_id=admin[0],
                                    text=admin_text,
                                    parse_mode="Markdown",
                                    reply_markup=payment_admin_keyboard(pay_id)
                                )
                            except:
                                pass
                    except Exception as e:
                        logger.error(f"Admin notify error: {e}")

                    await update.message.reply_text(
                        f"✅ *Payment submitted!*\n\n"
                        f"UTR: `{utr}`\n"
                        f"Credits requested: *{credits}*\n\n"
                        f"Admin verify karega, thodi der mein credits add ho jayenge! 🙏",
                        parse_mode="Markdown"
                    )
                else:
                    ctx.user_data["waiting_utr"] = False
                    await update.message.reply_text("❌ Kuch galat hua! /buy se dobara try karo.")
                return

            # Non-text
            if not update.message.text:
                await update.message.reply_text("Arey kya bheja yeh? Text mein likho na! 😄")
                return

            # Credit check
            credits = get_credits(uid)
            if credits <= 0:
                await update.message.reply_text(
                    f"❌ *Credits khatam ho gaye!*\n\n"
                    f"🔄 Daily credits midnight pe reset honge.\n"
                    f"💳 Ya abhi /buy karo aur zyada credits lo!\n\n"
                    f"Help: {SUPPORT_USER}",
                    parse_mode="Markdown"
                )
                return

            # Use credit & reply
            use_credit(uid)
            remaining = get_credits(uid)

            async def send_status(msg):
                await update.message.reply_text(msg, parse_mode="Markdown")

            reply = await ask_shekha(update.message.text, user_name, send_status)
            # Add credits reminder at low balance
            if remaining <= 2:
                reply += f"\n\n_(⚠️ Sirf {remaining} credits bache! /buy karo)_"
            await update.message.reply_text(reply)
            return

        # ── GROUP CHAT ──
        if chat.type in ["group", "supergroup"]:
            register_group(chat.id)
            group = get_group(chat.id)
            if not group or not group["is_active"]: return
            if not update.message.text: return

            bot_username   = ctx.bot.username
            is_mentioned   = bool(bot_username and f"@{bot_username}" in update.message.text)
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

                reply = await ask_shekha(clean_text, user_name, send_status)
                await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"handle_message error: {e}")

# ─────────────────────── MAIN ───────────────────────

def main():
    init_db()
    logger.info("🤖 Shekha Bot starting...")
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",        start))
    app.add_handler(CommandHandler("credits",      credits_cmd))
    app.add_handler(CommandHandler("buy",          buy_cmd))
    app.add_handler(CommandHandler("admin",        admin_cmd))
    app.add_handler(CommandHandler("payments",     payments_cmd))
    app.add_handler(CommandHandler("addcredits",   addcredits_cmd))
    app.add_handler(CommandHandler("on",           on_cmd))
    app.add_handler(CommandHandler("off",          off_cmd))
    app.add_handler(CommandHandler("setpromo",     setpromo_cmd))
    app.add_handler(CommandHandler("removepromo",  removepromo_cmd))
    app.add_handler(CommandHandler("groups",       groups_cmd))
    app.add_handler(CommandHandler("users",        users_cmd))
    app.add_handler(CommandHandler("broadcast",    broadcast_cmd))
    app.add_handler(CommandHandler("forward",      forward_cmd))

    # Buttons
    app.add_handler(CallbackQueryHandler(button_handler))

    # Messages
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    logger.info("🤖 Shekha Bot is LIVE!")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
