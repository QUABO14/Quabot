import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import datetime
import os
from flask import Flask
from threading import Thread
from openai import AsyncOpenAI

# ====================== 환경 설정 ======================
TOKEN              = os.getenv("TOKEN")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
AI_MODEL           = os.getenv("AI_MODEL", "gpt-5")

WELCOME_CHANNEL_ID = 1496478743873589448
LOG_CHANNEL_ID     = 1496478745538855146
TICKET_CATEGORY_ID = 1496840441654677614
VERIFY_ROLE_ID     = 1496479066075697234

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

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

def split_message(text, limit=1900):
    return [text[i:i + limit] for i in range(0, len(text), limit)]

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

        if role is None:
            return await interaction.response.send_message("❌ 인증 역할을 찾을 수 없습니다.", ephemeral=True)

        await interaction.user.add_roles(role)
        await interaction.response.send_message("✅ 인증 완료", ephemeral=True)

class VerifyView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="인증", style=discord.ButtonStyle.success)
    async def verify(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(VerifyModal())

@bot.command()
async def 인증패널(ctx):
    await ctx.send("버튼 눌러 인증", view=VerifyView())

# ====================== 티켓 ======================
class TicketModal(Modal, title="문의"):
    subject = TextInput(label="제목")
    body = TextInput(label="내용", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)

        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category
        )

        await channel.send(
            f"{interaction.user.mention} 티켓 생성됨\n"
            f"제목: {self.subject.value}\n"
            f"내용: {self.body.value}"
        )

        await interaction.response.send_message("티켓 생성 완료", ephemeral=True)

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="티켓 열기", style=discord.ButtonStyle.primary)
    async def open(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(TicketModal())

@bot.tree.command(name="티켓패널", description="티켓 생성 패널을 보냅니다.")
async def ticket_panel(interaction: discord.Interaction):
    await interaction.response.send_message("티켓 생성 버튼", view=TicketView())

# ====================== AI 대화 ======================
@bot.tree.command(name="ai", description="AI와 대화합니다.")
@app_commands.describe(질문="AI에게 물어볼 내용을 입력하세요.")
async def ai_chat(interaction: discord.Interaction, 질문: str):
    if not OPENAI_API_KEY:
        return await interaction.response.send_message(
            "❌ OPENAI_API_KEY가 설정되지 않았습니다.",
            ephemeral=True
        )

    await interaction.response.defer(thinking=True)

    try:
        response = await openai_client.responses.create(
            model=AI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": "너는 디스코드 서버에서 사용자를 도와주는 친절한 한국어 AI야. 답변은 너무 길지 않게 해."
                },
                {
                    "role": "user",
                    "content": 질문
                }
            ]
        )

        answer = response.output_text.strip()

        if not answer:
            answer = "답변을 생성하지 못했습니다."

        parts = split_message(answer)

        await interaction.followup.send(parts[0])

        for part in parts[1:]:
            await interaction.followup.send(part)

    except Exception as e:
        await interaction.followup.send(f"❌ AI 오류 발생: `{e}`")

# ====================== 입장 ======================
@bot.event
async def on_member_join(member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await ch.send(f"{member.mention} 환영합니다 🎉")

# ====================== 경고 ======================
@bot.tree.command(name="경고", description="유저에게 경고를 지급합니다.")
async def warn(interaction: discord.Interaction, user: discord.Member, 이유: str):
    warnings[user.id] = warnings.get(user.id, 0) + 1
    await interaction.response.send_message(f"{user} 경고 +1\n이유: {이유}")

@bot.tree.command(name="경고취소", description="유저의 경고를 1회 취소합니다.")
async def unwarn(interaction: discord.Interaction, user: discord.Member):
    prev = warnings.get(user.id, 0)
    warnings[user.id] = max(prev - 1, 0)

    await interaction.response.send_message(
        f"{user} 경고 {prev} → {warnings[user.id]}"
    )

# ====================== 준비 ======================
@bot.event
async def on_ready():
    bot.add_view(VerifyView())
    bot.add_view(TicketView())

    await bot.tree.sync()
    print(f"봇 실행됨: {bot.user}")

# ====================== 실행 ======================
keep_alive()

if not TOKEN:
    raise RuntimeError("TOKEN 환경변수가 설정되지 않았습니다.")

bot.run(TOKEN)
