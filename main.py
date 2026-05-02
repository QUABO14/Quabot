# ================== IMPORT ==================
import discord
from discord.ext import commands
import os
import sqlite3
import datetime
import asyncio
import random
from flask import Flask
from threading import Thread

# ================== CONFIG ==================
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.all()
# help_command=None → discord.py 기본 !help 제거 (alias 충돌 방지)
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ================== KEEP ALIVE ==================
# UptimeRobot 없이도 Render 웹 서비스로 유지됨
# Render 배포 시 "Web Service"로 설정하면 포트 자동 관리됨
app = Flask(__name__)

@app.route("/")
def home():
    return "BOT ONLINE", 200

@app.route("/health")
def health():
    return "OK", 200

def keep_alive():
    port = int(os.environ.get("PORT", 10000))
    Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, use_reloader=False),
        daemon=True
    ).start()

# ================== DB ==================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

def init_db():
    cur.execute("CREATE TABLE IF NOT EXISTS money (uid INTEGER PRIMARY KEY, bal INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS warn  (uid INTEGER PRIMARY KEY, cnt INTEGER DEFAULT 0)")
    cur.execute("""CREATE TABLE IF NOT EXISTS party (
        guild_id  INTEGER,
        owner_id  INTEGER,
        voice_id  INTEGER,
        PRIMARY KEY (guild_id, owner_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS guild_config (
        guild_id      INTEGER PRIMARY KEY,
        verify_role   INTEGER,
        admin_role    INTEGER,
        welcome_ch    INTEGER,
        log_ch        INTEGER,
        levelup_ch    INTEGER,
        party_cat     INTEGER
    )""")
    # 기존 테이블 컬럼 마이그레이션
    for col in ["levelup_ch INTEGER", "party_cat INTEGER"]:
        try:
            cur.execute(f"ALTER TABLE guild_config ADD COLUMN {col}")
        except Exception:
            pass
    cur.execute("""CREATE TABLE IF NOT EXISTS sticky (
        channel_id INTEGER PRIMARY KEY,
        guild_id   INTEGER,
        content    TEXT,
        message_id INTEGER
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS levels (
        guild_id INTEGER,
        uid      INTEGER,
        xp       INTEGER DEFAULT 0,
        lv       INTEGER DEFAULT 0,
        last_msg INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, uid)
    )""")
    # 음성채널 체류시간 추적 (입장 타임스탬프)
    cur.execute("""CREATE TABLE IF NOT EXISTS voice_track (
        guild_id   INTEGER,
        uid        INTEGER,
        joined_at  INTEGER,
        PRIMARY KEY (guild_id, uid)
    )""")
    conn.commit()

# ================== EMBED HELPERS ==================
def _base_embed(title, desc, color, footer=None, icon=None):
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = datetime.datetime.utcnow()
    if footer:
        e.set_footer(text=footer, icon_url=icon)
    return e

def success_embed(t, d=""): return _base_embed(f"✅  {t}", d, 0x57F287, "성공")
def error_embed(t, d=""):   return _base_embed(f"❌  {t}", d, 0xED4245, "오류")
def info_embed(t, d=""):    return _base_embed(f"ℹ️  {t}", d, 0x5865F2)
def warn_embed(t, d=""):    return _base_embed(f"⚠️  {t}", d, 0xFEE75C, "경고")

# ================== GUILD CONFIG ==================
def get_cfg(guild_id: int) -> dict:
    cur.execute("""SELECT verify_role, admin_role, welcome_ch, log_ch, levelup_ch, party_cat
                   FROM guild_config WHERE guild_id=?""", (guild_id,))
    r = cur.fetchone()
    keys = ["verify_role", "admin_role", "welcome_ch", "log_ch", "levelup_ch", "party_cat"]
    return dict(zip(keys, r)) if r else {k: None for k in keys}

def set_cfg(guild_id: int, **kwargs):
    cfg = get_cfg(guild_id)
    cfg.update({k: v for k, v in kwargs.items() if k in cfg})
    cur.execute("""INSERT INTO guild_config
                   (guild_id, verify_role, admin_role, welcome_ch, log_ch, levelup_ch, party_cat)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(guild_id) DO UPDATE SET
                   verify_role=excluded.verify_role, admin_role=excluded.admin_role,
                   welcome_ch=excluded.welcome_ch,  log_ch=excluded.log_ch,
                   levelup_ch=excluded.levelup_ch,  party_cat=excluded.party_cat""",
                (guild_id, cfg["verify_role"], cfg["admin_role"],
                 cfg["welcome_ch"], cfg["log_ch"], cfg["levelup_ch"], cfg["party_cat"]))
    conn.commit()

# ================== PERMISSION HELPERS ==================
def _check_perm(guild: discord.Guild, user: discord.Member) -> bool:
    """서버 소유자 또는 관리자 역할 보유자만 True"""
    if user.id == guild.owner_id:
        return True
    if user.guild_permissions.administrator:
        return True
    cfg = get_cfg(guild.id)
    if cfg["admin_role"]:
        role = guild.get_role(cfg["admin_role"])
        if role and role in user.roles:
            return True
    return False

def is_admin(interaction: discord.Interaction) -> bool:
    return _check_perm(interaction.guild, interaction.user)

def is_admin_ctx(ctx: commands.Context) -> bool:
    return _check_perm(ctx.guild, ctx.author)

async def deny(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=error_embed("권한 없음", "서버 소유자 또는 봇 관리자 역할이 필요합니다."),
        ephemeral=True
    )

# ================== LOG HELPER ==================
async def send_log(guild: discord.Guild, embeds: list):
    cfg = get_cfg(guild.id)
    if not cfg["log_ch"]:
        return
    ch = guild.get_channel(cfg["log_ch"])
    if ch:
        try:
            await ch.send(embeds=embeds)
        except Exception:
            pass

# ================== ECONOMY ==================
def money(uid):
    cur.execute("SELECT bal FROM money WHERE uid=?", (uid,))
    r = cur.fetchone(); return r[0] if r else 0

def add_money(uid, v):
    cur.execute("REPLACE INTO money VALUES (?,?)", (uid, money(uid) + v)); conn.commit()

def sub_money(uid, v):
    cur.execute("REPLACE INTO money VALUES (?,?)", (uid, money(uid) - v)); conn.commit()

# ================== WARN ==================
def get_warn(uid):
    cur.execute("SELECT cnt FROM warn WHERE uid=?", (uid,))
    r = cur.fetchone(); return r[0] if r else 0

def add_warn(uid):
    c = get_warn(uid) + 1
    cur.execute("REPLACE INTO warn VALUES (?,?)", (uid, c)); conn.commit(); return c

def clear_warn(uid):
    cur.execute("REPLACE INTO warn VALUES (?,0)", (uid,)); conn.commit()

# ================== LEVEL SYSTEM ==================
def xp_needed(lv: int) -> int:
    return 5 * (lv ** 2) + 50 * lv + 100

def get_lv(guild_id, uid):
    cur.execute("SELECT xp, lv, last_msg FROM levels WHERE guild_id=? AND uid=?", (guild_id, uid))
    r = cur.fetchone(); return (r[0], r[1], r[2]) if r else (0, 0, 0)

def save_lv(guild_id, uid, xp, lv, last_msg):
    cur.execute("""INSERT INTO levels (guild_id,uid,xp,lv,last_msg) VALUES(?,?,?,?,?)
                   ON CONFLICT(guild_id,uid) DO UPDATE SET
                   xp=excluded.xp, lv=excluded.lv, last_msg=excluded.last_msg""",
                (guild_id, uid, xp, lv, last_msg)); conn.commit()

def get_rank(guild_id, uid):
    cur.execute("SELECT uid FROM levels WHERE guild_id=? ORDER BY lv DESC, xp DESC", (guild_id,))
    for i, (r,) in enumerate(cur.fetchall(), 1):
        if r == uid: return i
    return 0

def get_top(guild_id, limit=10):
    cur.execute("SELECT uid,xp,lv FROM levels WHERE guild_id=? ORDER BY lv DESC, xp DESC LIMIT ?",
                (guild_id, limit)); return cur.fetchall()

async def grant_xp(guild: discord.Guild, member: discord.Member, amount: int):
    """XP 부여 후 레벨업 처리. 레벨업 시 알림 전송."""
    if member.bot: return
    xp, lv, last_msg = get_lv(guild.id, member.id)
    xp += amount
    leveled_up = False
    new_lv = lv
    while xp >= xp_needed(new_lv):
        xp -= xp_needed(new_lv)
        new_lv += 1
        leveled_up = True
    save_lv(guild.id, member.id, xp, new_lv, last_msg)

    if leveled_up:
        cfg = get_cfg(guild.id)
        ch = guild.get_channel(cfg["levelup_ch"]) if cfg["levelup_ch"] else None

        lv_e = discord.Embed(
            title="🎉  레벨 업!",
            description=(
                f"{member.mention} 님이 레벨업 했습니다!\n\n"
                f"> 레벨  **{lv}** → **{new_lv}**\n"
                f"> 다음 레벨까지  **{xp_needed(new_lv):,} XP**"
            ),
            color=0xF1C40F,
            timestamp=datetime.datetime.utcnow()
        )
        lv_e.set_thumbnail(url=member.display_avatar.url)
        lv_e.set_footer(text=f"{guild.name} 레벨 시스템")
        if ch:
            await ch.send(content=member.mention, embed=lv_e)

async def process_chat_xp(message: discord.Message):
    """채팅 XP: 60초 쿨다운, 메시지당 15~25 XP"""
    if not message.guild or message.author.bot: return
    xp, lv, last_msg = get_lv(message.guild.id, message.author.id)
    now = int(datetime.datetime.utcnow().timestamp())
    if now - last_msg < 60: return
    save_lv(message.guild.id, message.author.id, xp, lv, now)   # 쿨다운 갱신 먼저
    await grant_xp(message.guild, message.author, random.randint(15, 25))

# ================== VOICE XP BACKGROUND TASK ==================
# 음성채널 입장 시간을 tracking, 1분마다 XP 부여
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    guild = member.guild
    now = int(datetime.datetime.utcnow().timestamp())

    # 파티 자동 이동 처리
    cur.execute("SELECT voice_id FROM party WHERE guild_id=? AND owner_id=?", (guild.id, member.id))
    r = cur.fetchone()
    if r and after.channel:
        vc = guild.get_channel(r[0])
        if vc and after.channel.id != vc.id:
            try:
                await member.move_to(vc)
            except Exception:
                pass

    # 음성 채널 입장
    if after.channel and not before.channel:
        cur.execute("INSERT OR REPLACE INTO voice_track VALUES (?,?,?)", (guild.id, member.id, now))
        conn.commit()

    # 음성 채널 퇴장 → 체류시간에 따라 XP 지급
    elif before.channel and not after.channel:
        cur.execute("SELECT joined_at FROM voice_track WHERE guild_id=? AND uid=?", (guild.id, member.id))
        row = cur.fetchone()
        if row:
            duration = now - row[0]   # 초 단위
            minutes = duration // 60
            if minutes > 0:
                xp_gain = min(minutes * 10, 200)   # 분당 10XP, 최대 200XP
                await grant_xp(guild, member, xp_gain)
            cur.execute("DELETE FROM voice_track WHERE guild_id=? AND uid=?", (guild.id, member.id))
            conn.commit()

# ================== STICKY ==================
def get_sticky(channel_id):
    cur.execute("SELECT content, message_id FROM sticky WHERE channel_id=?", (channel_id,))
    r = cur.fetchone(); return r if r else None

def set_sticky(channel_id, guild_id, content, message_id):
    cur.execute("""INSERT INTO sticky VALUES (?,?,?,?)
                   ON CONFLICT(channel_id) DO UPDATE SET
                   content=excluded.content, message_id=excluded.message_id""",
                (channel_id, guild_id, content, message_id)); conn.commit()

def del_sticky(channel_id):
    cur.execute("DELETE FROM sticky WHERE channel_id=?", (channel_id,)); conn.commit()

# ============================================================
# =====================  UI VIEWS  ===========================
# ============================================================

# ── 인증 뷰 ──
class VerifyView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="인증하기", emoji="✅", style=discord.ButtonStyle.success, custom_id="v_verify")
    async def verify(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer(ephemeral=True)
        cfg = get_cfg(itx.guild.id)
        role = itx.guild.get_role(cfg["verify_role"]) if cfg["verify_role"] else None
        if not role:
            role = discord.utils.get(itx.guild.roles, name="인증") or \
                   await itx.guild.create_role(name="인증", color=discord.Color.green())
        if role in itx.user.roles:
            return await itx.followup.send(embed=warn_embed("이미 인증됨", "이미 인증된 상태입니다."), ephemeral=True)
        await itx.user.add_roles(role)
        # DM
        try:
            dm_e = discord.Embed(title="✅  인증 완료",
                description=f"**{itx.guild.name}** 인증 완료!\n> 역할 `{role.name}` 이(가) 부여되었습니다.\n> 즐거운 시간 보내세요 🎉",
                color=0x57F287)
            dm_e.set_thumbnail(url=itx.guild.icon.url if itx.guild.icon else None)
            dm_e.set_footer(text=itx.guild.name)
            dm_e.timestamp = datetime.datetime.utcnow()
            await itx.user.send(embed=dm_e)
        except discord.Forbidden: pass
        await itx.followup.send(embed=success_embed("인증 완료!", f"`{role.name}` 역할 부여됨"), ephemeral=True)
        log_e = discord.Embed(title="📋 인증 로그", color=0x57F287, timestamp=datetime.datetime.utcnow())
        log_e.add_field(name="유저", value=f"{itx.user.mention} (`{itx.user}`)")
        log_e.add_field(name="역할", value=role.mention)
        log_e.set_thumbnail(url=itx.user.display_avatar.url)
        await send_log(itx.guild, [log_e])

# ── 티켓 뷰 ──
class TicketView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="티켓 생성", emoji="🎟️", style=discord.ButtonStyle.primary, custom_id="v_ticket")
    async def create(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer(ephemeral=True)
        existing = discord.utils.get(itx.guild.text_channels, name=f"ticket-{itx.user.name.lower()}")
        if existing:
            return await itx.followup.send(embed=warn_embed("이미 티켓 존재", f"열린 티켓: {existing.mention}"), ephemeral=True)
        cfg = get_cfg(itx.guild.id)
        ow = {
            itx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            itx.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }
        if cfg["admin_role"]:
            ar = itx.guild.get_role(cfg["admin_role"])
            if ar: ow[ar] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        ch = await itx.guild.create_text_channel(
            name=f"ticket-{itx.user.name}", overwrites=ow,
            topic=f"{itx.user} 의 티켓 | {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
        te = discord.Embed(title="🎟️ 티켓 생성됨",
            description=f"안녕하세요 {itx.user.mention}님!\n관리자가 곧 답변드립니다.\n문의 내용을 작성해 주세요.",
            color=0x5865F2, timestamp=datetime.datetime.utcnow())
        te.set_footer(text="티켓을 닫으려면 아래 버튼을 눌러주세요.")
        te.set_thumbnail(url=itx.user.display_avatar.url)
        await ch.send(embed=te, view=TicketCloseView())
        await itx.followup.send(embed=success_embed("티켓 생성 완료", f"채널: {ch.mention}"), ephemeral=True)
        log_e = discord.Embed(title="🎟️ 티켓 생성 로그", color=0x5865F2, timestamp=datetime.datetime.utcnow())
        log_e.add_field(name="유저", value=f"{itx.user.mention} (`{itx.user}`)")
        log_e.add_field(name="채널", value=ch.mention)
        log_e.set_thumbnail(url=itx.user.display_avatar.url)
        await send_log(itx.guild, [log_e])

class TicketCloseView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="티켓 닫기", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="v_ticket_close")
    async def close(self, itx: discord.Interaction, btn: discord.ui.Button):
        if not is_admin(itx):
            return await itx.response.send_message(embed=error_embed("권한 없음", "봇 관리자 역할이 필요합니다."), ephemeral=True)
        await itx.response.send_message(embed=warn_embed("티켓 닫는 중...", "3초 후 채널이 삭제됩니다."))
        await asyncio.sleep(3)
        await itx.channel.delete()

# ── 파티 뷰 ──
class PartyView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="파티 참가", emoji="🎮", style=discord.ButtonStyle.success, custom_id="v_party_join")
    async def join(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer(ephemeral=True)
        cur.execute("SELECT voice_id FROM party WHERE guild_id=? AND owner_id=?", (itx.guild.id, itx.user.id))
        r = cur.fetchone()
        if not r:
            return await itx.followup.send(embed=error_embed("파티 없음"), ephemeral=True)
        vc = itx.guild.get_channel(r[0])
        if vc:
            await itx.user.move_to(vc)
            await itx.followup.send(embed=success_embed("참가 완료", f"{vc.mention}으로 이동"), ephemeral=True)
        else:
            await itx.followup.send(embed=error_embed("채널 없음"), ephemeral=True)

# ── 관리자 패널 뷰 ──
class AdminPanel(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="파티 목록", emoji="🎮", style=discord.ButtonStyle.primary, custom_id="v_ap_party")
    async def party(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer(ephemeral=True)
        cur.execute("SELECT owner_id, voice_id FROM party WHERE guild_id=?", (itx.guild.id,))
        rows = cur.fetchall()
        if not rows:
            return await itx.followup.send(embed=info_embed("파티 없음"), ephemeral=True)
        await itx.followup.send(embed=info_embed("파티 목록", "\n".join(f"<@{r[0]}> → <#{r[1]}>" for r in rows)), ephemeral=True)

    @discord.ui.button(label="경고 목록", emoji="⚠️", style=discord.ButtonStyle.danger, custom_id="v_ap_warn")
    async def warns(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer(ephemeral=True)
        cur.execute("SELECT uid, cnt FROM warn WHERE cnt > 0")
        rows = cur.fetchall()
        if not rows:
            return await itx.followup.send(embed=info_embed("경고 없음"), ephemeral=True)
        await itx.followup.send(embed=warn_embed("경고 목록", "\n".join(f"<@{r[0]}> — **{r[1]}회**" for r in rows)), ephemeral=True)

    @discord.ui.button(label="티켓 목록", emoji="🎟️", style=discord.ButtonStyle.success, custom_id="v_ap_ticket")
    async def tickets(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer(ephemeral=True)
        tks = [c for c in itx.guild.text_channels if c.name.startswith("ticket-")]
        if not tks:
            return await itx.followup.send(embed=info_embed("티켓 없음"), ephemeral=True)
        await itx.followup.send(embed=info_embed(f"티켓 목록 ({len(tks)}개)", "\n".join(c.mention for c in tks)), ephemeral=True)

# ============================================================
# =================  SLASH COMMANDS  ========================
# ============================================================

# ── /역할 ──
@bot.tree.command(name="역할", description="[소유자 전용] 인증 역할 및 봇 관리자 역할을 설정합니다.")
async def cmd_roles(itx: discord.Interaction, 인증역할: discord.Role, 관리자역할: discord.Role):
    if itx.user.id != itx.guild.owner_id and not itx.user.guild_permissions.administrator:
        return await deny(itx)
    set_cfg(itx.guild.id, verify_role=인증역할.id, admin_role=관리자역할.id)
    e = discord.Embed(title="⚙️ 역할 설정 완료", color=0x57F287, timestamp=datetime.datetime.utcnow())
    e.add_field(name="✅ 인증 역할", value=인증역할.mention, inline=True)
    e.add_field(name="🛡️ 관리자 역할", value=관리자역할.mention, inline=True)
    e.set_footer(text=f"설정자: {itx.user}")
    await itx.response.send_message(embed=e)

# ── /채널설정 ──
@bot.tree.command(name="채널설정", description="입장·로그·레벨업 채널 및 파티 카테고리를 설정합니다.")
async def cmd_channels(
    itx: discord.Interaction,
    입장채널: discord.TextChannel,
    로그채널: discord.TextChannel,
    레벨업채널: discord.TextChannel,
    파티카테고리: discord.CategoryChannel
):
    if not is_admin(itx): return await deny(itx)
    set_cfg(itx.guild.id,
            welcome_ch=입장채널.id,
            log_ch=로그채널.id,
            levelup_ch=레벨업채널.id,
            party_cat=파티카테고리.id)
    e = discord.Embed(title="⚙️ 채널 설정 완료", color=0x57F287, timestamp=datetime.datetime.utcnow())
    e.add_field(name="👋 입장", value=입장채널.mention, inline=True)
    e.add_field(name="📋 로그", value=로그채널.mention, inline=True)
    e.add_field(name="⬆️ 레벨업", value=레벨업채널.mention, inline=True)
    e.add_field(name="🎮 파티 카테고리", value=f"`{파티카테고리.name}`", inline=True)
    e.set_footer(text=f"설정자: {itx.user}")
    await itx.response.send_message(embed=e)

# ── /인증패널 ──
@bot.tree.command(name="인증패널", description="인증 패널을 전송합니다.")
async def cmd_verify_panel(itx: discord.Interaction):
    if not is_admin(itx): return await deny(itx)
    e = discord.Embed(title="✅ 서버 인증",
        description="아래 버튼을 눌러 인증을 완료하세요.\n> 인증 완료 시 역할이 자동 부여됩니다.\n> 완료 후 DM으로 안내가 전송됩니다.",
        color=0x57F287, timestamp=datetime.datetime.utcnow())
    e.set_footer(text=itx.guild.name, icon_url=itx.guild.icon.url if itx.guild.icon else None)
    await itx.response.send_message(embed=e, view=VerifyView())

# ── /티켓패널 ──
@bot.tree.command(name="티켓패널", description="티켓 패널을 전송합니다.")
async def cmd_ticket_panel(itx: discord.Interaction):
    if not is_admin(itx): return await deny(itx)
    e = discord.Embed(title="🎟️ 티켓 시스템",
        description="문의사항이 있으면 아래 버튼을 눌러 티켓을 생성하세요.\n> 1인당 1개만 생성 가능합니다.",
        color=0x5865F2, timestamp=datetime.datetime.utcnow())
    e.set_footer(text=itx.guild.name, icon_url=itx.guild.icon.url if itx.guild.icon else None)
    await itx.response.send_message(embed=e, view=TicketView())

# ── /관리자패널 ──
@bot.tree.command(name="관리자패널", description="관리자 패널을 전송합니다.")
async def cmd_admin_panel(itx: discord.Interaction):
    if not is_admin(itx): return await deny(itx)
    e = discord.Embed(title="⚙️ 관리자 패널",
        description="서버 관리 도구입니다. 버튼으로 각 기능을 확인하세요.",
        color=0xEB459E, timestamp=datetime.datetime.utcnow())
    e.set_footer(text=f"관리자: {itx.user}", icon_url=itx.user.display_avatar.url)
    await itx.response.send_message(embed=e, view=AdminPanel())

# ── /청소 ──
@bot.tree.command(name="청소", description="메시지를 일괄 삭제합니다. (최대 100개)")
async def cmd_purge(itx: discord.Interaction, 개수: int):
    if not is_admin(itx): return await deny(itx)
    if not 1 <= 개수 <= 100:
        return await itx.response.send_message(embed=error_embed("잘못된 입력", "1~100 사이 숫자를 입력하세요."), ephemeral=True)
    await itx.response.defer(ephemeral=True)
    deleted = await itx.channel.purge(limit=개수)
    res_e = discord.Embed(title="🧹 청소 완료", description=f"**{len(deleted)}개** 삭제 완료",
        color=0x57F287, timestamp=datetime.datetime.utcnow())
    res_e.add_field(name="채널", value=itx.channel.mention, inline=True)
    res_e.add_field(name="실행자", value=itx.user.mention, inline=True)
    await itx.followup.send(embed=res_e, ephemeral=True)
    log_e = discord.Embed(title="🧹 청소 로그", color=0x57F287, timestamp=datetime.datetime.utcnow())
    log_e.add_field(name="채널", value=itx.channel.mention)
    log_e.add_field(name="삭제 수", value=f"**{len(deleted)}개**")
    log_e.add_field(name="실행자", value=f"{itx.user.mention} (`{itx.user}`)", inline=False)
    await send_log(itx.guild, [log_e])

# ── /경고 ──
@bot.tree.command(name="경고", description="유저에게 경고를 부여합니다.")
async def cmd_warn(itx: discord.Interaction, 유저: discord.Member):
    if not is_admin(itx): return await deny(itx)
    c = add_warn(유저.id)
    e = discord.Embed(title="⚠️ 경고 부여", color=0xFEE75C, timestamp=datetime.datetime.utcnow())
    e.add_field(name="대상", value=유저.mention, inline=True)
    e.add_field(name="누적 경고", value=f"**{c}회**", inline=True)
    e.set_thumbnail(url=유저.display_avatar.url)
    await itx.response.send_message(embed=e)
    await send_log(itx.guild, [e])
    # 자동 처벌
    try:
        if c == 3:
            until = discord.utils.utcnow() + datetime.timedelta(hours=1)
            await 유저.timeout(until, reason="경고 3회 누적 — 1시간 타임아웃")
        elif c == 5:
            await 유저.kick(reason="경고 5회 누적")
        elif c >= 7:
            await 유저.ban(reason="경고 7회 누적")
    except Exception:
        pass

# ── /경고삭제 ──
@bot.tree.command(name="경고삭제", description="유저의 경고를 초기화합니다.")
async def cmd_warn_clear(itx: discord.Interaction, 유저: discord.Member):
    if not is_admin(itx): return await deny(itx)
    clear_warn(유저.id)
    await itx.response.send_message(embed=success_embed("경고 초기화", f"{유저.mention} 경고 초기화 완료"))

# ── /잔액 ──
@bot.tree.command(name="잔액", description="잔액을 확인합니다.")
async def cmd_bal(itx: discord.Interaction, 유저: discord.Member = None):
    user = 유저 or itx.user
    e = discord.Embed(title="💰 잔액 조회", color=0xF1C40F, timestamp=datetime.datetime.utcnow())
    e.add_field(name="유저", value=user.mention, inline=True)
    e.add_field(name="잔액", value=f"**{money(user.id):,}원**", inline=True)
    e.set_thumbnail(url=user.display_avatar.url)
    await itx.response.send_message(embed=e)

# ── /송금 ──
@bot.tree.command(name="송금", description="다른 유저에게 송금합니다.")
async def cmd_pay(itx: discord.Interaction, 유저: discord.Member, 금액: int):
    if 금액 <= 0:
        return await itx.response.send_message(embed=error_embed("잘못된 금액"), ephemeral=True)
    if money(itx.user.id) < 금액:
        return await itx.response.send_message(embed=error_embed("잔액 부족"), ephemeral=True)
    sub_money(itx.user.id, 금액); add_money(유저.id, 금액)
    e = discord.Embed(title="💸 송금 완료", color=0x57F287, timestamp=datetime.datetime.utcnow())
    e.add_field(name="보낸 사람", value=itx.user.mention, inline=True)
    e.add_field(name="받은 사람", value=유저.mention, inline=True)
    e.add_field(name="금액", value=f"**{금액:,}원**", inline=False)
    await itx.response.send_message(embed=e)

# ── /레벨 ──
@bot.tree.command(name="레벨", description="레벨을 확인합니다.")
async def cmd_level(itx: discord.Interaction, 유저: discord.Member = None):
    user = 유저 or itx.user
    xp, lv, _ = get_lv(itx.guild.id, user.id)
    needed = xp_needed(lv)
    rank = get_rank(itx.guild.id, user.id)
    filled = int((xp / needed) * 20)
    bar = "█" * filled + "░" * (20 - filled)
    e = discord.Embed(title="⭐ 레벨 정보", color=0xF1C40F, timestamp=datetime.datetime.utcnow())
    e.set_thumbnail(url=user.display_avatar.url)
    e.add_field(name="유저",     value=user.mention,              inline=True)
    e.add_field(name="레벨",     value=f"**{lv}**",               inline=True)
    e.add_field(name="서버 순위", value=f"**#{rank}**",            inline=True)
    e.add_field(name="경험치",   value=f"`{xp:,}` / `{needed:,}`", inline=True)
    e.add_field(name="진행도",   value=f"`{bar}` {int(xp/needed*100)}%", inline=False)
    e.set_footer(text=f"{itx.guild.name} 레벨 시스템")
    await itx.response.send_message(embed=e)

# ── /순위 ──
@bot.tree.command(name="순위", description="서버 레벨 순위를 확인합니다.")
async def cmd_rank(itx: discord.Interaction):
    rows = get_top(itx.guild.id)
    if not rows:
        return await itx.response.send_message(embed=info_embed("순위 없음", "아직 레벨 데이터가 없습니다."), ephemeral=True)
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    desc = "\n".join(f"{medals.get(i, f'`{i}.`')} <@{uid}> — **레벨 {lv}** (`{xp:,}` XP)"
                     for i, (uid, xp, lv) in enumerate(rows, 1))
    e = discord.Embed(title="🏆 레벨 순위", description=desc, color=0xF1C40F, timestamp=datetime.datetime.utcnow())
    e.set_footer(text=f"{itx.guild.name} 레벨 시스템")
    await itx.response.send_message(embed=e)

# ── /파티생성 ──
@bot.tree.command(name="파티생성", description="파티 음성 채널을 생성합니다.")
async def cmd_party_create(itx: discord.Interaction):
    await itx.response.defer()
    cur.execute("SELECT voice_id FROM party WHERE guild_id=? AND owner_id=?", (itx.guild.id, itx.user.id))
    if cur.fetchone():
        return await itx.followup.send(embed=warn_embed("이미 파티 존재", "기존 파티를 먼저 삭제하세요."), ephemeral=True)
    cfg = get_cfg(itx.guild.id)
    category = itx.guild.get_channel(cfg["party_cat"]) if cfg["party_cat"] else None
    vc = await itx.guild.create_voice_channel(
        name=f"🎮 {itx.user.display_name}의 파티",
        category=category
    )
    cur.execute("INSERT OR REPLACE INTO party VALUES (?,?,?)", (itx.guild.id, itx.user.id, vc.id))
    conn.commit()
    await itx.followup.send(embed=success_embed("파티 생성 완료", f"채널 {vc.mention} 생성됨"), view=PartyView())

# ── /파티삭제 ──
@bot.tree.command(name="파티삭제", description="자신의 파티 채널을 삭제합니다.")
async def cmd_party_delete(itx: discord.Interaction):
    await itx.response.defer()
    cur.execute("SELECT voice_id FROM party WHERE guild_id=? AND owner_id=?", (itx.guild.id, itx.user.id))
    r = cur.fetchone()
    if not r:
        return await itx.followup.send(embed=error_embed("파티 없음"), ephemeral=True)
    vc = itx.guild.get_channel(r[0])
    if vc: await vc.delete()
    cur.execute("DELETE FROM party WHERE guild_id=? AND owner_id=?", (itx.guild.id, itx.user.id))
    conn.commit()
    await itx.followup.send(embed=success_embed("파티 삭제 완료"))

# ── /스티키 ──
@bot.tree.command(name="스티키", description="채널에 고정 메시지를 설정합니다.")
async def cmd_sticky_set(itx: discord.Interaction, 내용: str):
    if not is_admin(itx): return await deny(itx)
    await itx.response.defer(ephemeral=True)
    existing = get_sticky(itx.channel.id)
    if existing:
        try:
            old = await itx.channel.fetch_message(existing[1])
            await old.delete()
        except Exception: pass
    se = discord.Embed(title="📌 고정 메시지", description=내용, color=0xF1C40F, timestamp=datetime.datetime.utcnow())
    se.set_footer(text="📌 이 메시지는 채널 하단에 고정됩니다.")
    msg = await itx.channel.send(embed=se)
    set_sticky(itx.channel.id, itx.guild.id, 내용, msg.id)
    await itx.followup.send(embed=success_embed("스티키 설정 완료"), ephemeral=True)

# ── /스티키해제 ──
@bot.tree.command(name="스티키해제", description="채널의 고정 메시지를 해제합니다.")
async def cmd_sticky_remove(itx: discord.Interaction):
    if not is_admin(itx): return await deny(itx)
    existing = get_sticky(itx.channel.id)
    if not existing:
        return await itx.response.send_message(embed=warn_embed("스티키 없음"), ephemeral=True)
    try:
        old = await itx.channel.fetch_message(existing[1])
        await old.delete()
    except Exception: pass
    del_sticky(itx.channel.id)
    await itx.response.send_message(embed=success_embed("스티키 해제 완료"), ephemeral=True)

# ============================================================
# ================  PREFIX COMMANDS (!)  =====================
# ============================================================

@bot.command(name="레벨", aliases=["lv", "level"])
async def pfx_level(ctx: commands.Context, 유저: discord.Member = None):
    user = 유저 or ctx.author
    xp, lv, _ = get_lv(ctx.guild.id, user.id)
    needed = xp_needed(lv)
    rank = get_rank(ctx.guild.id, user.id)
    filled = int((xp / needed) * 20)
    bar = "█" * filled + "░" * (20 - filled)
    e = discord.Embed(title="⭐ 레벨 정보", color=0xF1C40F, timestamp=datetime.datetime.utcnow())
    e.set_thumbnail(url=user.display_avatar.url)
    e.add_field(name="유저",     value=user.mention)
    e.add_field(name="레벨",     value=f"**{lv}**")
    e.add_field(name="서버 순위", value=f"**#{rank}**")
    e.add_field(name="경험치",   value=f"`{xp:,}` / `{needed:,}`")
    e.add_field(name="진행도",   value=f"`{bar}` {int(xp/needed*100)}%", inline=False)
    e.set_footer(text=f"{ctx.guild.name} 레벨 시스템")
    await ctx.send(embed=e)

@bot.command(name="순위", aliases=["rank", "top"])
async def pfx_rank(ctx: commands.Context):
    rows = get_top(ctx.guild.id)
    if not rows:
        return await ctx.send(embed=info_embed("순위 없음", "아직 데이터가 없습니다."))
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    desc = "\n".join(f"{medals.get(i, f'`{i}.`')} <@{uid}> — **레벨 {lv}** (`{xp:,}` XP)"
                     for i, (uid, xp, lv) in enumerate(rows, 1))
    e = discord.Embed(title="🏆 레벨 순위", description=desc, color=0xF1C40F, timestamp=datetime.datetime.utcnow())
    e.set_footer(text=f"{ctx.guild.name} 레벨 시스템")
    await ctx.send(embed=e)

@bot.command(name="잔액", aliases=["bal", "money"])
async def pfx_bal(ctx: commands.Context, 유저: discord.Member = None):
    user = 유저 or ctx.author
    e = discord.Embed(title="💰 잔액 조회", color=0xF1C40F, timestamp=datetime.datetime.utcnow())
    e.add_field(name="유저", value=user.mention)
    e.add_field(name="잔액", value=f"**{money(user.id):,}원**")
    e.set_thumbnail(url=user.display_avatar.url)
    await ctx.send(embed=e)

@bot.command(name="송금", aliases=["pay"])
async def pfx_pay(ctx: commands.Context, 유저: discord.Member, 금액: int):
    if 금액 <= 0: return await ctx.send(embed=error_embed("잘못된 금액"))
    if money(ctx.author.id) < 금액: return await ctx.send(embed=error_embed("잔액 부족"))
    sub_money(ctx.author.id, 금액); add_money(유저.id, 금액)
    e = discord.Embed(title="💸 송금 완료", color=0x57F287, timestamp=datetime.datetime.utcnow())
    e.add_field(name="보낸 사람", value=ctx.author.mention, inline=True)
    e.add_field(name="받은 사람", value=유저.mention, inline=True)
    e.add_field(name="금액", value=f"**{금액:,}원**", inline=False)
    await ctx.send(embed=e)

@bot.command(name="경고", aliases=["warn"])
async def pfx_warn(ctx: commands.Context, 유저: discord.Member):
    if not is_admin_ctx(ctx):
        return await ctx.send(embed=error_embed("권한 없음", "봇 관리자 역할이 필요합니다."))
    c = add_warn(유저.id)
    e = discord.Embed(title="⚠️ 경고 부여", color=0xFEE75C, timestamp=datetime.datetime.utcnow())
    e.add_field(name="대상", value=유저.mention, inline=True)
    e.add_field(name="누적 경고", value=f"**{c}회**", inline=True)
    e.set_thumbnail(url=유저.display_avatar.url)
    await ctx.send(embed=e)
    await send_log(ctx.guild, [e])
    try:
        if c == 3:
            until = discord.utils.utcnow() + datetime.timedelta(hours=1)
            await 유저.timeout(until, reason="경고 3회 — 타임아웃")
        elif c == 5:
            await 유저.kick(reason="경고 5회 — 킥")
        elif c >= 7:
            await 유저.ban(reason="경고 7회 — 밴")
    except Exception: pass

@bot.command(name="경고삭제", aliases=["clearwarn"])
async def pfx_warn_clear(ctx: commands.Context, 유저: discord.Member):
    if not is_admin_ctx(ctx):
        return await ctx.send(embed=error_embed("권한 없음"))
    clear_warn(유저.id)
    await ctx.send(embed=success_embed("경고 초기화", f"{유저.mention} 경고 초기화 완료"))

@bot.command(name="청소", aliases=["purge", "clear"])
async def pfx_purge(ctx: commands.Context, 개수: int):
    if not is_admin_ctx(ctx):
        return await ctx.send(embed=error_embed("권한 없음"))
    if not 1 <= 개수 <= 100:
        return await ctx.send(embed=error_embed("잘못된 입력", "1~100 사이 숫자를 입력하세요."))
    deleted = await ctx.channel.purge(limit=개수 + 1)
    notice = await ctx.send(embed=success_embed("청소 완료", f"**{len(deleted)-1}개** 삭제 완료"))
    await asyncio.sleep(5); await notice.delete()
    log_e = discord.Embed(title="🧹 청소 로그", color=0x57F287, timestamp=datetime.datetime.utcnow())
    log_e.add_field(name="채널", value=ctx.channel.mention)
    log_e.add_field(name="삭제 수", value=f"**{len(deleted)-1}개**")
    log_e.add_field(name="실행자", value=f"{ctx.author.mention} (`{ctx.author}`)", inline=False)
    await send_log(ctx.guild, [log_e])

@bot.command(name="도움말", aliases=["h", "명령어"])
async def pfx_help(ctx: commands.Context):
    e = discord.Embed(title="📖 명령어 도움말",
        description="슬래시(`/`) 및 접두사(`!`) 명령어 모두 지원합니다.",
        color=0x5865F2, timestamp=datetime.datetime.utcnow())
    e.add_field(name="⭐ 레벨",     value="`/레벨 [유저]`  `!레벨`\n`/순위`  `!순위`", inline=False)
    e.add_field(name="💰 경제",     value="`/잔액 [유저]`  `!잔액`\n`/송금 @유저 금액`  `!송금`", inline=False)
    e.add_field(name="⚠️ 경고",     value="`/경고 @유저`  `!경고`\n`/경고삭제 @유저`  `!경고삭제`", inline=False)
    e.add_field(name="🧹 청소",     value="`/청소 개수`  `!청소 개수`", inline=False)
    e.add_field(name="📌 스티키",   value="`/스티키 내용`  `/스티키해제`", inline=False)
    e.add_field(name="🎮 파티",     value="`/파티생성`  `/파티삭제`", inline=False)
    e.add_field(name="⚙️ 설정 (관리자)", value="`/역할`  `/채널설정`\n`/인증패널`  `/티켓패널`  `/관리자패널`", inline=False)
    e.set_footer(text=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    await ctx.send(embed=e)

# ============================================================
# ===================  GLOBAL EVENTS  =======================
# ============================================================

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot: return
    await bot.process_commands(message)
    if not message.guild: return

    # 채팅 XP
    await process_chat_xp(message)

    # 스티키 처리
    sticky = get_sticky(message.channel.id)
    if not sticky: return
    content, old_id = sticky
    try:
        old_msg = await message.channel.fetch_message(old_id)
        await old_msg.delete()
    except Exception: pass
    se = discord.Embed(title="📌 고정 메시지", description=content, color=0xF1C40F, timestamp=datetime.datetime.utcnow())
    se.set_footer(text="📌 이 메시지는 채널 하단에 고정됩니다.")
    new_msg = await message.channel.send(embed=se)
    set_sticky(message.channel.id, message.guild.id, content, new_msg.id)


@bot.event
async def on_member_join(member: discord.Member):
    cfg = get_cfg(member.guild.id)
    if not cfg["welcome_ch"]: return
    ch = member.guild.get_channel(cfg["welcome_ch"])
    if not ch: return
    e = discord.Embed(
        title="👋 새로운 멤버 입장!",
        description=(
            f"{member.mention} 님, **{member.guild.name}** 에 오신 것을 환영합니다!\n\n"
            "> 서버 규칙을 꼭 읽어보세요.\n"
            "> 인증을 완료하면 더 많은 채널을 이용할 수 있습니다."
        ),
        color=0x57F287, timestamp=datetime.datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"현재 멤버 수: {member.guild.member_count}명")
    await ch.send(embed=e)


@bot.event
async def on_member_remove(member: discord.Member):
    cfg = get_cfg(member.guild.id)
    if not cfg["log_ch"]: return
    ch = member.guild.get_channel(cfg["log_ch"])
    if not ch: return
    e = discord.Embed(
        title="👋 멤버 퇴장",
        description=f"**{member}** 님이 서버를 떠났습니다.",
        color=0xED4245, timestamp=datetime.datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"현재 멤버 수: {member.guild.member_count}명")
    await ch.send(embed=e)


@bot.event
async def on_ready():
    init_db()
    # Persistent View 등록 (봇 재시작 후 버튼 유지)
    for view in [VerifyView(), TicketView(), TicketCloseView(), PartyView(), AdminPanel()]:
        bot.add_view(view)
    await bot.tree.sync()
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="서버 관리 중 👀")
    )
    print(f"🔥 QUABOT READY | {bot.user} ({bot.user.id})")


# ================== RUN ==================
def start():
    keep_alive()
    bot.run(TOKEN)

start()
