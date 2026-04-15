import sqlite3
import os
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

DB_PATH = os.environ.get("DB_PATH", "satta_bot.db")

SIGNUP_BONUS = 100
DAILY_MIN = 20
DAILY_MAX = 150


class Database:
    def __init__(self):
        self.db_path = DB_PATH
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id     INTEGER PRIMARY KEY,
                    username    TEXT    NOT NULL,
                    full_name   TEXT,
                    coins       INTEGER DEFAULT 100,
                    games_played INTEGER DEFAULT 0,
                    wins        INTEGER DEFAULT 0,
                    losses      INTEGER DEFAULT 0,
                    last_daily  TEXT,
                    joined_at   TEXT    DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    type        TEXT    NOT NULL,
                    amount      INTEGER NOT NULL,
                    balance     INTEGER NOT NULL,
                    description TEXT,
                    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS game_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    game        TEXT    NOT NULL,
                    bet         INTEGER NOT NULL,
                    result      TEXT    NOT NULL,
                    payout      INTEGER NOT NULL,
                    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );
            """)

    # ─────────────────────────────────────────
    # USER MANAGEMENT
    # ─────────────────────────────────────────

    def get_or_create_user(self, user_id: int, username: str, full_name: str):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()

            if row:
                return False, dict(row)

            conn.execute(
                "INSERT INTO users (user_id, username, full_name, coins) VALUES (?, ?, ?, ?)",
                (user_id, username, full_name, SIGNUP_BONUS)
            )
            conn.execute(
                "INSERT INTO transactions (user_id, type, amount, balance, description) VALUES (?, ?, ?, ?, ?)",
                (user_id, "bonus", SIGNUP_BONUS, SIGNUP_BONUS, "Signup bonus")
            )
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return True, dict(row)

    def get_user(self, user_id: int) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    def update_coins(self, user_id: int, delta: int) -> int:
        """Add or subtract coins. Returns new balance."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET coins = MAX(0, coins + ?) WHERE user_id = ?",
                (delta, user_id)
            )
            row = conn.execute(
                "SELECT coins FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return row["coins"]

    def record_game(self, user_id: int, game: str, bet: int, result: str, payout: int):
        """Record game result and update stats."""
        won = payout > 0
        net = payout - bet  # can be negative

        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET coins = MAX(0, coins + ?), games_played = games_played + 1, "
                "wins = wins + ?, losses = losses + ? WHERE user_id = ?",
                (net, 1 if won else 0, 0 if won else 1, user_id)
            )
            row = conn.execute(
                "SELECT coins FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            new_balance = row["coins"]

            conn.execute(
                "INSERT INTO game_history (user_id, game, bet, result, payout) VALUES (?, ?, ?, ?, ?)",
                (user_id, game, bet, result, payout)
            )
            conn.execute(
                "INSERT INTO transactions (user_id, type, amount, balance, description) VALUES (?, ?, ?, ?, ?)",
                (user_id, "game_win" if won else "game_loss", abs(net), new_balance, f"{game}: {result}")
            )
        return new_balance

    # ─────────────────────────────────────────
    # DAILY BONUS
    # ─────────────────────────────────────────

    def is_daily_ready(self, user_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT last_daily FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not row or not row["last_daily"]:
                return True
            last = datetime.fromisoformat(row["last_daily"])
            return datetime.utcnow() - last >= timedelta(hours=24)

    def claim_daily(self, user_id: int) -> Dict:
        user = self.get_user(user_id)
        if not user:
            return {"success": False, "error": "User not found"}

        if not self.is_daily_ready(user_id):
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT last_daily FROM users WHERE user_id = ?", (user_id,)
                ).fetchone()
                last = datetime.fromisoformat(row["last_daily"])
                diff = timedelta(hours=24) - (datetime.utcnow() - last)
                total_secs = int(diff.total_seconds())
                hours_left = total_secs // 3600
                minutes_left = (total_secs % 3600) // 60
            return {
                "success": False,
                "balance": user["coins"],
                "hours_left": hours_left,
                "minutes_left": minutes_left
            }

        amount = random.randint(DAILY_MIN, DAILY_MAX)
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET coins = coins + ?, last_daily = ? WHERE user_id = ?",
                (amount, datetime.utcnow().isoformat(), user_id)
            )
            row = conn.execute(
                "SELECT coins FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            new_balance = row["coins"]
            conn.execute(
                "INSERT INTO transactions (user_id, type, amount, balance, description) VALUES (?, ?, ?, ?, ?)",
                (user_id, "daily", amount, new_balance, "Daily bonus")
            )

        return {"success": True, "amount": amount, "new_balance": new_balance}

    # ─────────────────────────────────────────
    # LEADERBOARD
    # ─────────────────────────────────────────

    def get_leaderboard(self, limit: int = 10):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT username, coins, wins, games_played FROM users ORDER BY coins DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_rank(self, user_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT coins FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not row:
                return 0
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE coins > ?",
                (row["coins"],)
            ).fetchone()
            return count["cnt"] + 1
