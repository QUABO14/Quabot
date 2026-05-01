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

VERIFY_ROLE_ID = 1499675598178750560  # 인증 역할
ADMIN_ROLE_ID = 1499675598178750561    # 봇 관리자 역할

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
    cursor.execute("CREATE TABLE IF NOT EXISTS warnings (user_id INTEGER PRIMARY KEY, count INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS levels (user_id INTEGER PRIMARY KEY, xp INTEGER, level INTEGER)")
    conn.commit()

# ================= BOT =================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= UTIL =================
def embed(title, desc="", color=0x5865F2):
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = datetime.datetime.utcnow()
    return e

def is_admin(member: discord.Member):
    return any(role.id == ADMIN_ROLE_ID for role in member.roles)

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
        await i.response.send_message("삭제됩니다")
        await asyncio.sleep(3)
        await i.channel.delete()

class TicketView(discord.ui.View):
    @discord.ui.button(label="티켓 생성", style=discord.ButtonStyle.primary)
    async def create(self, i, b):
        cat = i.guild.get_channel(TICKET_CATEGORY_ID)

        ch = await i.guild.create_text_channel(
            name=f"ticket-{i.user.id}",
            category=cat
        )

        await ch.send(
            embed=embed("티켓 생성됨", f"{i.user.mention}"),
            view=CloseView()
        )

        await i.response.send_message("티켓 생성 완료", ephemeral=True)

# ================= VERIFY =================
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
            await i.user.send(
                embed=embed("인증 완료", "서버 이용이 가능합니다")
            )
        except:
            pass

        await i.response.send_message(
            embed=embed("완료", "인증 역할 지급됨"),
            ephemeral=True
        )

# ================= EVENTS =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print("🔥 BOT READY (STABLE VERSION)")

@bot.event
async def on_member_join(member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)

    if ch:
        await ch.send(embed=embed("환영", f"{member.mention}"))

    try:
        await member.send(embed=embed("환영", "서버에 오신 것을 환영합니다"))
    except:
        pass

@bot.event
async def on_message(m):
    if m.author.bot:
        return

    lv, xp = add_xp(m.author.id)

    if xp == 0:
        await m.channel.send(f"{m.author.mention} 레벨업 {lv}")

    await bot.process_commands(m)

# ================= SLASH COMMANDS =================

@bot.tree.command(name="경고")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str = "없음"):

    if not is_admin(interaction.user):
        return await interaction.response.send_message("권한 없음", ephemeral=True)

    c = add_warn(user.id)

    await interaction.response.send_message(
        embed=embed("경고", f"{user.mention} | {c}회 | {reason}")
    )

@bot.tree.command(name="경고확인")
async def check(interaction: discord.Interaction, user: discord.Member):

    await interaction.response.send_message(
        embed=embed("경고 확인", f"{user.mention} → {get_warn(user.id)}회")
    )

@bot.tree.command(name="경고감소")
async def minus(interaction: discord.Interaction, user: discord.Member):

    if not is_admin(interaction.user):
        return await interaction.response.send_message("권한 없음", ephemeral=True)

    c = remove_warn(user.id)

    await interaction.response.send_message(
        embed=embed("경고 감소", f"{user.mention} → {c}회")
    )

@bot.tree.command(name="티켓패널")
async def ticket(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=embed("티켓 시스템"),
        view=TicketView()
    )

@bot.tree.command(name="인증패널")
async def verify(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=embed("인증 시스템", "버튼을 눌러 인증하세요"),
        view=VerifyView()
    )

# ================= RUN =================
async def main():
    keep_alive()
    await bot.start(TOKEN)

asyncio.run(main())
