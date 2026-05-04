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


async def backup_data():
    data = await load_data()
    with open(BACKUP_FILE, "w") as f:
        json.dump(data, f, indent=4)

# -------------------- Time Helpers --------------------

def init_next_spawn(tod_str, respawn, tz):
    now = datetime.now(ZoneInfo(tz))
    hh, mm = map(int, tod_str.split(":"))
    tod = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if tod > now:
        tod -= timedelta(days=1)
    return int((tod + timedelta(hours=respawn)).timestamp())

# -------------------- Board --------------------

async def update_board(gid):
    data = await load_data()
    g = data.get(gid)
    if not g:
        return

    cid = g.get("board_channel")
    mid = g.get("board_message")
    tz = g.get("timezone", "UTC")

    if not cid or not mid:
        return

    if mid in message_cache:
        msg = message_cache[mid]
    else:
        channel = bot.get_channel(cid)
        if not channel:
            return
        try:
            msg = await channel.fetch_message(mid)
            message_cache[mid] = msg
        except Exception as e:
            print("Board fetch error:", e)
            return

    now = datetime.now(ZoneInfo(tz))
    soon, upcoming, waiting = "", "", ""

    for name, boss in g.get("bosses", {}).items():
        ns = boss.get("next_spawn")
        if not ns:
            waiting += f"**{name.title()}**\n⏳ Waiting for TOD\n\n"
            continue

        spawn = datetime.fromtimestamp(ns, ZoneInfo(tz))
        left = spawn - now

        block = (
            f"**{name.title()}**\n"
            f"Spawn: <t:{ns}:F> (<t:{ns}:R>)\n"
            f"Time Left: {str(left).split('.')[0]}\n\n"
        )

        if left.total_seconds() < 3600:
            soon += block
        else:
            upcoming += block

    desc = ""
    if soon:
        desc += "🟢 **Spawning Soon**\n" + soon
    if upcoming:
        desc += "🟡 **Upcoming**\n" + upcoming
    if waiting:
        desc += "⏳ **Waiting for TOD**\n" + waiting

    embed = discord.Embed(title="⚔️ Boss Timer Board", description=desc, color=0x2b2d31)
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

            # ⚠️ Warning message with timestamp
            if warning and not boss.get("warned"):
                if warning * 60 - 10 < diff < warning * 60 + 10:
                    ts = int(spawn.timestamp())
                    await channel.send(
                        f"⚠️ **{name.title()} in {warning} minutes!** {role}\n"
                        f"Spawn Time: <t:{ts}:F> (<t:{ts}:R>)"
                    )
                    boss["warned"] = True

            # 🔥 Spawn message with timestamp
            if not boss.get("spawned") and -10 < diff < 10:
                ts = int(spawn.timestamp())
                await channel.send(
                    f"🔥 **{name.title()} SPAWNING NOW!** {role}\n"
                    f"Spawn Time: <t:{ts}:F> (<t:{ts}:R>)"
                )
                boss["spawned"] = True

            # ♻️ Auto cycle after 10 minutes
            if diff < -600:
                boss["next_spawn"] = int(
                    (spawn + timedelta(hours=boss["respawn"])).timestamp()
                )
                boss["warned"] = False
                boss["spawned"] = False

    await save_data(data)


@tasks.loop(minutes=5)
async def backup_loop():
    await backup_data()

# -------------------- Events --------------------

@bot.event
async def on_ready():
    print("Bot Ready")
    await bot.tree.sync()
    board_loop.start()
    alert_loop.start()
    backup_loop.start()

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
    try:
        ZoneInfo(tz)
    except Exception:
        await interaction.response.send_message("Invalid timezone.", ephemeral=True)
        return

    data = await load_data()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["timezone"] = tz

    await save_data(data)
    await interaction.response.send_message("Timezone set.", ephemeral=True)


@bot.tree.command(name="set_warning_minutes")
async def set_warning_minutes(interaction: discord.Interaction, minutes: int):
    data = await load_data()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["warning_minutes"] = minutes

    await save_data(data)
    await interaction.response.send_message("Warning time set.", ephemeral=True)


@bot.tree.command(name="boss_add")
async def boss_add(interaction: discord.Interaction, name: str, respawn_hours: int, role: discord.Role = None):
    data = await load_data()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {}).setdefault("bosses", {})
    key = name.lower()

    if key in data[gid]["bosses"]:
        await interaction.response.send_message("Boss already exists.", ephemeral=True)
        return

    data[gid]["bosses"][key] = {
        "respawn": respawn_hours,
        "role": role.id if role else None,
        "tod": None,
        "next_spawn": None,
        "warned": False,
        "spawned": False
    }

    await save_data(data)
    await update_board(gid)
    await interaction.response.send_message("Boss added.", ephemeral=True)


@bot.tree.command(name="boss_tod")
async def boss_tod(interaction: discord.Interaction, name: str, time: str):
    try:
        datetime.strptime(time, "%H:%M")
    except:
        await interaction.response.send_message("Use HH:MM format.", ephemeral=True)
        return

    data = await load_data()
    gid = str(interaction.guild.id)
    boss = data.get(gid, {}).get("bosses", {}).get(name.lower())

    if not boss:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return

    tz = data[gid].get("timezone", "UTC")
    boss["tod"] = time
    boss["next_spawn"] = init_next_spawn(time, boss["respawn"], tz)
    boss["warned"] = False
    boss["spawned"] = False

    await save_data(data)
    await update_board(gid)
    await interaction.response.send_message("TOD saved.", ephemeral=True)


bot.run(TOKEN)
