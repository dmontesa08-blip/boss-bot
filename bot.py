import os
import json
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TOKEN = os.getenv("TOKEN")
DATA_FILE = "data.json"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# -------------------- Storage --------------------

def load():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


# -------------------- Time Math (NO DRIFT) --------------------

def calculate_next_spawn(tod_str, respawn, tz):
    now = datetime.now(ZoneInfo(tz))

    hh, mm = map(int, tod_str.split(":"))
    tod = now.replace(hour=hh, minute=mm, second=0, microsecond=0)

    # If TOD is in the future, it was yesterday
    if tod > now:
        tod -= timedelta(days=1)

    return tod + timedelta(hours=respawn)


def ts(dt):
    return f"<t:{int(dt.timestamp())}:F>"


# -------------------- Board Loop --------------------

@tasks.loop(seconds=30)
async def board_loop():
    data = load()

    for gid, g in data.items():
        channel_id = g.get("board_channel")
        msg_id = g.get("board_message")
        tz = g.get("timezone", "UTC")

        if not channel_id or not msg_id:
            continue

        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        try:
            msg = await channel.fetch_message(msg_id)
        except:
            continue

        desc = ""
        for name, boss in g.get("bosses", {}).items():
            if not boss.get("tod"):
                desc += f"**{name.title()}**\n⏳ Waiting for TOD\n\n"
                continue

            spawn = calculate_next_spawn(
                boss["tod"], boss["respawn"], tz
            )

            desc += (
                f"**{name.title()}**\n"
                f"Spawn: {ts(spawn)}\n\n"
            )

        embed = discord.Embed(
            title="⚔️ Boss Timer Board",
            description=desc,
            color=discord.Color.orange()
        )

        await msg.edit(embed=embed)


# -------------------- Alert Loop --------------------

@tasks.loop(seconds=15)
async def alert_loop():
    data = load()

    for gid, g in data.items():
        alert_channel = g.get("alert_channel")
        tz = g.get("timezone", "UTC")

        if not alert_channel:
            continue

        channel = bot.get_channel(alert_channel)
        if not channel:
            continue

        now = datetime.now(ZoneInfo(tz))

        for name, boss in g.get("bosses", {}).items():
            if not boss.get("tod"):
                continue

            spawn = calculate_next_spawn(
                boss["tod"], boss["respawn"], tz
            )

            diff = (spawn - now).total_seconds()

            role = f"<@&{boss['role']}>" if boss.get("role") else ""

            # 10 minute warning
            if 590 < diff < 610:
                await channel.send(
                    f"⚠️ **{name.title()}** spawns in 10 minutes! {role}"
                )

            # Spawn
            if -10 < diff < 10:
                await channel.send(
                    f"🔥 **{name.title()}** SPAWNING NOW! {role}"
                )


# -------------------- Events --------------------

@bot.event
async def on_ready():
    print("Bot Ready")

    try:
        board_loop.start()
    except RuntimeError:
        pass

    try:
        alert_loop.start()
    except RuntimeError:
        pass

    await bot.tree.sync()


# -------------------- Commands --------------------

@bot.tree.command(name="set_board_channel")
async def set_board_channel(interaction: discord.Interaction):
    data = load()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["board_channel"] = interaction.channel.id

    msg = await interaction.channel.send("Boss board initialized...")
    data[gid]["board_message"] = msg.id

    save(data)
    await interaction.response.send_message("✅ Board channel set.", ephemeral=True)


@bot.tree.command(name="set_alert_channel")
async def set_alert_channel(interaction: discord.Interaction):
    data = load()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["alert_channel"] = interaction.channel.id

    save(data)
    await interaction.response.send_message("✅ Alert channel set.", ephemeral=True)


@bot.tree.command(name="set_timezone")
async def set_timezone(interaction: discord.Interaction, tz: str):
    data = load()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["timezone"] = tz

    save(data)
    await interaction.response.send_message(f"✅ Timezone set to {tz}", ephemeral=True)


@bot.tree.command(name="boss_add")
async def boss_add(
    interaction: discord.Interaction,
    name: str,
    respawn_hours: int,
    role: discord.Role = None
):
    data = load()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid].setdefault("bosses", {})

    data[gid]["bosses"][name.lower()] = {
        "respawn": respawn_hours,
        "role": role.id if role else None,
        "tod": None
    }

    save(data)
    await interaction.response.send_message(f"✅ {name} added.", ephemeral=True)


@bot.tree.command(name="boss_tod")
async def boss_tod(
    interaction: discord.Interaction,
    name: str,
    time: str
):
    data = load()
    gid = str(interaction.guild.id)

    boss = data[gid]["bosses"].get(name.lower())
    if not boss:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return

    boss["tod"] = time
    save(data)

    await interaction.response.send_message("✅ TOD saved.", ephemeral=True)


# --------------------

bot.run(TOKEN)
