import discord
from discord.ext import commands
import datetime
import os
import sqlite3
import asyncio
from flask import Flask
from threading import Thread

# ================= CONFIG =================
TOKEN = os.getenv("TOKEN")

LOG_CHANNEL_ID = 1496478745538855146
WELCOME_CHANNEL_ID = 1496478743873589448
TICKET_CATEGORY_ID = 1496840441654677614

BOT_ADMIN_ROLE_ID = 1499675598178750561  # 🔴 봇 관리자 역할

# ================= WEB (Render keep alive) =================
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
        staff_role_id INTEGER
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

# ================= ROLE SYSTEM =================
async def get_staff_role(guild: discord.Guild):
    cursor.execute("SELECT staff_role_id FROM guild_config WHERE guild_id=?", (guild.id,))
    r = cursor.fetchone()

    if r:
        role = guild.get_role(r[0])
        if role:
            return role

    role = discord.utils.get(guild.roles, name="운영진")

    if role is None:
        role = await guild.create_role(name="운영진")

    cursor.execute("REPLACE INTO guild_config VALUES (?,?)", (guild.id, role.id))
    conn.commit()

    return role

def is_staff(member: discord.Member):
    cursor.execute("SELECT staff_role_id FROM guild_config WHERE guild_id=?", (member.guild.id,))
    r = cursor.fetchone()
    if not r:
        return False
    return any(role.id == r[0] for role in member.roles)

def is_bot_admin(member: discord.Member):
    return any(role.id == BOT_ADMIN_ROLE_ID for role in member.roles)

# ================= WARNING =================
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

# ================= LEVEL =================
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

# ================= TICKET =================
class CloseView(discord.ui.View):
    @discord.ui.button(label="닫기", style=discord.ButtonStyle.danger)
    async def close(self, i, b):
        await i.response.send_message("삭제됨")
        await asyncio.sleep(2)
        await i.channel.delete()

class TicketView(discord.ui.View):
    @discord.ui.button(label="티켓 생성", style=discord.ButtonStyle.primary)
    async def create(self, i, b):
        cat = i.guild.get_channel(TICKET_CATEGORY_ID)
        ch = await i.guild.create_text_channel(name=f"ticket-{i.user.id}", category=cat)
        await ch.send(i.user.mention, view=CloseView())
        await i.response.send_message("생성 완료", ephemeral=True)

# ================= VERIFY =================
class VerifyView(discord.ui.View):
    @discord.ui.button(label="인증", style=discord.ButtonStyle.success)
    async def verify(self, i, b):
        role = discord.utils.get(i.guild.roles, name="운영진")
        if role:
            await i.user.add_roles(role)
        await i.response.send_message("인증 완료", ephemeral=True)

# ================= EVENTS =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print("🔥 BOT READY (STABLE VERSION)")

@bot.event
async def on_member_join(m):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await ch.send(embed=embed("환영", m.mention))

@bot.event
async def on_message(m):
    if m.author.bot:
        return

    lv, xp = add_xp(m.author.id)
    if xp == 0:
        await m.channel.send(f"{m.author.mention} 레벨업 {lv}")

    await bot.process_commands(m)

# ================= SETUP =================
@bot.tree.command(name="setup")
async def setup(interaction: discord.Interaction):
    if not is_bot_admin(interaction.user):
        return await interaction.response.send_message("❌ 봇 관리자만 가능", ephemeral=True)

    role = await get_staff_role(interaction.guild)

    await interaction.response.send_message(
        f"✅ 설정 완료\n운영진 역할: {role.mention}",
        ephemeral=True
    )

# ================= COMMANDS =================
@bot.tree.command(name="경고")
async def warn(interaction: discord.Interaction, user: discord.Member):
    if not is_staff(interaction.user):
        return await interaction.response.send_message("❌ 권한 없음", ephemeral=True)

    c = add_warn(user.id)
    await interaction.response.send_message(embed=embed("경고", f"{user.mention} | {c}회"))

@bot.tree.command(name="경고확인")
async def check(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.send_message(embed=embed("경고", f"{user.mention} | {get_warn(user.id)}회"))

@bot.tree.command(name="경고감소")
async def minus(interaction: discord.Interaction, user: discord.Member):
    if not is_staff(interaction.user):
        return await interaction.response.send_message("❌ 권한 없음", ephemeral=True)

    c = remove_warn(user.id)
    await interaction.response.send_message(embed=embed("감소", f"{user.mention} | {c}회"))

@bot.tree.command(name="티켓패널")
async def ticket(interaction: discord.Interaction):
    await interaction.response.send_message("티켓", view=TicketView())

@bot.tree.command(name="인증패널")
async def verify_panel(interaction: discord.Interaction):
    await interaction.response.send_message("인증", view=VerifyView())

# ================= RUN =================
async def main():
    keep_alive()
    await bot.start(TOKEN)

asyncio.run(main())
