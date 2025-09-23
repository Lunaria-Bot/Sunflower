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
    # Debug minimal pour savoir si on reçoit des messages
    # print(f"[DEBUG] Message reçu de {message.author} (ID={message.author.id})")

    if not client.redis:
        return
    if message.author.id == client.user.id:
        return
    if message.guild and message.guild.id != GUILD_ID:
        return

    # Only listen to Mazoku bot
    if message.author.bot and message.author.id == MAZOKU_BOT_ID:
        user = None
        cmd = None

        # --- Cas 1 : via interaction (slash command directe) ---
        if getattr(message, "interaction", None):
            cmd = message.interaction.name
            user = message.interaction.user
            print(f"🎯 Detected /{cmd} by {user} ({user.id})")

        # --- Cas 2 : fallback via embed ---
        elif message.embeds:
            embed = message.embeds[0]
            title = embed.title.lower() if embed.title else ""
            desc = embed.description or ""

            # Summon Claimed -> associer au /summon
            if "summon claimed" in title:
                cmd = "summon"

                # Cherche "Claimed By" dans description
                match = re.search(r"Claimed By\s+<@!?(\d+)>", desc)
                if match:
                    user = message.guild.get_member(int(match.group(1)))

                # Cherche aussi dans les fields
                if not user and embed.fields:
                    for field in embed.fields:
                        match = re.search(r"Claimed By\s+<@!?(\d+)>", field.value)
                        if match:
                            user = message.guild.get_member(int(match.group(1)))
                            break

                # Cherche dans le footer
                if not user and embed.footer and embed.footer.text:
                    match = re.search(r"Claimed By\s+<@!?(\d+)>", embed.footer.text)
                    if match:
                        user = message.guild.get_member(int(match.group(1)))

                if not user:
                    # Dernier recours: si le format est "Claimed by **Pseudo**" sans mention,
                    # on tente de matcher le pseudo et de le retrouver dans la guild.
                    match = re.search(r"Claimed by\s+\*{0,2}([^*\n]+)\*{0,2}", desc, flags=re.IGNORECASE)
                    if not match and embed.fields:
                        for field in embed.fields:
                            match = re.search(r"Claimed by\s+\*{0,2}([^*\n]+)\*{0,2}", field.value, flags=re.IGNORECASE)
                            if match:
                                break
                    if not match and embed.footer and embed.footer.text:
                        match = re.search(r"Claimed by\s+\*{0,2}([^*\n]+)\*{0,2}", embed.footer.text, flags=re.IGNORECASE)

                    if match:
                        pseudo = match.group(1).strip()
                        for member in message.guild.members:
                            if member.display_name == pseudo or member.name == pseudo:
                                user = member
                                break

                    if not user:
                        print("⚠️ Aucun utilisateur trouvé dans Summon Claimed")

            elif "pack opened" in title:
                cmd = "open-pack"
            elif "box opened" in title:
                cmd = "open-boxes"
            elif "auto summon" in title:
                cmd = None

        # --- Application du cooldown ---
        if user and cmd in COOLDOWN_SECONDS:
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
            print(f"✅ Cooldown posé: {key} TTL={cd_time}")

            # Log début
            log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(
                    f"📌 Cooldown démarré pour {user.mention} → `/{cmd}` ({cd_time}s)"
                )

            async def cooldown_task():
                await asyncio.sleep(cd_time)
                try:
                    # Message public
                    await message.channel.send(
                        f"✅ {user.mention}, cooldown for `/{cmd}` is over!"
                    )
                    # Log fin
                    if log_channel:
                        await log_channel.send(
                            f"🕒 Fin du cooldown pour {user.mention} → `/{cmd}`"
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
