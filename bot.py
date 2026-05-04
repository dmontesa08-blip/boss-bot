import os
import json
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

TOKEN = os.getenv("TOKEN")
DATA_FILE = "data.json"
BACKUP_FILE = "data_backup.json"

intents = discord.Intents(guilds=True)
bot = commands.Bot(command_prefix="!", intents=intents)

data_lock = asyncio.Lock()
message_cache = {}

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

# -------------------- Time Helpers --------------------

def init_next_spawn(tod_str, respawn, tz):
    now = datetime.now(ZoneInfo(tz))
    hh, mm = map(int, tod_str.split(":"))
    tod = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if tod > now:
        tod -= timedelta(days=1)
    return int((tod + timedelta(hours=respawn)).timestamp())

def next_scheduled_spawn(schedule, tz):
    now = datetime.now(ZoneInfo(tz))
    candidates = []

    for entry in schedule:
        hh, mm = map(int, entry["time"].split(":"))
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)

        days_ahead = (entry["weekday"] - now.weekday()) % 7
        target += timedelta(days=days_ahead)

        if target <= now:
            target += timedelta(days=7)

        candidates.append(target)

    return int(min(candidates).timestamp())

# -------------------- Board --------------------

async def update_board(gid):
    data = await load_data()  # ✅ async fix
    g = data.get(gid)
    if not g:
        return

    channel_id = g.get("board_channel")
    msg_id = g.get("board_message")
    tz = g.get("timezone", "UTC")

    if not channel_id or not msg_id:
        return

    try:
        channel = await bot.fetch_channel(channel_id)
        msg = await channel.fetch_message(msg_id)
    except:
        return

    now = datetime.now(ZoneInfo(tz))

    soon_blocks = []
    upcoming_blocks = []
    waiting_blocks = []

    for name, boss in g.get("bosses", {}).items():

        ns = boss.get("next_spawn")
        if not ns:
            waiting_blocks.append(f"**{name.title()}**")
            continue

        spawn = datetime.fromtimestamp(ns, ZoneInfo(tz))
        diff = (spawn - now).total_seconds()

        block = (
            f"**{name.title()}**\n"
            f"Spawn: <t:{ns}:F> (<t:{ns}:R>)\n"
        )

        if diff <= 3600:
            soon_blocks.append(block)
        else:
            upcoming_blocks.append(block)

    desc = "⚔️ **WORLD BOSS TIMER BOARD** ⚔️\n\n"

    if soon_blocks:
        desc += "🟢 **Spawning Soon**\n━━━━━━━━━━━━━━━━━━\n"
        desc += "\n".join(soon_blocks) + "\n\n"

    if upcoming_blocks:
        desc += "🟡 **Upcoming**\n━━━━━━━━━━━━━━━━━━\n"
        desc += "\n".join(upcoming_blocks) + "\n\n"

    if waiting_blocks:
        desc += "⏳ **Waiting for Schedule/TOD**\n━━━━━━━━━━━━━━━━━━\n"
        desc += "\n".join(waiting_blocks)

    embed = discord.Embed(description=desc, color=0x2b2d31)
    await msg.edit(embed=embed)

# -------------------- Loops --------------------

@tasks.loop(seconds=30)
async def board_loop():
    data = await load_data()
    for gid in data.keys():
        await update_board(gid)

@tasks.loop(seconds=15)
async def alert_loop():
    data = await load_data()

    for gid, g in data.items():
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
            role = f"<@&{boss['role']}>" if boss.get("role") else ""

            # Warning
            if warning and not boss.get("warned"):
                if warning * 60 - 10 < diff < warning * 60 + 10:
                    ts = int(spawn.timestamp())
                    await channel.send(
                        f"⚠️ **{name.title()} in {warning} minutes!** {role}\n"
                        f"Spawn Time: <t:{ts}:F> (<t:{ts}:R>)"
                    )
                    boss["warned"] = True

            # Spawn
            if not boss.get("spawned") and -10 < diff < 10:
                ts = int(spawn.timestamp())
                await channel.send(
                    f"🔥 **{name.title()} SPAWNING NOW!** {role}\n"
                    f"Spawn Time: <t:{ts}:F> (<t:{ts}:R>)"
                )
                boss["spawned"] = True

            # Cycle reset
            if diff < -600:
                if "schedule" in boss:
                    boss["next_spawn"] = next_scheduled_spawn(boss["schedule"], tz)
                else:
                    boss["next_spawn"] = int(
                        (spawn + timedelta(hours=boss["respawn"])).timestamp()
                    )
                boss["warned"] = False
                boss["spawned"] = False

    await save_data(data)

# -------------------- Events --------------------

@bot.event
async def on_ready():
    print("Bot Ready")
    await bot.tree.sync()
    board_loop.start()
    alert_loop.start()

# -------------------- Commands --------------------

@bot.tree.command(name="set_board_channel")
async def set_board_channel(interaction: discord.Interaction):
    data = await load_data()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["board_channel"] = interaction.channel.id

    msg = await interaction.channel.send("Boss board initialized...")
    data[gid]["board_message"] = msg.id

    await save_data(data)
    await interaction.response.send_message("Board channel set.", ephemeral=True)

@bot.tree.command(name="set_alert_channel")
async def set_alert_channel(interaction: discord.Interaction):
    data = await load_data()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["alert_channel"] = interaction.channel.id

    await save_data(data)
    await interaction.response.send_message("Alert channel set.", ephemeral=True)

@bot.tree.command(name="set_timezone")
async def set_timezone(interaction: discord.Interaction, tz: str):
    ZoneInfo(tz)  # validate
    data = await load_data()
    data.setdefault(str(interaction.guild.id), {})["timezone"] = tz
    await save_data(data)
    await interaction.response.send_message("Timezone set.", ephemeral=True)

@bot.tree.command(name="set_warning_minutes")
async def set_warning_minutes(interaction: discord.Interaction, minutes: int):
    data = await load_data()
    data.setdefault(str(interaction.guild.id), {})["warning_minutes"] = minutes
    await save_data(data)
    await interaction.response.send_message("Warning time set.", ephemeral=True)

# -------- Boss Commands --------

@bot.tree.command(name="boss_add")
async def boss_add(interaction: discord.Interaction, name: str, respawn_hours: int, role: discord.Role = None):
    data = await load_data()
    gid = str(interaction.guild.id)
    data.setdefault(gid, {}).setdefault("bosses", {})

    data[gid]["bosses"][name.lower()] = {
        "respawn": respawn_hours,
        "role": role.id if role else None,
        "tod": None,
        "next_spawn": None,
        "warned": False,
        "spawned": False
    }

    await save_data(data)
    await interaction.response.send_message("Boss added.", ephemeral=True)

@bot.tree.command(name="boss_tod")
async def boss_tod(interaction: discord.Interaction, name: str, time: str):
    data = await load_data()
    gid = str(interaction.guild.id)
    boss = data[gid]["bosses"].get(name.lower())

    tz = data[gid].get("timezone", "UTC")
    boss["tod"] = time
    boss["next_spawn"] = init_next_spawn(time, boss["respawn"], tz)

    await save_data(data)
    await update_board(gid)
    await interaction.response.send_message("TOD saved.", ephemeral=True)

@bot.tree.command(name="boss_add_schedule")
async def boss_add_schedule(interaction: discord.Interaction, name: str, weekday: int, time: str):
    data = await load_data()
    gid = str(interaction.guild.id)
    data.setdefault(gid, {}).setdefault("bosses", {})

    boss = data[gid]["bosses"].setdefault(name.lower(), {
        "schedule": [],
        "warned": False,
        "spawned": False
    })

    boss["schedule"].append({"weekday": weekday, "time": time})

    tz = data[gid].get("timezone", "UTC")
    boss["next_spawn"] = next_scheduled_spawn(boss["schedule"], tz)

    await save_data(data)
    await interaction.response.send_message("Scheduled boss added.", ephemeral=True)

bot.run(TOKEN)
