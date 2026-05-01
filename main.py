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

BOT_ADMIN_ROLE_ID = 1499675598178750561

# ================= WEB =================
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

# ================= EMBED =================
def embed(title, desc="", color=0x5865F2):
    e = discord.Embed(title=title, description=desc, color=color)
    e.set_footer(text="운영 시스템")
    e.timestamp = datetime.datetime.utcnow()
    return e

# ================= PERMISSION =================
def is_bot_admin(member):
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
    @discord.ui.button(label="🔒 닫기", style=discord.ButtonStyle.danger)
    async def close(self, i, b):
        await i.response.send_message(embed=embed("티켓", "⛔ 3초 후 삭제됩니다"))
        await asyncio.sleep(3)
        await i.channel.delete()

class TicketView(discord.ui.View):
    @discord.ui.button(label="🎫 티켓 생성", style=discord.ButtonStyle.primary)
    async def create(self, i, b):
        cat = i.guild.get_channel(TICKET_CATEGORY_ID)
        ch = await i.guild.create_text_channel(
            name=f"ticket-{i.user.id}",
            category=cat
        )

        await ch.send(
            embed=embed(
                "🎫 티켓 생성됨",
                f"{i.user.mention}\n\n관리자가 곧 도와드립니다."
            ),
            view=CloseView()
        )

        await i.response.send_message(
            embed=embed("성공", "티켓이 생성되었습니다"),
            ephemeral=True
        )

# ================= VERIFY =================
class VerifyView(discord.ui.View):
    @discord.ui.button(label="✅ 인증하기", style=discord.ButtonStyle.success)
    async def verify(self, i, b):
        role = discord.utils.get(i.guild.roles, id=BOT_ADMIN_ROLE_ID)

        if role:
            await i.user.add_roles(role)

        await i.response.send_message(
            embed=embed("인증 완료", "서버 이용이 가능합니다"),
            ephemeral=True
        )

# ================= EVENTS =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print("🔥 OPERATING BOT READY")

@bot.event
async def on_member_join(m):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await ch.send(embed=embed("👋 환영합니다", f"{m.mention} 님 입장"))

@bot.event
async def on_message(m):
    if m.author.bot:
        return

    lv, xp = add_xp(m.author.id)

    if xp == 0:
        await m.channel.send(
            embed=embed("📈 레벨업", f"{m.author.mention} → LV {lv}")
        )

    await bot.process_commands(m)

# ================= SLASH COMMANDS =================

@bot.tree.command(name="경고")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str = "없음"):

    if not is_bot_admin(interaction.user):
        return await interaction.response.send_message(
            embed=embed("권한 오류", "봇 관리자만 사용 가능", 0xFF0000),
            ephemeral=True
        )

    count = add_warn(user.id)

    log = discord.Embed(
        title="⚠️ 경고 발급",
        description=f"""
👤 대상: {user.mention}
👮 관리자: {interaction.user.mention}
📌 사유: {reason}
🔢 누적 경고: {count}회
        """,
        color=0xFF5555
    )
    log.timestamp = datetime.datetime.utcnow()

    await interaction.response.send_message(embed=log)

    ch = bot.get_channel(LOG_CHANNEL_ID)
    if ch:
        await ch.send(embed=log)

@bot.tree.command(name="경고확인")
async def check(interaction: discord.Interaction, user: discord.Member):

    await interaction.response.send_message(
        embed=embed(
            "📊 경고 조회",
            f"👤 {user.mention}\n⚠️ {get_warn(user.id)}회"
        )
    )

@bot.tree.command(name="경고감소")
async def minus(interaction: discord.Interaction, user: discord.Member):

    if not is_bot_admin(interaction.user):
        return await interaction.response.send_message(
            embed=embed("권한 오류", "봇 관리자만 사용 가능", 0xFF0000),
            ephemeral=True
        )

    c = remove_warn(user.id)

    await interaction.response.send_message(
        embed=embed("📉 경고 감소", f"{user.mention} → {c}회")
    )

@bot.tree.command(name="티켓패널")
async def ticket(interaction: discord.Interaction):

    await interaction.response.send_message(
        embed=embed(
            "🎫 티켓 시스템",
            "문제가 있으면 아래 버튼을 눌러주세요"
        ),
        view=TicketView()
    )

@bot.tree.command(name="인증패널")
async def verify_panel(interaction: discord.Interaction):

    await interaction.response.send_message(
        embed=embed(
            "🔐 인증 시스템",
            "아래 버튼을 눌러 인증을 진행하세요"
        ),
        view=VerifyView()
    )

# ================= RUN =================
async def main():
    keep_alive()
    await bot.start(TOKEN)

asyncio.run(main())
