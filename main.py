import discord
from discord.ext import commands
import os
import sqlite3
import datetime
import asyncio
import random
from flask import Flask
from threading import Thread

# ================= CONFIG =================
TOKEN = os.getenv("TOKEN")

WELCOME_CHANNEL_ID = 1496478743873589448
TICKET_CATEGORY_ID = 1496840441654677614
VERIFY_ROLE_ID = 1499675598178750560

PARTY_CATEGORY_NAME = "🎮 파티"

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
    cursor.execute("CREATE TABLE IF NOT EXISTS guild_config (guild_id INTEGER PRIMARY KEY, admin_role_id INTEGER)")
    conn.commit()

# ================= BOT =================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= EMBED =================
def embed(title, desc="", color=0x5865F2):
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = datetime.datetime.utcnow()
    return e

# ================= ADMIN ROLE =================
def get_admin_role(guild_id):
    cursor.execute("SELECT admin_role_id FROM guild_config WHERE guild_id=?", (guild_id,))
    r = cursor.fetchone()
    return r[0] if r else None

def is_admin(member):
    if member.guild_permissions.administrator:
        return True

    role_id = get_admin_role(member.guild.id)
    return role_id and any(r.id == role_id for r in member.roles)

# ================= WARNING =================
def get_warn(uid):
    cursor.execute("SELECT count FROM warnings WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r[0] if r else 0

def set_warn(uid, value):
    cursor.execute("REPLACE INTO warnings VALUES(?,?)", (uid, value))
    conn.commit()

def add_warn(uid):
    c = get_warn(uid) + 1
    set_warn(uid, c)
    return c

def remove_warn(uid):
    c = max(get_warn(uid) - 1, 0)
    set_warn(uid, c)
    return c

def clear_warn(uid):
    set_warn(uid, 0)

# ================= PUNISH =================
async def auto_punish(member, count):
    try:
        if count == 1:
            await member.timeout(datetime.timedelta(minutes=10))
        elif count == 2:
            await member.timeout(datetime.timedelta(hours=1))
        elif count == 3:
            await member.timeout(datetime.timedelta(days=1))
        elif count == 4:
            await member.kick()
        elif count >= 5:
            await member.ban()
    except:
        pass

async def remove_punish(member):
    try:
        await member.timeout(None)
    except:
        pass

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

# ================= VERIFY =================
class VerifyView(discord.ui.View):
    @discord.ui.button(label="인증", style=discord.ButtonStyle.success)
    async def verify(self, i, b):
        role = i.guild.get_role(VERIFY_ROLE_ID)
        if not role:
            role = await i.guild.create_role(name="인증")

        await i.user.add_roles(role)
        await i.response.send_message(embed=embed("인증 완료"), ephemeral=True)

# ================= TICKET =================
class CloseView(discord.ui.View):
    @discord.ui.button(label="닫기", style=discord.ButtonStyle.danger)
    async def close(self, i, b):
        await i.channel.delete()

class TicketView(discord.ui.View):
    @discord.ui.button(label="티켓 생성", style=discord.ButtonStyle.primary)
    async def create(self, i, b):
        cat = discord.utils.get(i.guild.categories, id=TICKET_CATEGORY_ID)

        ch = await i.guild.create_text_channel(
            name=f"ticket-{i.user.id}",
            category=cat
        )

        await ch.send(i.user.mention, view=CloseView())
        await i.response.send_message(embed=embed("티켓 생성"), ephemeral=True)

# ================= PARTY =================
class PartyControlView(discord.ui.View):
    def __init__(self, owner_id):
        super().__init__(timeout=None)
        self.owner_id = owner_id

    @discord.ui.button(label="파티 삭제", style=discord.ButtonStyle.danger)
    async def delete(self, i, b):
        if i.user.id != self.owner_id:
            return await i.response.send_message("❌ 파티장만 가능", ephemeral=True)

        await i.channel.delete()

class PartyView(discord.ui.View):
    async def create(self, i, size):
        cat = discord.utils.get(i.guild.categories, name=PARTY_CATEGORY_NAME)
        if not cat:
            cat = await i.guild.create_category(PARTY_CATEGORY_NAME)

        await i.guild.create_voice_channel(
            name=f"🎮 파티-{i.user.display_name}-{size}",
            category=cat
        )

        await i.response.send_message(embed=embed("파티 생성 완료"), ephemeral=True)

    @discord.ui.button(label="솔로", style=discord.ButtonStyle.primary)
    async def solo(self, i, b):
        await self.create(i, 1)

    @discord.ui.button(label="듀오", style=discord.ButtonStyle.primary)
    async def duo(self, i, b):
        await self.create(i, 2)

    @discord.ui.button(label="트리오", style=discord.ButtonStyle.primary)
    async def trio(self, i, b):
        await self.create(i, 3)

    @discord.ui.button(label="스쿼드", style=discord.ButtonStyle.primary)
    async def squad(self, i, b):
        await self.create(i, 4)

    @discord.ui.button(label="5인", style=discord.ButtonStyle.primary)
    async def five(self, i, b):
        await self.create(i, 5)

# ================= 홀수 짝수 게임 =================
class OddEvenView(discord.ui.View):
    def __init__(self, player_id):
        super().__init__(timeout=30)
        self.player_id = player_id
        self.finished = False

    async def check_answer(self, i, choice):
        if i.user.id != self.player_id:
            return await i.response.send_message("❌ 게임을 시작한 사람만 누를 수 있습니다.", ephemeral=True)

        if self.finished:
            return await i.response.send_message("❌ 이미 끝난 게임입니다.", ephemeral=True)

        self.finished = True

        number = random.randint(1, 100)
        result = "홀수" if number % 2 == 1 else "짝수"

        for item in self.children:
            item.disabled = True

        if choice == result:
            title = "🎉 정답"
            desc = f"나온 숫자: `{number}`\n결과: `{result}`\n{i.user.mention} 승리!"
            color = 0x57F287
        else:
            title = "💥 실패"
            desc = f"나온 숫자: `{number}`\n결과: `{result}`\n{i.user.mention} 패배!"
            color = 0xED4245

        await i.response.edit_message(embed=embed(title, desc, color), view=self)

    @discord.ui.button(label="홀수", style=discord.ButtonStyle.primary)
    async def odd(self, i, b):
        await self.check_answer(i, "홀수")

    @discord.ui.button(label="짝수", style=discord.ButtonStyle.success)
    async def even(self, i, b):
        await self.check_answer(i, "짝수")

# ================= EVENTS =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print("🔥 BOT READY")

@bot.event
async def on_member_join(member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await ch.send(embed=embed("환영", member.mention))

@bot.event
async def on_message(m):
    if m.author.bot:
        return

    lv, xp = add_xp(m.author.id)

    if xp == 0:
        await m.channel.send(embed=embed("레벨업", f"{m.author.mention} → LV {lv}"))

    await bot.process_commands(m)

# ================= COMMANDS =================
@bot.tree.command(name="경고")
async def warn(i, user: discord.Member, reason: str = "없음"):
    if not is_admin(i.user):
        return await i.response.send_message("❌ 권한 없음", ephemeral=True)

    c = add_warn(user.id)
    await auto_punish(user, c)

    await i.response.send_message(embed=embed("경고", f"{user.mention}\n{reason}\n{c}회"))

@bot.tree.command(name="경고삭제")
async def warn_clear(i, user: discord.Member):
    if not is_admin(i.user):
        return await i.response.send_message("❌ 권한 없음", ephemeral=True)

    clear_warn(user.id)
    await remove_punish(user)

    await i.response.send_message(embed=embed("경고 초기화"))

@bot.tree.command(name="인증패널")
async def verify_panel(i):
    await i.response.send_message(embed=embed("인증"), view=VerifyView())

@bot.tree.command(name="티켓패널")
async def ticket_panel(i):
    await i.response.send_message(embed=embed("티켓"), view=TicketView())

@bot.tree.command(name="파티패널")
async def party_panel(i):
    await i.response.send_message(embed=embed("파티 시스템 🎮"), view=PartyView())

@bot.tree.command(name="홀짝")
async def odd_even_game(i):
    await i.response.send_message(
        embed=embed("🎲 홀수 짝수 게임", f"{i.user.mention}, 홀수 또는 짝수를 선택하세요!"),
        view=OddEvenView(i.user.id)
    )

@bot.tree.command(name="파티삭제")
async def party_delete(i):
    if not isinstance(i.channel, discord.VoiceChannel):
        return await i.response.send_message("❌ 음성채널만 가능", ephemeral=True)

    await i.channel.delete()

# ================= RUN =================
async def main():
    keep_alive()
    await bot.start(TOKEN)

asyncio.run(main())
