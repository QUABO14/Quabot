# ================== IMPORT ==================
import discord
from discord.ext import commands
import os
import sqlite3
import datetime
import asyncio
import random
from flask import Flask
from threading import Thread

# ================== CONFIG ==================
TOKEN = os.getenv("TOKEN")

VERIFY_ROLE_ID = 1499675598178750560

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================== KEEP ALIVE ==================
app = Flask(__name__)

@app.route("/")
def home():
    return "BOT ONLINE"

def run():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def keep_alive():
    Thread(target=run, daemon=True).start()

# ================== DB ==================
DB = sqlite3.connect("bot.db", check_same_thread=False)
CUR = DB.cursor()

def init_db():
    CUR.execute("""CREATE TABLE IF NOT EXISTS warn (
        guild_id INTEGER,
        user_id INTEGER,
        count INTEGER,
        PRIMARY KEY (guild_id, user_id)
    )""")

    CUR.execute("""CREATE TABLE IF NOT EXISTS warn_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER,
        user_id INTEGER,
        mod_id INTEGER,
        reason TEXT,
        time TEXT
    )""")

    CUR.execute("""CREATE TABLE IF NOT EXISTS channel (
        guild_id INTEGER PRIMARY KEY,
        welcome INTEGER,
        log INTEGER
    )""")

    DB.commit()

# ================== UTIL ==================
def embed(t, d="", c=0x5865F2):
    e = discord.Embed(title=t, description=d, color=c)
    e.timestamp = datetime.datetime.utcnow()
    return e

def is_admin(m: discord.Member):
    return m.guild_permissions.administrator

# ================== CHANNEL ==================
def set_channel(gid, key, val):
    CUR.execute("INSERT OR IGNORE INTO channel (guild_id) VALUES (?)", (gid,))
    CUR.execute(f"UPDATE channel SET {key}=? WHERE guild_id=?", (val, gid))
    DB.commit()

def get_channel(gid, key):
    CUR.execute(f"SELECT {key} FROM channel WHERE guild_id=?", (gid,))
    r = CUR.fetchone()
    return r[0] if r else None

# ================== WARNING SYSTEM 2.0 ==================
def get_warn(gid, uid):
    CUR.execute("SELECT count FROM warn WHERE guild_id=? AND user_id=?", (gid, uid))
    r = CUR.fetchone()
    return r[0] if r else 0

def add_warn_db(gid, uid):
    c = get_warn(gid, uid) + 1
    CUR.execute("REPLACE INTO warn VALUES (?,?,?)", (gid, uid, c))
    DB.commit()
    return c

def remove_warn_db(gid, uid):
    c = max(get_warn(gid, uid) - 1, 0)
    CUR.execute("REPLACE INTO warn VALUES (?,?,?)", (gid, uid, c))
    DB.commit()
    return c

def clear_warn_db(gid, uid):
    CUR.execute("REPLACE INTO warn VALUES (?,?,0)", (gid, uid))
    DB.commit()

def log_warn(gid, uid, mod, reason):
    CUR.execute("""
        INSERT INTO warn_log (guild_id, user_id, mod_id, reason, time)
        VALUES (?,?,?,?,?)
    """, (gid, uid, mod, reason, str(datetime.datetime.utcnow())))
    DB.commit()

# ================== PUNISH ==================
async def punish(member, count):
    try:
        if count == 1:
            await member.timeout(datetime.timedelta(minutes=10))
        elif count == 2:
            await member.timeout(datetime.timedelta(hours=1))
        elif count == 3:
            await member.timeout(datetime.timedelta(days=1))
        elif count == 4:
            await member.kick()
        elif count >= 5:
            await member.ban()
    except:
        pass

# ================== VERIFY ==================
class VerifyView(discord.ui.View):
    @discord.ui.button(label="인증", style=discord.ButtonStyle.success)
    async def v(self, i, b):

        role = i.guild.get_role(VERIFY_ROLE_ID)
        if not role:
            role = discord.utils.get(i.guild.roles, name="인증")
        if not role:
            role = await i.guild.create_role(name="인증")

        await i.user.add_roles(role)

        await i.response.send_message("인증 완료", ephemeral=True)

# ================== TICKET ==================
class Close(discord.ui.View):
    @discord.ui.button(label="닫기", style=discord.ButtonStyle.danger)
    async def c(self, i, b):
        await i.channel.delete()

class Ticket(discord.ui.View):
    @discord.ui.button(label="티켓 생성", style=discord.ButtonStyle.primary)
    async def t(self, i, b):

        ch = await i.guild.create_text_channel(f"ticket-{i.user.id}")
        await ch.send(i.user.mention, view=Close())

        await i.response.send_message("생성 완료", ephemeral=True)

# ================== EVENTS ==================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print("🔥 FINAL BOT READY")

@bot.event
async def on_member_join(m):
    ch_id = get_channel(m.guild.id, "welcome")
    if ch_id:
        ch = bot.get_channel(ch_id)
        if ch:
            await ch.send(embed=embed("환영", m.mention))

# ================== LEVEL ==================
xp_db = {}

def add_xp(uid):
    xp, lv = xp_db.get(uid, (0,1))
    xp += 10
    if xp >= lv*100:
        lv += 1
        xp = 0
    xp_db[uid] = (xp, lv)
    return lv, xp

@bot.event
async def on_message(m):
    if m.author.bot:
        return

    lv, xp = add_xp(m.author.id)
    if xp == 0:
        await m.channel.send(embed=embed("레벨업", f"{m.author.mention} → {lv}"))

    await bot.process_commands(m)

# ================== 경고 2.0 ==================
@bot.tree.command(name="경고")
async def warn(i, user: discord.Member, reason: str):

    if not is_admin(i.user):
        return await i.response.send_message("권한 없음", ephemeral=True)

    count = add_warn_db(i.guild.id, user.id)
    log_warn(i.guild.id, user.id, i.user.id, reason)

    await punish(user, count)

    await i.response.send_message(
        embed=embed("⚠️ 경고", f"{user.mention}\n{reason}\n누적: {count}")
    )

@bot.tree.command(name="경고확인")
async def warn_check(i, user: discord.Member):
    c = get_warn(i.guild.id, user.id)

    await i.response.send_message(embed=embed("경고 확인", f"{user.mention} → {c}회"))

@bot.tree.command(name="경고삭제")
async def warn_clear(i, user: discord.Member):

    if not is_admin(i.user):
        return await i.response.send_message("권한 없음", ephemeral=True)

    clear_warn_db(i.guild.id, user.id)
    await i.response.send_message(embed=embed("초기화", f"{user.mention}"))

# ================== SET CHANNEL ==================
@bot.tree.command(name="채널설정")
async def setch(i, 종류: str, 채널: discord.TextChannel):

    mp = {"입장":"welcome","로그":"log"}
    set_channel(i.guild.id, mp[종류], 채널.id)

    await i.response.send_message("설정 완료")

# ================== VERIFY PANEL ==================
@bot.tree.command(name="인증패널")
async def vp(i):
    e = embed("인증", "버튼 클릭")
    await i.response.send_message(embed=e, view=VerifyView())

# ================== TICKET PANEL ==================
@bot.tree.command(name="티켓패널")
async def tp(i):
    await i.response.send_message("티켓", view=Ticket())

# ================== RUN ==================
async def main():
    keep_alive()
    await bot.start(TOKEN)

asyncio.run(main())
