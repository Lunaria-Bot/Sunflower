import discord
from discord import app_commands
import asyncio
import os
import re
import redis.asyncio as aioredis

TOKEN = os.getenv("DISCORD_TOKEN")
REDIS_URL = os.getenv("REDIS_URL")

# IDs (remplace par les tiens)
MAZOKU_BOT_ID = 1242388858897956906
GUILD_ID = 1196690004852883507
LOG_CHANNEL_ID = 1420095365494866001  # Salon pour logs

# Cooldown times per command (seconds)
COOLDOWN_SECONDS = {
    "summon": 1800,      # 30 min
    "open-boxes": 60     # 1 min
}

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True

class CooldownBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.redis = None
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        print("🔌 Connecting to Redis...")
        try:
            self.redis = await aioredis.from_url(
                REDIS_URL,
                decode_responses=True
            )
            pong = await self.redis.ping()
            print(f"✅ Redis connected: PING={pong}")
        except Exception as e:
            print(f"❌ Redis connection failed: {e}")
            self.redis = None

        guild = discord.Object(id=GUILD_ID)

        # ⚠️ On force la synchro uniquement dans la guilde
        synced = await self.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}")

client = CooldownBot()

# ----------------
# Ici tu gardes toutes tes commandes /cooldowns, /force-clear, /toggle-reminder,
# /leaderboard, /leaderboard_reset, /leaderboard_pause (inchangées)
# ----------------

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user} ({client.user.id})")
    if client.redis:
        paused = await client.redis.get("leaderboard:paused")
        print(f"🏆 Leaderboard paused = {paused}")
    client.loop.create_task(rotate_status())

async def rotate_status():
    activities = [
        discord.Game("MoonQuill is sleeping 😴"),
        discord.Activity(type=discord.ActivityType.watching, name="the sunflowers 🌻"),
        discord.Activity(type=discord.ActivityType.listening, name="the wind in the fields 🌬️"),
        discord.Activity(type=discord.ActivityType.competing, name="a sunflower growing contest 🌞")
    ]
    i = 0
    while True:
        try:
            await client.change_presence(status=discord.Status.idle, activity=activities[i % len(activities)])
        except Exception as e:
            print(f"⚠️ Failed to change presence: {e}")
        i += 1
        await asyncio.sleep(300)

# ----------------
# Ton on_message avec la logique cooldown + autosummon leaderboard
# (inchangé par rapport à la version précédente)
# ----------------

# ----------------
# Entry point
# ----------------
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from environment variables.")
client.run(TOKEN)
