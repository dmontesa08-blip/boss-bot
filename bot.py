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

    channel_id = g.get("board_channel")
    msg_id = g.get("board_message")
    tz = g.get("timezone", "UTC")

    if not channel_id or not msg_id:
        return

    key = f"{channel_id}:{msg_id}"
    msg = message_cache.get(key)

    if not msg:
        channel = await bot.fetch_channel(channel_id)
        msg = await channel.fetch_message(msg_id)
        message_cache[key] = msg

    now = datetime.now(ZoneInfo(tz))

    desc = "⚔️ **WORLD BOSS TIMER BOARD** ⚔️\n\n"

    for name, boss in g.get("bosses", {}).items():
        ns = boss.get("next_spawn")
        if not ns:
            continue

        desc += (
            f"**{name.title()}**\n"
            f"Spawn: <t:{ns}:F> (<t:{ns}:R>)\n\n"
        )

    embed = discord.Embed(description=desc, color=0x2b2d31)
    await msg.edit(embed=embed)

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
        if not channel:
            continue

        now = datetime.now(ZoneInfo(tz))

        for name, boss in g.get("bosses", {}).items():
            ns = boss.get("next_spawn")
            if not ns:
                continue

            spawn = datetime.fromtimestamp(ns, ZoneInfo(tz))
            diff = (spawn - now).total_seconds()
            mention = build_mention(boss)

            if warning and not boss.get("warned"):
                if warning * 60 - 10 < diff < warning * 60 + 10:
                    ts = int(spawn.timestamp())
                    await channel.send(
                        f"⚠️ **{name.title()} in {warning} minutes!** {mention}\n"
                        f"Spawn Time: <t:{ts}:F> (<t:{ts}:R>)"
                    )
                    boss["warned"] = True

            if not boss.get("spawned"):
                if -10 < diff < 10:
                    ts = int(spawn.timestamp())
                    await channel.send(
                        f"🔥 **{name.title()} SPAWNING NOW!** {mention}\n"
                        f"Spawn Time: <t:{ts}:F> (<t:{ts}:R>)"
                    )
                    boss["spawned"] = True

    await save_data(bot.guild_data)

# -------------------- Instant Command Sync --------------------

async def sync_commands():
    for guild in bot.guilds:
        await bot.tree.sync(guild=guild)
        print(f"Synced commands to {guild.name}")

# -------------------- Events --------------------

@bot.event
async def on_ready():
    print("Bot Ready")

    bot.guild_data = await load_data()
    await sync_commands()

    board_loop.start()
    alert_loop.start()

# -------------------- Commands --------------------

@bot.tree.command(name="boss_add")
@app_commands.checks.has_permissions(administrator=True)
async def boss_add(
    interaction: discord.Interaction,
    name: str,
    respawn_hours: int,
    role: str = None
):
    gid = str(interaction.guild.id)
    bot.guild_data.setdefault(gid, {}).setdefault("bosses", {})

    role_value = None
    if role:
        if role.lower() == "everyone":
            role_value = "everyone"
        else:
            discord_role = discord.utils.get(interaction.guild.roles, name=role)
            if not discord_role:
                await interaction.response.send_message(
                    "Role not found. Use exact role name or 'everyone'.",
                    ephemeral=True
                )
                return
            role_value = discord_role.id

    bot.guild_data[gid]["bosses"][name.lower()] = {
        "respawn": respawn_hours,
        "role": role_value,
        "next_spawn": None,
        "warned": False,
        "spawned": False
    }

    await save_data(bot.guild_data)
    await interaction.response.send_message("Boss added.", ephemeral=True)

bot.guild_data = {}
bot.run(TOKEN)
