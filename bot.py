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
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

client = CooldownBot()

# ----------------
# Slash Commands (cooldowns, reminders, leaderboard)
# ----------------
# ... (tes commandes /cooldowns, /force-clear, /toggle-reminder, /leaderboard, /leaderboard_reset, /leaderboard_pause restent inchangées)

# ----------------
# Events
# ----------------
@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user} ({client.user.id})")
    # Vérifie l’état du leaderboard au démarrage
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

@client.event
async def on_message(message: discord.Message):
    if not client.redis:
        return
    if message.author.id == client.user.id:
        return
    if message.guild and message.guild.id != GUILD_ID:
        return
    if not (message.author.bot and message.author.id == MAZOKU_BOT_ID):
        return

    user = None
    cmd = None

    # --- Détection Summon / Boxes ---
    if message.embeds:
        embed = message.embeds[0]
        title = (embed.title or "").lower()
        desc = embed.description or ""

        if "summon claimed" in title:
            cmd = "summon"
            match = re.search(r"Claimed By\s+<@!?(\d+)>", desc)
            if match:
                user = message.guild.get_member(int(match.group(1)))

        elif "box opened" in title:
            cmd = "open-boxes"

        # --- Détection Autosummon ---
        if "auto summon" in title:
            print("🔎 Autosummon detected, trying to identify claimer...")

            def resolve_member_by_name(name: str) -> discord.Member | None:
                if not name:
                    return None
                name = name.strip()
                for m in message.guild.members:
                    if m.display_name == name or m.name == name or m.name.lower() == name.lower():
                        return m
                return None

            auto_user = None
            m = re.search(r"Claimed By\s+<@!?(\d+)>", desc, flags=re.IGNORECASE)
            if m:
                auto_user = message.guild.get_member(int(m.group(1)))
            if not auto_user:
                m = re.search(r"Claimed By\s+([^\n<]+)", desc, flags=re.IGNORECASE)
                if m:
                    auto_user = resolve_member_by_name(m.group(1))

            if auto_user:
                paused = await client.redis.get("leaderboard:paused")
                if paused == "true":
                    print(f"⏸️ Leaderboard paused, no points added for {auto_user}.")
                else:
                    new_score = await client.redis.incr(f"leaderboard:{auto_user.id}")
                    print(f"🏆 {auto_user} gained 1 point (autosummon). New score={new_score}")
                    log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
                    if log_channel:
                        await log_channel.send(f"🏆 +1 point for {auto_user.mention} (autosummon) — total {new_score}")
            else:
                print("⚠️ Autosummon detected but no claimer found")

    # --- Application des cooldowns ---
    if user and cmd in COOLDOWN_SECONDS:
        user_id = str(user.id)
        key = f"cooldown:{user_id}:{cmd}"
        ttl = await client.redis.ttl(key)
        if ttl > 0:
            await message.channel.send(f"⏳ {user.mention}, you are still on cooldown for `/{cmd}` ({ttl}s left)!")
            return

        cd_time = COOLDOWN_SECONDS[cmd]
        await client.redis.setex(key, cd_time, "1")
        print(f"✅ Cooldown set: {key} TTL={cd_time}")

        log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"📌 Cooldown started for {user.mention} → `/{cmd}` ({cd_time}s)")

        async def cooldown_task():
            await asyncio.sleep(cd_time)
            reminder_key = f"reminder:{user.id}:{cmd}"
            reminder_status = await client.redis.get(reminder_key)
            if reminder_status != "off":
                end_embed = discord.Embed(
                    title="🌞 Cooldown finished!",
                    description=f"{user.mention}, your **/{cmd}** is available again.\n\nLike a sunflower, enjoy this new light 🌻",
                    color=discord.Color.from_rgb(255, 204, 0)
                )
                end_embed.set_footer(text="MoonQuill is watching over you ✨")
                await message.channel.send(embed=end_embed)
            if log_channel:
                await log_channel.send(f"🕒 Cooldown ended for {user.mention} → `/{cmd}`")

        asyncio.create_task(cooldown_task())

# ----------------
# Entry point
# ----------------
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from environment variables.")
client.run(TOKEN)
