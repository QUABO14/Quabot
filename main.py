import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
import datetime
import os

# =========================
# 🔥 ID 설정
# =========================
WELCOME_CHANNEL_ID = 1496478743873589448
LOG_CHANNEL_ID = 1496478745538855146
TICKET_CATEGORY_ID = 1496840441654677614
VERIFY_ROLE_ID = 1496479066075697234

TOKEN = os.getenv("TOKEN")

# =========================
# 🌐 슬립 방지 (Render용)
# =========================
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "alive"

def run():
    app.run(host='0.0.0.0', port=10000)

def keep_alive():
    Thread(target=run).start()

# =========================
# 🤖 봇 기본 설정
# =========================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

warnings = {}

# =========================
# 🔐 인증
# =========================
class VerifyView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="인증하기", style=discord.ButtonStyle.green)
    async def verify(self, interaction: discord.Interaction, button: Button):
        role = interaction.guild.get_role(VERIFY_ROLE_ID)
        if role:
            await interaction.user.add_roles(role)
        await interaction.response.send_message("✅ 인증 완료", ephemeral=True)

# =========================
# 🎫 티켓
# =========================
class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="티켓 생성", style=discord.ButtonStyle.blurple)
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True)
        }

        ch = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category,
            overwrites=overwrites
        )

        embed = discord.Embed(title="🎫 티켓 생성됨", description="문의 내용을 작성해주세요!", color=0x5865F2)
        await ch.send(embed=embed, view=CloseView())

        await interaction.response.send_message(f"{ch.mention} 생성됨", ephemeral=True)

class CloseView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="닫기", style=discord.ButtonStyle.red)
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.channel.delete()

# =========================
# 👋 입장 / 퇴장
# =========================
@bot.event
async def on_member_join(member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        embed = discord.Embed(title="👋 환영합니다!", color=0x00ffcc)
        embed.add_field(name="유저", value=member.mention)
        embed.add_field(name="ID", value=member.id)
        embed.add_field(name="가입일", value=member.created_at.strftime("%Y-%m-%d"))
        embed.add_field(name="입장일", value=datetime.datetime.now().strftime("%Y-%m-%d"))
        await ch.send(embed=embed)

@bot.event
async def on_member_remove(member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await ch.send(f"{member} 나감")

# =========================
# 📜 로그
# =========================
async def log(msg):
    ch = bot.get_channel(LOG_CHANNEL_ID)
    if ch:
        await ch.send(msg)

# =========================
# ⚠️ 경고 시스템 + 자동처벌
# =========================
@bot.tree.command(name="경고")
async def warn(interaction: discord.Interaction, user: discord.Member, 이유: str):
    warnings[user.id] = warnings.get(user.id, 0) + 1
    count = warnings[user.id]

    await interaction.response.send_message(f"{user.mention} 경고 {count}회")
    await log(f"{user} 경고 {count}회 (이유: {이유})")

    if count == 3:
        await user.timeout(datetime.timedelta(minutes=10))
    elif count == 5:
        await user.kick()
    elif count >= 7:
        await user.ban()

@bot.tree.command(name="경고취소")
async def unwarn(interaction: discord.Interaction, user: discord.Member):
    warnings[user.id] = max(warnings.get(user.id, 0) - 1, 0)
    await interaction.response.send_message("경고 감소")

# =========================
# 🧹 채팅 청소
# =========================
@bot.tree.command(name="청소")
async def clear(interaction: discord.Interaction, 개수: int):
    await interaction.channel.purge(limit=개수)
    await interaction.response.send_message(f"{개수}개 삭제 완료", ephemeral=True)

# =========================
# 👑 관리자 패널
# =========================
class AdminPanel(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="공지", style=discord.ButtonStyle.blurple)
    async def announce(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("공지 내용 입력", ephemeral=True)

        def check(m):
            return m.author == interaction.user

        msg = await bot.wait_for("message", check=check)
        embed = discord.Embed(title="📢 공지", description=msg.content)
        await interaction.channel.send(embed=embed)

    @discord.ui.button(label="티켓 전체삭제", style=discord.ButtonStyle.red)
    async def delete_ticket(self, interaction: discord.Interaction, button: Button):
        count = 0
        for ch in interaction.guild.channels:
            if isinstance(ch, discord.TextChannel) and ch.category_id == TICKET_CATEGORY_ID:
                await ch.delete()
                count += 1

        await interaction.response.send_message(f"{count}개 삭제 완료", ephemeral=True)

@bot.tree.command(name="관리자패널")
async def admin_panel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ 관리자만 가능", ephemeral=True)
        return

    embed = discord.Embed(title="👑 관리자 패널")
    await interaction.response.send_message(embed=embed, view=AdminPanel())

# =========================
# 📢 명령어
# =========================
@bot.command()
async def 인증(ctx):
    await ctx.send("버튼 클릭", view=VerifyView())

@bot.tree.command(name="티켓")
async def ticket(interaction: discord.Interaction):
    embed = discord.Embed(title="🎫 티켓 생성")
    await interaction.response.send_message(embed=embed, view=TicketView())

# =========================
# 🚀 실행
# =========================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} 실행됨")

keep_alive()
bot.run(TOKEN)
