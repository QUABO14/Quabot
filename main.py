# ==== DISCORD ALL-IN-ONE BOT FINAL ====
import discord
from discord.ext import commands
import sqlite3, datetime, random, asyncio, os
from flask import Flask
from threading import Thread

TOKEN = os.getenv("TOKEN")

# ================= KEEP ALIVE =================
app = Flask(__name__)
@app.route("/")
def home(): return "OK"

def run_web():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

def keep_alive():
    Thread(target=run_web, daemon=True).start()

# ================= DB =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

def init_db():
    cur.execute("CREATE TABLE IF NOT EXISTS money(user INTEGER PRIMARY KEY, balance INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS warn(user INTEGER PRIMARY KEY, count INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS level(user INTEGER PRIMARY KEY, xp INTEGER, lv INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS attendance(user INTEGER PRIMARY KEY, last TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS config(guild INTEGER PRIMARY KEY, log INTEGER, welcome INTEGER, admin INTEGER)")
    conn.commit()

# ================= BOT =================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

def embed(t, d="", c=0x5865F2):
    e = discord.Embed(title=t, description=d, color=c)
    e.timestamp = datetime.datetime.utcnow()
    return e

# ================= UTIL =================
def is_admin(m):
    if m.guild_permissions.administrator: return True
    cur.execute("SELECT admin FROM config WHERE guild=?", (m.guild.id,))
    r = cur.fetchone()
    return r and any(role.id == r[0] for role in m.roles)

async def log(guild, text):
    cur.execute("SELECT log FROM config WHERE guild=?", (guild.id,))
    r = cur.fetchone()
    if r and r[0]:
        ch = guild.get_channel(r[0])
        if ch: await ch.send(text)

# ================= MONEY =================
def get_money(uid):
    cur.execute("SELECT balance FROM money WHERE user=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

def set_money(uid, val):
    cur.execute("REPLACE INTO money VALUES(?,?)", (uid, max(0,val)))
    conn.commit()

def add_money(uid, val): set_money(uid, get_money(uid)+val)
def sub_money(uid, val): set_money(uid, get_money(uid)-val)

# ================= WARN =================
def get_warn(uid):
    cur.execute("SELECT count FROM warn WHERE user=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

def add_warn(uid):
    c = get_warn(uid)+1
    cur.execute("REPLACE INTO warn VALUES(?,?)", (uid,c))
    conn.commit()
    return c

def clear_warn(uid):
    cur.execute("REPLACE INTO warn VALUES(?,?)", (uid,0))
    conn.commit()

async def punish(member, c):
    try:
        if c==3: await member.timeout(datetime.timedelta(minutes=10))
        elif c==4: await member.kick()
        elif c>=5: await member.ban()
    except: pass

# ================= LEVEL =================
def add_xp(uid):
    cur.execute("SELECT xp,lv FROM level WHERE user=?", (uid,))
    r = cur.fetchone()
    xp,lv = r if r else (0,1)
    xp+=10
    if xp>=lv*100:
        lv+=1; xp=0
    cur.execute("REPLACE INTO level VALUES(?,?,?)",(uid,xp,lv))
    conn.commit()
    return lv,xp

# ================= EVENT =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print("READY")

@bot.event
async def on_message(m):
    if m.author.bot: return
    lv,xp = add_xp(m.author.id)
    if xp==0:
        await m.channel.send(embed=embed("레벨업",f"{m.author.mention} LV {lv}"))
    await bot.process_commands(m)

# ================= COMMANDS =================
@bot.tree.command(name="잔액")
async def balance(i:discord.Interaction, 유저:discord.Member=None):
    u = 유저 or i.user
    await i.response.send_message(embed=embed("잔액",f"{u.mention}: {get_money(u.id):,}원"))

@bot.tree.command(name="송금")
async def send(i:discord.Interaction, 유저:discord.Member, 금액:int):
    if get_money(i.user.id)<금액:
        return await i.response.send_message("돈 부족",ephemeral=True)
    sub_money(i.user.id,금액)
    add_money(유저.id,금액)
    await i.response.send_message(embed=embed("송금",f"{금액:,}원 → {유저.mention}"))
    await log(i.guild,f"{i.user} -> {유저} {금액}")

@bot.tree.command(name="출석")
async def attend(i:discord.Interaction):
    today=str(datetime.date.today())
    cur.execute("SELECT last FROM attendance WHERE user=?", (i.user.id,))
    r=cur.fetchone()
    if r and r[0]==today:
        return await i.response.send_message("이미 출석",ephemeral=True)
    cur.execute("REPLACE INTO attendance VALUES(?,?)",(i.user.id,today))
    conn.commit()
    add_money(i.user.id,500000)
    await i.response.send_message("출석 완료 500,000원")

@bot.tree.command(name="경고")
async def warn(i:discord.Interaction, 유저:discord.Member):
    if not is_admin(i.user):
        return await i.response.send_message("관리자만",ephemeral=True)
    c=add_warn(유저.id)
    await punish(유저,c)
    await i.response.send_message(f"{유저.mention} 경고 {c}")
    await log(i.guild,f"경고 {유저} {c}")

@bot.tree.command(name="경고확인")
async def warn_check(i:discord.Interaction, 유저:discord.Member):
    await i.response.send_message(f"{유저.mention}: {get_warn(유저.id)}회")

@bot.tree.command(name="경고삭제")
async def warn_clear_cmd(i:discord.Interaction, 유저:discord.Member):
    if not is_admin(i.user):
        return await i.response.send_message("관리자만",ephemeral=True)
    clear_warn(유저.id)
    await i.response.send_message("초기화 완료")

# ================= VERIFY =================
class VerifyView(discord.ui.View):
    @discord.ui.button(label="인증",style=discord.ButtonStyle.success)
    async def verify(self,i,b):
        role=discord.utils.get(i.guild.roles,name="인증")
        if not role:
            role=await i.guild.create_role(name="인증")
        await i.user.add_roles(role)
        await i.response.send_message("완료",ephemeral=True)

@bot.tree.command(name="인증패널")
async def verify_panel(i:discord.Interaction):
    await i.response.send_message("인증",view=VerifyView())

# ================= START =================
async def main():
    keep_alive()
    await bot.start(TOKEN)

asyncio.run(main())
