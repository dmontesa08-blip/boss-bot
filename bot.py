import os
import json
import time
import asyncio
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import tasks, commands

TOKEN = os.getenv("TOKEN")

DATA_FILE = "data.json"


# -------------------- Utilities --------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "bosses": {},
            "board_channel": None,
            "alert_channel": None,
            "role_id": None,
            "board_message_id": None
        }
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


def ts(unix: int) -> str:
    return f"<t:{unix}:F> (<t:{unix}:R>)"


def tod_to_unix(hhmm: str) -> int:
    now = datetime.now(timezone.utc)
    hh, mm = map(int, hhmm.split(":"))

    tod = datetime(
        year=now.year,
        month=now.month,
        day=now.day,
        hour=hh,
        minute=mm,
        second=0,
        tzinfo=timezone.utc
    )

    if tod > now:
        tod -= timedelta(days=1)

    return int(tod.timestamp())


# -------------------- Bot --------------------

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

data = load_data()


# -------------------- Board Builder --------------------

async def update_board():
    if not data["board_channel"]:
        return

    channel = bot.get_channel(data["board_channel"])
    if not channel:
        return

    embed = discord.Embed(
        title="Boss Timer Board",
        color=discord.Color.red()
    )

    now = int(time.time())
    lines = []

    for name, boss in data["bosses"].items():
        if "next_spawn" not in boss:
            lines.append(f"**{name}** — No TOD set")
            continue

        # Auto cycle
        if now >= boss["next_spawn"]:
            boss["next_spawn"] += boss["respawn_hours"] * 3600

        lines.append(
            f"**{name}**\nSpawn: {ts(boss['next_spawn'])}\n"
        )

    embed.description = "\n".join(lines) if lines else "No bosses added."

    # Send or edit persistent message
    try:
        if data["board_message_id"]:
            msg = await channel.fetch_message(data["board_message_id"])
            await msg.edit(embed=embed)
        else:
            msg = await channel.send(embed=embed)
            data["board_message_id"] = msg.id
            save_data(data)
    except:
        msg = await channel.send(embed=embed)
        data["board_message_id"] = msg.id
        save_data(data)

    save_data(data)


# -------------------- Alerts Loop --------------------

@tasks.loop(seconds=30)
async def alert_loop():
    if not data["alert_channel"] or not data["role_id"]:
        return

    channel = bot.get_channel(data["alert_channel"])
    role = channel.guild.get_role(data["role_id"])
    now = int(time.time())

    for name, boss in data["bosses"].items():
        if "next_spawn" not in boss:
            continue

        remaining = boss["next_spawn"] - now

        # 10 min warning
        if 590 <= remaining <= 610 and not boss.get("warned"):
            await channel.send(f"{role.mention} ⚠️ **{name}** spawns in 10 minutes!")
            boss["warned"] = True

        # Spawn ping
        if -10 <= remaining <= 10 and not boss.get("spawned"):
            await channel.send(f"{role.mention} 🔥 **{name}** has spawned!")
            boss["spawned"] = True
            boss["warned"] = False  # reset for next cycle

    save_data(data)


@tasks.loop(minutes=1)
async def board_loop():
    await update_board()


# -------------------- Events --------------------

@bot.event
async def on_ready():
    await tree.sync()
    board_loop.start()
    alert_loop.start()
    print(f"Logged in as {bot.user}")


# -------------------- Slash Commands --------------------

@tree.command(name="boss_channel", description="Set the boss timer board channel")
async def boss_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    data["board_channel"] = channel.id
    data["board_message_id"] = None
    save_data(data)
    await interaction.response.send_message("Boss board channel set.", ephemeral=True)


@tree.command(name="alert_channel", description="Set the alert channel")
async def alert_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    data["alert_channel"] = channel.id
    save_data(data)
    await interaction.response.send_message("Alert channel set.", ephemeral=True)


@tree.command(name="boss_role", description="Set the alert role")
async def boss_role(interaction: discord.Interaction, role: discord.Role):
    data["role_id"] = role.id
    save_data(data)
    await interaction.response.send_message("Alert role set.", ephemeral=True)


@tree.command(name="boss_add", description="Add a boss")
async def boss_add(interaction: discord.Interaction, name: str, respawn_hours: int):
    data["bosses"][name] = {
        "respawn_hours": respawn_hours
    }
    save_data(data)
    await interaction.response.send_message(f"{name} added.", ephemeral=True)


@tree.command(name="boss_remove", description="Remove a boss")
async def boss_remove(interaction: discord.Interaction, name: str):
    data["bosses"].pop(name, None)
    save_data(data)
    await interaction.response.send_message(f"{name} removed.", ephemeral=True)


@tree.command(name="boss_tod", description="Set Time of Death (HH:MM)")
async def boss_tod(interaction: discord.Interaction, name: str, time_hhmm: str):
    if name not in data["bosses"]:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return

    tod_unix = tod_to_unix(time_hhmm)
    next_spawn = tod_unix + data["bosses"][name]["respawn_hours"] * 3600

    data["bosses"][name]["next_spawn"] = next_spawn
    data["bosses"][name]["warned"] = False
    data["bosses"][name]["spawned"] = False

    save_data(data)

    await interaction.response.send_message(
        f"TOD set for **{name}**\nNext Spawn: {ts(next_spawn)}",
        ephemeral=True
    )


@tree.command(name="boss_list", description="List bosses")
async def boss_list(interaction: discord.Interaction):
    if not data["bosses"]:
        await interaction.response.send_message("No bosses added.", ephemeral=True)
        return

    msg = ""
    for name, boss in data["bosses"].items():
        msg += f"**{name}** — {boss['respawn_hours']}h\n"

    await interaction.response.send_message(msg, ephemeral=True)


# --------------------

bot.run(TOKEN)
