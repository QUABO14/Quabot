import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import datetime
import os
from flask import Flask
from threading import Thread

# ====================== 환경 설정 ======================
TOKEN              = os.getenv("TOKEN")
WELCOME_CHANNEL_ID = 1496478743873589448
LOG_CHANNEL_ID     = 1496478745538855146
TICKET_CATEGORY_ID = 1496840441654677614
VERIFY_ROLE_ID     = 1496479066075697234

# ====================== 색상 ======================
class Color:
    PRIMARY = 0x5865F2
    SUCCESS = 0x57F287
    WARNING = 0xFEE75C
    DANGER  = 0xED4245
    INFO    = 0x00CED1
    DARK    = 0x2B2D31

# ====================== 유틸 ======================
def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def make_embed(title, description="", color=Color.PRIMARY, footer=None, thumbnail=None):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.timestamp = datetime.datetime.utcnow()
    if footer:
        embed.set_footer(text=footer)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    return embed

# ====================== Keep Alive ======================
app = Flask(__name__)

@app.route("/")
def home():
    return "봇 실행중"

def keep_alive():
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()

# ====================== 봇 ======================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

warnings = {}

async def send_log(embed):
    ch = bot.get_channel(LOG_CHANNEL_ID)
    if ch:
        await ch.send(embed=embed)

# ====================== 인증 ======================
class VerifyModal(Modal, title="📜 규칙 동의"):
    agreement = TextInput(label="동의합니다 입력", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        if self.agreement.value.strip() != "동의합니다":
            return await interaction.response.send_message("❌ 정확히 입력", ephemeral=True)

        role = interaction.guild.get_role(VERIFY_ROLE_ID)
        await interaction.user.add_roles(role)

        await interaction.response.send_message("✅ 인증 완료", ephemeral=True)

class VerifyView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="인증", style=discord.ButtonStyle.success)
    async def verify(self, interaction, button):
        await interaction.response.send_modal(VerifyModal())

@bot.command()
async def 인증패널(ctx):
    await ctx.send("버튼 눌러 인증", view=VerifyView())

# ====================== 티켓 ======================
class TicketModal(Modal, title="문의"):
    subject = TextInput(label="제목")
    body = TextInput(label="내용", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction):
        guild = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)

        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category
        )

        await channel.send(f"{interaction.user.mention} 티켓 생성됨")
        await interaction.response.send_message("티켓 생성 완료", ephemeral=True)

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="티켓 열기", style=discord.ButtonStyle.primary)
    async def open(self, interaction, button):
        await interaction.response.send_modal(TicketModal())

@bot.tree.command(name="티켓패널")
async def ticket_panel(interaction):
    await interaction.response.send_message("티켓 생성 버튼", view=TicketView())

# ====================== 입장 ======================
@bot.event
async def on_member_join(member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await ch.send(f"{member.mention} 환영합니다 🎉")

# ====================== 경고 ======================
@bot.tree.command(name="경고")
async def warn(interaction, user: discord.Member, 이유: str):
    warnings[user.id] = warnings.get(user.id, 0) + 1
    await interaction.response.send_message(f"{user} 경고 +1")

@bot.tree.command(name="경고취소")
async def unwarn(interaction, user: discord.Member):
    prev = warnings.get(user.id, 0)
    warnings[user.id] = max(prev - 1, 0)

    await interaction.response.send_message(
        f"{user} 경고 {prev} → {warnings[user.id]}"
    )

# ====================== 준비 ======================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print("봇 실행됨")

# ====================== 실행 ======================
keep_alive()
bot.run(TOKEN)
