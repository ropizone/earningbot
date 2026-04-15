from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎮 Play Games", callback_data="games"),
            InlineKeyboardButton("👤 Profile", callback_data="profile"),
        ],
        [
            InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard"),
            InlineKeyboardButton("🎁 Daily Bonus", callback_data="daily"),
        ],
    ])


def games_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎲 Dice Roll", callback_data="game_dice"),
            InlineKeyboardButton("🪙 Coin Flip", callback_data="game_coinflip"),
        ],
        [
            InlineKeyboardButton("🎰 Lucky Spin", callback_data="game_luckyspin"),
            InlineKeyboardButton("⚡ Fast Crash", callback_data="game_crash"),
        ],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ])


def bet_keyboard(game_name: str) -> InlineKeyboardMarkup:
    amounts = [10, 25, 50, 100, 250, 500]
    rows = []
    for i in range(0, len(amounts), 3):
        row = [
            InlineKeyboardButton(
                f"💰 {a}", callback_data=f"bet_{game_name}_{a}"
            )
            for a in amounts[i:i+3]
        ]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="games")])
    return InlineKeyboardMarkup(rows)


def coinflip_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👑 HEADS", callback_data="flip_heads"),
            InlineKeyboardButton("🌟 TAILS", callback_data="flip_tails"),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="games")],
    ])


def dice_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1️⃣", callback_data="dice_1"),
            InlineKeyboardButton("2️⃣", callback_data="dice_2"),
            InlineKeyboardButton("3️⃣", callback_data="dice_3"),
        ],
        [
            InlineKeyboardButton("4️⃣", callback_data="dice_4"),
            InlineKeyboardButton("5️⃣", callback_data="dice_5"),
            InlineKeyboardButton("6️⃣", callback_data="dice_6"),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="games")],
    ])


def profile_keyboard(daily_ready: bool) -> InlineKeyboardMarkup:
    daily_btn = (
        InlineKeyboardButton("🎁 Claim Daily!", callback_data="daily")
        if daily_ready
        else InlineKeyboardButton("⏳ Daily (wait)", callback_data="daily")
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 Play Games", callback_data="games"), daily_btn],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ])


def leaderboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎮 Play Games", callback_data="games"),
            InlineKeyboardButton("🏠 Menu", callback_data="main_menu"),
        ],
    ])


def back_keyboard(destination: str = "main_menu") -> InlineKeyboardMarkup:
    labels = {
        "main_menu": "🏠 Main Menu",
        "games": "🎮 Games",
    }
    label = labels.get(destination, "⬅️ Back")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=destination)]
    ])
