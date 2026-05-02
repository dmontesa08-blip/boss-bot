import discord
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, timedelta, timezone
import os
import json

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

DATA_FILE = "boss_data.json"


# -------------------- DATA --------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"bosses": {}, "board_channel": None, "alert_channel": None, "board_message": None}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


data = load_data()


# -------------------- TIME UTILS --------------------

def parse_hhmm_to_datetime(hhmm: str):
    now = datetime.now(timezone.utc)
    hh, mm = map(int, hhmm.split(":"))
    tod = now.replace(hour=hh, minute=mm, second=0, microsecond=0)

    # If TOD time is in the future, it means it was yesterday
    if tod > now:
        tod -= timedelta(days=1)

    return tod


def discord_ts(dt):
    return f"<t:{int(dt.timestamp())}:F> (<t:{int(dt.timestamp())}:R>)"


# -------------------- EMBED BOARD --------------------

async def update_board():
    if not data["board_channel"] or not data["board_message"]:
        return

    channel = client.get_channel(data["board_channel"])
    try:
        message = await channel.fetch_message(data["board_message"])
    except:
        return

    embed = discord.Embed(title="⚔️ Boss Timer Board", color=0x2b2d31)

    for name, boss in data["bosses"].items():
        if "next_spawn" not in boss:
            embed.add_field(name=name.title(), value="⏳ Waiting for TOD", inline=False)
        else:
            dt = datetime.fromtimestamp(boss["next_spawn"], timezone.utc)
            embed.add_field(
                name=name.title(),
                value=f"Spawn: {discord_ts(dt)}",
                inline=False,
            )

    await message.edit(embed=embed)


# -------------------- ALERT LOOP --------------------

@tasks.loop(seconds=30)
async def alert_loop():
    if not data["alert_channel"]:
        return

    now = datetime.now(timezone.utc).timestamp()
    channel = client.get_channel(data["alert_channel"])

    for name, boss in data["bosses"].items():
        if "next_spawn" not in boss:
            continue

        next_spawn = boss["next_spawn"]
        role_id = boss["role"]
        role_ping = f"<@&{role_id}>"

        # 10 minute warning
        if 0 < next_spawn - now <= 600 and not boss.get("warned"):
            await channel.send(f"⏰ {role_ping} **{name.title()}** spawns in 10 minutes!")
            boss["warned"] = True
            save_data(data)

        # Spawn now
        if -30 <= next_spawn - now <= 30 and not boss.get("spawned"):
            await channel.send(f"🔥 {role_ping} **{name.title()}** SPAWNING NOW!")
            boss["spawned"] = True
            save_data(data)


# -------------------- COMMANDS --------------------

@tree.command(name="boss_add", description="Add a boss")
async def boss_add(interaction: discord.Interaction, name: str, respawn_hours: int, role: discord.Role):
    await interaction.response.defer(ephemeral=True)

    data["bosses"][name.lower()] = {
        "respawn": respawn_hours,
        "role": role.id
    }
    save_data(data)

    await interaction.followup.send(f"✅ Boss **{name}** added.")


@tree.command(name="boss_tod", description="Set boss TOD (HH:MM 24h)")
async def boss_tod(interaction: discord.Interaction, name: str, time: str):
    await interaction.response.defer(ephemeral=True)

    name = name.lower()
    if name not in data["bosses"]:
        await interaction.followup.send("❌ Boss not found.")
        return

    tod_dt = parse_hhmm_to_datetime(time)
    respawn = data["bosses"][name]["respawn"]

    next_spawn = tod_dt + timedelta(hours=respawn)

    data["bosses"][name]["next_spawn"] = next_spawn.timestamp()
    data["bosses"][name]["warned"] = False
    data["bosses"][name]["spawned"] = False

    save_data(data)
    await update_board()

    await interaction.followup.send(
        f"✅ TOD saved.\nNext spawn: {discord_ts(next_spawn)}"
    )


@tree.command(name="boss_list", description="List bosses")
async def boss_list(interaction: discord.Interaction):
    bosses = "\n".join(data["bosses"].keys())
    await interaction.response.send_message(f"Bosses:\n{bosses}", ephemeral=True)


@tree.command(name="set_board_channel", description="Set board channel")
async def set_board_channel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    data["board_channel"] = interaction.channel.id
    msg = await interaction.channel.send("📌 Boss board initialized...")
    data["board_message"] = msg.id
    save_data(data)

    await update_board()
    await interaction.followup.send("✅ Board channel set.")


@tree.command(name="set_alert_channel", description="Set alert channel")
async def set_alert_channel(interaction: discord.Interaction):
    data["alert_channel"] = interaction.channel.id
    save_data(data)
    await interaction.response.send_message("✅ Alert channel set.", ephemeral=True)


# -------------------- READY --------------------

@client.event
async def on_ready():
    await tree.sync()
    alert_loop.start()
    print(f"Logged in as {client.user}")


client.run(TOKEN)
