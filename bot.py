from zoneinfo import ZoneInfo

USER_TIMEZONE = ZoneInfo("Asia/Manila")  # <-- change to YOUR country

import os
import json
import discord
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, timedelta, timezone

TOKEN = os.getenv("TOKEN")
DATA_FILE = "bosses.json"

# ---------- Data ----------

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(bosses, f, indent=4)

bosses = load_data()

BOARD_CHANNEL_ID = None
ALERT_CHANNEL_ID = None
BOARD_MESSAGE_ID = None

# ---------- Helpers ----------

def ts(unix_ts: float) -> str:
    u = int(unix_ts)
    return f"<t:{u}:F> (<t:{u}:R>)"

def parse_tod_to_utc_timestamp(tod_hhmm: str, respawn_hours: int) -> float:
    now_user = datetime.now(USER_TIMEZONE)

    h, m = map(int, tod_hhmm.split(":"))

    tod_user = now_user.replace(hour=h, minute=m, second=0, microsecond=0)

    # If that time is in the future → it was yesterday
    if tod_user > now_user:
        tod_user -= timedelta(days=1)

    # Convert to UTC for storage
    tod_utc = tod_user.astimezone(timezone.utc)

    next_spawn_utc = tod_utc + timedelta(hours=respawn_hours)
    return next_spawn_utc.timestamp()

# ---------- Discord ----------

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

@client.event
async def on_ready():
    await tree.sync()
    update_board.start()
    alert_loop.start()
    print("Bot ready.")

# ---------- Commands ----------

@tree.command(name="set_board_channel")
async def set_board_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    global BOARD_CHANNEL_ID
    BOARD_CHANNEL_ID = channel.id
    await interaction.response.send_message("✅ Board channel set.", ephemeral=True)

@tree.command(name="set_alert_channel")
async def set_alert_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    global ALERT_CHANNEL_ID
    ALERT_CHANNEL_ID = channel.id
    await interaction.response.send_message("✅ Alert channel set.", ephemeral=True)

@tree.command(name="boss_add")
async def boss_add(interaction: discord.Interaction, name: str, respawn_hours: int, role: discord.Role):
    bosses[name] = {
        "respawn_hours": respawn_hours,
        "role_id": role.id,
        "next_spawn": None,
        "warned": False,
        "spawned": False,
    }
    save_data()
    await interaction.response.send_message(f"✅ Boss **{name}** added.", ephemeral=True)

@tree.command(name="boss_tod")
async def boss_tod(interaction: discord.Interaction, name: str, tod: str):
    if name not in bosses:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return

    next_spawn = parse_tod_to_utc_timestamp(tod, bosses[name]["respawn_hours"])

    bosses[name]["next_spawn"] = next_spawn
    bosses[name]["warned"] = False
    bosses[name]["spawned"] = False
    save_data()

    await interaction.response.send_message(
        f"✅ TOD saved.\nNext spawn: {ts(next_spawn)}",
        ephemeral=True
    )

# ---------- Board ----------

@tasks.loop(seconds=60)
async def update_board():
    if not BOARD_CHANNEL_ID:
        return

    channel = client.get_channel(BOARD_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(title="⚔️ Boss Timer Board", color=0x2f3136)

    for name, boss in bosses.items():
        if boss["next_spawn"]:
            value = f"Spawn: {ts(boss['next_spawn'])}"
        else:
            value = "⏳ Waiting for TOD"

        embed.add_field(name=name, value=value, inline=False)

    global BOARD_MESSAGE_ID

    try:
        if BOARD_MESSAGE_ID:
            msg = await channel.fetch_message(BOARD_MESSAGE_ID)
            await msg.edit(embed=embed)
        else:
            msg = await channel.send(embed=embed)
            BOARD_MESSAGE_ID = msg.id
    except:
        msg = await channel.send(embed=embed)
        BOARD_MESSAGE_ID = msg.id

# ---------- Alerts ----------

@tasks.loop(seconds=30)
async def alert_loop():
    if not ALERT_CHANNEL_ID:
        return

    channel = client.get_channel(ALERT_CHANNEL_ID)
    if not channel:
        return

    now = datetime.now(timezone.utc).timestamp()

    for name, boss in bosses.items():

        # ---- SAFE GUARDS (fix crash) ----
        if "next_spawn" not in boss or not boss["next_spawn"]:
            continue
        if "respawn_hours" not in boss:
            continue
        if "role_id" not in boss:
            continue

        while now >= boss["next_spawn"]:
            boss["next_spawn"] += boss["respawn_hours"] * 3600
            boss["warned"] = False
            boss["spawned"] = False
            save_data()

        remaining = boss["next_spawn"] - now
        role = channel.guild.get_role(boss["role_id"])

        if remaining <= 600 and not boss.get("warned", False):
            await channel.send(
                f"⚠️ {role.mention} **{name}** spawns in 10 minutes!\n{ts(boss['next_spawn'])}"
            )
            boss["warned"] = True
            save_data()

        if remaining <= 0 and not boss.get("spawned", False):
            await channel.send(
                f"🔥 {role.mention} **{name}** SPAWNING NOW!\n{ts(boss['next_spawn'])}"
            )
            boss["spawned"] = True
            save_data()

client.run(TOKEN)
