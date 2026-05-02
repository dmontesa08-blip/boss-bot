import os
import json
import discord
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TOKEN = os.getenv("TOKEN")
DATA_FILE = "data.json"

# -------------------- LOAD / SAVE --------------------

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "config": {
            "board_channel": None,
            "alert_channel": None,
            "board_message": None,
            "timezone": "UTC",
            "warning_minutes": 10
        },
        "bosses": {}
    }

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

data = load_data()
bosses = data["bosses"]
CONFIG = data["config"]

# -------------------- HELPERS --------------------

def tz():
    return ZoneInfo(CONFIG["timezone"])

def ts(unix_ts: float) -> str:
    u = int(unix_ts)
    return f"<t:{u}:F> (<t:{u}:R>)"

def time_left_str(unix_ts: float) -> str:
    now = datetime.now(timezone.utc).timestamp()
    diff = int(unix_ts - now)
    if diff <= 0:
        return "🔥 SPAWNING NOW"
    h, r = divmod(diff, 3600)
    m = r // 60
    return f"⏳ {h}h {m}m"

def parse_tod(tod_hhmm: str, respawn_hours: int) -> float:
    now_user = datetime.now(tz())
    h, m = map(int, tod_hhmm.split(":"))

    tod_user = now_user.replace(hour=h, minute=m, second=0, microsecond=0)
    if tod_user > now_user:
        tod_user -= timedelta(days=1)

    tod_utc = tod_user.astimezone(timezone.utc)
    next_spawn = tod_utc + timedelta(hours=respawn_hours)
    return next_spawn.timestamp()

# -------------------- DISCORD --------------------

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

@client.event
async def on_ready():
    await tree.sync()
    update_board.start()
    alert_loop.start()
    print("Bot ready.")

# -------------------- CONFIG COMMANDS --------------------

@tree.command(name="set_timezone")
async def set_timezone(interaction: discord.Interaction, timezone: str):
    CONFIG["timezone"] = timezone
    save_data()
    await interaction.response.send_message(f"✅ Timezone set to `{timezone}`", ephemeral=True)

@tree.command(name="set_board_channel")
async def set_board_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    CONFIG["board_channel"] = channel.id
    save_data()
    await interaction.response.send_message("✅ Board channel saved.", ephemeral=True)

@tree.command(name="set_alert_channel")
async def set_alert_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    CONFIG["alert_channel"] = channel.id
    save_data()
    await interaction.response.send_message("✅ Alert channel saved.", ephemeral=True)

@tree.command(name="set_warning")
async def set_warning(interaction: discord.Interaction, minutes: int):
    CONFIG["warning_minutes"] = minutes
    save_data()
    await interaction.response.send_message(
        f"⚠️ Warning time set to **{minutes} minutes** before spawn.",
        ephemeral=True
    )

# -------------------- BOSS COMMANDS --------------------

@tree.command(name="boss_add")
async def boss_add(interaction: discord.Interaction, name: str, respawn_hours: int, role: discord.Role):
    bosses[name] = {
        "respawn_hours": respawn_hours,
        "role_id": role.id,
        "next_spawn": None,
        "warned": False,
        "spawned": False
    }
    save_data()
    await interaction.response.send_message(f"✅ Boss **{name}** added.", ephemeral=True)

@tree.command(name="boss_remove")
async def boss_remove(interaction: discord.Interaction, name: str):
    if name in bosses:
        del bosses[name]
        save_data()
        await interaction.response.send_message(f"🗑️ Boss **{name}** removed.", ephemeral=True)
    else:
        await interaction.response.send_message("Boss not found.", ephemeral=True)

@tree.command(name="boss_list")
async def boss_list(interaction: discord.Interaction):
    if not bosses:
        await interaction.response.send_message("No bosses added.", ephemeral=True)
        return

    msg = ""
    for n, b in bosses.items():
        msg += f"**{n}** — {b['respawn_hours']}h\n"

    await interaction.response.send_message(msg, ephemeral=True)

@tree.command(name="boss_tod")
async def boss_tod(interaction: discord.Interaction, name: str, tod: str):
    if name not in bosses:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return

    next_spawn = parse_tod(tod, bosses[name]["respawn_hours"])
    bosses[name]["next_spawn"] = next_spawn
    bosses[name]["warned"] = False
    bosses[name]["spawned"] = False
    save_data()

    await interaction.response.send_message(
        f"✅ TOD saved.\nNext spawn: {ts(next_spawn)}",
        ephemeral=True
    )

# -------------------- BOARD --------------------

@tasks.loop(seconds=60)
async def update_board():
    cid = CONFIG["board_channel"]
    if not cid:
        return

    channel = client.get_channel(cid)
    if not channel:
        return

    embed = discord.Embed(title="⚔️ Boss Timer Board", color=0x2f3136)

    sorted_bosses = sorted(
        bosses.items(),
        key=lambda x: x[1]["next_spawn"] or 9999999999
    )

    for name, boss in sorted_bosses:
        if boss["next_spawn"]:
            value = f"Spawn: {ts(boss['next_spawn'])}\n{time_left_str(boss['next_spawn'])}"
        else:
            value = "⏳ Waiting for TOD"

        embed.add_field(name=name, value=value, inline=False)

    msg_id = CONFIG["board_message"]

    try:
        if msg_id:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(embed=embed)
        else:
            msg = await channel.send(embed=embed)
            CONFIG["board_message"] = msg.id
            save_data()
    except:
        msg = await channel.send(embed=embed)
        CONFIG["board_message"] = msg.id
        save_data()

# -------------------- ALERTS --------------------

@tasks.loop(seconds=30)
async def alert_loop():
    cid = CONFIG["alert_channel"]
    if not cid:
        return

    channel = client.get_channel(cid)
    if not channel:
        return

    now = datetime.now(timezone.utc).timestamp()
    warn_seconds = CONFIG.get("warning_minutes", 10) * 60

    for name, boss in bosses.items():
        if not boss.get("next_spawn"):
            continue

        while now >= boss["next_spawn"]:
            boss["next_spawn"] += boss["respawn_hours"] * 3600
            boss["warned"] = False
            boss["spawned"] = False
            save_data()

        remaining = boss["next_spawn"] - now
        role = channel.guild.get_role(boss["role_id"])

        if remaining <= warn_seconds and not boss["warned"]:
            await channel.send(
                f"⚠️ {role.mention} **{name}** in {CONFIG['warning_minutes']} minutes!\n{ts(boss['next_spawn'])}"
            )
            boss["warned"] = True
            save_data()

        if remaining <= 0 and not boss["spawned"]:
            await channel.send(
                f"🔥 {role.mention} **{name}** SPAWNING NOW!\n{ts(boss['next_spawn'])}"
            )
            boss["spawned"] = True
            save_data()

client.run(TOKEN)
