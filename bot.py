import os
import json
import asyncio
import aiohttp
import logging
from datetime import date, datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Aryan2010")
TG_CHANNEL     = os.environ.get("TG_CHANNEL", "@mahakaalneeds")
TG_CHANNEL_ID  = os.environ.get("TG_CHANNEL_ID", "")
DB_PATH        = os.environ.get("DB_PATH", "bot_data.json")

PHONE_API  = "https://ayaanmods.site/number.php?key=annonymous&number={number}"
FAMILY_API = "https://ayaanmods.site/family.php?key=annonymousfamily&term={uid}"

DAILY_CREDITS = 2
# ────────────────────────────────────────────────────────


# ── Database ─────────────────────────────────────────────
def load_db() -> dict:
    if not os.path.exists(DB_PATH):
        return {"users": {}, "admins": []}
    try:
        with open(DB_PATH, "r") as f:
            d = json.load(f)
        if "users" not in d:  d["users"] = {}
        if "admins" not in d: d["admins"] = []
        return d
    except Exception:
        return {"users": {}, "admins": []}

def save_db(db: dict):
    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

def today_str() -> str:
    return date.today().isoformat()

def get_or_create_user(db: dict, tg_user) -> dict:
    uid = str(tg_user.id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "id":             uid,
            "name":           tg_user.full_name,
            "username":       tg_user.username or "",
            "daily_credits":  DAILY_CREDITS,
            "daily_date":     today_str(),
            "refer_credits":  0,
            "refer_code":     gen_refer_code(uid, tg_user.full_name),
            "referred_by":    None,
            "joined":         datetime.now().strftime("%d %b %Y, %I:%M %p"),
            "total_searches": 0,
        }
    else:
        u = db["users"][uid]
        if u.get("daily_date") != today_str():
            u["daily_credits"] = DAILY_CREDITS
            u["daily_date"]    = today_str()
        db["users"][uid]["name"] = tg_user.full_name
    return db["users"][uid]

def gen_refer_code(uid: str, name: str) -> str:
    import hashlib
    raw = uid + name
    return hashlib.md5(raw.encode()).hexdigest()[:6].upper()

def total_credits(u: dict) -> int:
    return u.get("daily_credits", 0) + u.get("refer_credits", 0)

def deduct_credit(u: dict) -> str:
    if u.get("daily_credits", 0) > 0:
        u["daily_credits"] -= 1
        return "daily"
    u["refer_credits"] -= 1
    return "refer"

def refund_credit(u: dict, which: str):
    if which == "daily":
        u["daily_credits"] = min(u.get("daily_credits", 0) + 1, DAILY_CREDITS)
    else:
        u["refer_credits"] = u.get("refer_credits", 0) + 1
# ─────────────────────────────────────────────────────────


# ── API calls (with retry & better error handling) ───────
async def fetch_phone(number: str) -> dict:
    url = PHONE_API.format(number=number)
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    }
    timeout = aiohttp.ClientTimeout(total=20, connect=8)

    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=timeout, headers=headers, ssl=False) as r:
                    text = await r.text()
                    logger.info(f"Phone API [{r.status}] attempt {attempt+1}: {text[:200]}")
                    if r.status != 200:
                        raise Exception(f"HTTP {r.status}")
                    # Try JSON parse
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        # Sometimes API returns non-JSON on error
                        raise Exception(f"Invalid JSON: {text[:100]}")
        except asyncio.TimeoutError:
            logger.warning(f"Phone API timeout attempt {attempt+1}")
            if attempt < 2:
                await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Phone API error attempt {attempt+1}: {e}")
            if attempt < 2:
                await asyncio.sleep(2)

    raise Exception("Phone API failed after 3 attempts")


async def fetch_family(uid: str) -> dict:
    url = FAMILY_API.format(uid=uid)
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    }
    timeout = aiohttp.ClientTimeout(total=25, connect=8)

    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=timeout, headers=headers, ssl=False) as r:
                    text = await r.text()
                    logger.info(f"Family API [{r.status}] attempt {attempt+1}: {text[:200]}")
                    if r.status != 200:
                        raise Exception(f"HTTP {r.status}")
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        raise Exception(f"Invalid JSON: {text[:100]}")
        except asyncio.TimeoutError:
            logger.warning(f"Family API timeout attempt {attempt+1}")
            if attempt < 2:
                await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Family API error attempt {attempt+1}: {e}")
            if attempt < 2:
                await asyncio.sleep(2)

    raise Exception("Family API failed after 3 attempts")
# ─────────────────────────────────────────────────────────


# ── Helpers ──────────────────────────────────────────────
def credit_bar(daily: int, refer: int) -> str:
    total = daily + refer
    bar_len = 10
    filled = min(int((total / (DAILY_CREDITS + 5)) * bar_len), bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    return (
        f"⚡ `{bar}` {total} credits\n"
        f"   ☀️ Daily: `{daily}`  🔗 Refer: `{refer}`"
    )

def escape_md(text) -> str:
    if not text:
        return "—"
    text = str(text)
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text

def fmt_name(s) -> str:
    return str(s).strip() if s else "—"

CHANNEL_URL = f"https://t.me/{TG_CHANNEL.lstrip('@')}"
# ─────────────────────────────────────────────────────────


# ── Channel membership check ─────────────────────────────
async def is_member(bot, user_id: int) -> bool:
    if not TG_CHANNEL_ID and not TG_CHANNEL:
        return True
    channel = TG_CHANNEL_ID if TG_CHANNEL_ID else TG_CHANNEL
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning(f"Membership check failed: {e}")
        return True
# ─────────────────────────────────────────────────────────


# ── Keyboards ─────────────────────────────────────────────
def join_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📢 Join Channel", url=CHANNEL_URL),
        InlineKeyboardButton("✅ I've Joined", callback_data="check_join"),
    ]])

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Phone Search", callback_data="menu_phone"),
         InlineKeyboardButton("🪪 Aadhaar Search", callback_data="menu_aadhaar")],
        [InlineKeyboardButton("⚡ My Credits", callback_data="menu_credits"),
         InlineKeyboardButton("🔗 Refer & Earn", callback_data="menu_refer")],
        [InlineKeyboardButton("📋 History", callback_data="menu_history"),
         InlineKeyboardButton("❓ Help", callback_data="menu_help")],
    ])
# ─────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ══════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if not await is_member(context.bot, user.id):
        await update.message.reply_text(
            "🔱 *Mahakaal Trace*\n\n"
            "Access karne ke liye pehle hamare Telegram channel join karo\\!\n\n"
            f"📢 Channel: {escape_md(TG_CHANNEL)}",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=join_keyboard()
        )
        return

    db = load_db()
    u  = get_or_create_user(db, user)

    if args and not u.get("referred_by"):
        ref_code = args[0].upper()
        for uid2, u2 in db["users"].items():
            if uid2 != str(user.id) and u2.get("refer_code") == ref_code:
                u["referred_by"]    = uid2
                u["refer_credits"]  = u.get("refer_credits", 0) + 1
                u2["refer_credits"] = u2.get("refer_credits", 0) + 1
                try:
                    await context.bot.send_message(
                        chat_id=int(uid2),
                        text=f"🎉 *\\+1 Referral Credit\\!*\n\n"
                             f"*{escape_md(user.full_name)}* ne tera referral code use kiya\\!\n"
                             f"Tera balance: 🔗 `{u2['refer_credits']}` refer credits",
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                except Exception:
                    pass
                break

    save_db(db)

    daily = u["daily_credits"]
    refer = u.get("refer_credits", 0)

    await update.message.reply_text(
        f"🔱 *Mahakaal Trace*\n"
        f"_India's \\#1 Free \\+91 Intelligence Bot_\n\n"
        f"Namaste *{escape_md(user.first_name)}*\\! 👋\n\n"
        f"{credit_bar(daily, refer)}\n\n"
        f"*Kya search karna hai?*",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=main_keyboard()
    )


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_member(context.bot, user.id):
        await update.message.reply_text("Pehle channel join karo!", reply_markup=join_keyboard())
        return

    if not context.args:
        await update.message.reply_text(
            "📱 *Phone Number Search*\n\n"
            "Usage: `/search 9876543210`\n"
            "Sirf 10 digit number \\(without \\+91\\)",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    number = "".join(c for c in context.args[0] if c.isdigit())
    if number.startswith("91") and len(number) == 12:
        number = number[2:]
    await handle_phone_search(update, context, number)


async def cmd_aadhaar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_member(context.bot, user.id):
        await update.message.reply_text("Pehle channel join karo!", reply_markup=join_keyboard())
        return

    if not context.args:
        await update.message.reply_text(
            "🪪 *Aadhaar Family Lookup*\n\n"
            "Usage: `/aadhaar 979607168114`\n"
            "12 digit Aadhaar number",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    aadhaar = "".join(c for c in context.args[0] if c.isdigit())
    await handle_aadhaar_search(update, context, aadhaar)


async def cmd_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db   = load_db()
    u    = get_or_create_user(db, user)
    save_db(db)

    daily = u["daily_credits"]
    refer = u.get("refer_credits", 0)

    await update.message.reply_text(
        f"⚡ *Tera Credit Balance*\n\n"
        f"{credit_bar(daily, refer)}\n\n"
        f"☀️ *Daily Credits:* `{daily}/{DAILY_CREDITS}`\n"
        f"   Har roz midnight pe refill hote hain\n\n"
        f"🔗 *Referral Credits:* `{refer}`\n"
        f"   Kabhi expire nahi hote\\!\n\n"
        f"🔄 Total searches done: `{u.get('total_searches', 0)}`",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔗 Refer & Earn More", callback_data="menu_refer")
        ]])
    )


async def cmd_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db   = load_db()
    u    = get_or_create_user(db, user)
    save_db(db)

    code = u["refer_code"]
    bot_info = await context.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={code}"

    await update.message.reply_text(
        f"🎁 *Refer \\& Earn*\n\n"
        f"Har refer pe tujhe \\+1 permanent credit milega\\!\n"
        f"Jisko refer karo unhe bhi \\+1 bonus credit milta hai\\.\n\n"
        f"*Tera Refer Code:*\n"
        f"`{code}`\n\n"
        f"*Tera Refer Link:*\n"
        f"`{escape_md(link)}`\n\n"
        f"Link share karo WhatsApp, Instagram pe \\!",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📤 Share Link", switch_inline_query=f"Mahakaal Trace se free +91 lookup karo! {link}")
        ]])
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔱 *Mahakaal Trace — Help*\n\n"
        "*Search Commands:*\n"
        "🔍 `/search 9876543210` — Phone lookup\n"
        "🪪 `/aadhaar 979607168114` — Aadhaar family\n\n"
        "*Account:*\n"
        "⚡ `/credits` — Balance dekho\n"
        "🔗 `/refer` — Refer link pao\n"
        "📋 `/history` — Recent searches\n\n"
        "*Free Credits:*\n"
        "• `2` daily credits — roz midnight pe refill\n"
        "• Refer karo, permanent credits pao\n\n"
        "*Tip:* Direct number bhi bhej sakte ho —\n"
        "10 digit = phone search\n"
        "12 digit = aadhaar search",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db   = load_db()
    u    = get_or_create_user(db, user)
    save_db(db)

    hist = u.get("history", [])
    if not hist:
        await update.message.reply_text("📋 Koi search history nahi hai abhi.")
        return

    lines = ["📋 *Recent Searches* \\(last 10\\)\n"]
    for i, h in enumerate(hist[-10:][::-1], 1):
        t     = h.get("type", "phone")
        icon  = "🔍" if t == "phone" else "🪪"
        q     = escape_md(h.get("q", ""))
        ts    = escape_md(h.get("time", ""))
        found = h.get("found", 0)
        lines.append(f"`{i}.` {icon} `{q}` — {found} records — _{ts}_")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN_V2
    )


# ── Admin commands ─────────────────────────────────────────
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db   = load_db()

    if str(user.id) not in db.get("admins", []):
        if not context.args or context.args[0] != ADMIN_PASSWORD:
            await update.message.reply_text("❌ Wrong password.")
            return
        if str(user.id) not in db["admins"]:
            db["admins"].append(str(user.id))
            save_db(db)

    total_users    = len(db["users"])
    today_active   = sum(1 for u in db["users"].values() if u.get("daily_date") == today_str())
    total_searches = sum(u.get("total_searches", 0) for u in db["users"].values())

    await update.message.reply_text(
        f"🔐 *Admin Panel*\n\n"
        f"👥 Total Users: `{total_users}`\n"
        f"📅 Active Today: `{today_active}`\n"
        f"🔍 Total Searches: `{total_searches}`\n\n"
        f"*Commands:*\n"
        f"`/broadcast <message>` — Sabko message bhejo\n"
        f"`/addcredits <user\\_id> <n>` — Credits add karo\n"
        f"`/userinfo <user\\_id>` — User details",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db   = load_db()

    if str(user.id) not in db.get("admins", []):
        await update.message.reply_text("❌ Admin access required. Use /admin <password> first.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /broadcast Your message here")
        return

    msg_text = " ".join(context.args)
    sent = 0
    fail = 0

    status_msg = await update.message.reply_text(f"📢 Sending to {len(db['users'])} users...")

    for uid in db["users"]:
        try:
            await context.bot.send_message(
                chat_id=int(uid),
                text=f"📢 *Mahakaal Trace — Announcement*\n\n{msg_text}",
                parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1

    await status_msg.edit_text(
        f"✅ Broadcast done!\n\n"
        f"✓ Sent: {sent}\n"
        f"✗ Failed: {fail}"
    )


async def cmd_addcredits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db   = load_db()

    if str(user.id) not in db.get("admins", []):
        await update.message.reply_text("❌ Admin access required.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addcredits <user_id> <amount>")
        return

    target_id = context.args[0]
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Amount must be a number.")
        return

    if target_id not in db["users"]:
        await update.message.reply_text("User not found.")
        return

    db["users"][target_id]["refer_credits"] = db["users"][target_id].get("refer_credits", 0) + amount
    save_db(db)

    await update.message.reply_text(
        f"✅ Added {amount} credits to user `{target_id}`\n"
        f"New balance: {db['users'][target_id]['refer_credits']} refer credits",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=f"🎁 *Admin ne {amount} bonus credit\\(s\\) diye\\!*\n\n"
                 f"Tera refer credit balance: `{db['users'][target_id]['refer_credits']}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception:
        pass


async def cmd_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    if str(update.effective_user.id) not in db.get("admins", []):
        await update.message.reply_text("❌ Admin access required.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /userinfo <user_id>")
        return

    uid = context.args[0]
    u   = db["users"].get(uid)
    if not u:
        await update.message.reply_text("User not found.")
        return
    await update.message.reply_text(
        f"👤 *User Info*\n\n"
        f"ID: `{u['id']}`\n"
        f"Name: {escape_md(u['name'])}\n"
        f"Username: @{escape_md(u.get('username','—'))}\n"
        f"Daily: `{u['daily_credits']}`\n"
        f"Refer: `{u.get('refer_credits',0)}`\n"
        f"Total Searches: `{u.get('total_searches',0)}`\n"
        f"Joined: {escape_md(u['joined'])}",
        parse_mode=ParseMode.MARKDOWN_V2
    )


# ══════════════════════════════════════════════════════════
#  CORE SEARCH LOGIC
# ══════════════════════════════════════════════════════════

async def handle_phone_search(update: Update, context: ContextTypes.DEFAULT_TYPE, number: str):
    number = "".join(c for c in number if c.isdigit())
    # Handle if someone sends 91XXXXXXXXXX
    if number.startswith("91") and len(number) == 12:
        number = number[2:]
    if len(number) != 10:
        await update.message.reply_text(
            "❌ Invalid number\\. 10 digits chahiye \\(without \\+91\\)\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    user = update.effective_user
    db   = load_db()
    u    = get_or_create_user(db, user)

    if total_credits(u) <= 0:
        save_db(db)
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={u['refer_code']}"
        await update.message.reply_text(
            "😔 *Koi credit nahi bacha\\!*\n\n"
            "☀️ Daily credits kal midnight ko refill honge\\.\n"
            "🔗 Ya phir refer karo aur permanent credits pao\\!\n\n"
            f"Tera refer link:\n`{escape_md(link)}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    which = deduct_credit(u)
    u["total_searches"] = u.get("total_searches", 0) + 1
    save_db(db)

    msg = await update.message.reply_text("🔍 Searching\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)

    try:
        data = await fetch_phone(number)
        logger.info(f"Phone API response for {number}: {str(data)[:300]}")
    except Exception as e:
        logger.error(f"Phone API exception: {e}")
        refund_credit(u, which)
        u["total_searches"] = max(u.get("total_searches", 1) - 1, 0)
        save_db(db)
        await msg.edit_text(
            "❌ *API timeout ho gaya\\.*\n\n"
            "Server slow hai, thodi der baad dobara try karo\\.\n"
            "Credit refund ho gaya ✓",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    # Handle various response formats
    records = []
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        result = data.get("result", data.get("data", data.get("results", [])))
        if isinstance(result, list):
            records = result
        elif isinstance(result, dict):
            records = [result]
        elif data.get("name") or data.get("mobile"):
            records = [data]

    if not records:
        refund_credit(u, which)
        u["total_searches"] = max(u.get("total_searches", 1) - 1, 0)
        save_db(db)
        await msg.edit_text(
            f"🔍 `+91 {number}`\n\n"
            "❌ *Koi record nahi mila*\n"
            "Credit refund ho gaya automatically\\. ✓",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    # Save to history
    u.setdefault("history", []).append({
        "type": "phone", "q": number,
        "time": datetime.now().strftime("%d %b, %I:%M %p"),
        "found": len(records)
    })
    if len(u["history"]) > 20:
        u["history"] = u["history"][-20:]
    save_db(db)

    daily = u["daily_credits"]
    refer = u.get("refer_credits", 0)

    result_text = (
        f"✅ *\\+91 {number}*\n"
        f"📊 {len(records)} record\\(s\\) mila\n"
        f"{'─'*28}\n"
    )

    for i, r in enumerate(records[:3], 1):
        name    = fmt_name(r.get("name"))
        father  = fmt_name(r.get("father_name") or r.get("father"))
        mobile  = fmt_name(r.get("mobile") or r.get("phone") or number)
        alt     = fmt_name(r.get("alternate") or r.get("alt_mobile"))
        circle  = fmt_name(r.get("circle") or r.get("state"))
        address = fmt_name(r.get("address") or r.get("addr"))
        email   = fmt_name(r.get("email"))

        result_text += f"\n👤 *Record {i}*\n"
        result_text += f"📛 Name: `{escape_md(name)}`\n"
        if father and father != "—":
            result_text += f"👨 Father: `{escape_md(father)}`\n"
        result_text += f"📱 Mobile: `{escape_md(mobile)}`\n"
        if alt and alt != "—":
            result_text += f"📞 Alt: `{escape_md(alt)}`\n"
        if circle and circle != "—":
            result_text += f"📡 Circle: `{escape_md(circle)}`\n"
        if email and email != "—":
            result_text += f"✉️ Email: `{escape_md(email)}`\n"
        if address and address != "—":
            result_text += f"📍 Address: `{escape_md(address[:120])}`\n"
        if i < len(records[:3]):
            result_text += f"{'─'*28}\n"

    if len(records) > 3:
        result_text += f"\n\\+{len(records)-3} more records found\\.\n"

    result_text += f"\n\n{credit_bar(daily, refer)}"

    await msg.edit_text(result_text, parse_mode=ParseMode.MARKDOWN_V2)


async def handle_aadhaar_search(update: Update, context: ContextTypes.DEFAULT_TYPE, aadhaar: str):
    aadhaar = "".join(c for c in aadhaar if c.isdigit())
    if len(aadhaar) != 12:
        await update.message.reply_text(
            "❌ Invalid Aadhaar\\. 12 digits chahiye\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    user = update.effective_user
    db   = load_db()
    u    = get_or_create_user(db, user)

    if total_credits(u) <= 0:
        save_db(db)
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={u['refer_code']}"
        await update.message.reply_text(
            "😔 *Koi credit nahi bacha\\!*\n\n"
            "☀️ Daily credits kal midnight ko refill honge\\.\n"
            f"Refer link: `{escape_md(link)}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    which = deduct_credit(u)
    u["total_searches"] = u.get("total_searches", 0) + 1
    save_db(db)

    msg = await update.message.reply_text("🪪 Fetching family data\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)

    try:
        data = await fetch_family(aadhaar)
        logger.info(f"Family API response for {aadhaar}: {str(data)[:300]}")
    except Exception as e:
        logger.error(f"Family API exception: {e}")
        refund_credit(u, which)
        u["total_searches"] = max(u.get("total_searches", 1) - 1, 0)
        save_db(db)
        await msg.edit_text(
            "❌ *API timeout ho gaya\\.*\n\n"
            "Thodi der baad dobara try karo\\.\n"
            "Credit refund ho gaya ✓",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    if not data.get("success") or not data.get("result", {}).get("pd"):
        refund_credit(u, which)
        u["total_searches"] = max(u.get("total_searches", 1) - 1, 0)
        save_db(db)
        await msg.edit_text(
            f"🪪 `{aadhaar}`\n\n"
            "❌ *Koi family data nahi mila*\n"
            "Credit refund ho gaya\\. ✓",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    pd      = data["result"]["pd"]
    members = pd.get("memberDetailsList", [])
    hist    = data.get("result", {}).get("purchase_history", {}).get("pd", [])

    # Dedup history by receipt_id
    seen   = set()
    u_hist = []
    for h in hist:
        k = f"{h.get('receipt_id')}|{h.get('transaction_date')}"
        if k not in seen:
            seen.add(k)
            u_hist.append(h)

    # Save to history
    u.setdefault("history", []).append({
        "type": "aadhaar", "q": aadhaar,
        "time": datetime.now().strftime("%d %b, %I:%M %p"),
        "found": len(members)
    })
    if len(u["history"]) > 20:
        u["history"] = u["history"][-20:]
    save_db(db)

    rel_map = {
        "1": "SELF", "2": "WIFE", "3": "SON", "4": "DAUGHTER",
        "5": "FATHER", "6": "MOTHER", "7": "HUSBAND", "8": "SON", "9": "DAUGHTER"
    }
    rel_icon = {
        "SELF": "👑", "WIFE": "👸", "HUSBAND": "👨",
        "SON": "👦", "DAUGHTER": "👧", "FATHER": "👴", "MOTHER": "👵"
    }

    result = (
        f"✅ *Aadhaar: `{aadhaar}`*\n"
        f"🏠 *Ration Card Details*\n"
        f"{'─'*28}\n"
        f"📋 RC ID: `{escape_md(pd.get('rcId','—'))}`\n"
        f"🏛 State: `{escape_md(pd.get('homeStateName','—'))}`\n"
        f"🏙 District: `{escape_md(pd.get('homeDistName','—'))}`\n"
        f"📋 Scheme: `{escape_md(pd.get('schemeName','—'))}`\n"
        f"🔁 ONORC: `{escape_md(pd.get('allowed_onorc','—'))}`\n"
        f"📍 Address: `{escape_md(str(pd.get('address','—'))[:100])}`\n"
        f"{'─'*28}\n"
        f"👨‍👩‍👧‍👦 *Family Members \\({len(members)}\\)*\n"
    )

    for m in members:
        rel  = (m.get("releationship_name") or rel_map.get(str(m.get("relationship_code", "")), "MEMBER")).upper()
        icon = rel_icon.get(rel, "👤")
        linked = "✅" if m.get("uid") == "Yes" else "⏳"
        result += f"{icon} `{escape_md(m.get('memberName','—'))}` \\| {escape_md(rel)} {linked}\n"

    if u_hist:
        result += f"\n{'─'*28}\n🧾 *Last Purchase*\n"
        last = u_hist[0]
        result += (
            f"📅 {escape_md(str(last.get('transaction_date','—')))}\n"
            f"👤 {escape_md(str(last.get('member_name','—')))}\n"
            f"🌾 Wheat: `{last.get('wheat',0)} kg`  "
            f"🍚 Rice: `{last.get('rice',0)} kg`\n"
        )

    daily = u["daily_credits"]
    refer = u.get("refer_credits", 0)
    result += f"\n{credit_bar(daily, refer)}"

    await msg.edit_text(result, parse_mode=ParseMode.MARKDOWN_V2)


# ══════════════════════════════════════════════════════════
#  MESSAGE HANDLER — Direct number input
# ══════════════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    text = update.message.text.strip()

    if not await is_member(context.bot, user.id):
        await update.message.reply_text(
            "Pehle channel join karo access ke liye\\!",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=join_keyboard()
        )
        return

    digits = "".join(c for c in text if c.isdigit())

    if len(digits) == 10:
        await handle_phone_search(update, context, digits)
    elif len(digits) == 12:
        await handle_aadhaar_search(update, context, digits)
    elif len(digits) == 11 and digits.startswith("0"):
        await handle_phone_search(update, context, digits[1:])
    else:
        await update.message.reply_text(
            "💡 *Tip:*\n\n"
            "• 10 digit number bhejo → Phone search\n"
            "• 12 digit number bhejo → Aadhaar search\n\n"
            "Ya `/help` command use karo",
            parse_mode=ParseMode.MARKDOWN
        )


# ══════════════════════════════════════════════════════════
#  CALLBACK QUERY HANDLER
# ══════════════════════════════════════════════════════════

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    user = q.from_user
    await q.answer()

    if data == "check_join":
        if await is_member(context.bot, user.id):
            db = load_db()
            get_or_create_user(db, user)
            save_db(db)
            await q.message.edit_text(
                "✅ *Channel join ho gaya\\!*\n\nAb `/start` bhejo\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await q.answer("Abhi join nahi hua. Pehle join karo!", show_alert=True)
        return

    db = load_db()
    u  = get_or_create_user(db, user)
    save_db(db)

    daily = u["daily_credits"]
    refer = u.get("refer_credits", 0)
    code  = u["refer_code"]
    bot_info = await context.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={code}"

    if data == "menu_phone":
        await q.message.edit_text(
            "🔍 *Phone Number Search*\n\n"
            "Phone number bhejo \\(10 digits\\)\\:\n\n"
            "Examples:\n"
            "`9876543210`\n"
            "`/search 9876543210`\n\n"
            "_Bas number type karo aur bhej do\\!_",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]])
        )

    elif data == "menu_aadhaar":
        await q.message.edit_text(
            "🪪 *Aadhaar Family Lookup*\n\n"
            "12 digit Aadhaar number bhejo\\:\n\n"
            "Example:\n"
            "`979607168114`\n"
            "`/aadhaar 979607168114`\n\n"
            "_Ration card, family members, purchase history sab milega\\!_",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]])
        )

    elif data == "menu_credits":
        await q.message.edit_text(
            f"⚡ *Tera Credit Balance*\n\n"
            f"{credit_bar(daily, refer)}\n\n"
            f"☀️ Daily: `{daily}/{DAILY_CREDITS}` \\(midnight pe refill\\)\n"
            f"🔗 Refer: `{refer}` \\(kabhi expire nahi\\)\n\n"
            f"🔄 Total searches: `{u.get('total_searches',0)}`",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Refer & Earn", callback_data="menu_refer")],
                [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]
            ])
        )

    elif data == "menu_refer":
        await q.message.edit_text(
            f"🎁 *Refer \\& Earn*\n\n"
            f"Har ek refer pe \\+1 permanent credit\\!\n\n"
            f"*Tera Code:* `{code}`\n\n"
            f"*Tera Link:*\n`{escape_md(link)}`\n\n"
            f"👆 Copy karke share karo\\!",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Share", switch_inline_query=f"Mahakaal Trace - Free +91 Lookup Bot! {link}")],
                [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]
            ])
        )

    elif data == "menu_history":
        hist = u.get("history", [])
        if not hist:
            await q.message.edit_text(
                "📋 *Search History*\n\nKoi search nahi ki abhi tak\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]])
            )
        else:
            lines = ["📋 *Recent Searches*\n"]
            for i, h in enumerate(hist[-8:][::-1], 1):
                t    = h.get("type", "phone")
                icon = "🔍" if t == "phone" else "🪪"
                q_   = escape_md(h.get("q", ""))
                ts   = escape_md(h.get("time", ""))
                lines.append(f"`{i}.` {icon} `{q_}` — _{ts}_")
            await q.message.edit_text(
                "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]])
            )

    elif data == "menu_help":
        await q.message.edit_text(
            "❓ *Help*\n\n"
            "Sirf number bhejo — bot automatically samajh jaata hai\\!\n\n"
            "🔹 *10 digit* → Phone lookup\n"
            "🔹 *12 digit* → Aadhaar lookup\n\n"
            "*Commands:*\n"
            "`/search` \\- Phone search\n"
            "`/aadhaar` \\- Aadhaar search\n"
            "`/credits` \\- Balance\n"
            "`/refer` \\- Refer link\n"
            "`/history` \\- Recent searches",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]])
        )

    elif data == "menu_back":
        await q.message.edit_text(
            f"🔱 *Mahakaal Trace*\n"
            f"_India's \\#1 Free \\+91 Intelligence Bot_\n\n"
            f"{credit_bar(daily, refer)}\n\n"
            f"*Kya search karna hai?*",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=main_keyboard()
        )


# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set!")

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("search",      cmd_search))
    app.add_handler(CommandHandler("aadhaar",     cmd_aadhaar))
    app.add_handler(CommandHandler("credits",     cmd_credits))
    app.add_handler(CommandHandler("refer",       cmd_refer))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("history",     cmd_history))

    # Admin commands
    app.add_handler(CommandHandler("admin",       cmd_admin))
    app.add_handler(CommandHandler("broadcast",   cmd_broadcast))
    app.add_handler(CommandHandler("addcredits",  cmd_addcredits))
    app.add_handler(CommandHandler("userinfo",    cmd_userinfo))

    # Callbacks & messages
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🔱 Mahakaal Trace Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
