import discord
from discord.ext import commands
import os
import sqlite3
import datetime
import random
from flask import Flask
from threading import Thread

# ================= CONFIG =================
TOKEN = os.getenv("TOKEN")
PORT = int(os.environ.get("PORT", 10000))

VERIFY_ROLE_ID = 1499675598178750560
VOICE_LOBBY_ID = 123456789012345678  # 수정 필수

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= KEEP ALIVE (RENDER SAFE) =================
app = Flask(__name__)

@app.route("/")
def home():
    return "BOT ONLINE"

def run():
    app.run(host="0.0.0.0", port=PORT)

# ================= DB =================
DB = sqlite3.connect("bot.db", check_same_thread=False)
CUR = DB.cursor()

def init_db():
    CUR.execute("CREATE TABLE IF NOT EXISTS money (uid INTEGER PRIMARY KEY, bal INTEGER)")
    CUR.execute("CREATE TABLE IF NOT EXISTS warn (gid INTEGER, uid INTEGER, cnt INTEGER)")
    CUR.execute("CREATE TABLE IF NOT EXISTS sticky (cid INTEGER PRIMARY KEY, msg TEXT)")
    CUR.execute("CREATE TABLE IF NOT EXISTS attendance (uid INTEGER PRIMARY KEY, date TEXT)")
    DB.commit()

# ================= UTIL =================
def embed(t, d="", c=0x5865F2):
    e = discord.Embed(title=t, description=d, color=c)
    e.timestamp = datetime.datetime.utcnow()
    return e

# ================= ECONOMY =================
def money(uid):
    CUR.execute("SELECT bal FROM money WHERE uid=?", (uid,))
    r = CUR.fetchone()
    return r[0] if r else 0

def set_money(uid, v):
    CUR.execute("REPLACE INTO money VALUES (?,?)", (uid, max(v,0)))
    DB.commit()

def add_money(uid, v): set_money(uid, money(uid)+v)

# ================= WARNING SYSTEM =================
def get_warn(gid, uid):
    CUR.execute("SELECT cnt FROM warn WHERE gid=? AND uid=?", (gid, uid))
    r = CUR.fetchone()
    return r[0] if r else 0

def add_warn(gid, uid):
    c = get_warn(gid, uid) + 1
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

# ================= PARTY =================
class PartyView(discord.ui.View):
    def __init__(self, owner, size):
        super().__init__()
        self.owner = owner
        self.size = size
        self.members = [owner]
        self.voice = None

    async def create_voice(self, guild):
        self.voice = await guild.create_voice_channel(f"🎮 파티-{self.owner.name}")

    def build(self):
        return embed(
            "🎮 파티",
            "\n".join([m.mention for m in self.members])
        )

    @discord.ui.button(label="참가", style=discord.ButtonStyle.green)
    async def join(self, i, b):
        if i.user in self.members:
            return await i.response.send_message("이미 참가", ephemeral=True)

        if len(self.members) >= self.size:
            return await i.response.send_message("풀방", ephemeral=True)

        self.members.append(i.user)

        if self.voice and i.user.voice:
            await i.user.move_to(self.voice)

        await i.response.edit_message(embed=self.build(), view=self)

    @discord.ui.button(label="삭제", style=discord.ButtonStyle.red)
    async def delete(self, i, b):
        if i.user != self.owner:
            return await i.response.send_message("파티장만 가능", ephemeral=True)

        if self.voice:
            await self.voice.delete()

        await i.response.edit_message(embed=embed("삭제됨"), view=None)

# ================= VERIFY =================
class VerifyView(discord.ui.View):
    @discord.ui.button(label="인증", style=discord.ButtonStyle.green)
    async def v(self, i, b):
        role = i.guild.get_role(VERIFY_ROLE_ID)
        if not role:
            role = await i.guild.create_role(name="인증")

        await i.user.add_roles(role)
        await i.response.send_message("인증 완료", ephemeral=True)

# ================= STICKY =================
@bot.event
async def on_message(m):
    if m.author.bot:
        return

    CUR.execute("SELECT msg FROM sticky WHERE cid=?", (m.channel.id,))
    r = CUR.fetchone()

    if r:
        await m.channel.send(embed=embed("📌", r[0]))

    await bot.process_commands(m)

# ================= EVENTS =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print("🔥 RENDER BOT READY")

# ================= COMMANDS =================

@bot.tree.command(name="파티")
async def party(i, type: str):
    sizes = {"솔로":1,"듀오":2,"트리오":3,"스쿼드":4,"파이브":5}
    size = sizes.get(type)

    v = PartyView(i.user, size)
    await v.create_voice(i.guild)

    await i.response.send_message(embed=v.build(), view=v)

@bot.tree.command(name="인증패널")
async def verify_panel(i):
    await i.response.send_message(embed=embed("인증"), view=VerifyView())

@bot.tree.command(name="잔액")
async def bal(i, u: discord.Member=None):
    u = u or i.user
    await i.response.send_message(embed=embed("잔액", str(money(u.id))))

@bot.tree.command(name="경고")
async def warn(i, user: discord.Member):
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌", ephemeral=True)

    c = add_warn(i.guild.id, user.id)
    await punish(user, c)

    await i.response.send_message(embed=embed("경고", f"{user} {c}회"))

@bot.tree.command(name="스티키")
async def sticky(i, msg: str):
    CUR.execute("REPLACE INTO sticky VALUES (?,?)", (i.channel.id, msg))
    DB.commit()
    await i.response.send_message("고정됨")

# ================= RUN (RENDER SAFE) =================
def start():
    keep_alive = Thread(target=run)
    keep_alive.start()
    bot.run(TOKEN)

if __name__ == "__main__":
    start()
