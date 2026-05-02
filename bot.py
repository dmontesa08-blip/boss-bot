import os
import json
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TOKEN = os.getenv("TOKEN")
DATA_FILE = "data.json"
BACKUP_FILE = "data_backup.json"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# -------------------- Storage --------------------

def load():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


def backup(data):
    with open(BACKUP_FILE, "w") as f:
        json.dump(data, f, indent=4)


# -------------------- Time Math (NO DRIFT) --------------------

def calculate_spawn(tod_str, respawn, tz):
    now = datetime.now(ZoneInfo(tz))
    hh, mm = map(int, tod_str.split(":"))

    tod = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if tod > now:
        tod -= timedelta(days=1)

    return tod + timedelta(hours=respawn)


def ts(dt):
    return f"<t:{int(dt.timestamp())}:F> (<t:{int(dt.timestamp())}:R>)"


# -------------------- Board Builder --------------------

async def update_board(gid):
    data = load()
    g = data.get(gid)
    if not g:
        return

    channel_id = g.get("board_channel")
    msg_id = g.get("board_message")
    tz = g.get("timezone", "UTC")

    if not channel_id or not msg_id:
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        return

    try:
        msg = await channel.fetch_message(msg_id)
    except:
        return

    soon = ""
    upcoming = ""
    waiting = ""

    now = datetime.now(ZoneInfo(tz))

    for name, boss in g.get("bosses", {}).items():
        if not boss.get("tod"):
            waiting += f"**{name.title()}**\n⏳ Waiting for TOD\n\n"
            continue

        spawn = calculate_spawn(boss["tod"], boss["respawn"], tz)
        left = spawn - now

        block = (
            f"**{name.title()}**\n"
            f"Spawn: {ts(spawn)}\n"
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
    data = load()
    for gid in data.keys():
        await update_board(gid)


@tasks.loop(seconds=15)
async def alert_loop():
    data = load()

    for gid, g in data.items():
        tz = g.get("timezone", "UTC")
        channel_id = g.get("alert_channel")
        warning = g.get("warning_minutes")

        if not channel_id:
            continue

        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        now = datetime.now(ZoneInfo(tz))

        for name, boss in g.get("bosses", {}).items():
            if not boss.get("tod"):
                continue

            spawn = calculate_spawn(boss["tod"], boss["respawn"], tz)
            diff = (spawn - now).total_seconds()
            role = f"<@&{boss['role']}>" if boss.get("role") else ""

            # Warning
            if warning and not boss.get("warned"):
                if warning * 60 - 10 < diff < warning * 60 + 10:
                    await channel.send(f"⚠️ {name.title()} in {warning} minutes! {role}")
                    boss["warned"] = True

            # Spawn
            if not boss.get("spawned") and -10 < diff < 10:
                await channel.send(f"🔥 {name.title()} SPAWNING NOW! {role}")
                boss["spawned"] = True

        save(data)


@tasks.loop(minutes=5)
async def backup_loop():
    backup(load())


# -------------------- Events --------------------

@bot.event
async def on_ready():
    try:
        board_loop.start()
    except RuntimeError:
        pass

    try:
        alert_loop.start()
    except RuntimeError:
        pass

    try:
        backup_loop.start()
    except RuntimeError:
        pass

    await bot.tree.sync()
    print("Bot Ready")


# -------------------- Commands --------------------

@bot.tree.command(name="set_board_channel")
async def set_board_channel(interaction: discord.Interaction):
    data = load()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["board_channel"] = interaction.channel.id

    msg = await interaction.channel.send("Boss board initialized...")
    data[gid]["board_message"] = msg.id

    save(data)
    await interaction.response.send_message("Board channel set.", ephemeral=True)


@bot.tree.command(name="set_alert_channel")
async def set_alert_channel(interaction: discord.Interaction):
    data = load()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["alert_channel"] = interaction.channel.id

    save(data)
    await interaction.response.send_message("Alert channel set.", ephemeral=True)


@bot.tree.command(name="set_timezone")
async def set_timezone(interaction: discord.Interaction, tz: str):
    data = load()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["timezone"] = tz

    save(data)
    await interaction.response.send_message(f"Timezone set to {tz}", ephemeral=True)


@bot.tree.command(name="set_warning_minutes")
async def set_warning(interaction: discord.Interaction, minutes: int):
    data = load()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["warning_minutes"] = minutes

    save(data)
    await interaction.response.send_message("Warning time set.", ephemeral=True)


@bot.tree.command(name="boss_add")
async def boss_add(interaction: discord.Interaction, name: str, respawn_hours: int, role: discord.Role = None):
    data = load()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid].setdefault("bosses", {})

    key = name.lower()
    if key in data[gid]["bosses"]:
        await interaction.response.send_message("Boss already exists.", ephemeral=True)
        return

    data[gid]["bosses"][key] = {
        "respawn": respawn_hours,
        "role": role.id if role else None,
        "tod": None,
        "warned": False,
        "spawned": False
    }

    save(data)
    await update_board(gid)
    await interaction.response.send_message(f"{name} added.", ephemeral=True)


@bot.tree.command(name="boss_remove")
async def boss_remove(interaction: discord.Interaction, name: str):
    data = load()
    gid = str(interaction.guild.id)

    bosses = data.get(gid, {}).get("bosses", {})
    if name.lower() not in bosses:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return

    del bosses[name.lower()]
    save(data)
    await update_board(gid)
    await interaction.response.send_message("Boss removed.", ephemeral=True)


@bot.tree.command(name="boss_tod")
async def boss_tod(interaction: discord.Interaction, name: str, time: str):
    data = load()
    gid = str(interaction.guild.id)

    boss = data.get(gid, {}).get("bosses", {}).get(name.lower())
    if not boss:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return

    boss["tod"] = time
    boss["warned"] = False
    boss["spawned"] = False

    save(data)
    await update_board(gid)

    await interaction.response.send_message("TOD saved.", ephemeral=True)


@bot.tree.command(name="boss_list")
async def boss_list(interaction: discord.Interaction):
    data = load()
    gid = str(interaction.guild.id)
    bosses = data.get(gid, {}).get("bosses", {})

    if not bosses:
        await interaction.response.send_message("No bosses.", ephemeral=True)
        return

    names = "\n".join([b.title() for b in bosses.keys()])
    await interaction.response.send_message(names, ephemeral=True)


@bot.tree.command(name="boss_info")
async def boss_info(interaction: discord.Interaction, name: str):
    data = load()
    gid = str(interaction.guild.id)

    boss = data.get(gid, {}).get("bosses", {}).get(name.lower())
    if not boss:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return

    await interaction.response.send_message(json.dumps(boss, indent=2), ephemeral=True)


bot.run(TOKEN)
