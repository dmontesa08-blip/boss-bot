import discord
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, timedelta, timezone
import json
import os

TOKEN = os.getenv("TOKEN")
DATA_FILE = "bosses.json"

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


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

from datetime import datetime, timezone

def create_embed():
    embed = discord.Embed(
        title="🗡️ Boss Timer Board",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc)
    )

    now = datetime.now(timezone.utc)

    if not data["bosses"]:
        embed.description = "No bosses added yet."
        return embed

    for name, info in data["bosses"].items():
        spawn_time = datetime.fromisoformat(info["next_spawn"])
        remaining = (spawn_time - now).total_seconds()

        # Only show SPAWNING NOW in the real 60s window
        if 0 <= remaining <= 60:
            status = "🔥 **SPAWNING NOW**"
        elif remaining < 0:
            # Already passed, waiting for next cycle update
            total_minutes = int(abs(remaining) // 60)
            status = f"⌛ Waiting next cycle ({total_minutes}m ago)"
        else:
            total_minutes = int(remaining // 60)
            hours = total_minutes // 60
            minutes = total_minutes % 60
            status = f"⏳ {hours}h {minutes}m" if hours else f"⏳ {minutes}m"

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
    if not data.get("channel_id") or not data.get("message_id"):
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
    now = datetime.now(timezone.utc)
    role_id = data.get("role_id")

    for name, info in data["bosses"].items():
        spawn_time = datetime.fromisoformat(info["next_spawn"])
        remaining = (spawn_time - now).total_seconds()
        channel = client.get_channel(data["channel_id"])

        # If spawn time already passed → immediately roll to next cycle
        if remaining <= 0:
            respawn = timedelta(hours=info["respawn_hours"])
            next_spawn = spawn_time + respawn

            info["next_spawn"] = next_spawn.isoformat()
            info["warned"] = False
            info["spawned"] = False
            save_data(data)
            continue

        # 10-minute warning
        if 540 < remaining <= 600 and not info.get("warned"):
            await channel.send(f"⚠️ **{name} spawns in 10 minutes!**")
            info["warned"] = True

        # Spawn alert (real window)
        if 0 < remaining <= 60 and not info.get("spawned"):
            mention = f"<@&{role_id}>" if role_id else ""
            await channel.send(f"🔥 {mention} **{name} is SPAWNING NOW!**")
            info["spawned"] = True

    save_data(data)


# ------------------ SLASH COMMANDS ------------------

@tree.command(name="boss_channel", description="Set this channel as boss board")
async def boss_channel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    data["channel_id"] = interaction.channel.id
    msg = await interaction.channel.send(embed=create_embed())
    data["message_id"] = msg.id
    save_data(data)

    await interaction.followup.send("✅ Boss board created here.", ephemeral=True)


@tree.command(name="boss_role", description="Set role to ping on spawn")
async def boss_role(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(ephemeral=True)

    data["role_id"] = role.id
    save_data(data)

    await interaction.followup.send(f"✅ Role set to {role.name}", ephemeral=True)


@tree.command(name="boss_add", description="Add a boss")
async def boss_add(interaction: discord.Interaction, name: str, respawn_hours: int):
    await interaction.response.defer(ephemeral=True)

    data["bosses"][name] = {
        "respawn_hours": respawn_hours,
        "next_spawn": datetime.now(timezone.utc).isoformat(),
        "warned": False,
        "spawned": False
    }
    save_data(data)

    await interaction.followup.send(f"✅ Boss **{name}** added.", ephemeral=True)


@tree.command(name="boss_tod", description="Set Time of Death (optional HH:MM)")
async def boss_tod(interaction: discord.Interaction, name: str, time: str = None):
    await interaction.response.defer(ephemeral=True)

    if name not in data["bosses"]:
        await interaction.followup.send("❌ Boss not found.", ephemeral=True)
        return

    now = datetime.now(timezone.utc)

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

    await interaction.followup.send(
        f"✅ TOD set for **{name}**.\nNext spawn: <t:{int(next_spawn.timestamp())}:F>",
        ephemeral=True
    )


# ------------------ READY ------------------

@client.event
async def on_ready():
    await tree.sync()
    if not update_board.is_running():
        update_board.start()
    print(f"Logged in as {client.user}")


client.run(TOKEN)
