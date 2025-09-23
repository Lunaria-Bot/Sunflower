import discord
from discord import app_commands
import asyncio
import os
import re
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
intents.members = True  # nécessaire pour recherche par pseudo

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

# Commande admin pour reset cooldowns
@client.tree.command(name="force-clear", description="Réinitialise les cooldowns d'un joueur (ADMIN uniquement)")
@app_commands.describe(member="Le membre dont vous voulez réinitialiser les cooldowns",
                       command="Optionnel: le nom de la commande à réinitialiser (ex: summon, open-boxes)")
async def force_clear(interaction: discord.Interaction, member: discord.Member, command: str = None):
    # Vérifie si l'utilisateur est admin
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Vous devez être administrateur pour utiliser cette commande.", ephemeral=True)
        return

    if not client.redis:
        await interaction.response.send_message("❌ Redis non connecté.", ephemeral=True)
        return

    user_id = str(member.id)
    deleted = 0

    if command:
        if command not in COOLDOWN_SECONDS:
            await interaction.response.send_message(f"⚠️ Commande inconnue: `{command}`", ephemeral=True)
            return
        key = f"cooldown:{user_id}:{command}"
        deleted = await client.redis.delete(key)
    else:
        # Supprime toutes les clés de cooldown pour ce joueur
        for cmd in COOLDOWN_SECONDS.keys():
            key = f"cooldown:{user_id}:{cmd}"
            result = await client.redis.delete(key)
            deleted += result

    await interaction.response.send_message(
        f"✅ Cooldowns réinitialisés pour {member.mention} ({deleted} supprimés).",
        ephemeral=True
    )

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

    # Only listen to Mazoku bot
    if message.author.bot and message.author.id == MAZOKU_BOT_ID and message.embeds:
        embed = message.embeds[0]

        # Debug full embed
        print("=== DEBUG EMBED ===")
        print(f"Title: {embed.title}")
        print(f"Description: {embed.description}")
        print(f"Footer: {embed.footer.text if embed.footer else None}")
        for i, field in enumerate(embed.fields):
            print(f"Field {i}: name={field.name}, value={field.value}")
        print("===================")

        # Detect command
        command = None
        if embed.title and "Summon" in embed.title:
            command = "summon"
        elif embed.title and "Card" in embed.title:
            command = "open-boxes"

        if not command or command not in COOLDOWN_SECONDS:
            print("⚠️ Aucun cooldown associé à cet embed")
            return

        # Try to detect user
        user = None

        # 1. Mentions directes
        if message.mentions:
            user = message.mentions[0]
            print(f"👤 Utilisateur trouvé via mention: {user}")

        # 2. Regex dans description
        if not user and embed.description:
            match = re.search(r"<@!?(\d+)>", embed.description)
            if match:
                uid = int(match.group(1))
                user = message.guild.get_member(uid)
                print(f"👤 Utilisateur trouvé via description (ID): {uid}")
            else:
                # fallback pseudo si pas d'ID
                pseudo_match = re.search(r"(Claimed By|Summoned By)\s+@?([^\n]+)", embed.description)
                if pseudo_match:
                    pseudo = pseudo_match.group(2).strip()
                    pseudo = pseudo.replace("**", "").replace("*", "")
                    for member in message.guild.members:
                        if member.display_name == pseudo or member.name == pseudo:
                            user = member
                            print(f"👤 Utilisateur trouvé via pseudo: {pseudo}")
                            break

        # 3. Regex dans footer
        if not user and embed.footer and embed.footer.text:
            match = re.search(r"<@!?(\d+)>", embed.footer.text)
            if match:
                uid = int(match.group(1))
                user = message.guild.get_member(uid)
                print(f"👤 Utilisateur trouvé via footer: {uid}")

        # 4. Regex dans fields
        if not user and embed.fields:
            for field in embed.fields:
                match = re.search(r"<@!?(\d+)>", field.value)
                if match:
                    uid = int(match.group(1))
                    user = message.guild.get_member(uid)
                    print(f"👤 Utilisateur trouvé via field: {uid}")
                    break

        if not user:
            print("⚠️ Aucun utilisateur détecté dans cet embed")
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

        # Start cooldown
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
