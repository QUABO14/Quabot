# ================== IMPORT ==================
import discord
from discord.ext import commands
import os
import sqlite3
import datetime
import asyncio
from flask import Flask
from threading import Thread

# ================== CONFIG ==================
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================== KEEP ALIVE ==================
app = Flask(__name__)

@app.route("/")
def home():
    return "BOT ONLINE"

def keep_alive():
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000))), daemon=True).start()

# ================== DB ==================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

def init_db():
    cur.execute("CREATE TABLE IF NOT EXISTS money (uid INTEGER PRIMARY KEY, bal INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS warn (uid INTEGER PRIMARY KEY, cnt INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS channel_config (guild_id INTEGER PRIMARY KEY, welcome INTEGER, log INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS party (guild_id INTEGER, owner_id INTEGER, voice_id INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS party_config (guild_id INTEGER PRIMARY KEY, category_id INTEGER, voice_id INTEGER)")
    cur.execute("""CREATE TABLE IF NOT EXISTS guild_config (
        guild_id    INTEGER PRIMARY KEY,
        verify_role INTEGER,
        admin_role  INTEGER,
        welcome_ch  INTEGER,
        log_ch      INTEGER
    )""")
    conn.commit()

# ================== UTIL ==================
def embed(t, d="", c=0x5865F2, footer=None):
    e = discord.Embed(title=t, description=d, color=c)
    e.timestamp = datetime.datetime.utcnow()
    if footer:
        e.set_footer(text=footer)
    return e

def success_embed(t, d=""):
    return embed(f"✅  {t}", d, c=0x57F287, footer="성공")

def error_embed(t, d=""):
    return embed(f"❌  {t}", d, c=0xED4245, footer="오류")

def info_embed(t, d=""):
    return embed(f"ℹ️  {t}", d, c=0x5865F2)

def warn_embed(t, d=""):
    return embed(f"⚠️  {t}", d, c=0xFEE75C, footer="경고")

# ================== GUILD CONFIG HELPERS ==================
def get_guild_config(guild_id):
    cur.execute("SELECT verify_role, admin_role, welcome_ch, log_ch FROM guild_config WHERE guild_id=?", (guild_id,))
    r = cur.fetchone()
    if not r:
        return {"verify_role": None, "admin_role": None, "welcome_ch": None, "log_ch": None}
    return {"verify_role": r[0], "admin_role": r[1], "welcome_ch": r[2], "log_ch": r[3]}

def set_guild_config(guild_id, **kwargs):
    cfg = get_guild_config(guild_id)
    cfg.update({k: v for k, v in kwargs.items() if k in cfg})
    cur.execute("""INSERT INTO guild_config (guild_id, verify_role, admin_role, welcome_ch, log_ch)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(guild_id) DO UPDATE SET
                   verify_role=excluded.verify_role,
                   admin_role=excluded.admin_role,
                   welcome_ch=excluded.welcome_ch,
                   log_ch=excluded.log_ch""",
                (guild_id, cfg["verify_role"], cfg["admin_role"], cfg["welcome_ch"], cfg["log_ch"]))
    conn.commit()

async def send_log(guild, content=None, embeds=None):
    cfg = get_guild_config(guild.id)
    if not cfg["log_ch"]:
        return
    ch = guild.get_channel(cfg["log_ch"])
    if ch:
        if embeds:
            await ch.send(embeds=embeds)
        elif content:
            await ch.send(content)

# ================== ECONOMY ==================
def money(uid):
    cur.execute("SELECT bal FROM money WHERE uid=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

def add_money(uid, v):
    cur.execute("REPLACE INTO money VALUES (?,?)", (uid, money(uid)+v))
    conn.commit()

def sub_money(uid, v):
    cur.execute("REPLACE INTO money VALUES (?,?)", (uid, money(uid)-v))
    conn.commit()

# ================== WARN ==================
def get_warn(uid):
    cur.execute("SELECT cnt FROM warn WHERE uid=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

def add_warn(uid):
    c = get_warn(uid) + 1
    cur.execute("REPLACE INTO warn VALUES (?,?)", (uid, c))
    conn.commit()
    return c

def clear_warn(uid):
    cur.execute("REPLACE INTO warn VALUES (?,0)", (uid,))
    conn.commit()

# ================== VERIFY VIEW ==================
class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="인증하기", emoji="✅", style=discord.ButtonStyle.success, custom_id="verify_btn")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_guild_config(interaction.guild.id)
        role = None

        if cfg["verify_role"]:
            role = interaction.guild.get_role(cfg["verify_role"])

        if not role:
            role = discord.utils.get(interaction.guild.roles, name="인증")
            if not role:
                role = await interaction.guild.create_role(
                    name="인증",
                    color=discord.Color.green(),
                    reason="인증 시스템 자동 생성"
                )

        if role in interaction.user.roles:
            await interaction.response.send_message(
                embed=warn_embed("이미 인증됨", "이미 인증된 상태입니다."),
                ephemeral=True
            )
            return

        await interaction.user.add_roles(role, reason="인증 버튼 클릭")

        # DM 발송
        try:
            dm_embed = discord.Embed(
                title="✅  인증 완료",
                description=(
                    f"**{interaction.guild.name}** 서버 인증이 완료되었습니다!\n\n"
                    f"> 역할 `{role.name}` 이(가) 부여되었습니다.\n"
                    f"> 즐거운 시간 보내세요 🎉"
                ),
                color=0x57F287
            )
            dm_embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
            dm_embed.timestamp = datetime.datetime.utcnow()
            dm_embed.set_footer(text=interaction.guild.name)
            await interaction.user.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            embed=success_embed("인증 완료!", f"`{role.name}` 역할이 부여되었습니다."),
            ephemeral=True
        )

        # 로그
        log_e = discord.Embed(
            title="📋  인증 로그",
            color=0x57F287,
            timestamp=datetime.datetime.utcnow()
        )
        log_e.add_field(name="유저", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
        log_e.add_field(name="역할", value=role.mention, inline=True)
        log_e.set_thumbnail(url=interaction.user.display_avatar.url)
        await send_log(interaction.guild, embeds=[log_e])

# ================== TICKET VIEW ==================
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="티켓 생성", emoji="🎟️", style=discord.ButtonStyle.primary, custom_id="ticket_btn")
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 중복 티켓 체크
        existing = discord.utils.get(
            interaction.guild.text_channels,
            name=f"ticket-{interaction.user.name.lower()}"
        )
        if existing:
            await interaction.response.send_message(
                embed=warn_embed("이미 티켓 존재", f"이미 열린 티켓이 있습니다: {existing.mention}"),
                ephemeral=True
            )
            return

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }

        cfg = get_guild_config(interaction.guild.id)
        if cfg["admin_role"]:
            admin = interaction.guild.get_role(cfg["admin_role"])
            if admin:
                overwrites[admin] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        ch = await interaction.guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            overwrites=overwrites,
            topic=f"{interaction.user} 의 티켓 | {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
        )

        ticket_embed = discord.Embed(
            title="🎟️  티켓이 생성되었습니다",
            description=(
                f"안녕하세요, {interaction.user.mention}님!\n\n"
                "관리자가 곧 도움을 드릴 예정입니다.\n"
                "문의 내용을 아래에 자세히 작성해 주세요."
            ),
            color=0x5865F2,
            timestamp=datetime.datetime.utcnow()
        )
        ticket_embed.set_footer(text="티켓을 닫으려면 관리자에게 요청하세요.")
        ticket_embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await ch.send(embed=ticket_embed, view=TicketCloseView())

        await interaction.response.send_message(
            embed=success_embed("티켓 생성 완료", f"티켓 채널: {ch.mention}"),
            ephemeral=True
        )

        # 로그
        log_e = discord.Embed(
            title="🎟️  티켓 생성 로그",
            color=0x5865F2,
            timestamp=datetime.datetime.utcnow()
        )
        log_e.add_field(name="유저", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
        log_e.add_field(name="채널", value=ch.mention, inline=True)
        log_e.set_thumbnail(url=interaction.user.display_avatar.url)
        await send_log(interaction.guild, embeds=[log_e])

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="티켓 닫기", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket_close_btn")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message(
                embed=error_embed("권한 없음", "채널 관리 권한이 필요합니다."),
                ephemeral=True
            )
            return
        await interaction.response.send_message(embed=warn_embed("티켓 닫는 중...", "3초 후 채널이 삭제됩니다."))
        await asyncio.sleep(3)
        await interaction.channel.delete(reason=f"티켓 닫기: {interaction.user}")

# ================== PARTY VIEW ==================
class PartyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="파티 참가", emoji="🎮", style=discord.ButtonStyle.success, custom_id="party_join_btn")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        cur.execute("SELECT voice_id FROM party WHERE guild_id=? AND owner_id=?", (interaction.guild.id, interaction.user.id))
        r = cur.fetchone()
        if not r:
            return await interaction.response.send_message(embed=error_embed("파티 없음", "파티가 존재하지 않습니다."), ephemeral=True)
        vc = interaction.guild.get_channel(r[0])
        if vc:
            await interaction.user.move_to(vc)
            await interaction.response.send_message(embed=success_embed("참가 완료", f"{vc.mention} 에 이동했습니다."), ephemeral=True)

# ================== ADMIN PANEL ==================
class AdminPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="파티 관리", emoji="🎮", style=discord.ButtonStyle.primary, custom_id="admin_party_btn")
    async def p(self, interaction: discord.Interaction, button: discord.ui.Button):
        cur.execute("SELECT owner_id, voice_id FROM party WHERE guild_id=?", (interaction.guild.id,))
        rows = cur.fetchall()
        if not rows:
            return await interaction.response.send_message(embed=info_embed("파티 없음", "현재 생성된 파티가 없습니다."), ephemeral=True)
        desc = "\n".join([f"<@{r[0]}> → <#{r[1]}>" for r in rows])
        await interaction.response.send_message(embed=info_embed("파티 목록", desc), ephemeral=True)

    @discord.ui.button(label="경고 관리", emoji="⚠️", style=discord.ButtonStyle.danger, custom_id="admin_warn_btn")
    async def w(self, interaction: discord.Interaction, button: discord.ui.Button):
        cur.execute("SELECT uid, cnt FROM warn WHERE cnt > 0")
        rows = cur.fetchall()
        if not rows:
            return await interaction.response.send_message(embed=info_embed("경고 없음", "경고받은 유저가 없습니다."), ephemeral=True)
        desc = "\n".join([f"<@{r[0]}> → **{r[1]}회**" for r in rows])
        await interaction.response.send_message(embed=warn_embed("경고 목록", desc), ephemeral=True)

    @discord.ui.button(label="티켓 목록", emoji="🎟️", style=discord.ButtonStyle.success, custom_id="admin_ticket_btn")
    async def t(self, interaction: discord.Interaction, button: discord.ui.Button):
        tickets = [ch for ch in interaction.guild.text_channels if ch.name.startswith("ticket-")]
        if not tickets:
            return await interaction.response.send_message(embed=info_embed("티켓 없음", "현재 열린 티켓이 없습니다."), ephemeral=True)
        desc = "\n".join([ch.mention for ch in tickets])
        await interaction.response.send_message(embed=info_embed(f"티켓 목록 ({len(tickets)}개)", desc), ephemeral=True)

# ================== PANEL COMMANDS ==================
@bot.tree.command(name="인증패널", description="인증 패널을 전송합니다.")
async def verify_panel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(embed=error_embed("권한 없음"), ephemeral=True)

    e = discord.Embed(
        title="✅  서버 인증",
        description=(
            "아래 버튼을 눌러 서버 인증을 완료하세요.\n\n"
            "> 인증 완료 시 역할이 자동 부여됩니다.\n"
            "> 인증 완료 후 DM으로 안내 메시지가 전송됩니다."
        ),
        color=0x57F287,
        timestamp=datetime.datetime.utcnow()
    )
    e.set_footer(text=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
    await interaction.response.send_message(embed=e, view=VerifyView())

@bot.tree.command(name="티켓패널", description="티켓 패널을 전송합니다.")
async def ticket_panel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(embed=error_embed("권한 없음"), ephemeral=True)

    e = discord.Embed(
        title="🎟️  티켓 시스템",
        description=(
            "문의사항이 있으시면 아래 버튼을 눌러 티켓을 생성해 주세요.\n\n"
            "> 티켓은 1인당 1개만 생성 가능합니다.\n"
            "> 관리자가 확인 후 빠르게 답변드립니다."
        ),
        color=0x5865F2,
        timestamp=datetime.datetime.utcnow()
    )
    e.set_footer(text=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
    await interaction.response.send_message(embed=e, view=TicketView())

@bot.tree.command(name="관리자패널", description="관리자 패널을 전송합니다.")
async def admin_panel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(embed=error_embed("권한 없음"), ephemeral=True)

    e = discord.Embed(
        title="⚙️  관리자 패널",
        description="서버 관리 도구입니다. 아래 버튼을 통해 각 기능을 확인하세요.",
        color=0xEB459E,
        timestamp=datetime.datetime.utcnow()
    )
    e.set_footer(text=f"관리자: {interaction.user}", icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e, view=AdminPanel())

# ================== 역할 설정 ==================
@bot.tree.command(name="역할", description="인증 역할 및 봇 관리자 역할을 설정합니다.")
async def set_roles(
    interaction: discord.Interaction,
    인증역할: discord.Role,
    관리자역할: discord.Role
):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(embed=error_embed("권한 없음"), ephemeral=True)

    set_guild_config(interaction.guild.id, verify_role=인증역할.id, admin_role=관리자역할.id)

    e = discord.Embed(
        title="⚙️  역할 설정 완료",
        color=0x57F287,
        timestamp=datetime.datetime.utcnow()
    )
    e.add_field(name="✅ 인증 역할", value=인증역할.mention, inline=True)
    e.add_field(name="🛡️ 관리자 역할", value=관리자역할.mention, inline=True)
    e.set_footer(text=f"설정자: {interaction.user}")
    await interaction.response.send_message(embed=e)

# ================== 채널 설정 ==================
@bot.tree.command(name="채널설정", description="입장(웰컴) 채널과 로그 채널을 지정합니다.")
async def set_channels(
    interaction: discord.Interaction,
    입장채널: discord.TextChannel,
    로그채널: discord.TextChannel
):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(embed=error_embed("권한 없음"), ephemeral=True)

    set_guild_config(interaction.guild.id, welcome_ch=입장채널.id, log_ch=로그채널.id)

    e = discord.Embed(
        title="⚙️  채널 설정 완료",
        color=0x57F287,
        timestamp=datetime.datetime.utcnow()
    )
    e.add_field(name="👋 입장 채널", value=입장채널.mention, inline=True)
    e.add_field(name="📋 로그 채널", value=로그채널.mention, inline=True)
    e.set_footer(text=f"설정자: {interaction.user}")
    await interaction.response.send_message(embed=e)

# ================== PARTY COMMANDS ==================
@bot.tree.command(name="파티생성", description="파티 음성 채널을 생성합니다.")
async def party_create(interaction: discord.Interaction):
    cur.execute("SELECT voice_id FROM party WHERE guild_id=? AND owner_id=?", (interaction.guild.id, interaction.user.id))
    if cur.fetchone():
        return await interaction.response.send_message(embed=warn_embed("이미 파티 존재", "기존 파티를 먼저 삭제해 주세요."), ephemeral=True)

    vc = await interaction.guild.create_voice_channel(f"🎮 {interaction.user.display_name}의 파티")
    cur.execute("INSERT INTO party VALUES (?,?,?)", (interaction.guild.id, interaction.user.id, vc.id))
    conn.commit()

    await interaction.response.send_message(
        embed=success_embed("파티 생성 완료", f"음성 채널 {vc.mention} 이 생성되었습니다."),
        view=PartyView()
    )

@bot.tree.command(name="파티삭제", description="자신의 파티 채널을 삭제합니다.")
async def party_delete(interaction: discord.Interaction):
    cur.execute("SELECT voice_id FROM party WHERE guild_id=? AND owner_id=?", (interaction.guild.id, interaction.user.id))
    r = cur.fetchone()
    if not r:
        return await interaction.response.send_message(embed=error_embed("파티 없음"), ephemeral=True)

    vc = interaction.guild.get_channel(r[0])
    if vc:
        await vc.delete()

    cur.execute("DELETE FROM party WHERE guild_id=? AND owner_id=?", (interaction.guild.id, interaction.user.id))
    conn.commit()
    await interaction.response.send_message(embed=success_embed("파티 삭제 완료"))

# ================== ECONOMY ==================
@bot.tree.command(name="잔액", description="잔액을 확인합니다.")
async def bal(interaction: discord.Interaction, 유저: discord.Member = None):
    user = 유저 or interaction.user
    e = discord.Embed(
        title="💰  잔액 조회",
        color=0xF1C40F,
        timestamp=datetime.datetime.utcnow()
    )
    e.add_field(name="유저", value=user.mention, inline=True)
    e.add_field(name="잔액", value=f"**{money(user.id):,}원**", inline=True)
    e.set_thumbnail(url=user.display_avatar.url)
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="송금", description="다른 유저에게 송금합니다.")
async def pay(interaction: discord.Interaction, 유저: discord.Member, 금액: int):
    if 금액 <= 0:
        return await interaction.response.send_message(embed=error_embed("잘못된 금액", "0원 이상 입력하세요."), ephemeral=True)
    if money(interaction.user.id) < 금액:
        return await interaction.response.send_message(embed=error_embed("잔액 부족"), ephemeral=True)

    sub_money(interaction.user.id, 금액)
    add_money(유저.id, 금액)

    e = discord.Embed(title="💸  송금 완료", color=0x57F287, timestamp=datetime.datetime.utcnow())
    e.add_field(name="보낸 사람", value=interaction.user.mention, inline=True)
    e.add_field(name="받은 사람", value=유저.mention, inline=True)
    e.add_field(name="금액", value=f"**{금액:,}원**", inline=False)
    await interaction.response.send_message(embed=e)

# ================== WARN ==================
@bot.tree.command(name="경고", description="유저에게 경고를 부여합니다.")
async def warn_cmd(interaction: discord.Interaction, 유저: discord.Member):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message(embed=error_embed("권한 없음"), ephemeral=True)

    c = add_warn(유저.id)
    e = discord.Embed(title="⚠️  경고 부여", color=0xFEE75C, timestamp=datetime.datetime.utcnow())
    e.add_field(name="대상", value=유저.mention, inline=True)
    e.add_field(name="누적 경고", value=f"**{c}회**", inline=True)
    e.set_thumbnail(url=유저.display_avatar.url)
    await interaction.response.send_message(embed=e)

    # 로그
    await send_log(interaction.guild, embeds=[e])

@bot.tree.command(name="경고삭제", description="유저의 경고를 초기화합니다.")
async def warn_clear(interaction: discord.Interaction, 유저: discord.Member):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message(embed=error_embed("권한 없음"), ephemeral=True)

    clear_warn(유저.id)
    await interaction.response.send_message(embed=success_embed("경고 초기화 완료", f"{유저.mention} 경고 초기화 완료"))

# ================== AUTO VOICE MOVE ==================
@bot.event
async def on_voice_state_update(member, before, after):
    cur.execute("SELECT voice_id FROM party WHERE guild_id=? AND owner_id=?", (member.guild.id, member.id))
    r = cur.fetchone()
    if r and after.channel:
        vc = member.guild.get_channel(r[0])
        if vc and after.channel.id != vc.id:
            await member.move_to(vc)

# ================== WELCOME ==================
@bot.event
async def on_member_join(member):
    cfg = get_guild_config(member.guild.id)
    if not cfg["welcome_ch"]:
        return
    ch = member.guild.get_channel(cfg["welcome_ch"])
    if not ch:
        return

    e = discord.Embed(
        title="👋  새로운 멤버 입장!",
        description=(
            f"{member.mention} 님, **{member.guild.name}** 에 오신 것을 환영합니다!\n\n"
            f"> 서버 규칙을 꼭 읽어보세요.\n"
            f"> 인증을 완료하면 더 많은 채널을 이용할 수 있습니다."
        ),
        color=0x57F287,
        timestamp=datetime.datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"현재 멤버 수: {member.guild.member_count}명")
    await ch.send(embed=e)

# ================== EVENTS ==================
@bot.event
async def on_ready():
    init_db()
    bot.add_view(VerifyView())
    bot.add_view(TicketView())
    bot.add_view(TicketCloseView())
    bot.add_view(PartyView())
    bot.add_view(AdminPanel())
    await bot.tree.sync()
    print(f"🔥 BOT READY | {bot.user} ({bot.user.id})")

# ================== RUN ==================
def start():
    keep_alive()
    bot.run(TOKEN)

start()
