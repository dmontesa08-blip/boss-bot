USER_TIMEZONE_OFFSET = 8

import os
import json
import discord
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, timedelta

TOKEN = os.getenv("TOKEN")
DATA_FILE = "data.json"
USER_TIMEZONE_OFFSET = 8  # <<< CHANGE

# ---------- Helpers ----------

def utcnow():
    return datetime.utcnow()

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "bosses": {},
        "board_channel_id": None,
        "alert_channel_id": None,
        "board_message_id": None
    }

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def status_icon(spawn_ts):
    if not spawn_ts:
        return "⚫"
    remaining = spawn_ts - int(utcnow().timestamp())
    if remaining <= 600:
        return "🟢"
    elif remaining <= 3600:
        return "🟡"
    return "🔴"

# ---------- Setup ----------

data = load_data()

intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# ---------- Embed ----------

def build_embed():
    embed = discord.Embed(title="Boss Timers", color=0x2f3136)

    bosses_sorted = sorted(
        data["bosses"].items(),
        key=lambda x: x[1].get("next_spawn") or 9999999999
    )

    for name, boss in bosses_sorted:
        spawn = boss.get("next_spawn")
        icon = status_icon(spawn)

        if spawn:
            value = (
                f"{icon} Spawn: <t:{spawn}:F>\n"
                f"Time Left: <t:{spawn}:R>"
            )
        else:
            value = f"{icon} No TOD set"

        embed.add_field(name=name, value=value, inline=False)

    return embed

# ---------- Loops ----------

@tasks.loop(seconds=30)
async def update_board():
    if not data["board_channel_id"] or not data["board_message_id"]:
        return

    channel = bot.get_channel(data["board_channel_id"])
    if not channel:
        return

    try:
        msg = await channel.fetch_message(data["board_message_id"])
        await msg.edit(embed=build_embed())
    except:
        pass

@tasks.loop(seconds=20)
async def alert_loop():
    if not data["alert_channel_id"]:
        return

    alert_channel = bot.get_channel(data["alert_channel_id"])
    if not alert_channel:
        return

    now_ts = int(utcnow().timestamp())

    for name, boss in data["bosses"].items():
        spawn = boss.get("next_spawn")
        if not spawn:
            continue

        role_id = boss.get("role")
        role_mention = ""
        if role_id:
            role = alert_channel.guild.get_role(role_id)
            if role:
                role_mention = role.mention

        # 10 min warning WITH role ping
        if 0 < spawn - now_ts <= 600 and not boss.get("warned"):
            await alert_channel.send(
                f"{role_mention} ⚠️ **{name}** spawning in 10 minutes!\n"
                f"Spawn: <t:{spawn}:F>\n"
                f"Time Left: <t:{spawn}:R>"
            )
            boss["warned"] = True
            save_data()

        # Spawn alert WITH role ping
        if now_ts >= spawn and not boss.get("spawned"):
            await alert_channel.send(
                f"{role_mention} 🔥 **{name} HAS SPAWNED!**"
            )

            boss["spawned"] = True
            boss["warned"] = False
            boss["next_spawn"] = spawn + boss["respawn"]
            save_data()

# ---------- Events ----------

@bot.event
async def on_ready():
    await tree.sync()
    update_board.start()
    alert_loop.start()
    print("Bot Ready")

# ---------- Commands ----------

@tree.command(name="boss_channel")
async def boss_channel(interaction: discord.Interaction):
    embed = build_embed()
    msg = await interaction.channel.send(embed=embed)

    data["board_channel_id"] = interaction.channel.id
    data["board_message_id"] = msg.id
    save_data()

    await interaction.response.send_message("Board channel set.", ephemeral=True)

@tree.command(name="boss_alert_channel")
async def boss_alert_channel(interaction: discord.Interaction):
    data["alert_channel_id"] = interaction.channel.id
    save_data()
    await interaction.response.send_message("Alert channel set.", ephemeral=True)

@tree.command(name="boss_add")
async def boss_add(interaction: discord.Interaction, name: str, respawn_hours: int, role: discord.Role = None):
    data["bosses"][name] = {
        "respawn": respawn_hours * 3600,
        "next_spawn": None,
        "role": role.id if role else None,
        "warned": False,
        "spawned": False
    }
    save_data()
    await interaction.response.send_message(f"{name} added.", ephemeral=True)

@tree.command(name="boss_tod")
async def boss_tod(interaction: discord.Interaction, name: str, time: str = None):
    boss = data["bosses"].get(name)
    if not boss:
        return await interaction.response.send_message("Boss not found.", ephemeral=True)

    now = utcnow()

    if time:
        hh, mm = map(int, time.split(":"))
        local = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        tod = local - timedelta(hours=USER_TIMEZONE_OFFSET)
        if tod > now:
            tod -= timedelta(days=1)
    else:
        tod = now

    next_spawn = int((tod + timedelta(seconds=boss["respawn"])).timestamp())

    boss["next_spawn"] = next_spawn
    boss["warned"] = False
    boss["spawned"] = False
    save_data()

    await interaction.response.send_message(
        f"{name} TOD set.\nSpawn: <t:{next_spawn}:F>",
        ephemeral=True
    )

# ---------- Run ----------

bot.run(TOKEN)
