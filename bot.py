import sqlite3
import logging
import random
import asyncio
from datetime import datetime
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────── CONFIG ───────────────────────
BOT_TOKEN    = "8663479623:AAEcaM8MXa28bXqTBBh6y9AyH7PhtRHGUWA"
GROQ_API_KEY = "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"
ADMIN_PASS   = "2010"
DB_PATH      = "shekha.db"
SUPPORT_USER = "@earn_karo_pls"
PAYMENT_UPI  = "richaryanbro@fam"
FREE_CREDITS = 10

GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
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

BRAIN_MSGS = [
    "Ek sec... apna dimaag badal rahi hoon 🧠⚡",
    "Oops! Naya brain load ho raha hai 🔄🧠",
    "Yeh wala kaam nahi kar raha, doosra try karti hoon 😅",
    "Brain switching... 💫",
    "Naya mode on kar rahi hoon ⚙️✨",
    "Purana crash, naya install kar rahi hoon 😂🔧",
]

groq_client      = Groq(api_key=GROQ_API_KEY)
current_model_ix = 0

# ─────────────────────── DB ───────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        telegram_id   INTEGER PRIMARY KEY,
        username      TEXT,
        full_name     TEXT,
        credits       INTEGER DEFAULT 10,
        last_reset    TEXT    DEFAULT '',
        extra_credits INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS admins (
        telegram_id INTEGER PRIMARY KEY
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS groups (
        chat_id        INTEGER PRIMARY KEY,
        is_active      INTEGER DEFAULT 1,
        promo_text     TEXT    DEFAULT NULL,
        promo_interval INTEGER DEFAULT 0,
        message_count  INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS payments (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER,
        utr        TEXT,
        amount     TEXT,
        status     TEXT    DEFAULT 'pending',
        credits    INTEGER DEFAULT 0,
        created_at TEXT
    )""")
    conn.commit()
    conn.close()

# ─────────────────────── USER HELPERS ───────────────────────

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def save_user(tid, uname, fname):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT INTO users (telegram_id,username,full_name,credits,last_reset,extra_credits)
                    VALUES (?,?,?,10,?,'')
                    ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name""",
                 (tid, uname, fname, today_str()))
    conn.commit()
    conn.close()

def reset_if_needed(tid):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT last_reset FROM users WHERE telegram_id=?", (tid,)).fetchone()
    if row and row["last_reset"] != today_str():
        conn.execute("UPDATE users SET credits=?,last_reset=? WHERE telegram_id=?",
                     (FREE_CREDITS, today_str(), tid))
        conn.commit()
    conn.close()

def get_credits(tid):
    reset_if_needed(tid)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT credits,extra_credits FROM users WHERE telegram_id=?", (tid,)).fetchone()
    conn.close()
    return (row["credits"] + row["extra_credits"]) if row else 0

def use_credit(tid):
    reset_if_needed(tid)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT credits,extra_credits FROM users WHERE telegram_id=?", (tid,)).fetchone()
    if not row:
        conn.close(); return False
    if row["extra_credits"] > 0:
        conn.execute("UPDATE users SET extra_credits=extra_credits-1 WHERE telegram_id=?", (tid,))
    elif row["credits"] > 0:
        conn.execute("UPDATE users SET credits=credits-1 WHERE telegram_id=?", (tid,))
    else:
        conn.close(); return False
    conn.commit(); conn.close(); return True

def add_credits(tid, amount):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET extra_credits=extra_credits+? WHERE telegram_id=?", (amount, tid))
    conn.commit(); conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT telegram_id FROM users").fetchall()
    conn.close()
    return [r[0] for r in rows]

def is_admin(tid):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT 1 FROM admins WHERE telegram_id=?", (tid,)).fetchone()
    conn.close()
    return row is not None

def add_admin(tid):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (tid,))
    conn.commit(); conn.close()

# ─────────────────────── GROUP HELPERS ───────────────────────

def get_group(chat_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM groups WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close(); return row

def register_group(chat_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO groups (chat_id) VALUES (?)", (chat_id,))
    conn.commit(); conn.close()

def set_group_active(chat_id, val):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE groups SET is_active=? WHERE chat_id=?", (val, chat_id))
    conn.commit(); conn.close()

def set_promo(chat_id, text, interval):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE groups SET promo_text=?,promo_interval=?,message_count=0 WHERE chat_id=?",
                 (text, interval, chat_id))
    conn.commit(); conn.close()

def increment_msg(chat_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE groups SET message_count=message_count+1 WHERE chat_id=?", (chat_id,))
    row = conn.execute("SELECT message_count,promo_interval,promo_text FROM groups WHERE chat_id=?", (chat_id,)).fetchone()
    conn.commit(); conn.close()
    if row and row[1] and row[1] > 0 and row[0] >= row[1]:
        conn2 = sqlite3.connect(DB_PATH)
        conn2.execute("UPDATE groups SET message_count=0 WHERE chat_id=?", (chat_id,))
        conn2.commit(); conn2.close()
        return row[2]
    return None

# ─────────────────────── PAYMENT HELPERS ───────────────────────

def submit_payment(user_id, utr, amount, credits):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO payments (user_id,utr,amount,status,credits,created_at) VALUES (?,?,?,?,?,?)",
                 (user_id, utr, amount, "pending", credits,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close()

def get_pending_payments():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM payments WHERE status='pending' ORDER BY id DESC").fetchall()
    conn.close(); return rows

def get_payment(pay_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM payments WHERE id=?", (pay_id,)).fetchone()
    conn.close(); return row

def update_payment(pay_id, status):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE payments SET status=? WHERE id=?", (status, pay_id))
    conn.commit(); conn.close()

# ─────────────────────── GROQ AI ───────────────────────

async def ask_shekha(user_message, user_name, status_fn=None):
    global current_model_ix
    total = len(GROQ_MODELS)

    for attempt in range(total):
        model = GROQ_MODELS[current_model_ix]
        try:
            resp = await asyncio.to_thread(
                groq_client.chat.completions.create,
                model=model,
                messages=[
                    {"role": "system", "content": SHEKHA_PROMPT},
                    {"role": "user",   "content": f"{user_name} ne kaha: {user_message}"}
                ],
                max_tokens=200,
                temperature=0.9,
            )
            reply = resp.choices[0].message.content.strip()
            if reply:
                logger.info(f"Groq success: {model}")
                return reply
        except Exception as e:
            logger.warning(f"Groq [{model}] failed: {e}")
            current_model_ix = (current_model_ix + 1) % total
            if attempt + 1 < total and status_fn:
                next_model = GROQ_MODELS[current_model_ix]
                msg = random.choice(BRAIN_MSGS) + f"\n_(Brain #{current_model_ix+1}: {next_model})_"
                await status_fn(msg)

    return "Saare dimaag thak gaye! Thodi der baad try karo 😴"

# ─────────────────────── KEYBOARDS ───────────────────────

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Chat", callback_data="chat"),
         InlineKeyboardButton("📊 My Credits", callback_data="credits")],
        [InlineKeyboardButton("💳 Buy Credits", callback_data="buy"),
         InlineKeyboardButton("❓ Help", url=f"https://t.me/{SUPPORT_USER.lstrip('@')}")],
        [InlineKeyboardButton("📢 Support", url=f"https://t.me/{SUPPORT_USER.lstrip('@')}")],
    ])

def buy_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("50 Credits — ₹10",  callback_data="pack_50_10"),
         InlineKeyboardButton("100 Credits — ₹18", callback_data="pack_100_18")],
        [InlineKeyboardButton("250 Credits — ₹40", callback_data="pack_250_40"),
         InlineKeyboardButton("500 Credits — ₹75", callback_data="pack_500_75")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")],
    ])

def pay_admin_kb(pay_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{pay_id}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"reject_{pay_id}"),
    ]])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])

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
            await update.message.reply_text("Heyy! 👋 Main Shekha hoon! Masti shuru! 😄🔥")
            return

        cr = get_credits(uid)
        await update.message.reply_text(
            f"Heyy! 😊❤️ Main *Shekha* hoon!\n\n"
            f"Kuch bhi poochho, main ready hoon! 🎉\n"
            f"💰 Credits: *{cr}* available\n"
            f"_(Free: {FREE_CREDITS}/day — midnight reset)_\n\n"
            f"Kya karna hai? 👇",
            parse_mode="Markdown", reply_markup=main_kb()
        )
    except Exception as e:
        logger.error(f"start: {e}")

# ─────────────────────── CALLBACKS ───────────────────────

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    await q.answer()
    uid  = q.from_user.id
    data = q.data

    if data == "chat":
        await q.edit_message_text(
            "Bas message bhejo! Main hamesha ready hoon 😊\n"
            "_(/credits se balance check karo)_",
            parse_mode="Markdown"
        )

    elif data == "credits":
        reset_if_needed(uid)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT credits,extra_credits,last_reset FROM users WHERE telegram_id=?", (uid,)).fetchone()
        conn.close()
        total = (row["credits"] + row["extra_credits"]) if row else 0
        await q.edit_message_text(
            f"📊 *Your Credits*\n\n"
            f"🆓 Daily Credits: *{row['credits']}/{FREE_CREDITS}*\n"
            f"💎 Paid Credits: *{row['extra_credits']}*\n"
            f"✅ Total: *{total}*\n"
            f"📅 Last Reset: {row['last_reset']}\n"
            f"🔄 Resets daily at midnight!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Buy More", callback_data="buy"),
                 InlineKeyboardButton("🔙 Back", callback_data="back")]
            ])
        )

    elif data == "buy":
        await q.edit_message_text(
            f"💳 *Buy Credits*\n\n"
            f"UPI: `{PAYMENT_UPI}`\n\n"
            f"Pack chuno 👇\n"
            f"_(Pay karo → UTR bhejo → Admin approve karega)_",
            parse_mode="Markdown", reply_markup=buy_kb()
        )

    elif data == "back":
        cr = get_credits(uid)
        await q.edit_message_text(
            f"Heyy! 😊❤️ Main *Shekha* hoon!\n\n"
            f"Kuch bhi poochho, main ready hoon! 🎉\n"
            f"💰 Credits: *{cr}* available\n"
            f"_(Free: {FREE_CREDITS}/day — midnight reset)_\n\n"
            f"Kya karna hai? 👇",
            parse_mode="Markdown", reply_markup=main_kb()
        )

    elif data.startswith("pack_"):
        parts   = data.split("_")
        credits = int(parts[1])
        amount  = parts[2]
        ctx.user_data["pending_buy"] = {"credits": credits, "amount": amount}
        ctx.user_data["waiting_utr"] = True
        await q.edit_message_text(
            f"💳 *Payment Steps*\n\n"
            f"Pack: *{credits} Credits — ₹{amount}*\n\n"
            f"1️⃣ UPI ID: `{PAYMENT_UPI}`\n"
            f"2️⃣ ₹{amount} pay karo\n"
            f"3️⃣ UTR / Transaction ID yahan type karo\n\n"
            f"_Admin verify karega, credits add ho jayenge!_ ✅",
            parse_mode="Markdown", reply_markup=back_kb()
        )

    elif data.startswith("approve_"):
        if not is_admin(uid):
            await q.answer("❌ Sirf admin!", show_alert=True); return
        pay_id  = int(data.split("_")[1])
        payment = get_payment(pay_id)
        if not payment or payment["status"] != "pending":
            await q.answer("Already processed!", show_alert=True); return
        add_credits(payment["user_id"], payment["credits"])
        update_payment(pay_id, "approved")
        try:
            await ctx.bot.send_message(
                chat_id=payment["user_id"],
                text=f"✅ *Payment Approved!*\n\n"
                     f"*{payment['credits']} credits* add ho gaye!\n"
                     f"UTR: `{payment['utr']}`\n\nEnjoy! 😊",
                parse_mode="Markdown"
            )
        except: pass
        await q.edit_message_text(q.message.text + "\n\n✅ *APPROVED*", parse_mode="Markdown")

    elif data.startswith("reject_"):
        if not is_admin(uid):
            await q.answer("❌ Sirf admin!", show_alert=True); return
        pay_id  = int(data.split("_")[1])
        payment = get_payment(pay_id)
        if not payment or payment["status"] != "pending":
            await q.answer("Already processed!", show_alert=True); return
        update_payment(pay_id, "rejected")
        try:
            await ctx.bot.send_message(
                chat_id=payment["user_id"],
                text=f"❌ *Payment Rejected*\n\nUTR: `{payment['utr']}`\n"
                     f"Issues? Contact {SUPPORT_USER}",
                parse_mode="Markdown"
            )
        except: pass
        await q.edit_message_text(q.message.text + "\n\n❌ *REJECTED*", parse_mode="Markdown")

# ─────────────────────── COMMANDS ───────────────────────

async def credits_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cr  = get_credits(uid)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT credits,extra_credits FROM users WHERE telegram_id=?", (uid,)).fetchone()
    conn.close()
    await update.message.reply_text(
        f"📊 *Your Credits*\n\n"
        f"🆓 Daily: *{row['credits']}/{FREE_CREDITS}*\n"
        f"💎 Paid: *{row['extra_credits']}*\n"
        f"✅ Total: *{cr}*\n\n"
        f"🔄 Resets at midnight\n💳 /buy for more!",
        parse_mode="Markdown"
    )

async def buy_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"💳 *Buy Credits*\n\nUPI: `{PAYMENT_UPI}`\n\n"
        f"• 50 Credits — ₹10\n• 100 Credits — ₹18\n"
        f"• 250 Credits — ₹40\n• 500 Credits — ₹75\n\n"
        f"Pack select karo 👇",
        parse_mode="Markdown", reply_markup=buy_kb()
    )

async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid):
        await show_admin_panel(update); return
    await update.message.reply_text("🔐 Admin password bhejo:")
    ctx.user_data["waiting_admin_pass"] = True

async def show_admin_panel(update):
    await update.message.reply_text(
        "✅ *Admin Panel* 🛡️\n\n"
        "💳 `/payments` — Pending payments\n"
        "/addcredits <id> <amt> — Credits add\n\n"
        "👥 `/on` `/off` <group_id>\n"
        "/setpromo <id>|<interval>|<text>\n"
        "/removepromo <id>\n"
        "/groups — All groups\n\n"
        "📣 /broadcast <msg>\n"
        "/forward — Forward next msg\n"
        "/users — Total users",
        parse_mode="Markdown"
    )

async def payments_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    pending = get_pending_payments()
    if not pending:
        await update.message.reply_text("✅ No pending payments!"); return
    for p in pending:
        try:
            u = await ctx.bot.get_chat(p["user_id"])
            who = f"@{u.username}" if u.username else u.full_name
        except:
            who = str(p["user_id"])
        await update.message.reply_text(
            f"💳 *Payment #{p['id']}*\n\n"
            f"👤 {who} (`{p['user_id']}`)\n"
            f"💰 ₹{p['amount']} → {p['credits']} credits\n"
            f"🔢 UTR: `{p['utr']}`\n"
            f"📅 {p['created_at']}",
            parse_mode="Markdown", reply_markup=pay_admin_kb(p["id"])
        )

async def addcredits_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        uid = int(ctx.args[0]); amt = int(ctx.args[1])
        add_credits(uid, amt)
        await update.message.reply_text(f"✅ *{amt} credits* added to `{uid}`!", parse_mode="Markdown")
        try:
            await ctx.bot.send_message(uid, f"🎁 Admin ne *{amt} credits* diye! 😊", parse_mode="Markdown")
        except: pass
    except:
        await update.message.reply_text("Usage: /addcredits <user_id> <amount>")

async def on_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args: await update.message.reply_text("Usage: /on <group_id>"); return
    cid = int(ctx.args[0]); register_group(cid); set_group_active(cid, 1)
    await update.message.reply_text("✅ Shekha ON!")

async def off_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args: await update.message.reply_text("Usage: /off <group_id>"); return
    set_group_active(int(ctx.args[0]), 0)
    await update.message.reply_text("⏹ Shekha OFF!")

async def setpromo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        txt   = update.message.text.replace("/setpromo","").strip()
        parts = txt.split("|")
        set_promo(int(parts[0].strip()), parts[2].strip(), int(parts[1].strip()))
        await update.message.reply_text("✅ Promo set!", parse_mode="Markdown")
    except:
        await update.message.reply_text("Format: `/setpromo <id>|<interval>|<text>`", parse_mode="Markdown")

async def removepromo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args: await update.message.reply_text("Usage: /removepromo <id>"); return
    set_promo(int(ctx.args[0]), None, 0)
    await update.message.reply_text("🗑 Promo removed!")

async def groups_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    gs = conn.execute("SELECT * FROM groups").fetchall(); conn.close()
    if not gs: await update.message.reply_text("No groups."); return
    txt = "📊 *Groups:*\n\n"
    for g in gs:
        txt += f"`{g['chat_id']}` — {'✅ ON' if g['is_active'] else '⏹ OFF'} — "
        txt += f"promo har {g['promo_interval']} msgs\n" if g['promo_interval'] else "no promo\n"
    await update.message.reply_text(txt, parse_mode="Markdown")

async def users_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text(f"👤 Total Users: *{len(get_all_users())}*", parse_mode="Markdown")

async def broadcast_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    msg = update.message.text.replace("/broadcast","").strip()
    if not msg: await update.message.reply_text("Usage: /broadcast <msg>"); return
    sent = failed = 0
    for uid in get_all_users():
        try:
            await ctx.bot.send_message(uid, f"📢 *Announcement*\n\n{msg}", parse_mode="Markdown")
            sent += 1
        except: failed += 1
    await update.message.reply_text(f"✅ Sent: *{sent}*\n❌ Failed: *{failed}*", parse_mode="Markdown")

async def forward_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    ctx.user_data["waiting_forward"] = True
    await update.message.reply_text("📤 Next message sabko forward ho jayega!")

# ─────────────────────── MESSAGE HANDLER ───────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message: return
        uid   = update.effective_user.id
        chat  = update.effective_chat
        uname = update.effective_user.username or ""
        fname = update.effective_user.full_name or "User"
        name  = update.effective_user.first_name or "User"
        save_user(uid, uname, fname)

        # ── PRIVATE ──
        if chat.type == "private":

            # Admin password
            if ctx.user_data.get("waiting_admin_pass"):
                if update.message.text and update.message.text.strip() == ADMIN_PASS:
                    add_admin(uid)
                    ctx.user_data["waiting_admin_pass"] = False
                    await update.message.reply_text("✅ Admin ban gaye! /admin bhejo.")
                else:
                    ctx.user_data["waiting_admin_pass"] = False
                    await update.message.reply_text("❌ Wrong password!")
                return

            # Forward mode
            if ctx.user_data.get("waiting_forward"):
                ctx.user_data["waiting_forward"] = False
                sent = failed = 0
                for user_id in get_all_users():
                    try: await update.message.forward(chat_id=user_id); sent += 1
                    except: failed += 1
                await update.message.reply_text(f"✅ Forwarded: *{sent}*\n❌ Failed: *{failed}*", parse_mode="Markdown")
                return

            # UTR submission
            if ctx.user_data.get("waiting_utr") and update.message.text:
                utr  = update.message.text.strip()
                buy  = ctx.user_data.get("pending_buy", {})
                cred = buy.get("credits", 0)
                amt  = buy.get("amount", "?")
                if cred > 0:
                    submit_payment(uid, utr, amt, cred)
                    ctx.user_data["waiting_utr"] = False
                    ctx.user_data["pending_buy"] = {}
                    # Get payment id
                    conn = sqlite3.connect(DB_PATH)
                    pay  = conn.execute("SELECT id FROM payments WHERE user_id=? AND utr=? ORDER BY id DESC LIMIT 1",
                                        (uid, utr)).fetchone()
                    conn.close()
                    pay_id = pay[0] if pay else 0
                    # Notify admins
                    conn2  = sqlite3.connect(DB_PATH)
                    admins = conn2.execute("SELECT telegram_id FROM admins").fetchall()
                    conn2.close()
                    who = f"@{uname}" if uname else fname
                    for adm in admins:
                        try:
                            await ctx.bot.send_message(
                                adm[0],
                                f"💳 *New Payment!*\n\n"
                                f"👤 {who} (`{uid}`)\n"
                                f"💰 ₹{amt} → {cred} credits\n"
                                f"🔢 UTR: `{utr}`\n"
                                f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                                parse_mode="Markdown",
                                reply_markup=pay_admin_kb(pay_id)
                            )
                        except: pass
                    await update.message.reply_text(
                        f"✅ *Payment submitted!*\n\nUTR: `{utr}`\n"
                        f"Credits: *{cred}*\n\nAdmin verify karega soon! 🙏",
                        parse_mode="Markdown"
                    )
                else:
                    ctx.user_data["waiting_utr"] = False
                    await update.message.reply_text("❌ Kuch galat hua! /buy se try karo.")
                return

            # Non-text
            if not update.message.text:
                await update.message.reply_text("Text mein likho na yaar! 😄")
                return

            # Credit check
            cr = get_credits(uid)
            if cr <= 0:
                await update.message.reply_text(
                    f"❌ *Credits khatam!*\n\n"
                    f"🔄 Midnight pe {FREE_CREDITS} free credits reset honge.\n"
                    f"💳 Ya /buy karo abhi!\n\nHelp: {SUPPORT_USER}",
                    parse_mode="Markdown", reply_markup=main_kb()
                )
                return

            use_credit(uid)
            remaining = get_credits(uid)

            async def status_fn(msg):
                await update.message.reply_text(msg, parse_mode="Markdown")

            reply = await ask_shekha(update.message.text, name, status_fn)
            if remaining <= 2:
                reply += f"\n\n_(⚠️ Sirf {remaining} credits bache! /buy karo)_"
            await update.message.reply_text(reply)
            return

        # ── GROUP ──
        if chat.type in ["group", "supergroup"]:
            register_group(chat.id)
            grp = get_group(chat.id)
            if not grp or not grp["is_active"]: return
            if not update.message.text: return

            bot_uname     = ctx.bot.username
            is_mentioned  = bool(bot_uname and f"@{bot_uname}" in update.message.text)
            is_reply      = (update.message.reply_to_message is not None and
                             update.message.reply_to_message.from_user is not None and
                             update.message.reply_to_message.from_user.id == ctx.bot.id)

            promo = increment_msg(chat.id)
            if promo:
                await update.message.reply_text(f"📢 {promo}"); return

            if is_mentioned or is_reply:
                txt = update.message.text.replace(f"@{bot_uname}", "").strip() if bot_uname else update.message.text

                async def status_fn(msg):
                    await update.message.reply_text(msg, parse_mode="Markdown")

                reply = await ask_shekha(txt, name, status_fn)
                await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"handle_message: {e}")

# ─────────────────────── MAIN ───────────────────────

def main():
    init_db()
    logger.info("🤖 Shekha starting...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("credits",     credits_cmd))
    app.add_handler(CommandHandler("buy",         buy_cmd))
    app.add_handler(CommandHandler("admin",       admin_cmd))
    app.add_handler(CommandHandler("payments",    payments_cmd))
    app.add_handler(CommandHandler("addcredits",  addcredits_cmd))
    app.add_handler(CommandHandler("on",          on_cmd))
    app.add_handler(CommandHandler("off",         off_cmd))
    app.add_handler(CommandHandler("setpromo",    setpromo_cmd))
    app.add_handler(CommandHandler("removepromo", removepromo_cmd))
    app.add_handler(CommandHandler("groups",      groups_cmd))
    app.add_handler(CommandHandler("users",       users_cmd))
    app.add_handler(CommandHandler("broadcast",   broadcast_cmd))
    app.add_handler(CommandHandler("forward",     forward_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    logger.info("🤖 Shekha is LIVE!")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
