# ================= 기본 라이브러리 =================
import discord
from discord.ext import commands
import os, sqlite3, datetime, asyncio, random
from flask import Flask
from threading import Thread
from groq import AsyncGroq

# ================= 환경 변수 =================
TOKEN = os.getenv("TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

WELCOME_CHANNEL_ID = 0
TICKET_CATEGORY_ID = 0
VERIFY_ROLE_ID = 0

DB_PATH = "bot.db"

# ================= 경제 설정 =================
SALARY_AMOUNT = 100000
SALARY_COOLDOWN = 5
ATTENDANCE_AMOUNT = 500000
MAX_BET = 1000000

DICE_COST = 50000
DICE_WIN_AMOUNT = DICE_COST * 3

salary_cooldowns = {}

# ================= Flask =================
app = Flask(__name__)

@app.route("/")
def home():
    return "BOT ONLINE"

def keep_alive():
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

# ================= DB =================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.execute("CREATE TABLE IF NOT EXISTS warnings (user_id INTEGER PRIMARY KEY, count INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS levels (user_id INTEGER PRIMARY KEY, xp INTEGER, level INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS money (user_id INTEGER PRIMARY KEY, balance INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS attendance (user_id INTEGER PRIMARY KEY, last_date TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventory (user_id INTEGER, item TEXT)")
    conn.commit()

# ================= 봇 =================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

def embed(t, d="", c=0x5865F2):
    e = discord.Embed(title=t, description=d, color=c)
    e.timestamp = datetime.datetime.utcnow()
    return e

def format_money(x): return f"{x:,}원"

# ================= 돈 =================
def get_money(uid):
    cursor.execute("SELECT balance FROM money WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r[0] if r else 0

def set_money(uid, a):
    cursor.execute("REPLACE INTO money VALUES(?,?)", (uid, max(a, 0)))
    conn.commit()

def add_money(uid, a):
    b = get_money(uid) + a
    set_money(uid, b)
    return b

def remove_money(uid, a):
    b = max(get_money(uid) - a, 0)
    set_money(uid, b)
    return b

# ================= 경고 =================
def get_warn(uid):
    cursor.execute("SELECT count FROM warnings WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r[0] if r else 0

def set_warn(uid, v):
    cursor.execute("REPLACE INTO warnings VALUES(?,?)", (uid, v))
    conn.commit()

def clear_warn(uid): set_warn(uid, 0)

# ================= 이벤트 =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print("🔥 READY")

# ================= 명령어 =================

# 💰 잔액
@bot.tree.command(name="잔액")
async def balance(i: discord.Interaction, 유저: discord.Member=None):
    target = 유저 or i.user
    await i.response.send_message(embed=embed("잔액", f"{target.mention}: `{format_money(get_money(target.id))}`"))

# 💸 송금
@bot.tree.command(name="송금")
async def transfer(i: discord.Interaction, 대상: discord.Member, 금액: int):
    if get_money(i.user.id) < 금액:
        return await i.response.send_message("❌ 돈 부족", ephemeral=True)

    remove_money(i.user.id, 금액)
    add_money(대상.id, 금액)

    await i.response.send_message(embed=embed("송금 완료", f"{i.user.mention} → {대상.mention}\n{format_money(금액)}"))

# ⚠️ 경고 확인
@bot.tree.command(name="경고확인")
async def warn_check(i: discord.Interaction, user: discord.Member):
    await i.response.send_message(embed=embed("경고", f"{user.mention}: {get_warn(user.id)}회"))

# 📅 출석
@bot.tree.command(name="출석")
async def attendance(i: discord.Interaction):
    today = str(datetime.date.today())
    cursor.execute("SELECT last_date FROM attendance WHERE user_id=?", (i.user.id,))
    r = cursor.fetchone()

    if r and r[0] == today:
        return await i.response.send_message("❌ 이미 출석")

    cursor.execute("REPLACE INTO attendance VALUES(?,?)", (i.user.id, today))
    conn.commit()

    bal = add_money(i.user.id, ATTENDANCE_AMOUNT)
    await i.response.send_message(embed=embed("출석", f"{format_money(ATTENDANCE_AMOUNT)} 지급\n잔액: {format_money(bal)}"))

# 💰 월급
@bot.tree.command(name="월급")
async def salary(i: discord.Interaction):
    now = datetime.datetime.now().timestamp()
    if now - salary_cooldowns.get(i.user.id, 0) < SALARY_COOLDOWN:
        return await i.response.send_message("❌ 쿨타임", ephemeral=True)

    salary_cooldowns[i.user.id] = now
    bal = add_money(i.user.id, SALARY_AMOUNT)
    await i.response.send_message(embed=embed("월급", f"{format_money(SALARY_AMOUNT)} 지급\n잔액: {format_money(bal)}"))

# 🎲 주사위
@bot.tree.command(name="주사위")
async def dice(i: discord.Interaction):
    num = random.randint(1,6)
    if num == 6:
        bal = add_money(i.user.id, DICE_WIN_AMOUNT)
        await i.response.send_message(embed=embed("🎉 당첨", f"{num}\n+{format_money(DICE_WIN_AMOUNT)}"))
    else:
        bal = remove_money(i.user.id, DICE_COST)
        await i.response.send_message(embed=embed("💥 실패", f"{num}\n-{format_money(DICE_COST)}"))

# 🏆 돈랭킹
@bot.tree.command(name="돈랭킹")
async def rank(i: discord.Interaction):
    cursor.execute("SELECT user_id, balance FROM money ORDER BY balance DESC LIMIT 10")
    rows = cursor.fetchall()
    desc = "\n".join([f"{idx+1}. {i.guild.get_member(uid)} - {format_money(bal)}" for idx,(uid,bal) in enumerate(rows)])
    await i.response.send_message(embed=embed("랭킹", desc))

# 🛒 상점
SHOP_ITEMS = {"경고초기화권":1000000}

@bot.tree.command(name="상점")
async def shop(i: discord.Interaction):
    await i.response.send_message(embed=embed("상점", "\n".join([f"{k}: {format_money(v)}" for k,v in SHOP_ITEMS.items()])))

@bot.tree.command(name="구매")
async def buy(i: discord.Interaction, 아이템:str):
    if 아이템 not in SHOP_ITEMS:
        return await i.response.send_message("❌ 없음")

    price = SHOP_ITEMS[아이템]
    if get_money(i.user.id) < price:
        return await i.response.send_message("❌ 돈 부족")

    remove_money(i.user.id, price)
    cursor.execute("INSERT INTO inventory VALUES(?,?)", (i.user.id, 아이템))
    conn.commit()

    if 아이템 == "경고초기화권":
        clear_warn(i.user.id)

    await i.response.send_message(embed=embed("구매 완료", 아이템))

# ================= 실행 =================
async def main():
    keep_alive()
    await bot.start(TOKEN)

asyncio.run(main())
