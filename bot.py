import discord
from discord import app_commands
import asyncio
import os
import re
import redis.asyncio as aioredis

TOKEN = os.getenv("DISCORD_TOKEN")
REDIS_URL = os.getenv("REDIS_URL")
MAZOKU_BOT_ID = 1242388858897956906
GUILD_ID = 1196690004852883507
LOG_CHANNEL_ID = 1420095365494866001  # Salon où envoyer les logs

# Cooldown times per command (seconds)
COOLDOWN_SECONDS = {
    "summon": 1800,      # 30 min
    "open-boxes": 60,    # 1 min
    "open-pack": 60      # 1 min
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

@client.tree.command(name="force-clear", description="Réinitialise les cooldowns d'un joueur (ADMIN uniquement)")
@app_commands.describe(member="Le membre dont vous voulez réinitialiser les cooldowns",
                       command="Optionnel: le nom de la commande à réinitialiser (ex: summon, open-boxes, open-pack)")
async def force_clear(interaction: discord.Interaction, member: discord.Member, command: str = None):
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
        return

    if message.author.bot and message.author.id == MAZOKU_BOT_ID and message.embeds:
        embed = message.embeds[0]

        print("=== DEBUG EMBED ===")
        print(f"Title: {embed.title}")
        print(f"Description: {embed.description}")
        print("===================")

        # Detect command
        command = None
        user = None
        if embed.title:
            title = embed.title.lower()

            if title == "summon":
                command = "summon"
                # Essaye via interaction
                if hasattr(message, "interaction") and message.interaction and message.interaction.user:
                    user = message.interaction.user
                # Sinon, parse "X used summon"
                if not user and embed.description:
                    match = re.search(r"(.+?) used summon", embed.description)
                    if match:
                        pseudo = match.group(1).strip()
                        for member in message.guild.members:
                            if member.display_name == pseudo or member.name == pseudo:
                                user = member
                                break

            elif "summon claimed" in title:
                command = "summon"
                # Cherche "Claimed By" dans description
                if embed.description:
                    match = re.search(r"Claimed By\s+<@!?(\d+)>", embed.description)
                    if match:
                        uid = int(match.group(1))
                        user = message.guild.get_member(uid)
                # Cherche aussi dans les fields
                if not user and embed.fields:
                    for field in embed.fields:
                        match = re.search(r"Claimed By\s+<@!?(\d+)>", field.value)
                        if match:
                            uid = int(match.group(1))
                            user = message.guild.get_member(uid)
                            break
                # Cherche dans le footer
                if not user and embed.footer and embed.footer.text:
                    match = re.search(r"Claimed By\s+<@!?(\d+)>", embed.footer.text)
                    if match:
                        uid = int(match.group(1))
                        user = message.guild.get_member(uid)

                if not user:
                    print("⚠️ Aucun utilisateur trouvé dans Summon Claimed")

            elif "pack opened" in title:
                command = "open-pack"
            elif "box opened" in title:
                command = "open-boxes"

            if "auto summon" in title:
                command = None

        if not command or command not in COOLDOWN_SECONDS:
            return

        # Fallback mentions
        if not user and message.mentions:
            user = message.mentions[0]

        if not user:
            print("⚠️ Aucun utilisateur détecté dans cet embed")
            return

        user_id = str(user.id)
        key = f"cooldown:{user_id}:{command}"

        ttl = await client.redis.ttl(key)
        if ttl > 0:
            await message.channel.send(
                f"⏳ {user.mention}, you are still on cooldown for `/{command}` ({ttl}s left)!"
            )
            return

        cd_time = COOLDOWN_SECONDS[command]
        await client.redis.setex(key, cd_time, "1")
        print(f"✅ Cooldown posé: {key} TTL={cd_time}")

        # Log début
        log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(
                f"📌 Cooldown démarré pour {user.mention} → `/{command}` ({cd_time}s)"
            )

        async def cooldown_task():
            await asyncio.sleep(cd_time)
            try:
                # Message public
                await message.channel.send(
                    f"✅ {user.mention}, cooldown for `/{command}` is over!"
                )
                # Log fin
                if log_channel:
                    await log_channel.send(
                        f"🕒 Fin du cooldown pour {user.mention} → `/{command}`"
                    )
            except Exception as e:
                print(f"⚠️ Notification fin de cooldown échouée: {e}")

        asyncio.create_task(cooldown_task())

# ----------------
# Entrée du programme
# ----------------
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant dans les variables d'environnement.")
client.run(TOKEN)
