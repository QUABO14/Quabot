import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import datetime
import os
import sqlite3
import asyncio
from flask import Flask
from threading import Thread

# ================= KEEP ALIVE =================
app = Flask(__name__)

@app.route("/")
def home():
    return "🤖 Bot is alive", 200

def keep_alive():
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()

# ================= DB =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS warnings (user_id INTEGER PRIMARY KEY, count INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS tickets (channel_id INTEGER, user_id INTEGER)")
conn.commit()

# ================= 환경 =================
TOKEN = os.getenv("TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

WELCOME_CHANNEL_ID = 1496478743873589448
LOG_CHANNEL_ID = 1496478745538855146
TICKET_CATEGORY_ID = 1496840441654677614
VERIFY_ROLE_ID = 1496479066075697234

# ================= 봇 =================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= 유틸 =================
def now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def embed(title, desc="", color=0x5865F2):
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = datetime.datetime.utcnow()
    return e

async def log(msg):
    ch = bot.get_channel(LOG_CHANNEL_ID)
    if ch:
        await ch.send(embed=embed("📜 로그", msg))

# ================= 경고 =================
def get_warn(uid):
    cursor.execute("SELECT count FROM warnings WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r[0] if r else 0

def add_warn(uid):
    count = get_warn(uid) + 1
    cursor.execute("REPLACE INTO warnings VALUES(?,?)", (uid, count))
    conn.commit()
    return count

async def auto_punish(member, count):
    try:
        if count == 1:
            await member.timeout(datetime.timedelta(minutes=10))
            return "타임아웃 10분"
        elif count == 2:
            await member.timeout(datetime.timedelta(hours=1))
            return "타임아웃 1시간"
        elif count == 3:
            await member.timeout(datetime.timedelta(days=1))
            return "타임아웃 1일"
        elif count == 4:
            await member.kick()
            return "킥"
        elif count == 5:
            await member.ban()
            return "밴"
    except Exception as e:
        return f"처벌 실패: {e}"

# ================= 티켓 =================
class CloseTicket(View):
    @discord.ui.button(label="🔒 닫기", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("5초 후 삭제됨")
        await log(f"티켓 종료: {interaction.channel.name}")
        await asyncio.sleep(5)
        await interaction.channel.delete()

class TicketModal(Modal, title="티켓 생성"):
    title_input = TextInput(label="제목")

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild

        cursor.execute("SELECT * FROM tickets WHERE user_id=?", (interaction.user.id,))
        if cursor.fetchone():
            return await interaction.response.send_message("이미 티켓 있음", ephemeral=True)

        category = guild.get_channel(TICKET_CATEGORY_ID)
        ch = await guild.create_text_channel(
            name=f"ticket-{interaction.user.id}",
            category=category
        )

        cursor.execute("INSERT INTO tickets VALUES(?,?)", (ch.id, interaction.user.id))
        conn.commit()

        await ch.send(f"{interaction.user.mention} 티켓 생성", view=CloseTicket())
        await interaction.response.send_message(f"생성됨: {ch.mention}", ephemeral=True)
        await log(f"티켓 생성: {interaction.user}")

class TicketView(View):
    @discord.ui.button(label="🎫 티켓 열기", style=discord.ButtonStyle.blurple)
    async def ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(TicketModal())

# ================= 인증 =================
class Verify(View):
    @discord.ui.button(label="인증", style=discord.ButtonStyle.green)
    async def verify(self, interaction: discord.Interaction, button: Button):
        role = interaction.guild.get_role(VERIFY_ROLE_ID)
        if not role:
            return await interaction.response.send_message("역할 없음", ephemeral=True)

        await interaction.user.add_roles(role)
        await interaction.response.send_message("인증 완료", ephemeral=True)
        await log(f"인증: {interaction.user}")

# ================= 명령어 =================
@bot.tree.command(name="경고")
async def warn(interaction: discord.Interaction, user: discord.Member, 이유: str):
    count = add_warn(user.id)
    result = await auto_punish(user, count)

    msg = f"{user.mention} 경고 {count}회\n이유: {이유}"
    if result:
        msg += f"\n처벌: {result}"

    await interaction.response.send_message(embed=embed("⚠️ 경고", msg))
    await log(msg)

@bot.tree.command(name="티켓패널")
async def ticket_panel(interaction: discord.Interaction):
    await interaction.response.send_message(embed=embed("티켓"), view=TicketView())

@bot.command()
async def 인증패널(ctx):
    await ctx.send(embed=embed("인증"), view=Verify())

# ================= 입장 =================
@bot.event
async def on_member_join(member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await ch.send(embed=embed("환영", f"{member.mention} 환영"))

# ================= AI =================
from openai import OpenAI

client_ai = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None
user_memory = {}

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.content.startswith("!ai") and client_ai:
        user_id = message.author.id
        user_input = message.content[3:].strip()

        if user_id not in user_memory:
            user_memory[user_id] = [{"role": "system", "content": "친근한 디스코드 AI"}]

        user_memory[user_id].append({"role": "user", "content": user_input})

        try:
            res = client_ai.responses.create(
                model="gpt-4.1-mini",
                input=user_memory[user_id]
            )
            reply = getattr(res, "output_text", "(응답 없음)")

            user_memory[user_id].append({"role": "assistant", "content": reply})
            user_memory[user_id] = user_memory[user_id][-20:]

            await message.channel.send(embed=embed("🤖 AI", reply[:2000]))
        except Exception as e:
            await message.channel.send(f"❌ 오류: {e}")

    await bot.process_commands(message)

# ================= 실행 =================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print("🔥 봇 실행 완료")

keep_alive()

try:
    bot.run(TOKEN)
except Exception as e:
    print("🔥 실행 오류:", e)
