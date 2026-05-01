import discord
from discord.ext import commands
import datetime
import os
import sqlite3
import asyncio
from flask import Flask
from threading import Thread

# ================= 환경 =================
TOKEN = os.getenv("TOKEN")

LOG_CHANNEL_ID = 1496478745538855146
WELCOME_CHANNEL_ID = 1496478743873589448
VERIFY_ROLE_ID = 1496479066075697234
TICKET_CATEGORY_ID = 1496840441654677614
STAFF_ROLE_ID = 1499592576712577138

# ================= Flask (UptimeRobot 핵심) =================
app = Flask(__name__)

@app.route("/")
def home():
    return "OK - Bot Alive"

def run_web():
    port = int(os.environ.get("PORT", 10000))  # 🔥 Render 필수
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    Thread(target=run_web, daemon=True).start()

# ================= DB =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.execute("CREATE TABLE IF NOT EXISTS warnings (user_id INTEGER PRIMARY KEY, count INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS levels (user_id INTEGER PRIMARY KEY, xp INTEGER, level INTEGER)")
    conn.commit()

# ================= Bot =================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= Utils =================
def embed(title, desc="", color=0x5865F2):
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = datetime.datetime.utcnow()
    return e

async def safe_send(channel, **kwargs):
    try:
        await channel.send(**kwargs)
    except:
        pass

# ================= 권한 =================
def is_staff(member):
    return any(r.id == STAFF_ROLE_ID for r in member.roles)

# ================= 경고 =================
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

async def auto_punish(member, c):
    try:
        if c == 1:
            await member.timeout(datetime.timedelta(minutes=10))
        elif c == 2:
            await member.timeout(datetime.timedelta(hours=1))
        elif c == 3:
            await member.timeout(datetime.timedelta(days=1))
        elif c == 4:
            await member.kick()
        elif c >= 5:
            await member.ban()
    except:
        pass

# ================= 레벨 =================
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

# ================= 티켓 =================
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

# ================= 인증 =================
class VerifyView(discord.ui.View):
    @discord.ui.button(label="인증", style=discord.ButtonStyle.success)
    async def verify(self, i, b):
        role = i.guild.get_role(VERIFY_ROLE_ID)
        await i.user.add_roles(role)
        await i.response.send_message("인증 완료", ephemeral=True)

# ================= 이벤트 =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print("🔥 BOT READY - SERVICE MODE")

@bot.event
async def on_member_join(m):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await safe_send(ch, embed=embed("환영", m.mention))

@bot.event
async def on_message(m):
    if m.author.bot:
        return

    try:
        lv, xp = add_xp(m.author.id)
        if xp == 0:
            await m.channel.send(f"{m.author.mention} 레벨업 {lv}")
    except:
        pass

    await bot.process_commands(m)

# ================= 명령어 =================
@bot.command()
async def 인증패널(ctx):
    if not is_staff(ctx.author):
        return await ctx.reply("❌ 권한 없음")
    await ctx.send(embed=embed("인증"), view=VerifyView())

@bot.command()
async def 티켓패널(ctx):
    await ctx.send(embed=embed("티켓"), view=TicketView())

@bot.command()
async def 경고(ctx, user: discord.Member, 이유="없음"):
    if not is_staff(ctx.author):
        return await ctx.reply("❌ 권한 없음")

    c = add_warn(user.id)
    await auto_punish(user, c)

    await ctx.send(embed=embed("경고", f"{user.mention} {c}회 | {이유}"))

@bot.command()
async def 경고취소(ctx, user: discord.Member):
    if not is_staff(ctx.author):
        return await ctx.reply("❌ 권한 없음")

    c = remove_warn(user.id)
    await ctx.send(embed=embed("경고 감소", f"{user.mention} {c}회"))

@bot.command()
async def 경고확인(ctx, user: discord.Member):
    c = get_warn(user.id)
    await ctx.send(embed=embed("경고 확인", f"{user.mention} {c}회"))

# ================= 실행 =================
async def main():
    keep_alive()
    await bot.start(TOKEN)

asyncio.run(main())
