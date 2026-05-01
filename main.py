import discord
from discord.ext import commands
import os
import sqlite3
import datetime
import asyncio
import random
from flask import Flask
from threading import Thread

TOKEN = os.getenv("TOKEN")

WELCOME_CHANNEL_ID = 1496478743873589448
TICKET_CATEGORY_ID = 1496840441654677614
VERIFY_ROLE_ID = 1499675598178750560

PARTY_CATEGORY_NAME = "🎮 파티"
DB_PATH = "bot.db"

SALARY_AMOUNT = 100000
SALARY_COOLDOWN = 5
ATTENDANCE_AMOUNT = 500000
MAX_BET = 1000000

DICE_COST = 50000
DICE_WIN_AMOUNT = DICE_COST * 3

salary_cooldowns = {}

app = Flask(__name__)

@app.route("/")
def home():
    return "BOT ONLINE"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    Thread(target=run_web, daemon=True).start()

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.execute("CREATE TABLE IF NOT EXISTS warnings (user_id INTEGER PRIMARY KEY, count INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS levels (user_id INTEGER PRIMARY KEY, xp INTEGER, level INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS guild_config (guild_id INTEGER PRIMARY KEY, admin_role_id INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS money (user_id INTEGER PRIMARY KEY, balance INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS attendance (user_id INTEGER PRIMARY KEY, last_date TEXT)")
    conn.commit()

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
bot_ready_synced = False

def embed(title, desc="", color=0x5865F2):
    e = discord.Embed(title=title, description=desc, color=color)
    e.timestamp = datetime.datetime.utcnow()
    return e

def format_money(amount):
    return f"{amount:,}원"

def today_kst():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")

def get_money(uid):
    cursor.execute("SELECT balance FROM money WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r[0] if r else 0

def set_money(uid, amount):
    cursor.execute("REPLACE INTO money VALUES(?,?)", (uid, max(amount, 0)))
    conn.commit()

def add_money(uid, amount):
    balance = get_money(uid) + amount
    set_money(uid, balance)
    return balance

def remove_money(uid, amount):
    balance = max(get_money(uid) - amount, 0)
    set_money(uid, balance)
    return balance

def get_attendance(uid):
    cursor.execute("SELECT last_date FROM attendance WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r[0] if r else None

def set_attendance(uid, date_text):
    cursor.execute("REPLACE INTO attendance VALUES(?,?)", (uid, date_text))
    conn.commit()

def get_admin_role(guild_id):
    cursor.execute("SELECT admin_role_id FROM guild_config WHERE guild_id=?", (guild_id,))
    r = cursor.fetchone()
    return r[0] if r else None

def is_admin(member):
    if member.guild_permissions.administrator:
        return True
    role_id = get_admin_role(member.guild.id)
    return role_id and any(r.id == role_id for r in member.roles)

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
        ch = await i.guild.create_text_channel(name=f"ticket-{i.user.id}", category=cat)
        await ch.send(i.user.mention, view=CloseView())
        await i.response.send_message(embed=embed("티켓 생성"), ephemeral=True)

class PartyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def create(self, i: discord.Interaction, size: int):
        cat = discord.utils.get(i.guild.categories, name=PARTY_CATEGORY_NAME)
        if not cat:
            cat = await i.guild.create_category(PARTY_CATEGORY_NAME)

        await i.guild.create_voice_channel(name=f"🎮 파티-{i.user.display_name}-{size}", category=cat)
        await i.response.send_message(embed=embed("파티 생성 완료"), ephemeral=True)

    @discord.ui.button(label="솔로", style=discord.ButtonStyle.primary, custom_id="party_solo")
    async def solo(self, i, b): await self.create(i, 1)

    @discord.ui.button(label="듀오", style=discord.ButtonStyle.primary, custom_id="party_duo")
    async def duo(self, i, b): await self.create(i, 2)

    @discord.ui.button(label="트리오", style=discord.ButtonStyle.primary, custom_id="party_trio")
    async def trio(self, i, b): await self.create(i, 3)

    @discord.ui.button(label="스쿼드", style=discord.ButtonStyle.primary, custom_id="party_squad")
    async def squad(self, i, b): await self.create(i, 4)

    @discord.ui.button(label="5인", style=discord.ButtonStyle.primary, custom_id="party_five")
    async def five(self, i, b): await self.create(i, 5)

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
            desc = f"나온 숫자: `{number}`\n결과: `{result}`\n획득금: `{format_money(win_amount)}`\n현재 잔액: `{format_money(new_balance)}`"
            color = 0x57F287
        else:
            title = "💥 실패"
            desc = f"나온 숫자: `{number}`\n결과: `{result}`\n손해 없음!\n현재 잔액: `{format_money(get_money(i.user.id))}`"
            color = 0xED4245

        await i.response.edit_message(embed=embed(title, desc, color), view=self)

    @discord.ui.button(label="홀수", style=discord.ButtonStyle.primary)
    async def odd(self, i, b): await self.check_answer(i, "홀수")

    @discord.ui.button(label="짝수", style=discord.ButtonStyle.success)
    async def even(self, i, b): await self.check_answer(i, "짝수")

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

        if choice in self.choices.values():
            return await i.response.send_message("❌ 상대가 이미 선택한 쪽입니다. 반대쪽을 선택하세요.", ephemeral=True)

        self.choices[i.user.id] = choice

        if len(self.choices) < 2:
            return await i.response.send_message(f"✅ `{choice}` 선택 완료. 상대 선택을 기다리는 중입니다.", ephemeral=True)

        self.finished = True
        number = random.randint(1, 100)
        result = "홀수" if number % 2 == 1 else "짝수"

        winner_id = None
        loser_id = None

        for uid, selected in self.choices.items():
            if selected == result:
                winner_id = uid
            else:
                loser_id = uid

        pot = self.bet * 2
        add_money(winner_id, pot)

        winner = self.player1 if self.player1.id == winner_id else self.player2
        loser = self.player1 if self.player1.id == loser_id else self.player2

        for item in self.children:
            item.disabled = True

        desc = (
            f"나온 숫자: `{number}`\n결과: `{result}`\n\n"
            f"{self.player1.mention}: `{self.choices[self.player1.id]}`\n"
            f"{self.player2.mention}: `{self.choices[self.player2.id]}`\n\n"
            f"승자: {winner.mention}\n패자: {loser.mention}\n"
            f"상금: `{format_money(pot)}`\n패자 손해 없음\n"
            f"승자 잔액: `{format_money(get_money(winner.id))}`"
        )

        await i.response.edit_message(embed=embed("⚔️ 홀짝 대결 결과", desc, 0x57F287), view=self)

    @discord.ui.button(label="홀수", style=discord.ButtonStyle.primary)
    async def odd(self, i, b): await self.choose(i, "홀수")

    @discord.ui.button(label="짝수", style=discord.ButtonStyle.success)
    async def even(self, i, b): await self.choose(i, "짝수")

class DuelAcceptView(discord.ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member, bet: int):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.opponent = opponent
        self.bet = bet
        self.finished = False

    @discord.ui.button(label="수락", style=discord.ButtonStyle.success)
    async def accept(self, i: discord.Interaction, b: discord.ui.Button):
        if i.user.id != self.opponent.id:
            return await i.response.send_message("❌ 지목된 상대만 수락할 수 있습니다.", ephemeral=True)

        if self.finished:
            return await i.response.send_message("❌ 이미 처리된 대결입니다.", ephemeral=True)

        self.finished = True

        await i.response.edit_message(
            embed=embed(
                "⚔️ 홀짝 대결 시작",
                f"{self.challenger.mention} vs {self.opponent.mention}\n"
                f"기준 금액: `{format_money(self.bet)}`\n"
                f"상금: `{format_money(self.bet * 2)}`\n"
                f"돈은 차감되지 않습니다. 이긴 사람만 상금을 받습니다."
            ),
            view=DuelChoiceView(self.challenger, self.opponent, self.bet)
        )

    @discord.ui.button(label="거절", style=discord.ButtonStyle.danger)
    async def decline(self, i: discord.Interaction, b: discord.ui.Button):
        if i.user.id != self.opponent.id:
            return await i.response.send_message("❌ 지목된 상대만 거절할 수 있습니다.", ephemeral=True)

        self.finished = True
        await i.response.edit_message(embed=embed("❌ 대결 거절", f"{self.opponent.mention}님이 대결을 거절했습니다.", 0xED4245), view=None)

class DiceView(discord.ui.View):
    def __init__(self, player_id):
        super().__init__(timeout=30)
        self.player_id = player_id
        self.finished = False
        self.winning_number = random.randint(1, 6)
        others = [n for n in range(1, 7) if n != self.winning_number]
        self.open_numbers = sorted([self.winning_number] + random.sample(others, 2))

    async def pick(self, i: discord.Interaction, number: int):
        if i.user.id != self.player_id:
            return await i.response.send_message("❌ 게임을 시작한 사람만 선택할 수 있습니다.", ephemeral=True)

        if self.finished:
            return await i.response.send_message("❌ 이미 끝난 게임입니다.", ephemeral=True)

        self.finished = True

        for item in self.children:
            item.disabled = True

        if number == self.winning_number:
            new_balance = add_money(i.user.id, DICE_WIN_AMOUNT)
            title = "🎲 주사위 당첨"
            desc = (
                f"선택한 숫자: `{number}`\n"
                f"나온 숫자 3개: `{', '.join(map(str, self.open_numbers))}`\n"
                f"당첨 숫자: `{self.winning_number}`\n"
                f"획득금: `{format_money(DICE_WIN_AMOUNT)}`\n"
                f"현재 잔액: `{format_money(new_balance)}`"
            )
            color = 0x57F287
        else:
            new_balance = remove_money(i.user.id, DICE_COST)
            title = "🎲 주사위 실패"
            desc = (
                f"선택한 숫자: `{number}`\n"
                f"나온 숫자 3개: `{', '.join(map(str, self.open_numbers))}`\n"
                f"당첨 숫자: `{self.winning_number}`\n"
                f"잃은 금액: `{format_money(DICE_COST)}`\n"
                f"현재 잔액: `{format_money(new_balance)}`"
            )
            color = 0xED4245

        await i.response.edit_message(embed=embed(title, desc, color), view=self)

    @discord.ui.button(label="1", style=discord.ButtonStyle.secondary)
    async def one(self, i, b): await self.pick(i, 1)

    @discord.ui.button(label="2", style=discord.ButtonStyle.secondary)
    async def two(self, i, b): await self.pick(i, 2)

    @discord.ui.button(label="3", style=discord.ButtonStyle.secondary)
    async def three(self, i, b): await self.pick(i, 3)

    @discord.ui.button(label="4", style=discord.ButtonStyle.secondary)
    async def four(self, i, b): await self.pick(i, 4)

    @discord.ui.button(label="5", style=discord.ButtonStyle.secondary)
    async def five(self, i, b): await self.pick(i, 5)

    @discord.ui.button(label="6", style=discord.ButtonStyle.secondary)
    async def six(self, i, b): await self.pick(i, 6)

class DiceDuelChoiceView(discord.ui.View):
    def __init__(self, player1: discord.Member, player2: discord.Member):
        super().__init__(timeout=60)
        self.player1 = player1
        self.player2 = player2
        self.choices = {}
        self.finished = False
        self.winning_number = random.randint(1, 6)
        others = [n for n in range(1, 7) if n != self.winning_number]
        self.open_numbers = sorted([self.winning_number] + random.sample(others, 2))

    async def choose(self, i: discord.Interaction, number: int):
        if i.user.id not in [self.player1.id, self.player2.id]:
            return await i.response.send_message("❌ 대결 참가자만 선택할 수 있습니다.", ephemeral=True)

        if self.finished:
            return await i.response.send_message("❌ 이미 끝난 대결입니다.", ephemeral=True)

        if i.user.id in self.choices:
            return await i.response.send_message("❌ 이미 선택했습니다.", ephemeral=True)

        self.choices[i.user.id] = number

        if len(self.choices) < 2:
            return await i.response.send_message(f"✅ `{number}`번 선택 완료. 상대 선택을 기다리는 중입니다.", ephemeral=True)

        self.finished = True

        for item in self.children:
            item.disabled = True

        p1_pick = self.choices[self.player1.id]
        p2_pick = self.choices[self.player2.id]

        p1_win = p1_pick == self.winning_number
        p2_win = p2_pick == self.winning_number

        result_lines = [
            f"나온 숫자 3개: `{', '.join(map(str, self.open_numbers))}`",
            f"당첨 숫자: `{self.winning_number}`",
            "",
            f"{self.player1.mention}: `{p1_pick}`",
            f"{self.player2.mention}: `{p2_pick}`",
            ""
        ]

        if p1_win and p2_win:
            add_money(self.player1.id, DICE_WIN_AMOUNT)
            add_money(self.player2.id, DICE_WIN_AMOUNT)
            result_lines.append(f"둘 다 당첨! 각각 `{format_money(DICE_WIN_AMOUNT)}` 획득")
            color = 0x57F287
        elif p1_win:
            add_money(self.player1.id, DICE_WIN_AMOUNT)
            remove_money(self.player2.id, DICE_COST)
            result_lines.append(f"승자: {self.player1.mention}")
            result_lines.append(f"{self.player1.mention} 획득: `{format_money(DICE_WIN_AMOUNT)}`")
            result_lines.append(f"{self.player2.mention} 손실: `{format_money(DICE_COST)}`")
            color = 0x57F287
        elif p2_win:
            add_money(self.player2.id, DICE_WIN_AMOUNT)
            remove_money(self.player1.id, DICE_COST)
            result_lines.append(f"승자: {self.player2.mention}")
            result_lines.append(f"{self.player2.mention} 획득: `{format_money(DICE_WIN_AMOUNT)}`")
            result_lines.append(f"{self.player1.mention} 손실: `{format_money(DICE_COST)}`")
            color = 0x57F287
        else:
            remove_money(self.player1.id, DICE_COST)
            remove_money(self.player2.id, DICE_COST)
            result_lines.append(f"둘 다 실패! 각각 `{format_money(DICE_COST)}` 손실")
            color = 0xED4245

        result_lines.append("")
        result_lines.append(f"{self.player1.display_name} 잔액: `{format_money(get_money(self.player1.id))}`")
        result_lines.append(f"{self.player2.display_name} 잔액: `{format_money(get_money(self.player2.id))}`")

        await i.response.edit_message(
            embed=embed("🎲 주사위 대결 결과", "\n".join(result_lines), color),
            view=self
        )

    @discord.ui.button(label="1", style=discord.ButtonStyle.secondary)
    async def one(self, i, b): await self.choose(i, 1)

    @discord.ui.button(label="2", style=discord.ButtonStyle.secondary)
    async def two(self, i, b): await self.choose(i, 2)

    @discord.ui.button(label="3", style=discord.ButtonStyle.secondary)
    async def three(self, i, b): await self.choose(i, 3)

    @discord.ui.button(label="4", style=discord.ButtonStyle.secondary)
    async def four(self, i, b): await self.choose(i, 4)

    @discord.ui.button(label="5", style=discord.ButtonStyle.secondary)
    async def five(self, i, b): await self.choose(i, 5)

    @discord.ui.button(label="6", style=discord.ButtonStyle.secondary)
    async def six(self, i, b): await self.choose(i, 6)

class DiceDuelAcceptView(discord.ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.opponent = opponent
        self.finished = False

    @discord.ui.button(label="수락", style=discord.ButtonStyle.success)
    async def accept(self, i: discord.Interaction, b: discord.ui.Button):
        if i.user.id != self.opponent.id:
            return await i.response.send_message("❌ 지목된 상대만 수락할 수 있습니다.", ephemeral=True)

        if self.finished:
            return await i.response.send_message("❌ 이미 처리된 대결입니다.", ephemeral=True)

        if get_money(self.challenger.id) < DICE_COST:
            self.finished = True
            return await i.response.edit_message(embed=embed("❌ 대결 취소", "도전자 잔액이 부족합니다.", 0xED4245), view=None)

        if get_money(self.opponent.id) < DICE_COST:
            self.finished = True
            return await i.response.edit_message(embed=embed("❌ 대결 취소", "상대 잔액이 부족합니다.", 0xED4245), view=None)

        self.finished = True

        await i.response.edit_message(
            embed=embed(
                "🎲 주사위 대결 시작",
                f"{self.challenger.mention} vs {self.opponent.mention}\n"
                f"1~6 중 하나를 선택하세요.\n"
                f"당첨 시 `{format_money(DICE_WIN_AMOUNT)}`, 실패 시 `{format_money(DICE_COST)}` 손실."
            ),
            view=DiceDuelChoiceView(self.challenger, self.opponent)
        )

    @discord.ui.button(label="거절", style=discord.ButtonStyle.danger)
    async def decline(self, i: discord.Interaction, b: discord.ui.Button):
        if i.user.id != self.opponent.id:
            return await i.response.send_message("❌ 지목된 상대만 거절할 수 있습니다.", ephemeral=True)

        self.finished = True
        await i.response.edit_message(embed=embed("❌ 주사위 대결 거절", f"{self.opponent.mention}님이 대결을 거절했습니다.", 0xED4245), view=None)

@bot.event
async def on_ready():
    global bot_ready_synced

    if bot_ready_synced:
        return

    init_db()
    bot.add_view(VerifyView())
    bot.add_view(TicketView())
    bot.add_view(CloseView())
    bot.add_view(PartyView())

    synced = await bot.tree.sync()
    bot_ready_synced = True

    print(f"🔥 BOT READY: {bot.user}")
    print(f"✅ Slash commands synced: {len(synced)}")

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

@bot.tree.command(name="월급", description="월급 100,000원을 받습니다. 5초 쿨타임이 있습니다.")
async def salary(i: discord.Interaction):
    now = datetime.datetime.now().timestamp()
    last_time = salary_cooldowns.get(i.user.id, 0)
    remain = SALARY_COOLDOWN - (now - last_time)

    if remain > 0:
        return await i.response.send_message(f"❌ 아직 월급을 받을 수 없습니다. `{int(remain)}초` 후 다시 시도하세요.", ephemeral=True)

    salary_cooldowns[i.user.id] = now
    balance = add_money(i.user.id, SALARY_AMOUNT)

    await i.response.send_message(embed=embed("💰 월급 지급", f"{i.user.mention}님이 `{format_money(SALARY_AMOUNT)}`을 받았습니다.\n현재 잔액: `{format_money(balance)}`", 0x57F287))

@bot.tree.command(name="출석", description="하루에 한 번 출석 보상 500,000원을 받습니다.")
async def attendance(i: discord.Interaction):
    today = today_kst()
    last_date = get_attendance(i.user.id)

    if last_date == today:
        return await i.response.send_message("❌ 오늘은 이미 출석 보상을 받았습니다.", ephemeral=True)

    set_attendance(i.user.id, today)
    balance = add_money(i.user.id, ATTENDANCE_AMOUNT)

    await i.response.send_message(embed=embed("📅 출석 완료", f"{i.user.mention}님이 출석 보상 `{format_money(ATTENDANCE_AMOUNT)}`을 받았습니다.\n현재 잔액: `{format_money(balance)}`", 0x57F287))

@bot.tree.command(name="잔액", description="현재 보유 금액을 확인합니다.")
async def balance(i: discord.Interaction):
    await i.response.send_message(embed=embed("💵 잔액", f"{i.user.mention}님의 잔액: `{format_money(get_money(i.user.id))}`"))

@bot.tree.command(name="홀짝", description="혼자 홀수 짝수 게임을 합니다. 틀려도 손해가 없습니다.")
async def odd_even_game(i: discord.Interaction, 금액: int):
    if 금액 <= 0:
        return await i.response.send_message("❌ 금액은 1원 이상이어야 합니다.", ephemeral=True)

    if 금액 > MAX_BET:
        return await i.response.send_message("❌ 최대 금액은 1,000,000원입니다.", ephemeral=True)

    if get_money(i.user.id) < 금액:
        return await i.response.send_message(f"❌ 기준 금액보다 잔액이 부족합니다.\n현재 잔액: `{format_money(get_money(i.user.id))}`", ephemeral=True)

    await i.response.send_message(
        embed=embed("🎲 홀수 짝수 게임", f"{i.user.mention}, 홀수 또는 짝수를 선택하세요!\n기준 금액: `{format_money(금액)}`\n맞추면 `{format_money(금액 * 2)}` 지급, 틀려도 손해는 없습니다."),
        view=OddEvenView(i.user.id, 금액)
    )

@bot.tree.command(name="홀짝대결", description="상대와 1vs1 홀짝 대결을 합니다. 패자도 돈을 잃지 않습니다.")
async def odd_even_duel(i: discord.Interaction, 상대: discord.Member, 금액: int):
    if 상대.bot:
        return await i.response.send_message("❌ 봇과는 대결할 수 없습니다.", ephemeral=True)

    if 상대.id == i.user.id:
        return await i.response.send_message("❌ 자기 자신과는 대결할 수 없습니다.", ephemeral=True)

    if 금액 <= 0:
        return await i.response.send_message("❌ 금액은 1원 이상이어야 합니다.", ephemeral=True)

    if 금액 > MAX_BET:
        return await i.response.send_message("❌ 최대 금액은 1,000,000원입니다.", ephemeral=True)

    if get_money(i.user.id) < 금액:
        return await i.response.send_message("❌ 도전자 잔액이 부족합니다.", ephemeral=True)

    if get_money(상대.id) < 금액:
        return await i.response.send_message("❌ 상대 잔액이 부족합니다.", ephemeral=True)

    await i.response.send_message(
        embed=embed("⚔️ 홀짝 대결 신청", f"{i.user.mention}님이 {상대.mention}님에게 홀짝 대결을 신청했습니다.\n기준 금액: `{format_money(금액)}`\n상금: `{format_money(금액 * 2)}`\n패자도 돈을 잃지 않습니다.\n\n{상대.mention}님은 수락 또는 거절을 선택하세요."),
        view=DuelAcceptView(i.user, 상대, 금액)
    )

@bot.tree.command(name="주사위", description="1~6 중 숫자를 골라 당첨 숫자를 맞춥니다.")
async def dice_game(i: discord.Interaction):
    if get_money(i.user.id) < DICE_COST:
        return await i.response.send_message(f"❌ 주사위 게임을 하려면 최소 `{format_money(DICE_COST)}`이 필요합니다.", ephemeral=True)

    await i.response.send_message(
        embed=embed("🎲 주사위 맞추기", f"{i.user.mention}, 1~6 중 하나를 선택하세요.\n3개의 숫자가 나오고, 그중 1개가 당첨 숫자입니다.\n당첨 시 `{format_money(DICE_WIN_AMOUNT)}`, 실패 시 `{format_money(DICE_COST)}` 차감."),
        view=DiceView(i.user.id)
    )

@bot.tree.command(name="주사위대결", description="상대와 1vs1 주사위 맞추기 대결을 합니다.")
async def dice_duel(i: discord.Interaction, 상대: discord.Member):
    if 상대.bot:
        return await i.response.send_message("❌ 봇과는 대결할 수 없습니다.", ephemeral=True)

    if 상대.id == i.user.id:
        return await i.response.send_message("❌ 자기 자신과는 대결할 수 없습니다.", ephemeral=True)

    if get_money(i.user.id) < DICE_COST:
        return await i.response.send_message(f"❌ 도전자 잔액이 부족합니다. 최소 `{format_money(DICE_COST)}` 필요.", ephemeral=True)

    if get_money(상대.id) < DICE_COST:
        return await i.response.send_message(f"❌ 상대 잔액이 부족합니다. 최소 `{format_money(DICE_COST)}` 필요.", ephemeral=True)

    await i.response.send_message(
        embed=embed("🎲 주사위 대결 신청", f"{i.user.mention}님이 {상대.mention}님에게 주사위 대결을 신청했습니다.\n당첨 시 `{format_money(DICE_WIN_AMOUNT)}`, 실패 시 `{format_money(DICE_COST)}` 손실.\n\n{상대.mention}님은 수락 또는 거절을 선택하세요."),
        view=DiceDuelAcceptView(i.user, 상대)
    )

@bot.tree.command(name="경고", description="유저에게 경고를 지급합니다.")
async def warn(i: discord.Interaction, user: discord.Member, reason: str = "없음"):
    if not is_admin(i.user):
        return await i.response.send_message("❌ 권한 없음", ephemeral=True)

    c = add_warn(user.id)
    await auto_punish(user, c)
    await i.response.send_message(embed=embed("경고", f"{user.mention}\n{reason}\n{c}회"))

@bot.tree.command(name="경고삭제", description="유저의 경고를 초기화합니다.")
async def warn_clear(i: discord.Interaction, user: discord.Member):
    if not is_admin(i.user):
        return await i.response.send_message("❌ 권한 없음", ephemeral=True)

    clear_warn(user.id)
    await remove_punish(user)
    await i.response.send_message(embed=embed("경고 초기화"))

@bot.tree.command(name="인증패널", description="인증 패널을 보냅니다.")
async def verify_panel(i: discord.Interaction):
    await i.response.send_message(embed=embed("인증"), view=VerifyView())

@bot.tree.command(name="티켓패널", description="티켓 패널을 보냅니다.")
async def ticket_panel(i: discord.Interaction):
    await i.response.send_message(embed=embed("티켓"), view=TicketView())

@bot.tree.command(name="파티패널", description="파티 생성 패널을 보냅니다.")
async def party_panel(i: discord.Interaction):
    await i.response.send_message(embed=embed("파티 시스템 🎮"), view=PartyView())

@bot.tree.command(name="파티삭제", description="현재 음성 채널을 삭제합니다.")
async def party_delete(i: discord.Interaction):
    if not isinstance(i.channel, discord.VoiceChannel):
        return await i.response.send_message("❌ 음성채널만 가능", ephemeral=True)

    await i.channel.delete()

async def main():
    if not TOKEN:
        raise RuntimeError("TOKEN 환경변수가 설정되지 않았습니다.")

    keep_alive()
    await bot.start(TOKEN)

asyncio.run(main())
