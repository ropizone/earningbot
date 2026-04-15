import random
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from keyboards import games_keyboard, back_keyboard


# ──────────────────────────────────────────────
# 🎲 DICE ROLL
# ──────────────────────────────────────────────

class DiceGame:
    PAYOUT_MULTIPLIER = 5  # 5x if correct

    @staticmethod
    async def play(query, context, user, db, amount: int, choice: int):
        profile = db.get_user(user.id)
        if not profile or profile["coins"] < amount:
            await query.edit_message_text(
                "❌ Not enough coins!",
                reply_markup=back_keyboard("games")
            )
            return

        roll = random.randint(1, 6)
        dice_faces = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣"}

        won = (roll == choice)

        if won:
            payout = amount * DiceGame.PAYOUT_MULTIPLIER
            new_bal = db.record_game(user.id, "dice", amount, f"rolled {roll}", payout)
            text = (
                f"🎲 *DICE ROLL RESULT*\n\n"
                f"Your Pick: {dice_faces[choice]}\n"
                f"Rolled: {dice_faces[roll]}\n\n"
                f"🎉 *YOU WIN!*\n"
                f"💰 +`{payout - amount}` coins (5x payout!)\n"
                f"💳 Balance: `{new_bal}` coins"
            )
        else:
            new_bal = db.record_game(user.id, "dice", amount, f"rolled {roll}", 0)
            text = (
                f"🎲 *DICE ROLL RESULT*\n\n"
                f"Your Pick: {dice_faces[choice]}\n"
                f"Rolled: {dice_faces[roll]}\n\n"
                f"💥 *WRONG!*\n"
                f"❌ -`{amount}` coins\n"
                f"💳 Balance: `{new_bal}` coins"
            )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Play Again", callback_data="game_dice")],
            [InlineKeyboardButton("🎮 All Games", callback_data="games")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
        ])

        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)


# ──────────────────────────────────────────────
# 🪙 COIN FLIP
# ──────────────────────────────────────────────

class CoinFlipGame:
    PAYOUT_MULTIPLIER = 1.9

    @staticmethod
    async def play(query, context, user, db, amount: int, choice: str):
        profile = db.get_user(user.id)
        if not profile or profile["coins"] < amount:
            await query.edit_message_text(
                "❌ Not enough coins!",
                reply_markup=back_keyboard("games")
            )
            return

        result = random.choice(["heads", "tails"])
        won = (result == choice)

        heads_emoji = "👑"
        tails_emoji = "🌟"
        result_emoji = heads_emoji if result == "heads" else tails_emoji
        choice_emoji = heads_emoji if choice == "heads" else tails_emoji

        if won:
            payout = int(amount * CoinFlipGame.PAYOUT_MULTIPLIER)
            new_bal = db.record_game(user.id, "coinflip", amount, result, payout)
            text = (
                f"🪙 *COIN FLIP RESULT*\n\n"
                f"Your Pick: {choice_emoji} *{choice.title()}*\n"
                f"Result: {result_emoji} *{result.title()}*\n\n"
                f"🎉 *YOU WIN!*\n"
                f"💰 +`{payout - amount}` coins\n"
                f"💳 Balance: `{new_bal}` coins"
            )
        else:
            new_bal = db.record_game(user.id, "coinflip", amount, result, 0)
            text = (
                f"🪙 *COIN FLIP RESULT*\n\n"
                f"Your Pick: {choice_emoji} *{choice.title()}*\n"
                f"Result: {result_emoji} *{result.title()}*\n\n"
                f"💥 *WRONG SIDE!*\n"
                f"❌ -`{amount}` coins\n"
                f"💳 Balance: `{new_bal}` coins"
            )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🪙 Play Again", callback_data="game_coinflip")],
            [InlineKeyboardButton("🎮 All Games", callback_data="games")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
        ])

        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)


# ──────────────────────────────────────────────
# 🎰 LUCKY SPIN
# ──────────────────────────────────────────────

SLOT_SYMBOLS = ["🍋", "🍒", "🍇", "⭐", "🎯", "💎", "🔔", "🍀"]

SLOT_PAYOUTS = {
    "💎💎💎": 20,
    "🍒🍒🍒": 10,
    "⭐⭐⭐": 5,
    "🎯🎯🎯": 4,
    "🔔🔔🔔": 3,
    "🍀🍀🍀": 3,
    "🍋🍋🍋": 2,
    "🍇🍇🍇": 2,
}


class LuckySpinGame:
    @staticmethod
    async def play(query, context, user, db, amount: int):
        profile = db.get_user(user.id)
        if not profile or profile["coins"] < amount:
            await query.edit_message_text(
                "❌ Not enough coins!",
                reply_markup=back_keyboard("games")
            )
            return

        # Animated spinning message
        await query.edit_message_text(
            f"🎰 *SPINNING...*\n\n"
            f"[ 🔄 | 🔄 | 🔄 ]\n\n"
            f"Bet: `{amount}` coins",
            parse_mode="Markdown"
        )

        await asyncio.sleep(1.2)

        # Spin with weighted probabilities (jackpot is rare)
        weights = [30, 25, 20, 15, 10, 5, 5, 5, 5, 3, 2, 1]
        s1 = random.choices(SLOT_SYMBOLS, weights=weights[:len(SLOT_SYMBOLS)], k=1)[0]
        s2 = random.choices(SLOT_SYMBOLS, weights=weights[:len(SLOT_SYMBOLS)], k=1)[0]
        s3 = random.choices(SLOT_SYMBOLS, weights=weights[:len(SLOT_SYMBOLS)], k=1)[0]

        result_str = f"{s1}{s2}{s3}"
        multiplier = SLOT_PAYOUTS.get(result_str, 0)

        if multiplier > 0:
            payout = amount * multiplier
            new_bal = db.record_game(user.id, "luckyspin", amount, result_str, payout)
            text = (
                f"🎰 *LUCKY SPIN RESULT*\n\n"
                f"┌─────────────┐\n"
                f"│  {s1}  {s2}  {s3}  │\n"
                f"└─────────────┘\n\n"
                f"🎉 *{multiplier}x WINNER!*\n"
                f"💰 +`{payout - amount}` coins\n"
                f"💳 Balance: `{new_bal}` coins"
            )
        else:
            new_bal = db.record_game(user.id, "luckyspin", amount, result_str, 0)
            text = (
                f"🎰 *LUCKY SPIN RESULT*\n\n"
                f"┌─────────────┐\n"
                f"│  {s1}  {s2}  {s3}  │\n"
                f"└─────────────┘\n\n"
                f"💥 *NO MATCH!*\n"
                f"❌ -`{amount}` coins\n"
                f"💳 Balance: `{new_bal}` coins"
            )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎰 Spin Again", callback_data="game_luckyspin")],
            [InlineKeyboardButton("🎮 All Games", callback_data="games")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
        ])

        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)


# ──────────────────────────────────────────────
# ⚡ FAST CRASH
# ──────────────────────────────────────────────

class CrashGame:
    @staticmethod
    def _generate_crash_point() -> float:
        """Generate crash point with house edge. Most crash under 2x."""
        r = random.random()
        if r < 0.40:
            return round(random.uniform(1.0, 1.5), 2)
        elif r < 0.65:
            return round(random.uniform(1.5, 2.5), 2)
        elif r < 0.82:
            return round(random.uniform(2.5, 5.0), 2)
        elif r < 0.93:
            return round(random.uniform(5.0, 10.0), 2)
        elif r < 0.98:
            return round(random.uniform(10.0, 50.0), 2)
        else:
            return round(random.uniform(50.0, 200.0), 2)

    @staticmethod
    async def start(query, context, user, db, amount: int):
        profile = db.get_user(user.id)
        if not profile or profile["coins"] < amount:
            await query.edit_message_text(
                "❌ Not enough coins!",
                reply_markup=back_keyboard("games")
            )
            return

        crash_point = CrashGame._generate_crash_point()
        context.user_data["crash_point"] = crash_point
        context.user_data["crash_bet"] = amount
        context.user_data["crashed"] = False

        # Deduct bet immediately
        db.update_coins(user.id, -amount)

        cashout_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 CASH OUT NOW!", callback_data="crash_cashout")],
        ])

        await query.edit_message_text(
            f"⚡ *FAST CRASH*\n\n"
            f"Bet: `{amount}` coins locked in!\n\n"
            f"🚀 *Multiplier rising...*\n"
            f"Current: `1.00x`\n\n"
            f"⚠️ Cash out before it crashes!\n"
            f"The longer you wait, the more you win — or lose everything!",
            parse_mode="Markdown",
            reply_markup=cashout_kb
        )

        # Schedule crash after random delay
        asyncio.create_task(
            CrashGame._auto_crash(query, context, user, db, amount, crash_point)
        )

    @staticmethod
    async def _auto_crash(query, context, user, db, amount, crash_point):
        """Auto-crash the game after a delay based on crash point."""
        # Delay scales with crash point (higher = more time to cash out)
        delay = min(crash_point * 0.8, 8.0)
        await asyncio.sleep(delay)

        if context.user_data.get("crashed"):
            return  # Already cashed out

        context.user_data["crashed"] = True

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Play Again", callback_data="game_crash")],
            [InlineKeyboardButton("🎮 All Games", callback_data="games")],
        ])

        try:
            await query.edit_message_text(
                f"⚡ *CRASH RESULT*\n\n"
                f"💥 *CRASHED AT {crash_point}x!*\n\n"
                f"❌ You were too slow!\n"
                f"Lost: `{amount}` coins\n\n"
                f"Try to cash out faster next time!",
                parse_mode="Markdown",
                reply_markup=kb
            )
        except Exception:
            pass  # Message may have been edited already

    @staticmethod
    async def cashout(query, context, user, db):
        if context.user_data.get("crashed"):
            await query.answer("💥 Already crashed!", show_alert=True)
            return

        context.user_data["crashed"] = True
        crash_point = context.user_data.get("crash_point", 1.5)
        amount = context.user_data.get("crash_bet", 50)

        # Random cashout multiplier (between 1.0 and crash_point)
        cashout_mult = round(random.uniform(1.1, crash_point), 2)
        payout = int(amount * cashout_mult)
        net = payout - amount

        # Add winnings back (bet was already deducted)
        new_bal = db.update_coins(user.id, payout)

        # Record in history
        db.record_game(user.id, "crash", amount,
                       f"cashout@{cashout_mult}x (crash@{crash_point}x)", payout)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Play Again", callback_data="game_crash")],
            [InlineKeyboardButton("🎮 All Games", callback_data="games")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
        ])

        await query.edit_message_text(
            f"⚡ *CRASH RESULT*\n\n"
            f"✅ *Cashed out at {cashout_mult}x!*\n"
            f"🚨 Crashed at: `{crash_point}x`\n\n"
            f"💰 +`{net}` coins profit!\n"
            f"💳 Balance: `{new_bal}` coins",
            parse_mode="Markdown",
            reply_markup=kb
        )
