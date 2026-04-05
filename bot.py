import sqlite3
import logging
import random
import asyncio
from datetime import datetime
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════
#                    CONFIG
# ═══════════════════════════════════════════════
BOT_TOKEN    = "8663479623:AAEcaM8MXa28bXqTBBh6y9AyH7PhtRHGUWA"
GROQ_API_KEY = "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"
ADMIN_PASS   = "2010"
DB_PATH      = "/tmp/shekha.db"
SUPPORT_USER = "@earn_karo_pls"
PAYMENT_UPI  = "richaryanbro@fam"
FREE_CREDITS = 10

REFER_REWARD_REFERRER = 5
REFER_REWARD_NEW_USER = 3

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
    "Ek sec... apna dimaag badal rahi hoon \U0001f9e0\u26a1",
    "Oops! Naya brain load ho raha hai \U0001f504\U0001f9e0",
    "Yeh wala kaam nahi kar raha, doosra try karti hoon \U0001f605",
    "Brain switching... \U0001f4ab",
    "Naya mode on kar rahi hoon \u2699\ufe0f\u2728",
    "Purana crash, naya install kar rahi hoon \U0001f602\U0001f527",
]

groq_client      = Groq(api_key=GROQ_API_KEY)
current_model_ix = 0

# ═══════════════════════════════════════════════
#                   DATABASE
# ═══════════════════════════════════════════════
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        telegram_id    INTEGER PRIMARY KEY,
        username       TEXT,
        full_name      TEXT,
        credits        INTEGER DEFAULT 10,
        last_reset     TEXT    DEFAULT '',
        extra_credits  INTEGER DEFAULT 0,
        refer_code     TEXT    UNIQUE,
        referred_by    INTEGER DEFAULT NULL,
        total_referred INTEGER DEFAULT 0,
        total_earned   INTEGER DEFAULT 0,
        joined_at      TEXT    DEFAULT ''
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
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER,
        direction  TEXT,
        content    TEXT,
        created_at TEXT
    )""")
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════
#                 USER HELPERS
# ═══════════════════════════════════════════════
def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def make_refer_code(tid):
    return f"REF{tid}"

def save_user(tid, uname, fname, referred_by=None):
    ref_code = make_refer_code(tid)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    existing = conn.execute("SELECT telegram_id FROM users WHERE telegram_id=?", (tid,)).fetchone()
    if not existing:
        conn.execute("""INSERT INTO users
            (telegram_id, username, full_name, credits, last_reset, extra_credits, refer_code, referred_by, joined_at)
            VALUES (?, ?, ?, 10, ?, 0, ?, ?, ?)""",
            (tid, uname, fname, today_str(), ref_code, referred_by, today_str()))
        conn.commit()
        if referred_by:
            conn.execute("UPDATE users SET extra_credits=extra_credits+?, total_referred=total_referred+1, total_earned=total_earned+? WHERE telegram_id=?",
                         (REFER_REWARD_REFERRER, REFER_REWARD_REFERRER, referred_by))
            conn.execute("UPDATE users SET extra_credits=extra_credits+?, total_earned=total_earned+? WHERE telegram_id=?",
                         (REFER_REWARD_NEW_USER, REFER_REWARD_NEW_USER, tid))
            conn.commit()
    else:
        conn.execute("UPDATE users SET username=?, full_name=? WHERE telegram_id=?", (uname, fname, tid))
        conn.commit()
    conn.close()

def reset_if_needed(tid):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT last_reset FROM users WHERE telegram_id=?", (tid,)).fetchone()
    if row and row["last_reset"] != today_str():
        conn.execute("UPDATE users SET credits=?, last_reset=? WHERE telegram_id=?",
                     (FREE_CREDITS, today_str(), tid))
        conn.commit()
    conn.close()

def get_credits(tid):
    reset_if_needed(tid)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT credits, extra_credits FROM users WHERE telegram_id=?", (tid,)).fetchone()
    conn.close()
    if not row: return 0
    return int(row["credits"] or 0) + int(row["extra_credits"] or 0)

def use_credit(tid):
    reset_if_needed(tid)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT credits, extra_credits FROM users WHERE telegram_id=?", (tid,)).fetchone()
    if not row: conn.close(); return False
    ec = int(row["extra_credits"] or 0)
    cr = int(row["credits"] or 0)
    if ec > 0:
        conn.execute("UPDATE users SET extra_credits=extra_credits-1 WHERE telegram_id=?", (tid,))
    elif cr > 0:
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

def get_user_info(tid):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (tid,)).fetchone()
    conn.close()
    return row

def is_admin(tid):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT 1 FROM admins WHERE telegram_id=?", (tid,)).fetchone()
    conn.close()
    return row is not None

def add_admin(tid):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (tid,))
    conn.commit(); conn.close()

def remove_admin(tid):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM admins WHERE telegram_id=?", (tid,))
    conn.commit(); conn.close()

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    total_users    = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_payments = conn.execute("SELECT COUNT(*) FROM payments WHERE status='approved'").fetchone()[0]
    total_revenue  = conn.execute("SELECT SUM(CAST(amount AS INTEGER)) FROM payments WHERE status='approved'").fetchone()[0] or 0
    pending_pay    = conn.execute("SELECT COUNT(*) FROM payments WHERE status='pending'").fetchone()[0]
    total_msgs     = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    return total_users, total_payments, total_revenue, pending_pay, total_msgs

def log_message(uid, direction, content):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO messages (user_id, direction, content, created_at) VALUES (?,?,?,?)",
                     (uid, direction, content[:500], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit(); conn.close()
    except: pass

def get_top_referrers(limit=10):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM users ORDER BY total_referred DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return rows

# ═══════════════════════════════════════════════
#                GROUP HELPERS
# ═══════════════════════════════════════════════
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
    conn.execute("UPDATE groups SET promo_text=?, promo_interval=?, message_count=0 WHERE chat_id=?",
                 (text, interval, chat_id))
    conn.commit(); conn.close()

def increment_msg(chat_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE groups SET message_count=message_count+1 WHERE chat_id=?", (chat_id,))
    row = conn.execute("SELECT message_count, promo_interval, promo_text FROM groups WHERE chat_id=?", (chat_id,)).fetchone()
    conn.commit(); conn.close()
    if row and row[1] and row[1] > 0 and row[0] >= row[1]:
        conn2 = sqlite3.connect(DB_PATH)
        conn2.execute("UPDATE groups SET message_count=0 WHERE chat_id=?", (chat_id,))
        conn2.commit(); conn2.close()
        return row[2]
    return None

# ═══════════════════════════════════════════════
#              PAYMENT HELPERS
# ═══════════════════════════════════════════════
def submit_payment(user_id, utr, amount, credits):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO payments (user_id, utr, amount, status, credits, created_at) VALUES (?,?,?,?,?,?)",
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

# ═══════════════════════════════════════════════
#                  GROQ AI
# ═══════════════════════════════════════════════
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
    return "Saare dimaag thak gaye! Thodi der baad try karo \U0001f634"

# ═══════════════════════════════════════════════
#                  KEYBOARDS
# ═══════════════════════════════════════════════
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001f4ac Chat with Shekha", callback_data="chat"),
         InlineKeyboardButton("\U0001f4ca My Credits", callback_data="credits")],
        [InlineKeyboardButton("\U0001f4b3 Buy Credits", callback_data="buy"),
         InlineKeyboardButton("\U0001f465 Refer & Earn", callback_data="refer")],
        [InlineKeyboardButton("\U0001f3c6 Leaderboard", callback_data="leaderboard"),
         InlineKeyboardButton("\u2753 Help", callback_data="help")],
        [InlineKeyboardButton("\U0001f4de Support", url=f"https://t.me/{SUPPORT_USER.lstrip('@')}")],
    ])

def buy_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\u2b50 50 Credits \u2014 \u20b910",   callback_data="pack_50_10"),
         InlineKeyboardButton("\u2b50 100 Credits \u2014 \u20b918",  callback_data="pack_100_18")],
        [InlineKeyboardButton("\U0001f48e 250 Credits \u2014 \u20b940",  callback_data="pack_250_40"),
         InlineKeyboardButton("\U0001f48e 500 Credits \u2014 \u20b975",  callback_data="pack_500_75")],
        [InlineKeyboardButton("\U0001f451 1000 Credits \u2014 \u20b9130", callback_data="pack_1000_130")],
        [InlineKeyboardButton("\U0001f519 Back", callback_data="back")],
    ])

def pay_admin_kb(pay_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("\u2705 Approve", callback_data=f"approve_{pay_id}"),
        InlineKeyboardButton("\u274c Reject",  callback_data=f"reject_{pay_id}"),
    ]])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f519 Back", callback_data="back")]])

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001f4b3 Payments",     callback_data="adm_payments"),
         InlineKeyboardButton("\U0001f4ca Stats",         callback_data="adm_stats")],
        [InlineKeyboardButton("\U0001f465 Users",         callback_data="adm_users"),
         InlineKeyboardButton("\U0001f4e2 Broadcast",     callback_data="adm_broadcast")],
        [InlineKeyboardButton("\U0001f3d9 Groups",        callback_data="adm_groups"),
         InlineKeyboardButton("\u2795 Add Credits",       callback_data="adm_addcredits")],
        [InlineKeyboardButton("\U0001f4e4 Forward Post",  callback_data="adm_forward"),
         InlineKeyboardButton("\U0001f4e3 Promo DM All",  callback_data="adm_promo_dm")],
    ])

# ═══════════════════════════════════════════════
#                    /start
# ═══════════════════════════════════════════════
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uid   = update.effective_user.id
        uname = update.effective_user.username or ""
        fname = update.effective_user.full_name or "User"
        name  = update.effective_user.first_name or "User"
        chat  = update.effective_chat

        referred_by = None
        if ctx.args:
            ref = ctx.args[0]
            if ref.startswith("REF"):
                try:
                    ref_uid = int(ref[3:])
                    if ref_uid != uid:
                        referred_by = ref_uid
                except: pass

        save_user(uid, uname, fname, referred_by)

        # Silently remove any old bottom keyboard
        try:
            tmp = await update.message.reply_text("\u200b", reply_markup=ReplyKeyboardRemove())
            await tmp.delete()
        except: pass

        if chat.type in ["group", "supergroup"]:
            register_group(chat.id)
            await update.message.reply_text(
                "Heyy! \U0001f44b Main Shekha hoon! Masti shuru karte hain! \U0001f604\U0001f525",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("\U0001f4ac Chat with me!", url=f"https://t.me/{ctx.bot.username}")
                ]])
            )
            return

        cr = get_credits(uid)

        if referred_by:
            await update.message.reply_text(
                f"\U0001f389 *Welcome bonus!* Tumhe *{REFER_REWARD_NEW_USER} extra credits* mile referral ke liye!",
                parse_mode="Markdown"
            )

        await update.message.reply_text(
            f"Heyy *{name}*! \U0001f60a\u2764\ufe0f Main *Shekha* hoon!\n\n"
            f"Tumse milke bahut khushi hui! \U0001f389\n\n"
            f"\U0001f4b0 *Credits:* {cr} available\n"
            f"\U0001f193 Free: {FREE_CREDITS} messages/day\n"
            f"\U0001f550 Midnight pe reset hota hai\n"
            f"\U0001f465 Refer karke aur credits kamao!\n"
            f"\U0001f4b3 Credits khatam? /buy se kharido!\n\n"
            f"Kya karna hai? \U0001f447",
            parse_mode="Markdown",
            reply_markup=main_kb()
        )
    except Exception as e:
        logger.error(f"start error: {e}")

# ═══════════════════════════════════════════════
#               COMMANDS
# ═══════════════════════════════════════════════
async def credits_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    reset_if_needed(uid)
    info = get_user_info(uid)
    if not info:
        await update.message.reply_text("Pehle /start karo!"); return
    total = int(info["credits"] or 0) + int(info["extra_credits"] or 0)
    await update.message.reply_text(
        f"\U0001f4ca *Tumhare Credits*\n\n"
        f"\U0001f193 Daily Credits: *{info['credits']}/{FREE_CREDITS}*\n"
        f"\U0001f48e Paid Credits: *{info['extra_credits']}*\n"
        f"\u2705 Total: *{total}*\n"
        f"\U0001f4c5 Last Reset: {info['last_reset']}\n"
        f"\U0001f465 Referred: *{info['total_referred']}* log\n"
        f"\U0001f381 Earned via Refer: *{info['total_earned']}* credits",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f4b3 Buy More", callback_data="buy"),
             InlineKeyboardButton("\U0001f465 Refer & Earn", callback_data="refer")],
            [InlineKeyboardButton("\U0001f519 Back", callback_data="back")]
        ])
    )

async def refer_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    info = get_user_info(uid)
    if not info:
        await update.message.reply_text("Pehle /start karo!"); return
    bot_username = ctx.bot.username
    ref_link = f"https://t.me/{bot_username}?start={make_refer_code(uid)}"
    await update.message.reply_text(
        f"\U0001f465 *Refer & Earn!*\n\n"
        f"Apna referral link share karo:\n`{ref_link}`\n\n"
        f"\U0001f381 *Reward:*\n"
        f"\u2022 Tumhe: *{REFER_REWARD_REFERRER} credits* per referral\n"
        f"\u2022 New user ko: *{REFER_REWARD_NEW_USER} credits* bonus\n\n"
        f"\U0001f4c8 *Tumhara Record:*\n"
        f"\u2022 Referred: *{info['total_referred']}* log\n"
        f"\u2022 Total Earned: *{info['total_earned']}* credits\n\n"
        f"Jitna refer, utna earn! \U0001f680",
        parse_mode="Markdown",
        reply_markup=back_kb()
    )

async def buy_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"\U0001f4b3 *Credits Kharido!*\n\nUPI ID: `{PAYMENT_UPI}`\n\nPack chuno \U0001f447",
        parse_mode="Markdown",
        reply_markup=buy_kb()
    )

async def leaderboard_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    top = get_top_referrers(10)
    txt = "\U0001f3c6 *Top Referrers*\n\n"
    medals = ["\U0001f947","\U0001f948","\U0001f949","4\ufe0f\u20e3","5\ufe0f\u20e3","6\ufe0f\u20e3","7\ufe0f\u20e3","8\ufe0f\u20e3","9\ufe0f\u20e3","\U0001f51f"]
    if not top:
        txt += "Abhi koi nahi! Tum pehle ban sakte ho \U0001f680"
    for i, u in enumerate(top):
        name = (u["username"] and f"@{u['username']}") or u["full_name"] or "Unknown"
        txt += f"{medals[i]} {name} \u2014 *{u['total_referred']}* refs ({u['total_earned']} credits)\n"
    await update.message.reply_text(txt, parse_mode="Markdown", reply_markup=back_kb())

async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid):
        await show_admin_panel(update, ctx); return
    await update.message.reply_text("\U0001f510 *Admin password bhejo:*", parse_mode="Markdown")
    ctx.user_data["waiting_admin_pass"] = True

async def show_admin_panel(update, ctx):
    tu, tp, tr, pp, tm = get_stats()
    msg_obj = update.message if update.message else None
    if not msg_obj and update.callback_query:
        msg_obj = update.callback_query.message
    if not msg_obj: return
    await msg_obj.reply_text(
        f"\U0001f6e1\ufe0f *Admin Panel*\n\n"
        f"\U0001f465 Total Users: *{tu}*\n"
        f"\U0001f4ac Total Messages: *{tm}*\n"
        f"\u2705 Approved Payments: *{tp}*\n"
        f"\u23f3 Pending Payments: *{pp}*\n"
        f"\U0001f4b0 Total Revenue: *\u20b9{tr}*\n\n"
        f"Kya karna hai? \U0001f447",
        parse_mode="Markdown",
        reply_markup=admin_kb()
    )

async def payments_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    pending = get_pending_payments()
    if not pending:
        await update.message.reply_text("\u2705 No pending payments!"); return
    for p in pending:
        try:
            u = await ctx.bot.get_chat(p["user_id"])
            who = f"@{u.username}" if u.username else u.full_name
        except:
            who = str(p["user_id"])
        await update.message.reply_text(
            f"\U0001f4b3 *Payment #{p['id']}*\n\n"
            f"\U0001f464 {who} (`{p['user_id']}`)\n"
            f"\U0001f4b0 \u20b9{p['amount']} \u2192 {p['credits']} credits\n"
            f"\U0001f522 UTR: `{p['utr']}`\n"
            f"\U0001f4c5 {p['created_at']}",
            parse_mode="Markdown",
            reply_markup=pay_admin_kb(p["id"])
        )

async def addcredits_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        uid = int(ctx.args[0]); amt = int(ctx.args[1])
        add_credits(uid, amt)
        await update.message.reply_text(f"\u2705 *{amt} credits* added to `{uid}`!", parse_mode="Markdown")
        try:
            await ctx.bot.send_message(uid, f"\U0001f381 *Admin ne tumhe {amt} credits diye!* \U0001f389", parse_mode="Markdown")
        except: pass
    except:
        await update.message.reply_text("Usage: /addcredits <user_id> <amount>")

async def removeadmin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        tid = int(ctx.args[0])
        remove_admin(tid)
        await update.message.reply_text(f"\u2705 `{tid}` admin se remove!", parse_mode="Markdown")
    except:
        await update.message.reply_text("Usage: /removeadmin <user_id>")

async def on_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        cid = int(ctx.args[0]); set_group_active(cid, 1)
        await update.message.reply_text(f"\u2705 Group `{cid}` ON!", parse_mode="Markdown")
    except:
        await update.message.reply_text("Usage: /on <group_id>")

async def off_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        cid = int(ctx.args[0]); set_group_active(cid, 0)
        await update.message.reply_text(f"\u2705 Group `{cid}` OFF!", parse_mode="Markdown")
    except:
        await update.message.reply_text("Usage: /off <group_id>")

async def setpromo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        parts = update.message.text.split("|", 2)
        cid = int(parts[0].split()[-1]); interval = int(parts[1]); text = parts[2].strip()
        set_promo(cid, text, interval)
        await update.message.reply_text("\u2705 Promo set!", parse_mode="Markdown")
    except:
        await update.message.reply_text("Usage: /setpromo <group_id>|<interval>|<text>")

async def removepromo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        cid = int(ctx.args[0]); set_promo(cid, None, 0)
        await update.message.reply_text(f"\u2705 Promo removed!", parse_mode="Markdown")
    except:
        await update.message.reply_text("Usage: /removepromo <group_id>")

async def groups_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    groups = conn.execute("SELECT * FROM groups").fetchall()
    conn.close()
    if not groups:
        await update.message.reply_text("No groups registered."); return
    txt = "\U0001f3d9 *Registered Groups*\n\n"
    for g in groups:
        status = "\u2705 ON" if g["is_active"] else "\u274c OFF"
        txt += f"`{g['chat_id']}` \u2014 {status}\n"
        txt += f"Promo har {g['promo_interval']} msgs\n" if g["promo_interval"] else "No promo\n"
    await update.message.reply_text(txt, parse_mode="Markdown")

async def users_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text(f"\U0001f464 Total Users: *{len(get_all_users())}*", parse_mode="Markdown")

async def broadcast_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    msg = update.message.text.replace("/broadcast", "").strip()
    if not msg:
        await update.message.reply_text("Usage: /broadcast <msg>"); return
    sent = failed = 0
    for uid in get_all_users():
        try:
            await ctx.bot.send_message(uid, f"\U0001f4e2 *Announcement*\n\n{msg}", parse_mode="Markdown")
            sent += 1
        except: failed += 1
    await update.message.reply_text(f"\u2705 Sent: *{sent}*\n\u274c Failed: *{failed}*", parse_mode="Markdown")

async def forward_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    ctx.user_data["waiting_forward"] = True
    await update.message.reply_text("\U0001f4e4 Next message sabko forward ho jayega!")

async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    tu, tp, tr, pp, tm = get_stats()
    await update.message.reply_text(
        f"\U0001f4ca *Bot Statistics*\n\n"
        f"\U0001f465 Total Users: *{tu}*\n"
        f"\U0001f4ac Total Messages: *{tm}*\n"
        f"\u2705 Approved Payments: *{tp}*\n"
        f"\u23f3 Pending Payments: *{pp}*\n"
        f"\U0001f4b0 Total Revenue: *\u20b9{tr}*",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════
#              CALLBACK BUTTONS
# ═══════════════════════════════════════════════
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    uid  = q.from_user.id
    data = q.data

    if data == "chat":
        await q.edit_message_text(
            "\U0001f4ac Bas message bhejo! Main ready hoon \U0001f60a\n_(/credits se balance check karo)_",
            parse_mode="Markdown", reply_markup=back_kb())

    elif data == "credits":
        reset_if_needed(uid)
        info = get_user_info(uid)
        if not info: await q.edit_message_text("Pehle /start karo!"); return
        total = int(info["credits"] or 0) + int(info["extra_credits"] or 0)
        await q.edit_message_text(
            f"\U0001f4ca *Tumhare Credits*\n\n"
            f"\U0001f193 Daily: *{info['credits']}/{FREE_CREDITS}*\n"
            f"\U0001f48e Paid: *{info['extra_credits']}*\n"
            f"\u2705 Total: *{total}*\n"
            f"\U0001f465 Referred: *{info['total_referred']}* log\n"
            f"\U0001f381 Earned via Refer: *{info['total_earned']}* credits",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f4b3 Buy More", callback_data="buy"),
                 InlineKeyboardButton("\U0001f465 Refer & Earn", callback_data="refer")],
                [InlineKeyboardButton("\U0001f519 Back", callback_data="back")]
            ])
        )

    elif data == "buy":
        await q.edit_message_text(
            f"\U0001f4b3 *Credits Kharido!*\n\nUPI ID: `{PAYMENT_UPI}`\n\nPack chuno \U0001f447\n_(Pay \u2192 UTR bhejo \u2192 Credits turant!)_",
            parse_mode="Markdown", reply_markup=buy_kb())

    elif data == "refer":
        bot_username = ctx.bot.username
        ref_link = f"https://t.me/{bot_username}?start={make_refer_code(uid)}"
        info = get_user_info(uid)
        await q.edit_message_text(
            f"\U0001f465 *Refer & Earn!*\n\nLink:\n`{ref_link}`\n\n"
            f"\U0001f381 Tumhe: *{REFER_REWARD_REFERRER} credits* per refer\n"
            f"\U0001f381 New user: *{REFER_REWARD_NEW_USER} credits* bonus\n\n"
            f"\U0001f4c8 Referred: *{info['total_referred']}* | Earned: *{info['total_earned']}* credits",
            parse_mode="Markdown", reply_markup=back_kb())

    elif data == "leaderboard":
        top = get_top_referrers(10)
        txt = "\U0001f3c6 *Top Referrers*\n\n"
        medals = ["\U0001f947","\U0001f948","\U0001f949","4\ufe0f\u20e3","5\ufe0f\u20e3","6\ufe0f\u20e3","7\ufe0f\u20e3","8\ufe0f\u20e3","9\ufe0f\u20e3","\U0001f51f"]
        if not top:
            txt += "Abhi koi nahi! Tum pehle ban sakte ho \U0001f680"
        for i, u in enumerate(top):
            name = (u["username"] and f"@{u['username']}") or u["full_name"] or "Unknown"
            txt += f"{medals[i]} {name} \u2014 *{u['total_referred']}* refs\n"
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=back_kb())

    elif data == "help":
        await q.edit_message_text(
            f"\u2753 *Help & Commands*\n\n"
            f"/start \u2014 Bot shuru karo\n"
            f"/credits \u2014 Balance dekho\n"
            f"/buy \u2014 Credits kharido\n"
            f"/refer \u2014 Refer karke kamao\n"
            f"/leaderboard \u2014 Top referrers\n\n"
            f"\U0001f4a1 Har din {FREE_CREDITS} free credits!\n"
            f"\U0001f550 Midnight pe reset hota hai\n"
            f"\U0001f465 Refer karo, credits kamao!\n"
            f"\U0001f4b3 Zyada chahiye? Buy karo!\n\n"
            f"Support: {SUPPORT_USER}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f4de Support", url=f"https://t.me/{SUPPORT_USER.lstrip('@')}")],
                [InlineKeyboardButton("\U0001f519 Back", callback_data="back")]
            ]))

    elif data == "back":
        cr = get_credits(uid)
        name = q.from_user.first_name or "User"
        await q.edit_message_text(
            f"Heyy *{name}*! \U0001f60a\u2764\ufe0f Main *Shekha* hoon!\n\n\U0001f4b0 *Credits:* {cr}\nKya karna hai? \U0001f447",
            parse_mode="Markdown", reply_markup=main_kb())

    elif data.startswith("pack_"):
        parts = data.split("_")
        credits = int(parts[1]); amount = int(parts[2])
        ctx.user_data["waiting_utr"] = True
        ctx.user_data["pending_buy"] = {"credits": credits, "amount": str(amount)}
        await q.edit_message_text(
            f"\U0001f4b3 *Payment Details*\n\n"
            f"Pack: *{credits} Credits \u2014 \u20b9{amount}*\n\n"
            f"UPI: `{PAYMENT_UPI}`\n\n"
            f"1\ufe0f\u20e3 Pay karo \u20b9{amount}\n"
            f"2\ufe0f\u20e3 UTR/Transaction ID bhejo \U0001f447",
            parse_mode="Markdown", reply_markup=back_kb())

    # ── Admin callbacks ──────────────────────────
    elif data == "adm_payments":
        if not is_admin(uid): return
        pending = get_pending_payments()
        await q.edit_message_text(
            f"\U0001f4b3 *{len(pending)} Pending Payments*\n\n/payments se full list dekho.",
            parse_mode="Markdown", reply_markup=admin_kb())

    elif data == "adm_stats":
        if not is_admin(uid): return
        tu, tp, tr, pp, tm = get_stats()
        await q.edit_message_text(
            f"\U0001f4ca *Stats*\n\n\U0001f465 Users: *{tu}*\n\U0001f4ac Messages: *{tm}*\n\u2705 Payments: *{tp}*\n\u23f3 Pending: *{pp}*\n\U0001f4b0 Revenue: *\u20b9{tr}*",
            parse_mode="Markdown", reply_markup=admin_kb())

    elif data == "adm_users":
        if not is_admin(uid): return
        await q.edit_message_text(
            f"\U0001f464 Total Users: *{len(get_all_users())}*",
            parse_mode="Markdown", reply_markup=admin_kb())

    elif data == "adm_broadcast":
        if not is_admin(uid): return
        ctx.user_data["waiting_broadcast"] = True
        await q.edit_message_text("\U0001f4e2 Broadcast message type karo:", reply_markup=back_kb())

    elif data == "adm_promo_dm":
        if not is_admin(uid): return
        ctx.user_data["waiting_promo_dm"] = True
        await q.edit_message_text(
            "\U0001f4e3 *Promo DM*\n\nEk message type karo \u2014 sab users ko private DM ho jayega!\n\nMessage bhejo \U0001f447",
            parse_mode="Markdown", reply_markup=back_kb())

    elif data == "adm_groups":
        if not is_admin(uid): return
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        groups = conn.execute("SELECT * FROM groups").fetchall()
        conn.close()
        txt = "\U0001f3d9 *Groups*\n\n"
        for g in groups:
            status = "\u2705 ON" if g["is_active"] else "\u274c OFF"
            txt += f"`{g['chat_id']}` \u2014 {status}\n"
        await q.edit_message_text(txt or "No groups.", parse_mode="Markdown", reply_markup=admin_kb())

    elif data == "adm_addcredits":
        if not is_admin(uid): return
        ctx.user_data["waiting_addcredits"] = True
        await q.edit_message_text(
            "\u2795 Type: `<user_id> <amount>`\nExample: `123456789 50`",
            parse_mode="Markdown", reply_markup=back_kb())

    elif data == "adm_forward":
        if not is_admin(uid): return
        ctx.user_data["waiting_forward"] = True
        await q.edit_message_text("\U0001f4e4 Next message sabko forward ho jayega!", reply_markup=back_kb())

    elif data.startswith("approve_"):
        if not is_admin(uid): return
        pay_id = int(data.split("_")[1])
        pay = get_payment(pay_id)
        if not pay or pay["status"] != "pending":
            await q.edit_message_text("\u26a0\ufe0f Already processed!"); return
        update_payment(pay_id, "approved")
        add_credits(pay["user_id"], pay["credits"])
        await q.edit_message_text(
            f"\u2705 *Payment #{pay_id} Approved!*\nUser: `{pay['user_id']}`\nCredits: *{pay['credits']}*",
            parse_mode="Markdown")
        try:
            await ctx.bot.send_message(
                pay["user_id"],
                f"\U0001f389 *Payment approved!*\n*{pay['credits']} credits* add ho gaye! Enjoy! \U0001f680",
                parse_mode="Markdown")
        except: pass

    elif data.startswith("reject_"):
        if not is_admin(uid): return
        pay_id = int(data.split("_")[1])
        pay = get_payment(pay_id)
        if not pay or pay["status"] != "pending":
            await q.edit_message_text("\u26a0\ufe0f Already processed!"); return
        update_payment(pay_id, "rejected")
        await q.edit_message_text(f"\u274c *Payment #{pay_id} Rejected!*", parse_mode="Markdown")
        try:
            await ctx.bot.send_message(
                pay["user_id"],
                f"\u274c *Payment reject hua!*\nUTR: `{pay['utr']}`\nSupport: {SUPPORT_USER}",
                parse_mode="Markdown")
        except: pass

# ═══════════════════════════════════════════════
#            MESSAGE HANDLER
# ═══════════════════════════════════════════════
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message: return
        uid   = update.effective_user.id
        chat  = update.effective_chat
        uname = update.effective_user.username or ""
        fname = update.effective_user.full_name or "User"
        name  = update.effective_user.first_name or "User"
        save_user(uid, uname, fname)

        if chat.type == "private":

            # Admin password
            if ctx.user_data.get("waiting_admin_pass"):
                if update.message.text and update.message.text.strip() == ADMIN_PASS:
                    add_admin(uid)
                    ctx.user_data["waiting_admin_pass"] = False
                    await update.message.reply_text("\u2705 *Admin ban gaye!*", parse_mode="Markdown")
                    await show_admin_panel(update, ctx)
                else:
                    ctx.user_data["waiting_admin_pass"] = False
                    await update.message.reply_text("\u274c Wrong password!")
                return

            # Broadcast input
            if ctx.user_data.get("waiting_broadcast") and update.message.text:
                ctx.user_data["waiting_broadcast"] = False
                msg = update.message.text.strip()
                sent = failed = 0
                for user_id in get_all_users():
                    try:
                        await ctx.bot.send_message(user_id, f"\U0001f4e2 *Announcement*\n\n{msg}", parse_mode="Markdown")
                        sent += 1
                    except: failed += 1
                await update.message.reply_text(f"\u2705 Sent: *{sent}*\n\u274c Failed: *{failed}*", parse_mode="Markdown")
                return

            # Promo DM to all users
            if ctx.user_data.get("waiting_promo_dm") and update.message.text:
                ctx.user_data["waiting_promo_dm"] = False
                msg = update.message.text.strip()
                sent = failed = 0
                for user_id in get_all_users():
                    try:
                        await ctx.bot.send_message(
                            user_id,
                            f"\U0001f4e3 *Special Message!*\n\n{msg}\n\nSupport: {SUPPORT_USER}",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("\U0001f4de Contact", url=f"https://t.me/{SUPPORT_USER.lstrip('@')}")
                            ]])
                        )
                        sent += 1
                    except: failed += 1
                await update.message.reply_text(f"\u2705 Promo sent: *{sent}*\n\u274c Failed: *{failed}*", parse_mode="Markdown")
                return

            # Add credits input
            if ctx.user_data.get("waiting_addcredits") and update.message.text:
                ctx.user_data["waiting_addcredits"] = False
                try:
                    parts = update.message.text.strip().split()
                    tid = int(parts[0]); amt = int(parts[1])
                    add_credits(tid, amt)
                    await update.message.reply_text(f"\u2705 *{amt} credits* added to `{tid}`!", parse_mode="Markdown")
                    try:
                        await ctx.bot.send_message(tid, f"\U0001f381 *Admin ne tumhe {amt} credits diye!* \U0001f389", parse_mode="Markdown")
                    except: pass
                except:
                    await update.message.reply_text("\u274c Format: `<user_id> <amount>`", parse_mode="Markdown")
                return

            # Forward mode
            if ctx.user_data.get("waiting_forward"):
                ctx.user_data["waiting_forward"] = False
                sent = failed = 0
                for user_id in get_all_users():
                    try: await update.message.forward(chat_id=user_id); sent += 1
                    except: failed += 1
                await update.message.reply_text(f"\u2705 Forwarded: *{sent}*\n\u274c Failed: *{failed}*", parse_mode="Markdown")
                return

            # UTR submission
            if ctx.user_data.get("waiting_utr") and update.message.text:
                utr = update.message.text.strip()
                buy = ctx.user_data.get("pending_buy", {})
                cred = buy.get("credits", 0); amt = buy.get("amount", "?")
                if cred > 0:
                    submit_payment(uid, utr, amt, cred)
                    ctx.user_data["waiting_utr"] = False
                    ctx.user_data["pending_buy"] = {}
                    conn = sqlite3.connect(DB_PATH)
                    pay = conn.execute("SELECT id FROM payments WHERE user_id=? AND utr=? ORDER BY id DESC LIMIT 1",
                                       (uid, utr)).fetchone()
                    conn.close()
                    pay_id = pay[0] if pay else 0
                    conn2 = sqlite3.connect(DB_PATH)
                    admins = conn2.execute("SELECT telegram_id FROM admins").fetchall()
                    conn2.close()
                    who = f"@{uname}" if uname else fname
                    for adm in admins:
                        try:
                            await ctx.bot.send_message(
                                adm[0],
                                f"\U0001f4b3 *New Payment!*\n\n"
                                f"\U0001f464 {who} (`{uid}`)\n"
                                f"\U0001f4b0 \u20b9{amt} \u2192 {cred} credits\n"
                                f"\U0001f522 UTR: `{utr}`\n"
                                f"\U0001f4c5 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                                parse_mode="Markdown",
                                reply_markup=pay_admin_kb(pay_id))
                        except: pass
                    await update.message.reply_text(
                        f"\u2705 *Payment submitted!*\n\nUTR: `{utr}`\nCredits: *{cred}*\n\nAdmin verify karega soon! \U0001f64f",
                        parse_mode="Markdown")
                else:
                    ctx.user_data["waiting_utr"] = False
                    await update.message.reply_text("\u274c Kuch galat hua! /buy se try karo.")
                return

            if not update.message.text:
                await update.message.reply_text("Text mein likho na yaar! \U0001f604"); return

            cr = get_credits(uid)
            if cr <= 0:
                await update.message.reply_text(
                    f"\u274c *Credits khatam!*\n\n"
                    f"\U0001f504 Midnight pe {FREE_CREDITS} free milenge.\n"
                    f"\U0001f4b3 /buy karo\n"
                    f"\U0001f465 /refer karo \u2014 free credits!\n\n"
                    f"Help: {SUPPORT_USER}",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("\U0001f4b3 Buy Credits", callback_data="buy"),
                         InlineKeyboardButton("\U0001f465 Refer & Earn", callback_data="refer")],
                        [InlineKeyboardButton("\U0001f4de Support", url=f"https://t.me/{SUPPORT_USER.lstrip('@')}")]
                    ])
                ); return

            use_credit(uid)
            remaining = get_credits(uid)
            log_message(uid, "user", update.message.text)

            async def status_fn(msg):
                await update.message.reply_text(msg, parse_mode="Markdown")

            reply = await ask_shekha(update.message.text, name, status_fn)
            log_message(uid, "bot", reply)

            if remaining <= 2:
                reply += f"\n\n_(\u26a0\ufe0f Sirf {remaining} credits bache! /buy ya /refer karo!)_"

            await update.message.reply_text(reply)
            return

        # ── GROUP ────────────────────────────────────
        if chat.type in ["group", "supergroup"]:
            register_group(chat.id)
            grp = get_group(chat.id)
            if not grp or not grp["is_active"]: return
            if not update.message.text: return

            bot_uname    = ctx.bot.username
            is_mentioned = bool(bot_uname and f"@{bot_uname}" in update.message.text)
            is_reply     = (update.message.reply_to_message is not None and
                            update.message.reply_to_message.from_user is not None and
                            update.message.reply_to_message.from_user.id == ctx.bot.id)

            promo = increment_msg(chat.id)
            if promo:
                await update.message.reply_text(f"\U0001f4e2 {promo}"); return

            if is_mentioned or is_reply:
                txt = update.message.text.replace(f"@{bot_uname}", "").strip() if bot_uname else update.message.text
                async def status_fn(msg):
                    await update.message.reply_text(msg, parse_mode="Markdown")
                reply = await ask_shekha(txt, name, status_fn)
                await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"handle_message error: {e}")

# ═══════════════════════════════════════════════
#                    MAIN
# ═══════════════════════════════════════════════
def main():
    init_db()
    logger.info("\U0001f916 Shekha Bot starting...")
    app = Application.builder().token(BOT_TOKEN).build()

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error(f"Exception while handling update: {context.error}", exc_info=context.error)

    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("credits",     credits_cmd))
    app.add_handler(CommandHandler("buy",         buy_cmd))
    app.add_handler(CommandHandler("refer",       refer_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    app.add_handler(CommandHandler("admin",       admin_cmd))
    app.add_handler(CommandHandler("payments",    payments_cmd))
    app.add_handler(CommandHandler("addcredits",  addcredits_cmd))
    app.add_handler(CommandHandler("removeadmin", removeadmin_cmd))
    app.add_handler(CommandHandler("on",          on_cmd))
    app.add_handler(CommandHandler("off",         off_cmd))
    app.add_handler(CommandHandler("setpromo",    setpromo_cmd))
    app.add_handler(CommandHandler("removepromo", removepromo_cmd))
    app.add_handler(CommandHandler("groups",      groups_cmd))
    app.add_handler(CommandHandler("users",       users_cmd))
    app.add_handler(CommandHandler("broadcast",   broadcast_cmd))
    app.add_handler(CommandHandler("forward",     forward_cmd))
    app.add_handler(CommandHandler("stats",       stats_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("\U0001f916 Shekha Bot is running!")
    app.run_polling()

if __name__ == "__main__":
    main()
