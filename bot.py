import os
import json
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "boss_data.json"


# ------------------ Utilities ------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


def get_next_spawn(tod_str, respawn_hours, tz):
    tod = datetime.strptime(tod_str, "%H:%M")
    now = datetime.now(ZoneInfo(tz))

    tod = tod.replace(year=now.year, month=now.month, day=now.day)

    if tod > now:
        tod -= timedelta(days=1)

    return tod + timedelta(hours=respawn_hours)


def discord_time(dt):
    return f"<t:{int(dt.timestamp())}:F>"


# ------------------ Background Tasks ------------------

@tasks.loop(seconds=30)
async def board_loop():
    data = load_data()

    for guild_id, guild_data in data.items():
        channel_id = guild_data.get("board_channel")
        message_id = guild_data.get("board_message")

        if not channel_id or not message_id:
            continue

        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        try:
            msg = await channel.fetch_message(message_id)
        except:
            continue

        desc = ""
        tz = guild_data.get("timezone", "UTC")

        for name, boss in guild_data.get("bosses", {}).items():
            if not boss.get("tod"):
                desc += f"**{name.title()}**\n⏳ Waiting for TOD\n\n"
                continue

            next_spawn = get_next_spawn(
                boss["tod"], boss["respawn"], tz
            )

            desc += (
                f"**{name.title()}**\n"
                f"Spawn: {discord_time(next_spawn)}\n\n"
            )

        embed = discord.Embed(
            title="⚔️ Boss Timer Board",
            description=desc,
            color=discord.Color.orange()
        )

        await msg.edit(embed=embed)


@tasks.loop(seconds=20)
async def alert_loop():
    data = load_data()

    for guild_id, guild_data in data.items():
        alert_channel_id = guild_data.get("alert_channel")
        tz = guild_data.get("timezone", "UTC")

        if not alert_channel_id:
            continue

        channel = bot.get_channel(alert_channel_id)
        if not channel:
            continue

        for name, boss in guild_data.get("bosses", {}).items():
            if not boss.get("tod"):
                continue

            next_spawn = get_next_spawn(
                boss["tod"], boss["respawn"], tz
            )

            remaining = (next_spawn - datetime.now(ZoneInfo(tz))).total_seconds()

            # 10 min warning
            if 580 < remaining < 620:
                role = f"<@&{boss['role']}>" if boss.get("role") else ""
                await channel.send(
                    f"⚠️ **{name.title()}** spawning in 10 minutes! {role}"
                )

            # spawn alert
            if -10 < remaining < 10:
                role = f"<@&{boss['role']}>" if boss.get("role") else ""
                await channel.send(
                    f"🔥 **{name.title()}** is SPAWNING NOW! {role}"
                )


# ------------------ Events ------------------

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    try:
        board_loop.start()
    except RuntimeError:
        pass

    try:
        alert_loop.start()
    except RuntimeError:
        pass


# ------------------ Slash Commands ------------------

@bot.tree.command(name="set_board_channel")
async def set_board_channel(interaction: discord.Interaction):
    data = load_data()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["board_channel"] = interaction.channel.id

    msg = await interaction.channel.send("Boss board initialized...")
    data[gid]["board_message"] = msg.id

    save_data(data)
    await interaction.response.send_message("✅ Board channel set.", ephemeral=True)


@bot.tree.command(name="set_alert_channel")
async def set_alert_channel(interaction: discord.Interaction):
    data = load_data()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["alert_channel"] = interaction.channel.id

    save_data(data)
    await interaction.response.send_message("✅ Alert channel set.", ephemeral=True)


@bot.tree.command(name="set_timezone")
async def set_timezone(interaction: discord.Interaction, tz: str):
    data = load_data()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["timezone"] = tz

    save_data(data)
    await interaction.response.send_message(f"✅ Timezone set to {tz}", ephemeral=True)


@bot.tree.command(name="boss_add")
async def boss_add(
    interaction: discord.Interaction,
    name: str,
    respawn_hours: int,
    role: discord.Role = None
):
    data = load_data()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid].setdefault("bosses", {})

    data[gid]["bosses"][name.lower()] = {
        "respawn": respawn_hours,
        "role": role.id if role else None,
        "tod": None
    }

    save_data(data)
    await interaction.response.send_message(f"✅ Boss {name} added.", ephemeral=True)


@bot.tree.command(name="boss_tod")
async def boss_tod(
    interaction: discord.Interaction,
    name: str,
    time: str
):
    data = load_data()
    gid = str(interaction.guild.id)

    boss = data[gid]["bosses"].get(name.lower())
    if not boss:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return

    boss["tod"] = time
    save_data(data)

    await interaction.response.send_message("✅ TOD saved.", ephemeral=True)


# ------------------ Run ------------------

bot.run(TOKEN)
