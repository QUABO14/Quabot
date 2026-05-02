# ================= IMPORT =================
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
VERIFY_ROLE_ID = 1499675598178750560

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= KEEP ALIVE =================
app = Flask(__name__)

@app.route("/")
def home():
    return "BOT ONLINE"

def run():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def keep_alive():
    Thread(target=run, daemon=True).start()

# ================= DB =================
DB = sqlite3.connect("bot.db", check_same_thread=False)
CUR = DB.cursor()

def init_db():
    CUR.execute("CREATE TABLE IF NOT EXISTS money (uid INTEGER PRIMARY KEY, bal INTEGER)")
    CUR.execute("CREATE TABLE IF NOT EXISTS warn (guild_id INTEGER, user_id INTEGER, count INTEGER)")
    CUR.execute("CREATE TABLE IF NOT EXISTS attendance (uid INTEGER PRIMARY KEY, date TEXT)")
    DB.commit()

# ================= UTIL =================
def embed(t, d="", c=0x5865F2):
    e = discord.Embed(title=t, description=d, color=c)
    e.timestamp = datetime.datetime.utcnow()
    return e

def money(uid):
    CUR.execute("SELECT bal FROM money WHERE uid=?", (uid,))
    r = CUR.fetchone()
    return r[0] if r else 0

def set_money(uid, v):
    CUR.execute("REPLACE INTO money VALUES (?,?)", (uid, max(v,0)))
    DB.commit()

def add_money(uid, v): set_money(uid, money(uid)+v)
def sub_money(uid, v): set_money(uid, money(uid)-v)

# ================= WARNING 2.0 =================
def get_warn(gid, uid):
    CUR.execute("SELECT count FROM warn WHERE guild_id=? AND user_id=?", (gid, uid))
    r = CUR.fetchone()
    return r[0] if r else 0

def add_warn(gid, uid):
    c = get_warn(gid, uid)+1
    CUR.execute("REPLACE INTO warn VALUES (?,?,?)", (gid, uid, c))
    DB.commit()
    return c

async def punish(member, c):
    try:
        if c == 1:
            await member.timeout(datetime.timedelta(minutes=10))
        elif c == 2:
            await member.timeout(datetime.timedelta(hours=1))
        elif c == 3:
            await member.timeout(datetime.timedelta(days=1))
        elif c == 4:
            await member.kick()
        elif c >= 5:
            await member.ban()
    except:
        pass

# ================= PARTY SYSTEM =================
class PartyView(discord.ui.View):
    def __init__(self, owner, size):
        super().__init__(timeout=None)
        self.owner = owner
        self.size = size
        self.members = [owner]
        self.voice = None

    async def create_voice(self, guild):
        self.voice = await guild.create_voice_channel(
            name=f"🎮 파티-{self.owner.name}"
        )

    def embed(self):
        return discord.Embed(
            title="🎮 파티 시스템",
            description="\n".join([m.mention for m in self.members]) +
                        f"\n\n🎧 {self.voice.mention if self.voice else '생성중'}",
            color=0x00ff99
        )

    @discord.ui.button(label="참가", style=discord.ButtonStyle.success)
    async def join(self, i, b):

        if i.user in self.members:
            return await i.response.send_message("이미 참가", ephemeral=True)

        if len(self.members) >= self.size:
            return await i.response.send_message("파티 꽉참", ephemeral=True)

        self.members.append(i.user)

        # 🎧 자동 이동
        if self.voice and i.user.voice:
            try:
                await i.user.move_to(self.voice)
            except:
                pass

        await i.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="나가기", style=discord.ButtonStyle.danger)
    async def leave(self, i, b):
        if i.user in self.members:
            self.members.remove(i.user)
        await i.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="삭제", style=discord.ButtonStyle.gray)
    async def delete(self, i, b):

        if i.user != self.owner:
            return await i.response.send_message("파티장만 가능", ephemeral=True)

        if self.voice:
            await self.voice.delete()

        await i.response.edit_message(
            embed=discord.Embed(title="삭제됨", color=0xff0000),
            view=None
        )

# ================= VERIFY =================
class VerifyView(discord.ui.View):
    @discord.ui.button(label="인증", style=discord.ButtonStyle.success)
    async def v(self, i, b):
        role = i.guild.get_role(VERIFY_ROLE_ID)
        if not role:
            role = await i.guild.create_role(name="인증")
        await i.user.add_roles(role)
        await i.response.send_message("인증 완료", ephemeral=True)

# ================= ECONOMY =================
salary_cd = {}

@bot.tree.command(name="출석")
async def attend(i):
    add_money(i.user.id, 500000)
    await i.response.send_message(embed=embed("출석", "+500,000"))

@bot.tree.command(name="월급")
async def salary(i):
    now = datetime.datetime.utcnow().timestamp()
    last = salary_cd.get(i.user.id, 0)

    if now - last < 10:
        return await i.response.send_message("쿨타임", ephemeral=True)

    salary_cd[i.user.id] = now
    add_money(i.user.id, 100000)

    await i.response.send_message(embed=embed("월급", "+100,000"))

@bot.tree.command(name="잔액")
async def bal(i, user: discord.Member=None):
    user = user or i.user
    await i.response.send_message(embed=embed("잔액", str(money(user.id))))

# ================= PARTY COMMAND =================
@bot.tree.command(name="파티")
async def party(i, 타입: str):

    size = {"솔로":1,"듀오":2,"트리오":3,"스쿼드":4,"파이브":5}.get(타입)

    if not size:
        return await i.response.send_message("오류", ephemeral=True)

    v = PartyView(i.user, size)
    await v.create_voice(i.guild)

    await i.response.send_message(embed=v.embed(), view=v)

# ================= RUN =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print("🔥 FULL SYSTEM READY")

async def main():
    keep_alive()
    await bot.start(TOKEN)

asyncio.run(main())
