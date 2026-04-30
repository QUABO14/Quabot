import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import datetime
import os
import random
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

# ====================== 유틸리티 ======================
def now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def make_embed(title: str, description: str = "", color: int = Color.PRIMARY, 
               footer: str = None, thumbnail: str = None) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.timestamp = datetime.datetime.utcnow()
    if footer:
        embed.set_footer(text=footer)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    return embed

# ====================== 슬립 방지 (Keep Alive) ======================
_flask_app = Flask(__name__)

@_flask_app.route("/")
def _home():
    return "🤖 봇 정상 작동 중", 200

def keep_alive():
    Thread(target=lambda: _flask_app.run(host="0.0.0.0", port=10000), daemon=True).start()

# ====================== 봇 초기화 ======================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

warnings: dict[int, int] = {}  # {user_id: count}

# ====================== 로그 ======================
async def send_log(embed: discord.Embed):
    ch = bot.get_channel(LOG_CHANNEL_ID)
    if ch:
        await ch.send(embed=embed)

# ====================== 인증 시스템 (규칙 동의) ======================
class VerifyModal(Modal, title="📜 서버 규칙 동의"):
    agreement = TextInput(
        label="아래 규칙을 읽고 동의합니다를 입력하세요",
        placeholder="동의합니다",
        required=True,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        if self.agreement.value.strip() != "동의합니다":
            return await interaction.response.send_message("❌ '동의합니다'라고 정확히 입력해주세요.", ephemeral=True)

        role = interaction.guild.get_role(VERIFY_ROLE_ID)
        if role in interaction.user.roles:
            return await interaction.response.send_message("✅ 이미 인증된 유저입니다.", ephemeral=True)

        await interaction.user.add_roles(role)

        success_embed = make_embed(
            title="✅ 인증 완료",
            description=f"{interaction.user.mention} 님, 서버에 오신 것을 환영합니다!",
            color=Color.SUCCESS,
            footer=f"인증 시각: {now_str()}",
            thumbnail=interaction.user.display_avatar.url
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)

        log_embed = make_embed(
            title="🔐 인증 완료",
            description=f"{interaction.user.mention} 님이 인증을 완료했습니다.",
            color=Color.SUCCESS
        )
        log_embed.add_field(name="유저", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        log_embed.add_field(name="인증 방법", value="버튼 + 규칙 동의", inline=False)
        log_embed.add_field(name="시각", value=now_str(), inline=False)
        await send_log(log_embed)


class VerifyView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ 인증하기", style=discord.ButtonStyle.success, custom_id="verify_btn")
    async def verify(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(VerifyModal())


@bot.command(name="인증패널")
@commands.has_permissions(administrator=True)
async def verify_panel(ctx):
    embed = make_embed(
        title="🔐 서버 인증",
        description=(
            "**서버 이용을 위한 인증이 필요합니다.**\n\n"
            "1. 아래 버튼을 클릭하세요\n"
            "2. 규칙을 확인 후 **동의합니다** 입력\n"
            "3. 인증이 완료되면 모든 채널이 공개됩니다."
        ),
        color=Color.PRIMARY,
        footer="인증은 1회만 진행됩니다"
    )
    await ctx.send(embed=embed, view=VerifyView())
    await ctx.message.delete()

# ====================== 티켓 시스템 ======================
class TicketModal(Modal, title="📋 티켓 문의 작성"):
    subject = TextInput(label="문의 제목", placeholder="간단한 제목을 입력해 주세요", max_length=60)
    body = TextInput(label="문의 내용", style=discord.TextStyle.paragraph, 
                     placeholder="상세한 내용을 적어주세요.", max_length=1000)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)

        if discord.utils.get(guild.text_channels, name=f"ticket-{interaction.user.name}"):
            return await interaction.response.send_message("이미 티켓이 있어요!", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category,
            overwrites=overwrites,
            topic=f"티켓 주인: {interaction.user} | {now_str()}"
        )

        embed = make_embed(
            f"🎫 티켓 — {self.subject.value}",
            self.body.value,
            Color.PRIMARY,
            f"생성자: {interaction.user} | {now_str()}",
            interaction.user.display_avatar.url
        )
        embed.add_field(name="유저", value=interaction.user.mention)
        embed.add_field(name="ID", value=str(interaction.user.id))

        await channel.send(
            f"{interaction.user.mention} 님의 티켓이 열렸습니다.",
            embed=embed,
            view=CloseView()
        )
        await interaction.response.send_message(f"✅ 티켓이 생성됐어요! → {channel.mention}", ephemeral=True)
        await send_log(make_embed("🎫 티켓 생성 로그", f"{interaction.user.mention} — {self.subject.value}", Color.INFO))


class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 티켓 열기", style=discord.ButtonStyle.blurple, custom_id="ticket_open_btn")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(TicketModal())


class CloseView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 티켓 닫기", style=discord.ButtonStyle.danger, custom_id="ticket_close_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(embed=make_embed(
            "🔒 티켓 종료",
            f"{interaction.user.mention} 님이 티켓을 닫았습니다.\n**5초 후 채널이 삭제됩니다.**",
            Color.DANGER
        ))

        await send_log(make_embed(
            "🔒 티켓 종료 로그",
            f"채널: `{interaction.channel.name}` | 닫은 유저: {interaction.user.mention}",
            Color.WARNING
        ))

        await discord.utils.sleep_until(datetime.datetime.utcnow() + datetime.timedelta(seconds=5))
        await interaction.channel.delete()


@bot.tree.command(name="티켓패널", description="티켓 생성 패널을 전송합니다")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_panel(interaction: discord.Interaction):
    embed = make_embed(
        "🎫 문의 / 티켓 시스템",
        "도움이 필요하신가요?\n아래 버튼을 눌러 티켓을 생성하면\n운영진이 빠르게 도와드립니다.",
        Color.PRIMARY,
        "티켓은 1인 1개만 가능합니다"
    )
    await interaction.response.send_message(embed=embed, view=TicketView())

# ====================== 입장/퇴장 ======================
@bot.event
async def on_member_join(member: discord.Member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if not ch: return

    embed = make_embed(
        "🌟 새로운 멤버 입장!",
        f"**{member.mention}** 님, 서버에 오신 것을 환영합니다!",
        Color.SUCCESS,
        f"현재 멤버 수: {member.guild.member_count}명",
        member.display_avatar.url
    )
    embed.add_field(name="유저", value=str(member))
    embed.add_field(name="계정 생성일", value=member.created_at.strftime("%Y-%m-%d"))
    embed.add_field(name="입장일", value=now_str())
    await ch.send(embed=embed)


@bot.event
async def on_member_remove(member: discord.Member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if not ch: return
    embed = make_embed(
        "👋 멤버 퇴장",
        f"**{member}** 님이 서버를 떠났습니다.",
        Color.WARNING,
        f"현재 멤버 수: {member.guild.member_count}명"
    )
    await ch.send(embed=embed)

# ====================== 경고 시스템 ======================
WARN_THRESHOLDS = {
    3: ("타임아웃 10분", lambda u: u.timeout(datetime.timedelta(minutes=10))),
    5: ("킥", lambda u: u.kick()),
    7: ("밴", lambda u: u.ban()),
}

@bot.tree.command(name="경고", description="유저에게 경고를 부여합니다")
@app_commands.checks.has_permissions(kick_members=True)
async def warn(interaction: discord.Interaction, user: discord.Member, 이유: str):
    if user.bot:
        return await interaction.response.send_message("봇에게는 경고를 줄 수 없어요.", ephemeral=True)

    warnings[user.id] = warnings.get(user.id, 0) + 1
    count = warnings[user.id]

    punishment_msg = ""
    for threshold, (label, action) in sorted(WARN_THRESHOLDS.items()):
        if count == threshold:
            await action(user)
            punishment_msg = f"\n> 🔨 자동 처벌 적용: **{label}**"
            break

    embed = make_embed("⚠️ 경고 부여", color=Color.WARNING, footer=f"처리자: {interaction.user}",
                       thumbnail=user.display_avatar.url)
    embed.add_field(name="대상", value=user.mention)
    embed.add_field(name="누적 경고", value=f"**{count}회**")
    embed.add_field(name="이유", value=이유)
    if punishment_msg:
        embed.add_field(name="처벌", value=punishment_msg.strip())

    await interaction.response.send_message(embed=embed)
    await send_log(make_embed("⚠️ 경고 로그", f"{user.mention} | 누적 {count}회 | 이유: {이유}{punishment_msg}", Color.WARNING))

# ====================== 관리 명령어 ======================
@bot.tree.command(name="경고취소", description="유저 경고를 1회 감소시킵니다")
@app_commands.checks.has_permissions(kick_members=True)
async def unwarn(interaction: discord.Interaction, user: discord.Member):
    prev = warnings.get(user.id, 0)
    warnings[user.id] = max(prev - 1, 0)
    await interaction.response.send_message(embed=make_embed(
        "✅ 경고 취소",
        f"{user.mention} 경고 **{prev}회 → {warnings[user.id]}회**",
        Color.SUCCESS,
        f"처리자: {interaction.user}"
    ))

@bot.tree.command(name="경고조회", description="유저의 경고 횟수를 확인합니다")
@app_commands.checks.has_permissions(kick_members=True)
async def check_warns(interaction: discord.Interaction, user: discord.Member):
    count = warnings.get(user.id, 0)
    await interaction.response.send_message(embed=make_embed(
        "📋 경고 조회",
        f"{user.mention} 현재 경고 횟수: **{count}회**",
        Color.INFO,
        thumbnail=user.display_avatar.url
    ), ephemeral=True)

@bot.tree.command(name="청소", description="채널 메시지를 대량 삭제합니다")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, 개수: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=개수)
    await interaction.followup.send(embed=make_embed(
        "🧹 채팅 청소 완료",
        f"**{len(deleted)}개** 메시지를 삭제했습니다.",
        Color.SUCCESS,
        f"처리자: {interaction.user}"
    ), ephemeral=True)

# ====================== 관리자 패널 ======================
class AnnounceModal(Modal, title="📢 공지 작성"):
    ann_title = TextInput(label="공지 제목", max_length=100)
    ann_body = TextInput(label="공지 내용", style=discord.TextStyle.paragraph, max_length=2000)

    async def on_submit(self, interaction: discord.Interaction):
        embed = make_embed(f"📢 {self.ann_title.value}", self.ann_body.value, Color.PRIMARY,
                           f"공지자: {interaction.user} | {now_str()}")
        await interaction.channel.send("@everyone", embed=embed)
        await interaction.response.send_message("공지가 전송됐어요!", ephemeral=True)

class AdminPanel(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📢 공지 작성", style=discord.ButtonStyle.blurple, row=0)
    async def announce(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AnnounceModal())

    @discord.ui.button(label="🧹 채팅 전체 청소", style=discord.ButtonStyle.grey, row=0)
    async def purge_all(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=500)
        await interaction.followup.send(embed=make_embed("🧹 채팅 전체 청소", f"**{len(deleted)}개** 삭제 완료", Color.SUCCESS), ephemeral=True)

    @discord.ui.button(label="🎫 티켓 전체 삭제", style=discord.ButtonStyle.danger, row=1)
    async def delete_tickets(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        count = 0
        for ch in interaction.guild.text_channels:
            if ch.category_id == TICKET_CATEGORY_ID:
                await ch.delete()
                count += 1
        await interaction.followup.send(embed=make_embed("🎫 티켓 전체 삭제", f"**{count}개** 티켓 채널 삭제 완료", Color.DANGER), ephemeral=True)

    @discord.ui.button(label="📊 서버 정보", style=discord.ButtonStyle.success, row=1)
    async def server_info(self, interaction: discord.Interaction, button: Button):
        g = interaction.guild
        embed = make_embed(f"📊 {g.name} 서버 정보", color=Color.INFO, thumbnail=g.icon.url if g.icon else None)
        embed.add_field(name="멤버 수", value=f"{g.member_count}명")
        embed.add_field(name="채널 수", value=f"{len(g.channels)}개")
        embed.add_field(name="역할 수", value=f"{len(g.roles)}개")
        embed.add_field(name="서버 생성일", value=g.created_at.strftime("%Y-%m-%d"))
        embed.add_field(name="부스트 레벨", value=f"Lv.{g.premium_tier}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="관리자패널", description="관리자 전용 패널을 엽니다")
@app_commands.checks.has_permissions(administrator=True)
async def admin_panel(interaction: discord.Interaction):
    embed = make_embed("👑 관리자 패널", "아래 버튼으로 서버를 관리하세요.", Color.DARK)
    await interaction.response.send_message(embed=embed, view=AdminPanel(), ephemeral=True)

# ====================== 에러 핸들러 ======================
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ 이 명령어를 사용할 권한이 없어요."
    else:
        msg = f"❌ 오류 발생: `{error}`"
    embed = make_embed("오류", msg, Color.DANGER)
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ====================== 봇 시작 ======================
@bot.event
async def on_ready():
    await bot.tree.sync()
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(type=discord.ActivityType.watching, name="서버 관리 중 👀")
    )
    print(f"✅ 봇 로그인: {bot.user} | 서버 수: {len(bot.guilds)}개")

# ====================== 실행 ======================
keep_alive()
bot.run(TOKEN)# ====================== 로그 ======================
async def send_log(embed: discord.Embed):
    ch = bot.get_channel(LOG_CHANNEL_ID)
    if ch:
        await ch.send(embed=embed)

# ====================== 인증 시스템 (규칙 동의 버전) ======================
class VerifyModal(Modal, title="📜 서버 규칙 동의"):
    agreement = TextInput(
        label="아래 규칙을 읽고 동의합니다를 입력하세요",
        placeholder="동의합니다",
        required=True,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        if self.agreement.value.strip() != "동의합니다":
            return await interaction.response.send_message("❌ '동의합니다'라고 정확히 입력해주세요.", ephemeral=True)

        role = interaction.guild.get_role(VERIFY_ROLE_ID)
        if role in interaction.user.roles:
            return await interaction.response.send_message("✅ 이미 인증된 유저입니다.", ephemeral=True)

        await interaction.user.add_roles(role)

        # 인증 성공 임베드
        success_embed = make_embed(
            title="✅ 인증 완료",
            description=f"{interaction.user.mention} 님, 서버에 오신 것을 환영합니다!",
            color=Color.SUCCESS,
            footer=f"인증 시각: {now_str()}",
            thumbnail=interaction.user.display_avatar.url
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)

        # 로그 전송
        log_embed = make_embed(
            title="🔐 인증 완료",
            description=f"{interaction.user.mention} 님이 인증을 완료했습니다.",
            color=Color.SUCCESS
        )
        log_embed.add_field(name="유저", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        log_embed.add_field(name="인증 방법", value="버튼 + 규칙 동의", inline=False)
        log_embed.add_field(name="시각", value=now_str(), inline=False)
        await send_log(log_embed)


class VerifyView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="✅ 인증하기",
        style=discord.ButtonStyle.success,
        custom_id="verify_btn"
    )
    async def verify(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(VerifyModal())


# 인증 패널 명령어
@bot.command(name="인증패널")
@commands.has_permissions(administrator=True)
async def verify_panel(ctx):
    embed = make_embed(
        title="🔐 서버 인증",
        description=(
            "**서버 이용을 위한 인증이 필요합니다.**\n\n"
            "1. 아래 버튼을 클릭하세요\n"
            "2. 규칙을 확인 후 **동의합니다** 입력\n"
            "3. 인증이 완료되면 모든 채널이 공개됩니다."
        ),
        color=Color.PRIMARY,
        footer="인증은 1회만 진행됩니다"
    )
    await ctx.send(embed=embed, view=VerifyView())
    await ctx.message.delete()

# ====================== 티켓 시스템 ======================
class TicketModal(Modal, title="📋 티켓 문의 작성"):
    subject = TextInput(label="문의 제목", placeholder="간단한 제목을 입력해 주세요", max_length=60)
    body = TextInput(label="문의 내용", style=discord.TextStyle.paragraph, 
                     placeholder="상세한 내용을 적어주세요.", max_length=1000)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)

        if discord.utils.get(guild.text_channels, name=f"ticket-{interaction.user.name}"):
            return await interaction.response.send_message("이미 티켓이 있어요!", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category,
            overwrites=overwrites,
            topic=f"티켓 주인: {interaction.user} | {now_str()}"
        )

        embed = make_embed(
            f"🎫 티켓 — {self.subject.value}",
            self.body.value,
            Color.PRIMARY,
            f"생성자: {interaction.user} | {now_str()}",
            interaction.user.display_avatar.url
        )
        embed.add_field(name="유저", value=interaction.user.mention)
        embed.add_field(name="ID", value=str(interaction.user.id))

        await channel.send(
            f"{interaction.user.mention} 님의 티켓이 열렸습니다.",
            embed=embed,
            view=CloseView()
        )
        await interaction.response.send_message(f"✅ 티켓이 생성됐어요! → {channel.mention}", ephemeral=True)
        await send_log(make_embed("🎫 티켓 생성 로그", f"{interaction.user.mention} — {self.subject.value}", Color.INFO))


class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 티켓 열기", style=discord.ButtonStyle.blurple, custom_id="ticket_open_btn")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(TicketModal())


class CloseView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 티켓 닫기", style=discord.ButtonStyle.danger, custom_id="ticket_close_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(embed=make_embed(
            "🔒 티켓 종료",
            f"{interaction.user.mention} 님이 티켓을 닫았습니다.\n**5초 후 채널이 삭제됩니다.**",
            Color.DANGER
        ))

        await send_log(make_embed(
            "🔒 티켓 종료 로그",
            f"채널: `{interaction.channel.name}` | 닫은 유저: {interaction.user.mention}",
            Color.WARNING
        ))

        await discord.utils.sleep_until(datetime.datetime.utcnow() + datetime.timedelta(seconds=5))
        await interaction.channel.delete()

@bot.tree.command(name="티켓패널", description="티켓 생성 패널을 전송합니다")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_panel(interaction: discord.Interaction):
    embed = make_embed(
        "🎫 문의 / 티켓 시스템",
        "도움이 필요하신가요?\n아래 버튼을 눌러 티켓을 생성하면\n운영진이 빠르게 도와드립니다.",
        Color.PRIMARY,
        "티켓은 1인 1개만 가능합니다"
    )
    await interaction.response.send_message(embed=embed, view=TicketView())

# ====================== 입장/퇴장 ======================
@bot.event
async def on_member_join(member: discord.Member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if not ch: return

    embed = make_embed(
        "🌟 새로운 멤버 입장!",
        f"**{member.mention}** 님, 서버에 오신 것을 환영합니다!",
        Color.SUCCESS,
        f"현재 멤버 수: {member.guild.member_count}명",
        member.display_avatar.url
    )
    embed.add_field(name="유저", value=str(member))
    embed.add_field(name="계정 생성일", value=member.created_at.strftime("%Y-%m-%d"))
    embed.add_field(name="입장일", value=now_str())
    await ch.send(embed=embed)

@bot.event
async def on_member_remove(member: discord.Member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if not ch: return
    embed = make_embed(
        "👋 멤버 퇴장",
        f"**{member}** 님이 서버를 떠났습니다.",
        Color.WARNING,
        f"현재 멤버 수: {member.guild.member_count}명"
    )
    await ch.send(embed=embed)

# ====================== 경고 시스템 ======================
WARN_THRESHOLDS = {
    3: ("타임아웃 10분", lambda u: u.timeout(datetime.timedelta(minutes=10))),
    5: ("킥", lambda u: u.kick()),
    7: ("밴", lambda u: u.ban()),
}

@bot.tree.command(name="경고", description="유저에게 경고를 부여합니다")
@app_commands.checks.has_permissions(kick_members=True)
async def warn(interaction: discord.Interaction, user: discord.Member, 이유: str):
    if user.bot:
        return await interaction.response.send_message("봇에게는 경고를 줄 수 없어요.", ephemeral=True)

    warnings[user.id] = warnings.get(user.id, 0) + 1
    count = warnings[user.id]

    punishment_msg = ""
    for threshold, (label, action) in sorted(WARN_THRESHOLDS.items()):
        if count == threshold:
            await action(user)
            punishment_msg = f"\n> 🔨 자동 처벌 적용: **{label}**"
            break

    embed = make_embed("⚠️ 경고 부여", color=Color.WARNING, footer=f"처리자: {interaction.user}",
                       thumbnail=user.display_avatar.url)
    embed.add_field(name="대상", value=user.mention)
    embed.add_field(name="누적 경고", value=f"**{count}회**")
    embed.add_field(name="이유", value=이유)
    if punishment_msg:
        embed.add_field(name="처벌", value=punishment_msg.strip())

    await interaction.response.send_message(embed=embed)
    await send_log(make_embed("⚠️ 경고 로그", f"{user.mention} | 누적 {count}회 | 이유: {이유}{punishment_msg}", Color.WARNING))

# ====================== 기타 관리 명령어 ======================
@bot.tree.command(name="경고취소", description="유저 경고를 1회 감소시킵니다")
@app_commands.checks.has_permissions(kick_members=True)
async def unwarn(interaction: discord.Interaction, user: discord.Member):
    prev = 
    .get(user.id, 0)
    warnings[user.id] = max(prev - 1, 0)
    await interaction.response.send_message(embed=make_embed(
        "✅ 경고 취소
