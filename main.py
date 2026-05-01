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
DB_PATH = "bot.db"

SALARY_AMOUNT = 50000
SALARY_COOLDOWN = 15
MAX_BET = 1000000

salary_cooldowns = {}

# ================= KEEP ALIVE FOR RENDER =================
app = Flask(__name__)

@app.route("/")
def home():
    return "BOT ONLINE"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    Thread(target=run_web, daemon=True).start()

# ================= DB =================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            admin_role_id INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS money (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER
        )
    """)
    conn.commit()

# ================= BOT =================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
bot_ready_synced = False

# ================= EMBED =================
def embed(title, desc="", color=0x5865F2):
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = datetime.datetime.utcnow()
    return e

# ================= MONEY =================
def format_money(amount):
    return f"{amount:,}원"

def get_money(uid):
    cursor.execute("SELECT balance FROM money WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r[0] if r else 0

def set_money(uid, amount):
    amount = max(amount, 0)
    cursor.execute("REPLACE INTO money VALUES(?,?)", (uid, amount))
    conn.commit()

def add_money(uid, amount):
    balance = get_money(uid) + amount
    set_money(uid, balance)
    return balance

def remove_money(uid, amount):
    balance = max(get_money(uid) - amount, 0)
    set_money(uid, balance)
    return balance

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
    except Exception as e:
        print(f"처벌 오류: {e}")

async def remove_punish(member):
    try:
        await member.timeout(None)
    except Exception as e:
        print(f"처벌 해제 오류: {e}")

# ================= LEVEL =================
def add_xp(uid):
    cursor.execute("SELECT xp, level FROM levels WHERE user_id=?", (uid,))
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
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="인증", style=discord.ButtonStyle.success, custom_id="verify_button")
    async def verify(self, i: discord.Interaction, b: discord.ui.Button):
        role = i.guild.get_role(VERIFY_ROLE_ID)
        if not role:
            role = await i.guild.create_role(name="인증")

        await i.user.add_roles(role)
        await i.response.send_message(embed=embed("인증 완료"), ephemeral=True)

# ================= TICKET =================
class CloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="닫기", style=discord.ButtonStyle.danger, custom_id="ticket_close_button")
    async def close(self, i: discord.Interaction, b: discord.ui.Button):
        await i.channel.delete()

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="티켓 생성", style=discord.ButtonStyle.primary, custom_id="ticket_create_button")
    async def create(self, i: discord.Interaction, b: discord.ui.Button):
        cat = discord.utils.get(i.guild.categories, id=TICKET_CATEGORY_ID)

        ch = await i.guild.create_text_channel(
            name=f"ticket-{i.user.id}",
            category=cat
        )

        await ch.send(i.user.mention, view=CloseView())
        await i.response.send_message(embed=embed("티켓 생성"), ephemeral=True)

# ================= PARTY =================
class PartyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def create(self, i: discord.Interaction, size: int):
        cat = discord.utils.get(i.guild.categories, name=PARTY_CATEGORY_NAME)
        if not cat:
            cat = await i.guild.create_category(PARTY_CATEGORY_NAME)

        await i.guild.create_voice_channel(
            name=f"🎮 파티-{i.user.display_name}-{size}",
            category=cat
        )

        await i.response.send_message(embed=embed("파티 생성 완료"), ephemeral=True)

    @discord.ui.button(label="솔로", style=discord.ButtonStyle.primary, custom_id="party_solo")
    async def solo(self, i, b):
        await self.create(i, 1)

    @discord.ui.button(label="듀오", style=discord.ButtonStyle.primary, custom_id="party_duo")
    async def duo(self, i, b):
        await self.create(i, 2)

    @discord.ui.button(label="트리오", style=discord.ButtonStyle.primary, custom_id="party_trio")
    async def trio(self, i, b):
        await self.create(i, 3)

    @discord.ui.button(label="스쿼드", style=discord.ButtonStyle.primary, custom_id="party_squad")
    async def squad(self, i, b):
        await self.create(i, 4)

    @discord.ui.button(label="5인", style=discord.ButtonStyle.primary, custom_id="party_five")
    async def five(self, i, b):
        await self.create(i, 5)

# ================= SOLO 홀짝 =================
class OddEvenView(discord.ui.View):
    def __init__(self, player_id, bet):
        super().__init__(timeout=30)
        self.player_id = player_id
        self.bet = bet
        self.finished = False

    async def check_answer(self, i: discord.Interaction, choice: str):
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
            win_amount = self.bet * 2
            new_balance = add_money(i.user.id, win_amount)

            title = "🎉 정답"
            desc = (
                f"나온 숫자: `{number}`\n"
                f"결과: `{result}`\n"
                f"획득금: `{format_money(win_amount)}`\n"
                f"현재 잔액: `{format_money(new_balance)}`"
            )
            color = 0x57F287
        else:
            title = "💥 실패"
            desc = (
                f"나온 숫자: `{number}`\n"
                f"결과: `{result}`\n"
                f"잃은 금액: `{format_money(self.bet)}`\n"
                f"현재 잔액: `{format_money(get_money(i.user.id))}`"
            )
            color = 0xED4245

        await i.response.edit_message(embed=embed(title, desc, color), view=self)

    @discord.ui.button(label="홀수", style=discord.ButtonStyle.primary)
    async def odd(self, i, b):
        await self.check_answer(i, "홀수")

    @discord.ui.button(label="짝수", style=discord.ButtonStyle.success)
    async def even(self, i, b):
        await self.check_answer(i, "짝수")

# ================= 1VS1 홀짝 =================
class DuelChoiceView(discord.ui.View):
    def __init__(self, player1: discord.Member, player2: discord.Member, bet: int):
        super().__init__(timeout=60)
        self.player1 = player1
        self.player2 = player2
        self.bet = bet
        self.choices = {}
        self.finished = False

    async def choose(self, i: discord.Interaction, choice: str):
        if i.user.id not in [self.player1.id, self.player2.id]:
            return await i.response.send_message("❌ 대결 참가자만 선택할 수 있습니다.", ephemeral=True)

        if self.finished:
            return await i.response.send_message("❌ 이미 끝난 대결입니다.", ephemeral=True)

        if i.user.id in self.choices:
            return await i.response.send_message("❌ 이미 선택했습니다.", ephemeral=True)

        other_choices = list(self.choices.values())
        if choice in other_choices:
            return await i.response.send_message("❌ 상대가 이미 선택한 쪽입니다. 반대쪽을 선택하세요.", ephemeral=True)

        self.choices[i.user.id] = choice

        if len(self.choices) < 2:
            return await i.response.send_message(f"✅
