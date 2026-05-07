# --- FULL WORLD BOSS BOT (RESTORED) ---

import os
import json
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks
from discord import app_commands

TOKEN = os.getenv("TOKEN")
DATA_FILE = "data.json"

intents = discord.Intents.default()
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
data_lock = asyncio.Lock()
message_cache = {}

# -------------------- Helpers --------------------

def build_mention(boss):
    if boss.get("role") == "everyone":
        return "@everyone"
    elif boss.get("role"):
        return f"<@&{boss['role']}>"
    return ""

def init_next_spawn(tod_str, respawn, tz):
    now = datetime.now(ZoneInfo(tz))
    hh, mm = map(int, tod_str.split(":"))
    tod = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if tod > now:
        tod -= timedelta(days=1)
    return int((tod + timedelta(hours=respawn)).timestamp())

# -------------------- Storage --------------------

async def load_data():
    async with data_lock:
        if not os.path.exists(DATA_FILE):
            return {}
        with open(DATA_FILE, "r") as f:
            return json.load(f)

async def save_data(data):
    async with data_lock:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)

# -------------------- Board --------------------

async def update_board(gid):
    g = bot.guild_data.get(gid)
    if not g:
        return

    cid = g.get("board_channel")
    mid = g.get("board_message")
    tz = g.get("timezone", "UTC")

    if not cid or not mid:
        return

    key = f"{cid}:{mid}"
    msg = message_cache.get(key)

    if not msg:
        channel = await bot.fetch_channel(cid)
        msg = await channel.fetch_message(mid)
        message_cache[key] = msg

    desc = "⚔️ **WORLD BOSS TIMER BOARD** ⚔️\n\n"

    for name, boss in g.get("bosses", {}).items():
        ns = boss.get("next_spawn")
        if not ns:
            continue
        desc += f"**{name.title()}**\nSpawn: <t:{ns}:F> (<t:{ns}:R>)\n\n"

    await msg.edit(embed=discord.Embed(description=desc, color=0x2b2d31))

# -------------------- Loops --------------------

@tasks.loop(seconds=30)
async def board_loop():
    for gid in bot.guild_data.keys():
        await update_board(gid)

@tasks.loop(seconds=15)
async def alert_loop():
    for gid, g in bot.guild_data.items():
        tz = g.get("timezone", "UTC")
        cid = g.get("alert_channel")
        warning = g.get("warning_minutes")

        if not cid:
            continue

        channel = bot.get_channel(cid)
        now = datetime.now(ZoneInfo(tz))

        for name, boss in g.get("bosses", {}).items():
            ns = boss.get("next_spawn")
            if not ns:
                continue

            spawn = datetime.fromtimestamp(ns, ZoneInfo(tz))
            diff = (spawn - now).total_seconds()
            mention = build_mention(boss)

            if warning and not boss.get("warned"):
                if warning*60-10 < diff < warning*60+10:
                    await channel.send(
                        f"⚠️ **{name.title()} in {warning} minutes!** {mention}\n"
                        f"Spawn: <t:{ns}:F> (<t:{ns}:R>)"
                    )
                    boss["warned"] = True

            if not boss.get("spawned") and -10 < diff < 10:
                await channel.send(
                    f"🔥 **{name.title()} SPAWNING NOW!** {mention}\n"
                    f"Spawn: <t:{ns}:F> (<t:{ns}:R>)"
                )
                boss["spawned"] = True

    await save_data(bot.guild_data)

# -------------------- Instant Sync --------------------

async def sync_commands():
    for guild in bot.guilds:
        await bot.tree.sync(guild=guild)

# -------------------- Events --------------------

@bot.event
async def on_ready():
    bot.guild_data = await load_data()
    await sync_commands()
    board_loop.start()
    alert_loop.start()
    print("Bot Ready")

# -------------------- Commands --------------------

def admin():
    return app_commands.checks.has_permissions(administrator=True)

@bot.tree.command(name="set_board_channel")
@admin()
async def set_board_channel(inter: discord.Interaction):
    gid = str(inter.guild.id)
    bot.guild_data.setdefault(gid, {})
    bot.guild_data[gid]["board_channel"] = inter.channel.id
    msg = await inter.channel.send("Boss board initialized...")
    bot.guild_data[gid]["board_message"] = msg.id
    await save_data(bot.guild_data)
    await inter.response.send_message("Board set.", ephemeral=True)

@bot.tree.command(name="set_alert_channel")
@admin()
async def set_alert_channel(inter: discord.Interaction):
    gid = str(inter.guild.id)
    bot.guild_data.setdefault(gid, {})
    bot.guild_data[gid]["alert_channel"] = inter.channel.id
    await save_data(bot.guild_data)
    await inter.response.send_message("Alert channel set.", ephemeral=True)

@bot.tree.command(name="set_timezone")
@admin()
async def set_timezone(inter: discord.Interaction, tz: str):
    ZoneInfo(tz)
    bot.guild_data.setdefault(str(inter.guild.id), {})["timezone"] = tz
    await save_data(bot.guild_data)
    await inter.response.send_message("Timezone set.", ephemeral=True)

@bot.tree.command(name="set_warning_minutes")
@admin()
async def set_warning_minutes(inter: discord.Interaction, minutes: int):
    bot.guild_data.setdefault(str(inter.guild.id), {})["warning_minutes"] = minutes
    await save_data(bot.guild_data)
    await inter.response.send_message("Warning set.", ephemeral=True)

@bot.tree.command(name="boss_add")
@admin()
async def boss_add(inter: discord.Interaction, name: str, respawn_hours: int, role: str = None):
    gid = str(inter.guild.id)
    bot.guild_data.setdefault(gid, {}).setdefault("bosses", {})

    role_value = None
    if role:
        if role.lower() == "everyone":
            role_value = "everyone"
        else:
            r = discord.utils.get(inter.guild.roles, name=role)
            if not r:
                await inter.response.send_message("Role not found.", ephemeral=True)
                return
            role_value = r.id

    bot.guild_data[gid]["bosses"][name.lower()] = {
        "respawn": respawn_hours,
        "role": role_value,
        "next_spawn": None,
        "warned": False,
        "spawned": False
    }

    await save_data(bot.guild_data)
    await inter.response.send_message("Boss added.", ephemeral=True)

@bot.tree.command(name="boss_tod")
@admin()
async def boss_tod(inter: discord.Interaction, name: str, time: str):
    gid = str(inter.guild.id)
    boss = bot.guild_data[gid]["bosses"].get(name.lower())
    tz = bot.guild_data[gid].get("timezone", "UTC")
    boss["next_spawn"] = init_next_spawn(time, boss["respawn"], tz)
    await save_data(bot.guild_data)
    await update_board(gid)
    await inter.response.send_message("TOD set.", ephemeral=True)

bot.guild_data = {}
bot.run(TOKEN)
