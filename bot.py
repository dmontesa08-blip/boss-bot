import discord
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, timedelta
import json
import os

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

DATA_FILE = "bosses.json"


# ------------------ DATA ------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"bosses": {}, "channel_id": None, "role_id": None}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


data = load_data()


# ------------------ EMBED ------------------

def create_embed():
    embed = discord.Embed(
        title="🗡️ Boss Timer Board",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )

    now = datetime.utcnow()

    if not data["bosses"]:
        embed.description = "No bosses added yet."
        return embed

    for name, info in data["bosses"].items():
        spawn_time = datetime.fromisoformat(info["next_spawn"])
        remaining = spawn_time - now

        if remaining.total_seconds() <= 0:
            status = "🔥 **SPAWNING NOW**"
        else:
            mins = int(remaining.total_seconds() // 60)
            status = f"⏳ {mins} min"

        embed.add_field(
            name=name,
            value=(
                f"**Spawn:** <t:{int(spawn_time.timestamp())}:F>\n"
                f"**Time Left:** {status}"
            ),
            inline=False
        )

    return embed


# ------------------ BACKGROUND LOOP ------------------

@tasks.loop(minutes=1)
async def update_board():
    await check_alerts()
    await refresh_embed()


async def refresh_embed():
    if not data["channel_id"] or "message_id" not in data:
        return

    channel = client.get_channel(data["channel_id"])
    if not channel:
        return

    try:
        msg = await channel.fetch_message(data["message_id"])
        await msg.edit(embed=create_embed())
    except:
        pass


async def check_alerts():
    now = datetime.utcnow()
    role_id = data.get("role_id")

    for name, info in data["bosses"].items():
        spawn_time = datetime.fromisoformat(info["next_spawn"])
        remaining = (spawn_time - now).total_seconds()

        # 10 min warning
        if 540 < remaining <= 600 and not info.get("warned"):
            channel = client.get_channel(data["channel_id"])
            await channel.send(f"⚠️ **{name} spawns in 10 minutes!**")
            info["warned"] = True

        # Spawn alert
        if 0 < remaining <= 60 and not info.get("spawned"):
            channel = client.get_channel(data["channel_id"])
            mention = f"<@&{role_id}>" if role_id else ""
            await channel.send(f"🔥 {mention} **{name} is SPAWNING NOW!**")

            # Prepare next cycle
            respawn = timedelta(hours=info["respawn_hours"])
            next_spawn = spawn_time + respawn

            info["next_spawn"] = next_spawn.isoformat()
            info["warned"] = False
            info["spawned"] = True

        # Reset spawned flag after cycle passes
        if remaining < -120:
            info["spawned"] = False

    save_data(data)


# ------------------ SLASH COMMANDS ------------------

@tree.command(name="boss_channel", description="Set this channel as boss board")
async def boss_channel(interaction: discord.Interaction):
    data["channel_id"] = interaction.channel.id
    msg = await interaction.channel.send(embed=create_embed())
    data["message_id"] = msg.id
    save_data(data)
    await interaction.response.send_message("✅ Boss board created here.", ephemeral=True)


@tree.command(name="boss_role", description="Set role to ping on spawn")
async def boss_role(interaction: discord.Interaction, role: discord.Role):
    data["role_id"] = role.id
    save_data(data)
    await interaction.response.send_message(f"✅ Role set to {role.name}", ephemeral=True)


@tree.command(name="boss_add", description="Add a boss")
async def boss_add(interaction: discord.Interaction, name: str, respawn_hours: int):
    data["bosses"][name] = {
        "respawn_hours": respawn_hours,
        "next_spawn": datetime.utcnow().isoformat(),
        "warned": False,
        "spawned": False
    }
    save_data(data)
    await interaction.response.send_message(f"✅ Boss **{name}** added.", ephemeral=True)


@tree.command(name="boss_tod", description="Set Time of Death (optional HH:MM)")
async def boss_tod(interaction: discord.Interaction, name: str, time: str = None):
    if name not in data["bosses"]:
        await interaction.response.send_message("❌ Boss not found.", ephemeral=True)
        return

    now = datetime.utcnow()

    if time:
        hh, mm = map(int, time.split(":"))
        tod = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if tod > now:
            tod -= timedelta(days=1)
    else:
        tod = now

    respawn = timedelta(hours=data["bosses"][name]["respawn_hours"])
    next_spawn = tod + respawn

    data["bosses"][name]["next_spawn"] = next_spawn.isoformat()
    data["bosses"][name]["warned"] = False
    data["bosses"][name]["spawned"] = False

    save_data(data)

    await interaction.response.send_message(
        f"✅ TOD set for **{name}**.\nNext spawn: <t:{int(next_spawn.timestamp())}:F>",
        ephemeral=True
    )


# ------------------ READY ------------------

@client.event
async def on_ready():
    await tree.sync()
    update_board.start()
    print(f"Logged in as {client.user}")


client.run(TOKEN)