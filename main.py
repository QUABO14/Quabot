import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import os
import sqlite3
import asyncio
from flask import Flask, request, redirect, session, render_template_string
from threading import Thread

# ================= 환경 =================
TOKEN = os.getenv("TOKEN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

LOG_CHANNEL_ID = 1496478745538855146
WELCOME_CHANNEL_ID = 1496478743873589448
VERIFY_ROLE_ID = 1496479066075697234
TICKET_CATEGORY_ID = 1496840441654677614

STAFF_ROLE_ID = 1499592576712577138  # 🔥 운영진 역할

# ================= DB =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS warnings (user_id INTEGER PRIMARY KEY, count INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS levels (user_id INTEGER PRIMARY KEY, xp INTEGER, level INTEGER)")
conn.commit()

# ================= 봇 =================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= 웹 =================
app = Flask(__name__)
app.secret_key = "secretkey"

def is_logged_in():
    return session.get("login")

# HTML
HTML = """
<h1>🤖 봇 대시보드</h1>

<form method="POST" action="/warn">
<input name="user_id" placeholder="유저 ID">
<input name="reason" placeholder="이유">
<button>경고</button>
</form>

<h3>경고 목록</h3>
{% for w in warnings %}
<p>{{w[0]}} : {{w[1]}}</p>
{% endfor %}

<h3>레벨</h3>
{% for l in levels %}
<p>{{l[0]}} : LV {{l[2]}} (XP {{l[1]}})</p>
{% endfor %}
"""

@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form["pw"] == ADMIN_PASSWORD:
            session["login"] = True
            return redirect("/dash")
    return "<form method='POST'><input name='pw'><button>로그인</button></form>"

@app.route("/dash")
def dash():
    if not is_logged_in():
        return redirect("/")
    cursor.execute("SELECT * FROM warnings")
    w = cursor.fetchall()
    cursor.execute("SELECT * FROM levels")
    l = cursor.fetchall()
    return render_template_string(HTML, warnings=w, levels=l)

@app.route("/warn", methods=["POST"])
def web_warn():
    if not is_logged_in():
        return redirect("/")

    uid = int(request.form["user_id"])
    reason = request.form["reason"]

    count = add_warn(uid)

    async def punish():
        for g in bot.guilds:
            m = g.get_member(uid)
            if m:
                await auto_punish(m, count)
                await log(f"[웹] {m} 경고 {count} | {reason}")
                break

    bot.loop.create_task(punish())
    return redirect("/dash")

def run_web():
    app.run(host="0.0.0.0", port=10000)

def keep_alive():
    Thread(target=run_web, daemon=True).start()

# ================= 유틸 =================
def embed(t, d="", c=0x5865F2):
    e = discord.Embed(title=t, description=d, color=c)
    e.timestamp = datetime.datetime.utcnow()
    return e

async def safe_send(ch, **k):
    try:
        await ch.send(**k)
    except:
        pass

async def log(msg):
    ch = bot.get_channel(LOG_CHANNEL_ID)
    if ch:
        await safe_send(ch, embed=embed("📜 로그", msg))

# ================= 권한 =================
def is_staff(interaction: discord.Interaction):
    return any(r.id == STAFF_ROLE_ID for r in interaction.user.roles)

# ================= 경고 =================
def get_warn(uid):
    cursor.execute("SELECT count FROM warnings WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r[0] if r else 0

def add_warn(uid):
    c = get_warn(uid) + 1
    cursor.execute("REPLACE INTO warnings VALUES(?,?)", (uid,c))
    conn.commit()
    return c

def remove_warn(uid):
    c = max(get_warn(uid)-1,0)
    cursor.execute("REPLACE INTO warnings VALUES(?,?)", (uid,c))
    conn.commit()
    return c

async def auto_punish(m, c):
    try:
        if c==1:
            await m.timeout(datetime.timedelta(minutes=10))
        elif c==2:
            await m.timeout(datetime.timedelta(hours=1))
        elif c==3:
            await m.timeout(datetime.timedelta(days=1))
        elif c==4:
            await m.kick()
        elif c==5:
            await m.ban()
    except:
        pass

# ================= 레벨 =================
def add_xp(uid):
    cursor.execute("SELECT xp,level FROM levels WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    xp,lv = (r if r else (0,1))
    xp += 10
    if xp >= lv*100:
        lv += 1
        xp = 0
    cursor.execute("REPLACE INTO levels VALUES(?,?,?)",(uid,xp,lv))
    conn.commit()
    return lv,xp

# ================= 티켓 =================
class CloseView(discord.ui.View):
    @discord.ui.button(label="닫기",style=discord.ButtonStyle.danger)
    async def close(self,i,b):
        await i.response.send_message("삭제됨")
        await asyncio.sleep(5)
        try:
            await i.channel.delete()
        except:
            pass

class TicketView(discord.ui.View):
    @discord.ui.button(label="티켓",style=discord.ButtonStyle.primary)
    async def t(self,i,b):
        g=i.guild
        c=g.get_channel(TICKET_CATEGORY_ID)
        ch=await g.create_text_channel(name=f"ticket-{i.user.id}",category=c)
        await ch.send(f"{i.user.mention}",view=CloseView())
        await i.response.send_message("생성됨",ephemeral=True)

# ================= 인증 =================
class VerifyView(discord.ui.View):
    @discord.ui.button(label="인증",style=discord.ButtonStyle.success)
    async def v(self,i,b):
        r=i.guild.get_role(VERIFY_ROLE_ID)
        await i.user.add_roles(r)
        await i.response.send_message("완료",ephemeral=True)

# ================= 명령어 =================
@bot.tree.command(name="경고")
@app_commands.check(is_staff)
async def warn(i,u:discord.Member,이유:str):
    c=add_warn(u.id)
    await auto_punish(u,c)
    await i.response.send_message(embed=embed("경고",f"{u.mention} {c}회"))

@bot.tree.command(name="경고취소")
@app_commands.check(is_staff)
async def unwarn(i,u:discord.Member):
    c=remove_warn(u.id)
    await i.response.send_message(embed=embed("감소",f"{u.mention} {c}회"))

@bot.tree.command(name="경고확인")
@app_commands.check(is_staff)
async def check(i,u:discord.Member):
    c=get_warn(u.id)
    await i.response.send_message(embed=embed("확인",f"{u.mention} {c}회"))

@bot.tree.command(name="티켓패널")
@app_commands.check(is_staff)
async def ticket(i):
    await i.response.send_message(embed=embed("티켓"),view=TicketView())

@bot.command()
@commands.check(lambda ctx: any(r.id==STAFF_ROLE_ID for r in ctx.author.roles))
async def 인증패널(ctx):
    await ctx.send(embed=embed("인증"),view=VerifyView())

# ================= 이벤트 =================
@bot.event
async def on_message(m):
    if m.author.bot: return
    lv,xp=add_xp(m.author.id)
    if xp==0:
        await safe_send(m.channel,content=f"{m.author.mention} 레벨업 {lv}")
    await bot.process_commands(m)

@bot.event
async def on_member_join(m):
    ch=bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await safe_send(ch,embed=embed("환영",m.mention))

# ================= 에러 =================
@bot.tree.error
async def err(i,e):
    if isinstance(e,app_commands.errors.CheckFailure):
        await i.response.send_message("❌ 운영진만 사용 가능",ephemeral=True)

# ================= 실행 =================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print("🔥 최종 봇 실행 완료")

def run_bot():
    while True:
        try:
            bot.run(TOKEN)
        except Exception as e:
            print("재시작",e)
            asyncio.sleep(5)

keep_alive()
run_bot()
