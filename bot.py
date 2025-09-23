import discord
from discord import app_commands
import asyncio
import os
import redis.asyncio as aioredis  # async Redis client

TOKEN = os.getenv("DISCORD_TOKEN")
REDIS_URL = os.getenv("REDIS_URL")
MAZOKU_BOT_ID = 1242388858897956906
GUILD_ID = 1196690004852883507

# Cooldown times per command (seconds)
COOLDOWN_SECONDS = {
    "summon": 1800,   # 30 min
    "open-boxes": 60  # 1 min
}

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

class CooldownBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.redis = None

    async def setup_hook(self):
        # connect to Redis
        self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

client = CooldownBot()

# ----------------
# Slash Command
# ----------------
@client.tree.command(name="cooldowns", description="Check your active cooldowns")
async def cooldowns_cmd(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    lines = []

    for cmd in COOLDOWN_SECONDS.keys():
        key = f"cooldown:{user_id}:{cmd}"
        ttl = await client.redis.ttl(key)
        if ttl > 0:
            mins, secs = divmod(ttl, 60)
            lines.append(f"`/{cmd}` → {mins}m {secs}s left")

    if not lines:
        await interaction.response.send_message("✅ You have no active cooldowns!", ephemeral=True)
    else:
        await interaction.response.send_message("⏳ Active cooldowns:\n" + "\n".join(lines), ephemeral=True)

# ----------------
# Events
# ----------------
@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user} ({client.user.id})")

@client.event
async def on_message(message: discord.Message):
    if message.author.id == client.user.id:
        return
    if message.guild and message.guild.id != GUILD_ID:
        return

    # Only listen to Mazoku bot interactions
    if message.author.bot and message.author.id == MAZOKU_BOT_ID:
        cmd = None
        user = None

        if message.interaction_metadata:
            cmd = getattr(message.interaction_metadata, "command_name", None)
            user = getattr(message.interaction_metadata, "user", None)
        elif message.interaction:  # fallback (deprecated)
            cmd = message.interaction.name
            user = message.interaction.user

        if not cmd or cmd not in COOLDOWN_SECONDS or not user:
            return

        user_id = str(user.id)
        key = f"cooldown:{user_id}:{cmd}"
        ttl = await client.redis.ttl(key)

        if ttl > 0:
            await message.channel.send(
                f"⏳ {user.mention}, you are still on cooldown for `/{cmd}` ({ttl}s left)!"
            )
            return

        cd_time = COOLDOWN_SECONDS[cmd]
        await client.redis.setex(key, cd_time, "1")

        await message.channel.send(
            f"⚡ {user.mention}, cooldown started for `/{cmd}`! "
            f"I’ll remind you in {cd_time // 60 if cd_time >= 60 else cd_time} "
            f"{'minutes' if cd_time >= 60 else 'seconds'}."
        )

        async def cooldown_task():
            await asyncio.sleep(cd_time)
            await message.channel.send(
                f"✅ {user.mention}, cooldown for `/{cmd}` is over!"
            )

        asyncio.create_task(cooldown_task())

client.run(TOKEN)
