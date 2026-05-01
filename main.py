import discord
from discord.ext import commands
import os
import sqlite3
import datetime
import asyncio
from flask import Flask
from threading import Thread

# ================= CONFIG =================
TOKEN = os.getenv("TOKEN")

LOG_CHANNEL_ID = 1496478745538855146
WELCOME_CHANNEL_ID = 1496478743873589448
TICKET_CATEGORY_ID = 1496840441654677614
VERIFY_ROLE_ID = 1499675598178750560

# ================= KEEP ALIVE =================
app = Flask(__name__)

@app.route("/")
def home():
    return "BOT ONLINE"

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def keep_alive():
    Thread(target=run_web, daemon=True).start()

# ================= DB =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS guild_config (
        guild_id INTEGER PRIMARY KEY,
        admin_role_id INTEGER
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS warnings (
        user_id INTEGER PRIMARY KEY,
        count INTEGER
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS levels (
        user_id INTEGER PRIMARY KEY,
        xp INTEGER,
        level INTEGER
    )
    """)

    conn.commit()

# ================= BOT =================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= UTIL =================
def embed(title, desc="", color=0x5865F2):
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = datetime.datetime.utcnow()
    return e

# ================= SERVER ROLE SYSTEM =================
def get_admin_role_id(guild_id):
    cursor.execute(
        "SELECT admin_role_id FROM guild_config WHERE guild_id=?",
        (guild_id,)
    )
    r = cursor.fetchone()
    return r[0] if r else None

def is_admin(member: discord.Member):
    if member is None:
        return False

    if member.guild_permissions.administrator:
        return True

    role_id = get_admin_role_id(member.guild.id)
    if not role_id:
        return False

    return any(r.id == role_id for r in member.roles)

# ================= ROLE SET COMMAND =================
@bot.tree.command(name="역할", description="봇 관리자 역할 설정")
async def set_role(interaction: discord.Interaction, role: discord.Role):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ 서버 관리자만 설정 가능",
            ephemeral=True
        )

    cursor.execute(
        "REPLACE INTO guild_config VALUES(?, ?)",
        (interaction.guild.id, role.id)
    )
    conn.commit()

    await interaction.response.send_message(
        embed=embed("설정 완료", f"봇 관리자 역할 → {role.mention}")
    )

# ================= WARNING SYSTEM =================
def get_warn(uid):
    cursor.execute("SELECT count FROM warnings WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r[0] if r else 0

def add_warn(uid):
    c = get_warn(uid) + 1
    cursor.execute("REPLACE INTO warnings VALUES(?,?)", (uid, c))
    conn.commit()
    return c

def remove_warn(uid):
    c = max(get_warn(uid) - 1, 0)
    cursor.execute("REPLACE INTO warnings VALUES(?,?)", (uid, c))
    conn.commit()
    return c

# ================= LEVEL SYSTEM =================
def add_xp(uid):
    cursor.execute("SELECT xp,level FROM levels WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    xp, lv = r if r else (0, 1)

    xp += 10

    if xp >= lv * 100:
        lv += 1
        xp = 0

    cursor.execute("REPLACE INTO levels VALUES(?,?,?)", (uid, xp, lv))
    conn.commit()

    return lv, xp

# ================= VERIFY BUTTON =================
class VerifyView(discord.ui.View):
    @discord.ui.button(label="인증", style=discord.ButtonStyle.success)
    async def verify(self, i, b):

        role = i.guild.get_role(VERIFY_ROLE_ID)

        if role is None:
            role = discord.utils.get(i.guild.roles, name="인증")

        if role is None:
            role = await i.guild.create_role(name="인증")

        await i.user.add_roles(role)

        try:
            await i.user.send(embed=embed("인증 완료", "서버 이용 가능"))
        except:
            pass

        await i.response.send_message("인증 완료", ephemeral=True)

# ================= TICKET =================
class CloseView(discord.ui.View):
    @discord.ui.button(label="닫기", style=discord.ButtonStyle.danger)
    async def close(self, i, b):
        await i.response.send_message("삭제 중...")
        await asyncio.sleep(2)
        await i.channel.delete()

class TicketView(discord.ui.View):
    @discord.ui.button(label="티켓 생성", style=discord.ButtonStyle.primary)
    async def create(self, i, b):

        cat = i.guild.get_channel(TICKET_CATEGORY_ID)

        ch = await i.guild.create_text_channel(
            name=f"ticket-{i.user.id}",
            category=cat
        )

        await ch.send(i.user.mention, view=CloseView())

        await i.response.send_message("티켓 생성 완료", ephemeral=True)

# ================= EVENTS =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print("🔥 SERVER-AWARE BOT READY")

@bot.event
async def on_member_join(member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)

    if ch:
        await ch.send(embed=embed("환영", member.mention))

    try:
        await member.send(embed=embed("환영", "가입 감사합니다"))
    except:
        pass

@bot.event
async def on_message(m):
    if m.author.bot:
        return

    lv, xp = add_xp(m.author.id)

    if xp == 0:
        await m.channel.send(embed=embed("레벨업", f"{m.author.mention} → LV {lv}"))

    await bot.process_commands(m)

# ================= SLASH COMMANDS =================

@bot.tree.command(name="경고")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str = "없음"):

    member = interaction.guild.get_member(interaction.user.id)

    if not is_admin(member):
        return await interaction.response.send_message(
            embed=embed("권한 없음", "봇 관리자만 사용 가능", 0xFF0000),
            ephemeral=True
        )

    c = add_warn(user.id)

    await interaction.response.send_message(
        embed=embed("경고 발급", f"{user.mention}\n{reason}\n누적: {c}회")
    )

@bot.tree.command(name="경고확인")
async def check(interaction: discord.Interaction, user: discord.Member):

    await interaction.response.send_message(
        embed=embed("경고 확인", f"{user.mention} → {get_warn(user.id)}회")
    )

@bot.tree.command(name="경고감소")
async def minus(interaction: discord.Interaction, user: discord.Member):

    member = interaction.guild.get_member(interaction.user.id)

    if not is_admin(member):
        return await interaction.response.send_message(
            embed=embed("권한 없음", "봇 관리자만 사용 가능", 0xFF0000),
            ephemeral=True
        )

    c = remove_warn(user.id)

    await interaction.response.send_message(
        embed=embed("경고 감소", f"{user.mention} → {c}회")
    )

@bot.tree.command(name="인증패널")
async def verify_panel(interaction: discord.Interaction):
    await interaction.response.send_message("인증", view=VerifyView())

@bot.tree.command(name="티켓패널")
async def ticket_panel(interaction: discord.Interaction):
    await interaction.response.send_message("티켓", view=TicketView())

# ================= RUN =================
async def main():
    keep_alive()
    await bot.start(TOKEN)

asyncio.run(main())
