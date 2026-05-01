import discord
from discord import app_commands
import json
import time
from datetime import datetime, timezone

TOKEN = "YOUR_TOKEN_HERE"

DATA_FILE = "bosses.json"

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# ---------- Utilities ----------

def ts(t):
    return f"<t:{int(t)}:F> (<t:{int(t)}:R>)"


def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {"bosses": {}, "board": {}, "alert_channel": None, "alert_role": None}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


def tod_to_timestamp(hhmm: str):
    now = datetime.now(timezone.utc)
    hh, mm = map(int, hhmm.split(":"))

    tod = now.replace(hour=hh, minute=mm, second=0, microsecond=0)

    if tod.timestamp() > now.timestamp():
        tod = tod.replace(day=now.day - 1)

    return int(tod.timestamp())


# ---------- Background Loop ----------

async def board_loop():
    await client.wait_until_ready()

    while not client.is_closed():
        data = load_data()

        if not data["board"]:
            await asyncio.sleep(10)
            continue

        channel = client.get_channel(data["board"]["channel_id"])
        message = await channel.fetch_message(data["board"]["message_id"])

        embed = discord.Embed(title="🗡️ Boss Timers", color=0x2f3136)

        now = int(time.time())

        for name, boss in data["bosses"].items():

            # Auto-cycle after spawn
            if now >= boss["next_spawn"]:
                boss["next_spawn"] += boss["respawn_hours"] * 3600
                boss["warned"] = False
                boss["spawned"] = False

            time_left = boss["next_spawn"] - now

            embed.add_field(
                name=name,
                value=f"Spawn: {ts(boss['next_spawn'])}",
                inline=False
            )

            # Alerts
            alert_channel_id = data.get("alert_channel")
            alert_role_id = data.get("alert_role")

            if alert_channel_id and alert_role_id:
                alert_channel = client.get_channel(alert_channel_id)
                role_mention = f"<@&{alert_role_id}>"

                # 10 min warning
                if 0 < time_left <= 600 and not boss.get("warned"):
                    await alert_channel.send(
                        f"⚠️ {role_mention} **{name} spawning in 10 minutes!**\n{ts(boss['next_spawn'])}"
                    )
                    boss["warned"] = True

                # Spawn alert
                if -60 <= time_left <= 0 and not boss.get("spawned"):
                    await alert_channel.send(
                        f"🔥 {role_mention} **{name} SPAWNING NOW!**\n{ts(boss['next_spawn'])}"
                    )
                    boss["spawned"] = True

        save_data(data)
        await message.edit(embed=embed)
        await asyncio.sleep(30)


# ---------- Slash Commands ----------

@tree.command(name="board_create", description="Create boss timer board")
async def board_create(interaction: discord.Interaction):
    embed = discord.Embed(title="🗡️ Boss Timers", color=0x2f3136)
    msg = await interaction.channel.send(embed=embed)

    data = load_data()
    data["board"] = {
        "channel_id": interaction.channel.id,
        "message_id": msg.id
    }
    save_data(data)

    await interaction.response.send_message("✅ Board created.", ephemeral=True)


@tree.command(name="boss_add", description="Add a boss")
async def boss_add(interaction: discord.Interaction, name: str, respawn_hours: int):
    data = load_data()
    data["bosses"][name] = {
        "respawn_hours": respawn_hours,
        "next_spawn": int(time.time()) + respawn_hours * 3600,
        "warned": False,
        "spawned": False
    }
    save_data(data)
    await interaction.response.send_message(f"✅ Boss **{name}** added.", ephemeral=True)


@tree.command(name="boss_tod", description="Set Time of Death (HH:MM optional)")
async def boss_tod(interaction: discord.Interaction, name: str, time_hhmm: str | None = None):
    data = load_data()

    if name not in data["bosses"]:
        await interaction.response.send_message("Boss not found.", ephemeral=True)
        return

    boss = data["bosses"][name]

    if time_hhmm:
        tod_ts = tod_to_timestamp(time_hhmm)
    else:
        tod_ts = int(time.time())

    boss["next_spawn"] = tod_ts + boss["respawn_hours"] * 3600
    boss["warned"] = False
    boss["spawned"] = False

    save_data(data)

    await interaction.response.send_message(
        f"✅ TOD saved.\nNext spawn: {ts(boss['next_spawn'])}",
        ephemeral=True
    )


@tree.command(name="alert_setup", description="Set alert channel and role")
async def alert_setup(interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role):
    data = load_data()
    data["alert_channel"] = channel.id
    data["alert_role"] = role.id
    save_data(data)

    await interaction.response.send_message("✅ Alert system configured.", ephemeral=True)


# ---------- Startup ----------

import asyncio

@client.event
async def on_ready():
    await tree.sync()
    client.loop.create_task(board_loop())
    print("Bot is ready.")


client.run(TOKEN)
