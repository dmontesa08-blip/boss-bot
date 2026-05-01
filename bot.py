import discord
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, timedelta, timezone
import json
import os
import math

TOKEN = os.getenv("TOKEN")
DATA_FILE = "bosses.json"

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# ---------------- DATA ----------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"bosses": {}, "channel_id": None, "message_id": None, "role_id": None}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(d):
    with open(DATA_FILE, "w") as f:
        json.dump(d, f, indent=4)


data = load_data()


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


# ---------------- SPAWN MATH (NO DRIFT) ----------------

def calculate_next_spawn(tod_iso, respawn_hours):
    tod = datetime.fromisoformat(tod_iso).astimezone(timezone.utc)
    now = utcnow()

    cycle_seconds = respawn_hours * 3600
    elapsed = (now - tod).total_seconds()

    cycles = max(0, math.floor(elapsed / cycle_seconds) + 1)
    next_spawn = tod + timedelta(seconds=cycle_seconds * cycles)

    return next_spawn


# ---------------- EMBED ----------------

def create_embed():
    embed = discord.Embed(
        title="🗡️ Boss Timer Board",
        color=discord.Color.red(),
        timestamp=utcnow()
    )

    if not data["bosses"]:
        embed.description = "No bosses added yet."
        return embed

    for name, info in data["bosses"].items():
        next_spawn = calculate_next_spawn(info["tod"], info["respawn_hours"])
        remaining = (next_spawn - utcnow()).total_seconds()

        if 0 < remaining <= 60:
            status = "🔥 **SPAWNING NOW**"
        else:
            mins = int(remaining // 60)
            h = mins // 60
            m = mins % 60
            status = f"⏳ {h}h {m}m" if h else f"⏳ {m}m"

        embed.add_field(
            name=name,
            value=(
                f"**Spawn:** <t:{int(next_spawn.timestamp())}:F>\n"
                f"**Time Left:** {status}"
            ),
            inline=False
        )

    return embed


# ---------------- LOOP ----------------

@tasks.loop(minutes=1)
async def board_loop():
    await send_alerts()
    await update_board()


async def update_board():
    if not data["channel_id"] or not data["message_id"]:
        return
    ch = client.get_channel(data["channel_id"])
    msg = await ch.fetch_message(data["message_id"])
    await msg.edit(embed=create_embed())


async def send_alerts():
    ch = client.get_channel(data["channel_id"])
    role = data.get("role_id")

    for name, info in data["bosses"].items():
        next_spawn = calculate_next_spawn(info["tod"], info["respawn_hours"])
        remaining = (next_spawn - utcnow()).total_seconds()

        # 10 min warning
        if 540 < remaining <= 600 and not info.get("warned"):
            await ch.send(f"⚠️ **{name} spawns in 10 minutes!**")
            info["warned"] = True

        # spawn ping
        if 0 < remaining <= 60 and not info.get("spawned"):
            mention = f"<@&{role}>" if role else ""
            await ch.send(f"🔥 {mention} **{name} is SPAWNING NOW!**")
            info["spawned"] = True

        # reset flags after window
        if remaining > 600:
            info["warned"] = False
            info["spawned"] = False

    save_data(data)


# ---------------- COMMANDS ----------------

@tree.command(name="boss_channel")
async def boss_channel(inter: discord.Interaction):
    await inter.response.defer(ephemeral=True)
    data["channel_id"] = inter.channel.id
    msg = await inter.channel.send(embed=create_embed())
    data["message_id"] = msg.id
    save_data(data)
    await inter.followup.send("✅ Boss board created.", ephemeral=True)


@tree.command(name="boss_role")
async def boss_role(inter: discord.Interaction, role: discord.Role):
    data["role_id"] = role.id
    save_data(data)
    await inter.response.send_message("✅ Role set.", ephemeral=True)


@tree.command(name="boss_add")
async def boss_add(inter: discord.Interaction, name: str, respawn_hours: int):
    data["bosses"][name] = {
        "respawn_hours": respawn_hours,
        "tod": iso(utcnow()),
        "warned": False,
        "spawned": False
    }
    save_data(data)
    await inter.response.send_message(f"✅ {name} added.", ephemeral=True)


@tree.command(name="boss_tod")
async def boss_tod(inter: discord.Interaction, name: str, time: str = None):
    if name not in data["bosses"]:
        await inter.response.send_message("Boss not found.", ephemeral=True)
        return

    now = utcnow()

    if time:
        hh, mm = map(int, time.split(":"))
        tod = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if tod > now:
            tod -= timedelta(days=1)
    else:
        tod = now

    data["bosses"][name]["tod"] = iso(tod)
    save_data(data)

    next_spawn = calculate_next_spawn(iso(tod), data["bosses"][name]["respawn_hours"])

    await inter.response.send_message(
        f"✅ TOD saved.\nNext spawn: <t:{int(next_spawn.timestamp())}:F>",
        ephemeral=True
    )


# ---------------- READY ----------------

@client.event
async def on_ready():
    await tree.sync()
    board_loop.start()
    print("Bot ready")


client.run(TOKEN)
