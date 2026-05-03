import asyncio
import datetime
import os
import random
import sqlite3
from threading import Thread

import discord
from discord.ext import commands
from flask import Flask

# ================== CONFIG ==================
TOKEN = os.getenv("TOKEN")
SALARY_AMOUNT = 100000
SALARY_COOLDOWN = 10
ATTENDANCE_AMOUNT = 500000

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
salary_cd = {}

# ================== KEEP ALIVE ==================
app = Flask(__name__)
@app.route("/")
def home(): return "BOT ONLINE", 200

def keep_alive():
    port = int(os.environ.get("PORT", 10000))
    Thread(target=lambda: app.run(host="0.0.0.0", port=port, use_reloader=False), daemon=True).start()

# ================== DB ==================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

def init_db():
    tables = [
        "money (uid INTEGER PRIMARY KEY, bal INTEGER DEFAULT 0)",
        "attendance (uid INTEGER PRIMARY KEY, date TEXT)",
        "warn (uid INTEGER PRIMARY KEY, cnt INTEGER DEFAULT 0)",
        "party (guild_id INTEGER, owner_id INTEGER, voice_id INTEGER, PRIMARY KEY (guild_id, owner_id))",
        "guild_config (guild_id INTEGER PRIMARY KEY, verify_role INTEGER, admin_role INTEGER, welcome_ch INTEGER, log_ch INTEGER, levelup_ch INTEGER, party_cat INTEGER)",
        "sticky (channel_id INTEGER PRIMARY KEY, guild_id INTEGER, content TEXT, message_id INTEGER)",
        "levels (guild_id INTEGER, uid INTEGER, xp INTEGER DEFAULT 0, lv INTEGER DEFAULT 0, last_msg INTEGER DEFAULT 0, PRIMARY KEY (guild_id, uid))"
    ]
    for table in tables:
        cur.execute(f"CREATE TABLE IF NOT EXISTS {table}")
    conn.commit()

# ================== EMBEDS ==================
def base_embed(title, desc="", color=0x5865F2):
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = datetime.datetime.utcnow()
    return e

# ================== LOGIC ==================
def get_cfg(guild_id):
    cur.execute("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    keys = ["gid", "v_role", "a_role", "w_ch", "l_ch", "lu_ch", "p_cat"]
    return dict(zip(keys, row)) if row else {k: None for k in keys}

def money(uid):
    cur.execute("SELECT bal FROM money WHERE uid=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

# ================== MAIN LOOP ==================
@bot.event
async def on_ready():
    init_db()
    keep_alive()
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot: return
    # 레벨업 로직 추가
    await bot.process_commands(message)

# ================== RUN ==================
if __name__ == "__main__":
    if not TOKEN: exit("Token not found")
    bot.run(TOKEN)