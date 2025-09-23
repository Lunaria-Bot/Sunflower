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

        # Sync slash commands to your guild
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

client = CooldownBot()

# ----------------
# Slash Commands
# ----------------
@client.tree.command(name="cooldowns", description="Check your active cooldowns")
async def cooldowns_cmd(interaction: discord.Interaction):
    if not client.redis:
        await interaction.response.send_message("❌ Redis not connected!", ephemeral=True)
        return

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

# Commande de test Redis
@client.tree.command(name="test-redis", description="Test Redis setex and ttl")
async def test_redis(interaction: discord.Interaction):
    if not client.redis:
        await interaction.response.send_message("❌ Redis not connected!", ephemeral=True)
        return

    key = f"test:{interaction.user.id}"
    await client.redis.setex(key, 10, "test")
    ttl = await client.redis.ttl(key)
    await interaction.response.send_message(f"Redis TTL for test key: {ttl}s", ephemeral=True)

# ----------------
# Events
# ----------------
@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user} ({client.user.id})")

@client.event
async def on_message(message: discord.Message):
    if not client.redis:
        return

    if message.author.id == client.user.id:
        return
    if message.guild and message.guild.id != GUILD_ID:
        return  # only work in your server

    # Debug logs
    print(f"📩 Message reçu de {message.author} ({message.author.id})")
    if message.embeds:
        print(f"➡️ Embed détecté: {message.embeds[0].title}")
    else:
        print("⚠️ Pas d'embed dans ce message")
        return

    # Only listen to Mazoku bot
    if message.author.bot and message.author.id == MAZOKU_BOT_ID:
        embed = message.embeds[0]
        command = None

        # Detect command based on embed title
        if embed.title and "Summon" in embed.title:
            command = "summon"
        elif embed.title and "Card" in embed.title:
            command = "open-boxes"

        if not command or command not in COOLDOWN_SECONDS:
            print("⚠️ Aucun cooldown associé à cet embed")
            return

        # Detect mentioned user
        user = message.mentions[0] if message.mentions else None

        # Si pas de mention, tenter de récupérer depuis description
        if not user and embed.description:
            # Exemple: "Player <@123456789> did something"
            import re
            match = re.search(r"<@!?(\d+)>", embed.description)
            if match:
                user_id = int(match.group(1))
                user = message.guild.get_member(user_id)

        if not user:
            print("⚠️ Aucun utilisateur détecté dans ce message")
            return

        user_id = str(user.id)
        key = f"cooldown:{user_id}:{command}"

        # Check existing cooldown
        ttl = await client.redis.ttl(key)
        if ttl > 0:
            await message.channel.send(
                f"⏳ {user.mention}, you are still on cooldown for `/{command}` ({ttl}s left)!"
            )
            return

        # Start cooldown silently
        cd_time = COOLDOWN_SECONDS[command]
        await client.redis.setex(key, cd_time, "1")
        ttl_after = await client.redis.ttl(key)
        print(f"✅ Cooldown posé: {key} TTL={ttl_after}")

        async def cooldown_task():
            await asyncio.sleep(cd_time)
            await message.channel.send(
                f"✅ {user.mention}, cooldown for `/{command}` is over!"
            )

        asyncio.create_task(cooldown_task())

client.run(TOKEN)
