import discord
from discord.ext import tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone
import json
import os

TOKEN = os.getenv("TOKEN")

DATA_FILE = "data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "bosses": {},
            "board_channel": None,
            "alert_channel": None,
            "board_message_id": None,
            "warning_minutes": 10
        }
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

data = load_data()
bosses = data["bosses"]

intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# ---------------- TOD PARSER (FIXES ALL TIME ISSUES) ----------------
def parse_tod(hhmm: str):
    now = datetime.now(timezone.utc)
    h, m = map(int, hhmm.split(":"))
    tod = now.replace(hour=h, minute=m, second=0, microsecond=0)

    # If TOD is in the future today, it means it was yesterday
    if tod > now:
        tod -= timedelta(days=1)

    return tod

# ---------------- BOARD EMBED ----------------
async def update_board():
    if not data["board_channel"]:
        return

    channel = bot.get_channel(data["board_channel"])
    if not channel:
        return

    embed = discord.Embed(title="Boss Timer Board", color=discord.Color.red())

    sorted_bosses = sorted(
        bosses.items(),
        key=lambda x: x[1]["next_spawn"] or 9999999999
    )

    for name, b in sorted_bosses:
        if not b["next_spawn"]:
            embed.add_field(name=name, value="Waiting for TOD", inline=False)
        else:
            ts = b["next_spawn"]
            embed.add_field(
                name=name,
                value=f"Spawn: <t:{ts}:F>\nTime Left: <t:{ts}:R>",
                inline=False
            )

    if data["board_message_id"]:
        try:
            msg = await channel.fetch_message(data["board_message_id"])
            await msg.edit(embed=embed)
            return
        except:
            pass

    msg = await channel.send(embed=embed)
    data["board_message_id"] = msg.id
    save_data()

# ---------------- ALERT LOOP ----------------
@tasks.loop(seconds=30)
async def alert_loop():
    now = int(datetime.now(timezone.utc).timestamp())

    for name, b in bosses.items():
        if not b["next_spawn"]:
            continue

        spawn = b["next_spawn"]
        warn_time = spawn - (data["warning_minutes"] * 60)

        alert_channel = bot.get_channel(data["alert_channel"])
        role = alert_channel.guild.get_role(b["role_id"]) if alert_channel else None

        # 10-min warning
        if now >= warn_time and not b["warned"]:
            if alert_channel and role:
                await alert_channel.send(
                    f"⚠️ {role.mention} **{name} spawns in {data['warning_minutes']} minutes!**"
                )
            b["warned"] = True
            save_data()

        # Spawn ping
        if now >= spawn and not b["spawned"]:
            if alert_channel and role:
                await alert_channel.send(
                    f"🔥 {role.mention} **{name} HAS SPAWNED!**"
                )
            b["spawned"] = True
            save_data()

    await update_board()

# ---------------- EVENTS ----------------
@bot.event
async def on_ready():
    await tree.sync()
    alert_loop.start()
    print(f"Logged in as {bot.user}")

# ---------------- ADMIN COMMANDS ----------------
def admin_only():
    return app_commands.default_permissions(administrator=True)

@tree.command(name="set_board_channel")
@admin_only()
async def set_board_channel(interaction: discord.Interaction):
    data["board_channel"] = interaction.channel.id
    save_data()
    await update_board()
    await interaction.response.send_message("Board channel set.", ephemeral=True)

@tree.command(name="set_alert_channel")
@admin_only()
async def set_alert_channel(interaction: discord.Interaction):
    data["alert_channel"] = interaction.channel.id
    save_data()
    await interaction.response.send_message("Alert channel set.", ephemeral=True)

@tree.command(name="set_warning")
@admin_only()
async def set_warning(interaction: discord.Interaction, minutes: int):
    data["warning_minutes"] = minutes
    save_data()
    await interaction.response.send_message("Warning time updated.", ephemeral=True)

@tree.command(name="boss_add")
@admin_only()
async def boss_add(interaction: discord.Interaction, name: str, respawn_hours: int, role: discord.Role):
    bosses[name] = {
        "respawn_hours": respawn_hours,
        "role_id": role.id,
        "next_spawn": None,
        "last_tod": None,
        "warned": False,
        "spawned": False
    }
    save_data()
    await interaction.response.send_message(f"{name} added.", ephemeral=True)

@tree.command(name="boss_edit")
@admin_only()
async def boss_edit(interaction: discord.Interaction, name: str, respawn_hours: int, role: discord.Role):
    if name not in bosses:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return
    bosses[name]["respawn_hours"] = respawn_hours
    bosses[name]["role_id"] = role.id
    save_data()
    await interaction.response.send_message("Boss updated.", ephemeral=True)

@tree.command(name="boss_remove")
@admin_only()
async def boss_remove(interaction: discord.Interaction, name: str):
    bosses.pop(name, None)
    save_data()
    await interaction.response.send_message("Boss removed.", ephemeral=True)

@tree.command(name="boss_clear_tod")
@admin_only()
async def boss_clear_tod(interaction: discord.Interaction, name: str):
    b = bosses.get(name)
    if not b:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return
    b["next_spawn"] = None
    b["last_tod"] = None
    b["warned"] = False
    b["spawned"] = False
    save_data()
    await interaction.response.send_message("TOD cleared.", ephemeral=True)

@tree.command(name="boss_info")
@admin_only()
async def boss_info(interaction: discord.Interaction, name: str):
    b = bosses.get(name)
    if not b:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return

    msg = (
        f"Respawn: {b['respawn_hours']}h\n"
        f"Last TOD: <t:{b['last_tod']}:F>\n"
        f"Next Spawn: <t:{b['next_spawn']}:F>\n"
        f"Warned: {b['warned']}\n"
        f"Spawned: {b['spawned']}"
    )
    await interaction.response.send_message(msg, ephemeral=True)

# ---------------- USER COMMAND ----------------
@tree.command(name="boss")
async def boss_tod(interaction: discord.Interaction, name: str, time: str):
    b = bosses.get(name)
    if not b:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return

    tod_time = parse_tod(time)
    next_spawn = tod_time + timedelta(hours=b["respawn_hours"])

    b["last_tod"] = int(tod_time.timestamp())
    b["next_spawn"] = int(next_spawn.timestamp())
    b["warned"] = False
    b["spawned"] = False
    save_data()

    await update_board()

    await interaction.response.send_message(
        f"TOD set for {name}\nNext spawn: <t:{b['next_spawn']}:F>",
        ephemeral=True
    )

bot.run(TOKEN)
