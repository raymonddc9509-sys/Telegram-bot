import os
import sqlite3
import asyncio
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID", "-1003773746541"))

if not TOKEN:
    raise Exception("BOT_TOKEN is missing!")

# =========================
# TIME (PH TIMEZONE)
# =========================

def now():
    return datetime.now(ZoneInfo("Asia/Manila"))

# =========================
# DATABASE
# =========================

conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    last_seen TEXT,
    warned INTEGER DEFAULT 0
)
""")
conn.commit()

# =========================
# DB FUNCTIONS
# =========================

def upsert_user(user_id, name):
    cursor.execute("""
    INSERT OR IGNORE INTO users (user_id, name, last_seen, warned)
    VALUES (?, ?, ?, 0)
    """, (user_id, name, now().isoformat()))

    cursor.execute("""
    UPDATE users
    SET name=?, last_seen=?
    WHERE user_id=?
    """, (name, now().isoformat(), user_id))

    conn.commit()

def update_photo(user_id, name):
    upsert_user(user_id, name)

    cursor.execute("""
    UPDATE users
    SET last_seen=?, warned=0
    WHERE user_id=?
    """, (now().isoformat(), user_id))

    conn.commit()

def set_warned(user_id):
    cursor.execute("""
    UPDATE users
    SET warned=1
    WHERE user_id=?
    """, (user_id,))
    conn.commit()

# =========================
# HANDLERS
# =========================

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    update_photo(user.id, user.first_name)

    await update.message.reply_text(
        f"📸 Thanks {user.first_name}! Photo recorded ✔"
    )

async def save_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        upsert_user(user.id, user.first_name)

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        upsert_user(member.id, member.first_name)

        await update.message.reply_text(
            f"🎉 Welcome {member.first_name}!\nSend photos daily 📸"
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running ✅")

# =========================
# AUTO CHECK (WARNING + KICK)
# =========================

async def check_users(app: Application):
    cursor.execute("SELECT user_id, name, last_seen, warned FROM users")
    users = cursor.fetchall()

    for user_id, name, last_seen, warned in users:
        try:
            last_time = datetime.fromisoformat(last_seen)
        except:
            continue

        diff = now() - last_time

        if diff >= timedelta(days=1) and warned == 0:
            try:
                await app.bot.send_message(
                    chat_id=GROUP_ID,
                    text=f"⚠️ {name}, please send a photo today or you will be removed tomorrow."
                )
                set_warned(user_id)
            except:
                pass

        if diff >= timedelta(days=2):
            try:
                await app.bot.ban_chat_member(
                    chat_id=GROUP_ID,
                    user_id=user_id
                )

                await app.bot.send_message(
                    chat_id=GROUP_ID,
                    text=f"🚫 {name} removed for 2 days no photo."
                )

                cursor.execute("DELETE FROM users WHERE user_id=?", (user_id,))
                conn.commit()

            except Exception as e:
                print("Kick error:", e)

# =========================
# SHIFT REMINDERS
# =========================

async def shift_reminder(app: Application):
    last_sent = ""

    messages = {
        "00:00": "🌙 Shift Started\n🕛 12:00 AM - 6:00 AM",
        "06:00": "☀️ Shift 6AM - 12PM",
        "12:00": "🌤 Shift 12PM - 6PM",
        "18:00": "🌆 Shift 6PM - 12AM",
    }

    while True:
        current = now().strftime("%H:%M")

        if current in messages and current != last_sent:
            try:
                await app.bot.send_message(
                    chat_id=GROUP_ID,
                    text=messages[current]
                )
                last_sent = current
            except Exception as e:
                print("Shift reminder error:", e)

        await asyncio.sleep(30)

# =========================
# SCHEDULER
# =========================

def start_scheduler(app: Application):

    async def user_loop():
        while True:
            await check_users(app)
            await asyncio.sleep(3600)

    asyncio.create_task(user_loop())
    asyncio.create_task(shift_reminder(app))

# =========================
# MAIN (RAILWAY FIXED)
# =========================

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_user))
    app.add_handler(CommandHandler("start", start))

    async def post_init(app: Application):
        start_scheduler(app)

    app.post_init = post_init

    print("Bot running...")

    try:
        app.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
    except Exception as e:
        print("Bot crashed:", e)
        sys.exit(1)

if __name__ == "__main__":
    main()