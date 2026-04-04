import os
import sqlite3
import random
import string
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

BOT_TOKEN = os.environ.get("8663479623:AAEmBgQ8cxNymOqxSflOxjypnhFxOd_u8NE")
ADMIN_IDS = [8338072770]
ADMIN_PASS = "2010"
MIN_WITHDRAW = 1000
MAX_DAILY_CLAIM = 10
REFERRAL_BONUS = 2

(WITHDRAW_METHOD, WITHDRAW_UPI, WITHDRAW_BANK_NAME, WITHDRAW_ACC,
 WITHDRAW_IFSC, WITHDRAW_HOLDER, ADMIN_LOGIN, ADMIN_MENU,
 ADMIN_BONUS_CODE, ADMIN_BONUS_AMT, ADMIN_BONUS_USES,
 ADMIN_BROADCAST, ADMIN_PAY_ID, ADMIN_PAY_AMT, ADMIN_REJECT_ID,
 ADMIN_REJECT_NOTE, BONUS_CLAIM) = range(17)

DB_PATH = "earnbot.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE NOT NULL,
        username TEXT,
        full_name TEXT,
        balance REAL DEFAULT 0,
        total_earned REAL DEFAULT 0,
        referral_code TEXT UNIQUE NOT NULL,
        referred_by INTEGER DEFAULT NULL,
        last_claim TEXT DEFAULT NULL,
        joined_at TEXT DEFAULT (datetime('now')),
        is_banned INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        claimed_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS referral_earnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER NOT NULL,
        referred_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        earned_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS bonus_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        amount REAL NOT NULL,
        max_uses INTEGER DEFAULT 1,
        used_count INTEGER DEFAULT 0,
        expires_at TEXT DEFAULT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        is_active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS bonus_redemptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER NOT NULL,
        code TEXT NOT NULL,
        amount REAL NOT NULL,
        redeemed_at TEXT DEFAULT (datetime('now')),
        UNIQUE(telegram_id, code)
    );
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER NOT NULL,
        full_name TEXT,
        amount REAL NOT NULL,
        method TEXT NOT NULL,
        upi_id TEXT DEFAULT NULL,
        bank_name TEXT DEFAULT NULL,
        account_number TEXT DEFAULT NULL,
        ifsc_code TEXT DEFAULT NULL,
        account_holder TEXT DEFAULT NULL,
        status TEXT DEFAULT 'pending',
        admin_note TEXT DEFAULT NULL,
        requested_at TEXT DEFAULT (datetime('now')),
        processed_at TEXT DEFAULT NULL
    );
    """)
    conn.commit()
    conn.close()

def make_ref_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def get_or_create_user(telegram_id, username, full_name, ref_code=None):
    conn = get_db()
    c = conn.cursor()
    user = c.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not user:
        code = make_ref_code()
        while c.execute("SELECT id FROM users WHERE referral_code=?", (code,)).fetchone():
            code = make_ref_code()
        referred_by = None
        if ref_code:
            referrer = c.execute("SELECT telegram_id FROM users WHERE referral_code=?", (ref_code,)).fetchone()
            if referrer and referrer["telegram_id"] != telegram_id:
                referred_by = referrer["telegram_id"]
        c.execute("""INSERT INTO users (telegram_id, username, full_name, referral_code, referred_by)
                     VALUES (?, ?, ?, ?, ?)""", (telegram_id, username, full_name, code, referred_by))
        conn.commit()
        user = c.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    return user

def get_user(telegram_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    return user

def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["💰 Claim Daily", "👛 My Wallet"],
        ["👥 Refer & Earn", "🎁 Bonus Code"],
        ["💸 Withdraw", "📊 Leaderboard"],
        ["ℹ️ Help"]
    ], resize_keyboard=True)

def admin_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Pending Withdrawals", callback_data="adm_pending")],
        [InlineKeyboardButton("🎁 Create Bonus Code", callback_data="adm_create_bonus")],
        [InlineKeyboardButton("📢 Broadcast Message", callback_data="adm_broadcast")],
        [InlineKeyboardButton("📊 Bot Statistics", callback_data="adm_stats")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban"),
         InlineKeyboardButton("✅ Unban User", callback_data="adm_unban")],
        [InlineKeyboardButton("❌ Close Panel", callback_data="adm_close")]
    ])

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or ""
    fname = update.effective_user.full_name or "User"
    ref_code = ctx.args[0] if ctx.args else None
    user = get_or_create_user(uid, uname, fname, ref_code)

    conn = get_db()
    if ref_code and user["referred_by"]:
        already = conn.execute("SELECT id FROM referral_earnings WHERE referred_id=?", (uid,)).fetchone()
        if not already:
            conn.execute("UPDATE users SET balance=balance+?, total_earned=total_earned+? WHERE telegram_id=?",
                         (REFERRAL_BONUS, REFERRAL_BONUS, user["referred_by"]))
            conn.execute("INSERT INTO referral_earnings (referrer_id, referred_id, amount) VALUES (?,?,?)",
                         (user["referred_by"], uid, REFERRAL_BONUS))
            conn.commit()
            try:
                await ctx.bot.send_message(
                    chat_id=user["referred_by"],
                    text=f"🎉 *New Referral Bonus!*\n\n"
                         f"👤 *{fname}* joined using your link!\n"
                         f"💰 You earned *₹{REFERRAL_BONUS}* bonus! 🚀\n\n"
                         f"Keep sharing to earn more! 💪",
                    parse_mode="Markdown"
                )
            except:
                pass
    conn.close()

    await update.message.reply_text(
        f"🌟 *Welcome to Daily Earn Bot!* 🌟\n\n"
        f"Namaste *{fname}*! 👋\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 Earn up to *₹{MAX_DAILY_CLAIM} daily* by claiming!\n"
        f"👥 Refer friends & earn *₹{REFERRAL_BONUS}* per referral!\n"
        f"🎁 Redeem *bonus codes* for extra cash!\n"
        f"💸 Withdraw via *UPI or Bank* (min ₹{MIN_WITHDRAW})\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"👇 Use the menu below to get started!",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

async def daily_claim(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ Please send /start first!")
        return
    if user["is_banned"]:
        await update.message.reply_text("🚫 You are banned from this bot.")
        return

    now = datetime.utcnow()
    if user["last_claim"]:
        last = datetime.fromisoformat(user["last_claim"])
        next_claim = last + timedelta(hours=24)
        if now < next_claim:
            remaining = next_claim - now
            hrs = int(remaining.total_seconds() // 3600)
            mins = int((remaining.total_seconds() % 3600) // 60)
            await update.message.reply_text(
                f"⏳ *Already Claimed Today!*\n\n"
                f"🕐 Next claim available in:\n"
                f"*{hrs} hours {mins} minutes*\n\n"
                f"💡 Tip: Refer friends to earn more! 👥\n"
                f"🎁 Check for bonus codes too!",
                parse_mode="Markdown"
            )
            return

    amount = round(random.uniform(1, MAX_DAILY_CLAIM), 2)
    conn = get_db()
    conn.execute("UPDATE users SET balance=balance+?, total_earned=total_earned+?, last_claim=? WHERE telegram_id=?",
                 (amount, amount, now.isoformat(), uid))
    conn.execute("INSERT INTO claims (telegram_id, amount) VALUES (?,?)", (uid, amount))
    conn.commit()
    conn.close()

    user = get_user(uid)
    await update.message.reply_text(
        f"🎉 *Daily Claim Successful!* 🎉\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 Earned Today: *₹{amount}*\n"
        f"👛 Total Balance: *₹{user['balance']:.2f}*\n"
        f"📈 Total Earned: *₹{user['total_earned']:.2f}*\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"⏰ Come back in 24 hours to claim again!\n"
        f"👥 Refer friends to earn faster! 🚀",
        parse_mode="Markdown"
    )

async def my_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ Please send /start first!")
        return

    conn = get_db()
    total_refs = conn.execute("SELECT COUNT(*) as c FROM referral_earnings WHERE referrer_id=?", (uid,)).fetchone()["c"]
    pending_w = conn.execute("SELECT COUNT(*) as c FROM withdrawals WHERE telegram_id=? AND status='pending'", (uid,)).fetchone()["c"]
    approved_w = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM withdrawals WHERE telegram_id=? AND status='approved'", (uid,)).fetchone()["s"]
    conn.close()

    next_claim_txt = "✅ Available Now!"
    if user["last_claim"]:
        last = datetime.fromisoformat(user["last_claim"])
        next_claim = last + timedelta(hours=24)
        now = datetime.utcnow()
        if now < next_claim:
            remaining = next_claim - now
            hrs = int(remaining.total_seconds() // 3600)
            mins = int((remaining.total_seconds() % 3600) // 60)
            next_claim_txt = f"⏳ {hrs}h {mins}m remaining"

    await update.message.reply_text(
        f"👛 *My Wallet*\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 Balance: *₹{user['balance']:.2f}*\n"
        f"📈 Total Earned: *₹{user['total_earned']:.2f}*\n"
        f"✅ Total Withdrawn: *₹{approved_w:.2f}*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👥 Referrals: *{total_refs}*\n"
        f"⏳ Pending Withdrawal: *{pending_w}*\n"
        f"⏰ Next Claim: *{next_claim_txt}*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💸 Min Withdrawal: *₹{MIN_WITHDRAW}*\n\n"
        f"🔑 Referral Code: `{user['referral_code']}`",
        parse_mode="Markdown"
    )

async def refer_earn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ Please send /start first!")
        return

    conn = get_db()
    refs = conn.execute("SELECT COUNT(*) as c FROM referral_earnings WHERE referrer_id=?", (uid,)).fetchone()["c"]
    ref_total = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM referral_earnings WHERE referrer_id=?", (uid,)).fetchone()["s"]
    conn.close()

    bot_username = (await ctx.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user['referral_code']}"

    await update.message.reply_text(
        f"👥 *Refer & Earn Program* 👥\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🎁 Earn *₹{REFERRAL_BONUS}* for every friend who joins!\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"📊 *Your Referral Stats:*\n"
        f"👤 Total Referrals: *{refs}*\n"
        f"💵 Referral Earnings: *₹{ref_total:.2f}*\n\n"
        f"🔗 *Your Referral Link:*\n`{ref_link}`\n\n"
        f"📤 Share with friends and earn when they join! 🚀",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📤 Share My Link", url=f"https://t.me/share/url?url={ref_link}&text=🤑%20Join%20Daily%20Earn%20Bot%20and%20earn%20daily%20₹10!%20Use%20my%20link%20to%20join%20now!")
        ]])
    )

async def bonus_code_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ Please send /start first!")
        return
    if user["is_banned"]:
        await update.message.reply_text("🚫 You are banned.")
        return
    await update.message.reply_text(
        "🎁 *Bonus Code Redemption*\n\n"
        "Enter your bonus code below 👇\n\n"
        "_(Type /cancel to go back)_",
        parse_mode="Markdown"
    )
    return BONUS_CLAIM

async def bonus_code_redeem(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    code = update.message.text.strip().upper()
    if code == "/CANCEL":
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    conn = get_db()
    bonus = conn.execute("SELECT * FROM bonus_codes WHERE code=? AND is_active=1", (code,)).fetchone()

    if not bonus:
        conn.close()
        await update.message.reply_text(
            "❌ *Invalid or expired bonus code!*\n\nTry again or type /cancel.",
            parse_mode="Markdown"
        )
        return BONUS_CLAIM

    if bonus["expires_at"] and datetime.utcnow() > datetime.fromisoformat(bonus["expires_at"]):
        conn.execute("UPDATE bonus_codes SET is_active=0 WHERE code=?", (code,))
        conn.commit()
        conn.close()
        await update.message.reply_text("⌛ *This bonus code has expired!*", parse_mode="Markdown")
        return ConversationHandler.END

    if bonus["used_count"] >= bonus["max_uses"]:
        conn.close()
        await update.message.reply_text("😔 *This bonus code is fully used!*", parse_mode="Markdown")
        return ConversationHandler.END

    already = conn.execute("SELECT id FROM bonus_redemptions WHERE telegram_id=? AND code=?", (uid, code)).fetchone()
    if already:
        conn.close()
        await update.message.reply_text("⚠️ *You already redeemed this code!*", parse_mode="Markdown")
        return ConversationHandler.END

    amount = bonus["amount"]
    conn.execute("INSERT INTO bonus_redemptions (telegram_id, code, amount) VALUES (?,?,?)", (uid, code, amount))
    conn.execute("UPDATE bonus_codes SET used_count=used_count+1 WHERE code=?", (code,))
    if bonus["used_count"] + 1 >= bonus["max_uses"]:
        conn.execute("UPDATE bonus_codes SET is_active=0 WHERE code=?", (code,))
    conn.execute("UPDATE users SET balance=balance+?, total_earned=total_earned+? WHERE telegram_id=?", (amount, amount, uid))
    conn.commit()
    conn.close()

    user = get_user(uid)
    await update.message.reply_text(
        f"🎉 *Bonus Code Redeemed!* 🎉\n\n"
        f"🎁 Code: `{code}`\n"
        f"💰 Bonus Earned: *₹{amount}*\n"
        f"👛 New Balance: *₹{user['balance']:.2f}*\n\n"
        f"🚀 Keep earning!",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

async def leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    top = conn.execute(
        "SELECT full_name, total_earned FROM users WHERE is_banned=0 ORDER BY total_earned DESC LIMIT 10"
    ).fetchall()
    conn.close()
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    text = "🏆 *Top Earners Leaderboard* 🏆\n\n━━━━━━━━━━━━━━━━\n"
    for i, row in enumerate(top):
        name = row["full_name"] or "Anonymous"
        text += f"{medals[i]} *{name}*\n    💰 ₹{row['total_earned']:.2f}\n"
    if not top:
        text += "_No data yet. Be the first! 🚀_"
    text += "\n━━━━━━━━━━━━━━━━"
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *How to Use Daily Earn Bot* ℹ️\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "💰 *Claim Daily* — Earn ₹1–₹10 every 24h\n"
        "👛 *My Wallet* — View balance & stats\n"
        "👥 *Refer & Earn* — ₹2 per referral\n"
        "🎁 *Bonus Code* — Redeem for extra cash\n"
        "💸 *Withdraw* — UPI or Bank (min ₹1000)\n"
        "📊 *Leaderboard* — Top earners\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "📌 *Rules:*\n"
        "• One claim per 24 hours only\n"
        "• Minimum withdrawal ₹1000\n"
        "• Withdrawals in 24–48 hours\n"
        "• No fraud or multiple accounts\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "❓ Contact: @earn_karo_pls",
        parse_mode="Markdown"
    )

async def withdraw_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ Please send /start first!")
        return ConversationHandler.END
    if user["is_banned"]:
        await update.message.reply_text("🚫 You are banned.")
        return ConversationHandler.END
    if user["balance"] < MIN_WITHDRAW:
        await update.message.reply_text(
            f"❌ *Insufficient Balance!*\n\n"
            f"💰 Your Balance: *₹{user['balance']:.2f}*\n"
            f"💸 Minimum Required: *₹{MIN_WITHDRAW}*\n\n"
            f"📈 Keep claiming daily!\n"
            f"👥 Refer friends to earn faster! 🚀",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    conn = get_db()
    pending = conn.execute("SELECT id FROM withdrawals WHERE telegram_id=? AND status='pending'", (uid,)).fetchone()
    conn.close()
    if pending:
        await update.message.reply_text(
            "⏳ *Pending Withdrawal Exists!*\n\n"
            "You already have a pending withdrawal.\n"
            "Please wait for it to be processed first! ⏳",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    ctx.user_data["withdraw_amount"] = user["balance"]
    await update.message.reply_text(
        f"💸 *Withdrawal Request*\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 Amount to Withdraw: *₹{user['balance']:.2f}*\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Choose payment method 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 UPI Payment", callback_data="w_upi"),
             InlineKeyboardButton("🏦 Bank Transfer", callback_data="w_bank")],
            [InlineKeyboardButton("❌ Cancel", callback_data="w_cancel")]
        ])
    )
    return WITHDRAW_METHOD

async def withdraw_method(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "w_cancel":
        await query.edit_message_text("❌ Withdrawal cancelled.")
        return ConversationHandler.END
    ctx.user_data["withdraw_method"] = "upi" if data == "w_upi" else "bank"
    if data == "w_upi":
        await query.edit_message_text(
            "📱 *UPI Payment*\n\nEnter your *UPI ID* 👇\n_(e.g. name@upi or 9876543210@paytm)_\n\nType /cancel to go back.",
            parse_mode="Markdown"
        )
        return WITHDRAW_UPI
    else:
        await query.edit_message_text(
            "🏦 *Bank Transfer*\n\nEnter your *Bank Name* 👇\n_(e.g. State Bank of India)_\n\nType /cancel to go back.",
            parse_mode="Markdown"
        )
        return WITHDRAW_BANK_NAME

async def withdraw_upi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "/cancel":
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    ctx.user_data["upi_id"] = update.message.text.strip()
    uid = update.effective_user.id
    fname = update.effective_user.full_name
    amount = ctx.user_data["withdraw_amount"]
    upi_id = ctx.user_data["upi_id"]

    conn = get_db()
    conn.execute("INSERT INTO withdrawals (telegram_id, full_name, amount, method, upi_id) VALUES (?,?,?,?,?)",
                 (uid, fname, amount, "upi", upi_id))
    conn.execute("UPDATE users SET balance=balance-? WHERE telegram_id=?", (amount, uid))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ *Withdrawal Requested!*\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 Amount: *₹{amount:.2f}*\n"
        f"📱 Method: *UPI*\n"
        f"🔗 UPI ID: `{upi_id}`\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"⏳ Processing: *24–48 hours*\n"
        f"📲 You'll be notified once paid! 🎉",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    for admin_id in ADMIN_IDS:
        try:
            await ctx.bot.send_message(
                chat_id=admin_id,
                text=f"🔔 *New Withdrawal Request!*\n\n"
                     f"👤 Name: {fname}\n"
                     f"🆔 ID: `{uid}`\n"
                     f"💰 Amount: *₹{amount:.2f}*\n"
                     f"📱 UPI: `{upi_id}`\n\n"
                     f"Use /admin to manage ✅",
                parse_mode="Markdown"
            )
        except:
            pass
    return ConversationHandler.END

async def withdraw_bank_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "/cancel":
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    ctx.user_data["bank_name"] = update.message.text.strip()
    await update.message.reply_text("🏦 Enter your *Account Number* 👇\n\nType /cancel to go back.", parse_mode="Markdown")
    return WITHDRAW_ACC

async def withdraw_acc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "/cancel":
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    ctx.user_data["acc_number"] = update.message.text.strip()
    await update.message.reply_text("🏦 Enter your *IFSC Code* 👇\n_(e.g. SBIN0001234)_\n\nType /cancel to go back.", parse_mode="Markdown")
    return WITHDRAW_IFSC

async def withdraw_ifsc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "/cancel":
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    ctx.user_data["ifsc"] = update.message.text.strip().upper()
    await update.message.reply_text("👤 Enter *Account Holder Name* 👇\n\nType /cancel to go back.", parse_mode="Markdown")
    return WITHDRAW_HOLDER

async def withdraw_holder(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "/cancel":
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    uid = update.effective_user.id
    fname = update.effective_user.full_name
    ctx.user_data["holder"] = update.message.text.strip()
    amount = ctx.user_data["withdraw_amount"]

    conn = get_db()
    conn.execute("""INSERT INTO withdrawals (telegram_id, full_name, amount, method, bank_name, account_number, ifsc_code, account_holder)
                    VALUES (?,?,?,?,?,?,?,?)""",
                 (uid, fname, amount, "bank", ctx.user_data["bank_name"],
                  ctx.user_data["acc_number"], ctx.user_data["ifsc"], ctx.user_data["holder"]))
    conn.execute("UPDATE users SET balance=balance-? WHERE telegram_id=?", (amount, uid))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ *Withdrawal Requested!*\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 Amount: *₹{amount:.2f}*\n"
        f"🏦 Bank: *{ctx.user_data['bank_name']}*\n"
        f"🔢 Account: `{ctx.user_data['acc_number']}`\n"
        f"📍 IFSC: `{ctx.user_data['ifsc']}`\n"
        f"👤 Holder: *{ctx.user_data['holder']}*\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"⏳ Processing: *24–48 hours*\n"
        f"📲 You'll be notified once paid! 🎉",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    for admin_id in ADMIN_IDS:
        try:
            await ctx.bot.send_message(
                chat_id=admin_id,
                text=f"🔔 *New Withdrawal Request!*\n\n"
                     f"👤 {fname} | ID: `{uid}`\n"
                     f"💰 *₹{amount:.2f}* via Bank\n"
                     f"🏦 {ctx.user_data['bank_name']}\n"
                     f"Acc: `{ctx.user_data['acc_number']}`\n"
                     f"IFSC: `{ctx.user_data['ifsc']}`\n"
                     f"Holder: {ctx.user_data['holder']}\n\n"
                     f"Use /admin to manage ✅",
                parse_mode="Markdown"
            )
        except:
            pass
    return ConversationHandler.END

async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in ADMIN_IDS:
        await show_admin_panel(update, ctx)
        return ConversationHandler.END
    await update.message.reply_text("🔐 *Admin Login*\n\nEnter admin password 👇", parse_mode="Markdown")
    return ADMIN_LOGIN

async def show_admin_panel(update, ctx):
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    total_pending = conn.execute("SELECT COUNT(*) as c FROM withdrawals WHERE status='pending'").fetchone()["c"]
    total_paid = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM withdrawals WHERE status='approved'").fetchone()["s"]
    total_claimed = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM claims").fetchone()["s"]
    conn.close()
    text = (
        f"🛡️ *Admin Panel* 🛡️\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users: *{total_users}*\n"
        f"💰 Total Claimed: *₹{total_claimed:.2f}*\n"
        f"⏳ Pending Withdrawals: *{total_pending}*\n"
        f"✅ Total Paid Out: *₹{total_paid:.2f}*\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Select an action 👇"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=admin_menu_keyboard())
    else:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=admin_menu_keyboard())

async def admin_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == ADMIN_PASS:
        ADMIN_IDS.append(update.effective_user.id)
        await show_admin_panel(update, ctx)
    else:
        await update.message.reply_text("❌ Wrong password!")
    return ConversationHandler.END

async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    data = query.data

    if uid not in ADMIN_IDS:
        await query.edit_message_text("❌ Not authorized.")
        return ConversationHandler.END

    if data == "adm_close":
        await query.edit_message_text("✅ Admin panel closed.")
        return ConversationHandler.END

    if data == "adm_back":
        await show_admin_panel(update, ctx)
        return

    if data == "adm_stats":
        conn = get_db()
        total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        total_claimed = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM claims").fetchone()["s"]
        total_refs = conn.execute("SELECT COUNT(*) as c FROM referral_earnings").fetchone()["c"]
        total_bonus = conn.execute("SELECT COUNT(*) as c FROM bonus_redemptions").fetchone()["c"]
        banned = conn.execute("SELECT COUNT(*) as c FROM users WHERE is_banned=1").fetchone()["c"]
        conn.close()
        await query.edit_message_text(
            f"📊 *Bot Statistics*\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👥 Total Users: *{total_users}*\n"
            f"🚫 Banned Users: *{banned}*\n"
            f"💰 Total Claimed: *₹{total_claimed:.2f}*\n"
            f"👤 Total Referrals: *{total_refs}*\n"
            f"🎁 Bonus Redemptions: *{total_bonus}*\n"
            f"━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_back")]])
        )

    elif data == "adm_pending":
        conn = get_db()
        pending = conn.execute(
            "SELECT * FROM withdrawals WHERE status='pending' ORDER BY requested_at DESC LIMIT 10"
        ).fetchall()
        conn.close()
        if not pending:
            await query.edit_message_text(
                "✅ *No pending withdrawals!*\n\nAll clear! 🎉",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_back")]])
            )
            return
        text = "⏳ *Pending Withdrawals*\n\n━━━━━━━━━━━━━━━━\n"
        buttons = []
        for w in pending:
            method_info = f"📱 UPI: {w['upi_id']}" if w["method"] == "upi" else f"🏦 {w['bank_name']} | {w['account_number']}"
            text += (
                f"🆔 *#{w['id']}* | 👤 {w['full_name']}\n"
                f"💰 ₹{w['amount']:.2f} | {method_info}\n"
                f"📅 {w['requested_at'][:16]}\n\n"
            )
            buttons.append([
                InlineKeyboardButton(f"✅ Pay #{w['id']}", callback_data=f"adm_pay_{w['id']}"),
                InlineKeyboardButton(f"❌ Reject #{w['id']}", callback_data=f"adm_reject_{w['id']}")
            ])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="adm_back")])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("adm_pay_"):
        wid = int(data.split("_")[2])
        conn = get_db()
        w = conn.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
        if w and w["status"] == "pending":
            conn.execute("UPDATE withdrawals SET status='approved', processed_at=? WHERE id=?",
                         (datetime.utcnow().isoformat(), wid))
            conn.commit()
            conn.close()
            try:
                await ctx.bot.send_message(
                    chat_id=w["telegram_id"],
                    text=f"🎉 *Withdrawal Approved & Paid!* 🎉\n\n"
                         f"━━━━━━━━━━━━━━━━\n"
                         f"💰 Amount: *₹{w['amount']:.2f}*\n"
                         f"✅ Status: *PAID*\n"
                         f"━━━━━━━━━━━━━━━━\n\n"
                         f"💵 Your payment has been processed!\n"
                         f"Thank you for using Daily Earn Bot! 🙏\n\n"
                         f"Keep earning! 🚀",
                    parse_mode="Markdown"
                )
            except:
                pass
            await query.edit_message_text(f"✅ Withdrawal #{wid} approved! User notified. 🎉")
        else:
            conn.close()
            await query.answer("Already processed!")

    elif data.startswith("adm_reject_"):
        wid = int(data.split("_")[2])
        ctx.user_data["reject_wid"] = wid
        await query.edit_message_text(
            f"❌ *Reject Withdrawal #{wid}*\n\nEnter reason 👇\n_(Type /skip for no reason)_",
            parse_mode="Markdown"
        )
        return ADMIN_REJECT_NOTE

    elif data == "adm_create_bonus":
        await query.edit_message_text(
            "🎁 *Create Bonus Code*\n\nEnter the *code name* (letters & numbers only) 👇\n_(e.g. EARN50 or DIWALI100)_",
            parse_mode="Markdown"
        )
        return ADMIN_BONUS_CODE

    elif data == "adm_broadcast":
        await query.edit_message_text(
            "📢 *Broadcast to All Users*\n\nEnter your message 👇\n\nType /cancel to go back.",
            parse_mode="Markdown"
        )
        return ADMIN_BROADCAST

    elif data == "adm_ban":
        ctx.user_data["ban_action"] = "ban"
        await query.edit_message_text("🚫 Enter Telegram *User ID* to ban 👇", parse_mode="Markdown")
        return ADMIN_PAY_ID

    elif data == "adm_unban":
        ctx.user_data["ban_action"] = "unban"
        await query.edit_message_text("✅ Enter Telegram *User ID* to unban 👇", parse_mode="Markdown")
        return ADMIN_PAY_ID

async def admin_reject_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wid = ctx.user_data["reject_wid"]
    note = "" if update.message.text.strip() == "/skip" else update.message.text.strip()
    conn = get_db()
    w = conn.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
    if w and w["status"] == "pending":
        conn.execute("UPDATE withdrawals SET status='rejected', admin_note=?, processed_at=? WHERE id=?",
                     (note, datetime.utcnow().isoformat(), wid))
        conn.execute("UPDATE users SET balance=balance+? WHERE telegram_id=?", (w["amount"], w["telegram_id"]))
        conn.commit()
        conn.close()
        try:
            await ctx.bot.send_message(
                chat_id=w["telegram_id"],
                text=f"❌ *Withdrawal Rejected*\n\n"
                     f"💰 ₹{w['amount']:.2f} refunded to your balance.\n"
                     f"{'📝 Reason: ' + note if note else ''}\n\n"
                     f"Contact @earn_karo_pls for help.",
                parse_mode="Markdown"
            )
        except:
            pass
        await update.message.reply_text(f"❌ Withdrawal #{wid} rejected. Balance refunded to user.")
    else:
        conn.close()
        await update.message.reply_text("Already processed!")
    return ConversationHandler.END

async def admin_bonus_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    if not code.isalnum():
        await update.message.reply_text("❌ Only letters and numbers allowed! Try again 👇")
        return ADMIN_BONUS_CODE
    ctx.user_data["new_bonus_code"] = code
    await update.message.reply_text(f"💰 Code: *{code}*\n\nEnter *amount (₹)* for this code 👇", parse_mode="Markdown")
    return ADMIN_BONUS_AMT

async def admin_bonus_amt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ Invalid! Enter a number like 50 👇")
        return ADMIN_BONUS_AMT
    ctx.user_data["new_bonus_amt"] = amount
    await update.message.reply_text("🔢 How many times can this code be used?\n_(Enter 0 for unlimited)_", parse_mode="Markdown")
    return ADMIN_BONUS_USES

async def admin_bonus_uses(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uses = int(update.message.text.strip())
        if uses < 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ Invalid! Enter a whole number 👇")
        return ADMIN_BONUS_USES
    code = ctx.user_data["new_bonus_code"]
    amount = ctx.user_data["new_bonus_amt"]
    max_uses = 999999 if uses == 0 else uses
    conn = get_db()
    try:
        conn.execute("INSERT INTO bonus_codes (code, amount, max_uses) VALUES (?,?,?)", (code, amount, max_uses))
        conn.commit()
        conn.close()
        await update.message.reply_text(
            f"✅ *Bonus Code Created!* 🎉\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🎁 Code: `{code}`\n"
            f"💰 Amount: *₹{amount}*\n"
            f"🔢 Max Uses: *{'Unlimited' if uses == 0 else uses}*\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"Share with users! 🚀",
            parse_mode="Markdown"
        )
    except:
        conn.close()
        await update.message.reply_text("❌ Code already exists! Use a different name.")
    return ConversationHandler.END

async def admin_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "/cancel":
        await update.message.reply_text("❌ Cancelled.")
        return ConversationHandler.END
    msg = update.message.text.strip()
    conn = get_db()
    users = conn.execute("SELECT telegram_id FROM users WHERE is_banned=0").fetchall()
    conn.close()
    sent = 0
    failed = 0
    for u in users:
        try:
            await ctx.bot.send_message(
                chat_id=u["telegram_id"],
                text=f"📢 *Announcement*\n\n{msg}",
                parse_mode="Markdown"
            )
            sent += 1
        except:
            failed += 1
    await update.message.reply_text(
        f"📢 *Broadcast Complete!*\n\n✅ Sent: *{sent}*\n❌ Failed: *{failed}*",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def admin_ban_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        target_id = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ Invalid ID! Numbers only.")
        return ConversationHandler.END
    action = ctx.user_data.get("ban_action", "ban")
    conn = get_db()
    if action == "ban":
        conn.execute("UPDATE users SET is_banned=1 WHERE telegram_id=?", (target_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🚫 User `{target_id}` has been *banned!*", parse_mode="Markdown")
    else:
        conn.execute("UPDATE users SET is_banned=0 WHERE telegram_id=?", (target_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ User `{target_id}` has been *unbanned!*", parse_mode="Markdown")
    return ConversationHandler.END

async def text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "💰 Claim Daily":
        await daily_claim(update, ctx)
    elif text == "👛 My Wallet":
        await my_wallet(update, ctx)
    elif text == "👥 Refer & Earn":
        await refer_earn(update, ctx)
    elif text == "💸 Withdraw":
        await withdraw_start(update, ctx)
    elif text == "📊 Leaderboard":
        await leaderboard(update, ctx)
    elif text == "ℹ️ Help":
        await help_cmd(update, ctx)
    else:
        await update.message.reply_text(
            "❓ Please use the menu buttons below 👇",
            reply_markup=main_menu_keyboard()
        )

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    withdraw_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💸 Withdraw$"), withdraw_start)],
        states={
            WITHDRAW_METHOD: [CallbackQueryHandler(withdraw_method, pattern="^w_")],
            WITHDRAW_UPI: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_upi)],
            WITHDRAW_BANK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_bank_name)],
            WITHDRAW_ACC: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_acc)],
            WITHDRAW_IFSC: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_ifsc)],
            WITHDRAW_HOLDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_holder)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        allow_reentry=True
    )

    bonus_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎁 Bonus Code$"), bonus_code_start)],
        states={
            BONUS_CLAIM: [MessageHandler(filters.TEXT & ~filters.COMMAND, bonus_code_redeem)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        allow_reentry=True
    )

    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_cmd)],
        states={
            ADMIN_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_login)],
            ADMIN_BONUS_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_bonus_code)],
            ADMIN_BONUS_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_bonus_amt)],
            ADMIN_BONUS_USES: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_bonus_uses)],
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast)],
            ADMIN_PAY_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_ban_unban)],
            ADMIN_REJECT_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reject_note)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(withdraw_conv)
    app.add_handler(bonus_conv)
    app.add_handler(admin_conv)
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    print("🤖 Daily Earn Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
