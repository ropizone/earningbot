import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from database import Database
from games import DiceGame, CoinFlipGame, LuckySpinGame, CrashGame
from keyboards import (
    main_menu_keyboard, games_keyboard, profile_keyboard,
    leaderboard_keyboard, bet_keyboard, back_keyboard
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database()

# ─────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_new, profile = db.get_or_create_user(
        user_id=user.id,
        username=user.username or user.first_name,
        full_name=user.full_name
    )

    if is_new:
        welcome_text = (
            f"🎉 *Welcome to Satta King Bot, {user.first_name}!*\n\n"
            f"🎁 You've received *100 coins* signup bonus!\n\n"
            f"💰 *Your Balance:* `{profile['coins']} coins`\n\n"
            f"🎮 Play games, earn coins & climb the leaderboard!\n"
            f"📅 Don't forget your *daily bonus* every 24 hours!"
        )
    else:
        welcome_text = (
            f"👋 *Welcome back, {user.first_name}!*\n\n"
            f"💰 *Your Balance:* `{profile['coins']} coins`\n"
            f"🏆 *Rank:* `#{db.get_rank(user.id)}`\n\n"
            f"Ready to play?"
        )

    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )


async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    profile = db.get_user(user.id)
    if not profile:
        await update.message.reply_text("Please /start first!")
        return

    rank = db.get_rank(user.id)
    daily_ready = db.is_daily_ready(user.id)
    daily_status = "✅ Ready to claim!" if daily_ready else "⏳ Already claimed today"

    text = (
        f"👤 *Your Profile*\n\n"
        f"🆔 Username: `@{profile['username']}`\n"
        f"💰 Coins: `{profile['coins']}`\n"
        f"🏆 Rank: `#{rank}`\n"
        f"🎮 Games Played: `{profile['games_played']}`\n"
        f"✅ Wins: `{profile['wins']}`\n"
        f"❌ Losses: `{profile['losses']}`\n"
        f"📅 Daily Bonus: {daily_status}\n\n"
        f"Win Rate: `{_win_rate(profile)}%`"
    )

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=profile_keyboard(daily_ready)
    )


async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = db.get_leaderboard(10)
    user_rank = db.get_rank(update.effective_user.id)

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 *TOP 10 LEADERBOARD*\n"]

    for i, row in enumerate(top):
        medal = medals[i] if i < 3 else f"`{i+1}.`"
        lines.append(f"{medal} *{row['username']}* — `{row['coins']} coins`")

    lines.append(f"\n📍 Your Rank: `#{user_rank}`")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=leaderboard_keyboard()
    )


async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    result = db.claim_daily(user.id)

    if result["success"]:
        await update.message.reply_text(
            f"🎁 *Daily Bonus Claimed!*\n\n"
            f"💰 You received: *+{result['amount']} coins*\n"
            f"💳 New Balance: *{result['new_balance']} coins*\n\n"
            f"Come back tomorrow for more! 🔄",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            f"⏳ *Already Claimed!*\n\n"
            f"Come back in *{result['hours_left']}h {result['minutes_left']}m*\n"
            f"💰 Balance: *{result['balance']} coins*",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )


async def games_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    profile = db.get_user(update.effective_user.id)
    if not profile:
        await update.message.reply_text("Please /start first!")
        return

    await update.message.reply_text(
        f"🎮 *Choose a Game*\n\n"
        f"💰 Your Balance: `{profile['coins']} coins`\n\n"
        f"Pick a game to play:",
        parse_mode="Markdown",
        reply_markup=games_keyboard()
    )


# ─────────────────────────────────────────────
# CALLBACK HANDLERS
# ─────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    # ── NAVIGATION ──
    if data == "main_menu":
        profile = db.get_user(user.id)
        await query.edit_message_text(
            f"🏠 *Main Menu*\n\n💰 Balance: `{profile['coins'] if profile else 0} coins`",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )

    elif data == "games":
        profile = db.get_user(user.id)
        await query.edit_message_text(
            f"🎮 *Choose a Game*\n\n💰 Balance: `{profile['coins']} coins`\n\nPick a game:",
            parse_mode="Markdown",
            reply_markup=games_keyboard()
        )

    elif data == "profile":
        profile = db.get_user(user.id)
        rank = db.get_rank(user.id)
        daily_ready = db.is_daily_ready(user.id)
        daily_status = "✅ Ready!" if daily_ready else "⏳ Claimed"
        await query.edit_message_text(
            f"👤 *Profile*\n\n"
            f"💰 Coins: `{profile['coins']}`\n"
            f"🏆 Rank: `#{rank}`\n"
            f"🎮 Played: `{profile['games_played']}`\n"
            f"✅ Wins: `{profile['wins']}` | ❌ Losses: `{profile['losses']}`\n"
            f"📅 Daily: {daily_status}",
            parse_mode="Markdown",
            reply_markup=profile_keyboard(daily_ready)
        )

    elif data == "leaderboard":
        top = db.get_leaderboard(10)
        user_rank = db.get_rank(user.id)
        medals = ["🥇", "🥈", "🥉"]
        lines = ["🏆 *TOP 10 LEADERBOARD*\n"]
        for i, row in enumerate(top):
            medal = medals[i] if i < 3 else f"`{i+1}.`"
            lines.append(f"{medal} *{row['username']}* — `{row['coins']} coins`")
        lines.append(f"\n📍 Your Rank: `#{user_rank}`")
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=leaderboard_keyboard()
        )

    elif data == "daily":
        result = db.claim_daily(user.id)
        if result["success"]:
            await query.edit_message_text(
                f"🎁 *Daily Bonus!*\n\n+*{result['amount']} coins* received!\n"
                f"💳 Balance: *{result['new_balance']} coins*\n\nCome back tomorrow! 🔄",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        else:
            await query.edit_message_text(
                f"⏳ Come back in *{result['hours_left']}h {result['minutes_left']}m*\n"
                f"💰 Balance: *{result['balance']} coins*",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )

    # ── GAME SELECTION ──
    elif data.startswith("game_"):
        game_name = data.split("_", 1)[1]
        context.user_data["current_game"] = game_name
        game_info = _get_game_info(game_name)
        await query.edit_message_text(
            game_info,
            parse_mode="Markdown",
            reply_markup=bet_keyboard(game_name)
        )

    # ── BETTING ──
    elif data.startswith("bet_"):
        parts = data.split("_")
        game_name = parts[1]
        amount = int(parts[2])
        await _start_game(query, context, user, game_name, amount, db)

    # ── CRASH GAME CASHOUT ──
    elif data == "crash_cashout":
        await CrashGame.cashout(query, context, user, db)

    # ── COIN FLIP CHOICE ──
    elif data.startswith("flip_"):
        choice = data.split("_")[1]
        amount = context.user_data.get("bet_amount", 50)
        await CoinFlipGame.play(query, context, user, db, amount, choice)

    # ── DICE CHOICE ──
    elif data.startswith("dice_"):
        choice = int(data.split("_")[1])
        amount = context.user_data.get("bet_amount", 50)
        await DiceGame.play(query, context, user, db, amount, choice)

    # ── NUMBER GUESS (via Lucky Spin) ──
    elif data.startswith("spin_"):
        amount = context.user_data.get("bet_amount", 50)
        await LuckySpinGame.play(query, context, user, db, amount)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _get_game_info(game_name: str) -> str:
    infos = {
        "dice": (
            "🎲 *DICE ROLL*\n\n"
            "Guess the dice number (1–6)!\n"
            "🎯 Win = *5x* your bet\n"
            "❌ Wrong = lose your bet\n\n"
            "Select your bet amount:"
        ),
        "coinflip": (
            "🪙 *COIN FLIP*\n\n"
            "Pick Heads or Tails!\n"
            "🎯 Win = *1.9x* your bet\n"
            "❌ Wrong = lose your bet\n\n"
            "Select your bet amount:"
        ),
        "luckyspin": (
            "🎰 *LUCKY SPIN*\n\n"
            "Spin the slot wheel!\n"
            "🍋🍋🍋 = *10x* | 🍒🍒🍒 = *5x*\n"
            "⭐⭐⭐ = *3x* | 🎯🎯🎯 = *2x*\n"
            "Mixed = 0x (lose)\n\n"
            "Select your bet amount:"
        ),
        "crash": (
            "⚡ *FAST CRASH*\n\n"
            "Watch the multiplier rise — cash out before it crashes!\n"
            "🚀 Cash out early = safe win\n"
            "💥 Wait too long = lose all!\n\n"
            "Select your bet amount:"
        ),
    }
    return infos.get(game_name, "Select bet:")


async def _start_game(query, context, user, game_name, amount, db):
    profile = db.get_user(user.id)
    if not profile or profile["coins"] < amount:
        await query.edit_message_text(
            f"❌ *Not enough coins!*\n\nYou need `{amount}` coins but have `{profile['coins'] if profile else 0}`.\n\n"
            f"Claim your daily bonus to get more! 🎁",
            parse_mode="Markdown",
            reply_markup=back_keyboard("games")
        )
        return

    context.user_data["bet_amount"] = amount
    context.user_data["current_game"] = game_name

    if game_name == "dice":
        from keyboards import dice_choice_keyboard
        await query.edit_message_text(
            f"🎲 *Dice Roll* — Bet: `{amount} coins`\n\nPick a number (1–6):",
            parse_mode="Markdown",
            reply_markup=dice_choice_keyboard()
        )
    elif game_name == "coinflip":
        from keyboards import coinflip_choice_keyboard
        await query.edit_message_text(
            f"🪙 *Coin Flip* — Bet: `{amount} coins`\n\nPick Heads or Tails:",
            parse_mode="Markdown",
            reply_markup=coinflip_choice_keyboard()
        )
    elif game_name == "luckyspin":
        await LuckySpinGame.play(query, context, user, db, amount)
    elif game_name == "crash":
        await CrashGame.start(query, context, user, db, amount)


def _win_rate(profile) -> float:
    played = profile.get("games_played", 0)
    wins = profile.get("wins", 0)
    if played == 0:
        return 0.0
    return round((wins / played) * 100, 1)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable not set!")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    app.add_handler(CommandHandler("daily", daily_cmd))
    app.add_handler(CommandHandler("games", games_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("🤖 Satta King Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
