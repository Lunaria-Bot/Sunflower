import discord
from discord import app_commands
import asyncio
import os
import re
import redis.asyncio as aioredis

TOKEN = os.getenv("DISCORD_TOKEN")
REDIS_URL = os.getenv("REDIS_URL")

# IDs (replace with yours)
MAZOKU_BOT_ID = 1242388858897956906
GUILD_ID = 1196690004852883507
LOG_CHANNEL_ID = 1420095365494866001   # Channel for logs
ROLE_ID_E = 1420099864548868167        # Rôle spécial (ping / autosummon)
ROLE_ID_SUNFLOWER = 1298320344037462177  # Rôle Sunflower
CONTACT_ID = 801879772421423115          # Contact pour rejoindre

# Emojis rares Mazoku (IDs connus)
RARITY_EMOTES = {
    "1342202597389373530": "SR",
    "1342202212948115510": "SSR",
    "1342202203515125801": "UR"
}

# Messages associés
RARITY_MESSAGES = {
    "UR":  "Eh a Ultra Rare Flower just bloomed  grab it !",
    "SSR": "Eh a Super Super Rare Flower just bloomed catch it !",
    "SR":  "Eh a Super Rare Flower just bloomed catch it !"
}

EMOJI_REGEX = re.compile(r"<a?:\w+:(\d+)>")

COOLDOWN_SECONDS = {
    "summon": 1800,
    "open-boxes": 60,
    "open-pack": 60
}

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True

# ----------------
# Utilitaire safe_send
# ----------------
async def safe_send(channel: discord.TextChannel, *args, **kwargs):
    """Envoie un message en gérant les rate limits (429) avec un simple retry."""
    try:
        return await channel.send(*args, **kwargs)
    except discord.HTTPException as e:
        if getattr(e, "status", None) == 429:
            await asyncio.sleep(2)
            try:
                return await channel.send(*args, **kwargs)
            except Exception:
                pass
    except Exception:
        pass

class CooldownBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.redis = None
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        try:
            self.redis = await aioredis.from_url(
                REDIS_URL,
                decode_responses=True
            )
            await self.redis.ping()
            print("✅ Redis connected")
        except Exception as e:
            print(f"❌ Redis connection failed: {e}")
            self.redis = None

        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

client = CooldownBot()

# ----------------
# Slash command /flower
# ----------------
@client.tree.command(name="flower", description="Get the special flower role if you are part of Sunflower")
async def flower(interaction: discord.Interaction):
    guild = interaction.guild
    member = interaction.user
    sunflower_role = guild.get_role(ROLE_ID_SUNFLOWER)
    special_role = guild.get_role(ROLE_ID_E)

    if sunflower_role in member.roles:
        if special_role not in member.roles:
            await member.add_roles(special_role)
            await interaction.response.send_message(
                f"🌻 {member.mention}, you have received the role **{special_role.name}**!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"✅ You already have the role **{special_role.name}**.",
                ephemeral=True
            )
    else:
        await interaction.response.send_message(
            f"❌ You are not part of Sunflower but you can always join us, "
            f"contact <@{CONTACT_ID}> to join us !",
            ephemeral=True
        )

# ----------------
# Events
# ----------------
@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user} ({client.user.id})")
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
        except Exception:
            pass
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

    if getattr(message, "interaction", None):
        cmd = message.interaction.name
        user = message.interaction.user

    elif message.embeds:
        embed = message.embeds[0]
        title = (embed.title or "").lower()
        desc = embed.description or ""

        if "summon claimed" in title:
            cmd = "summon"
            match = re.search(r"Claimed By\s+<@!?(\d+)>", desc)
            if match:
                user = message.guild.get_member(int(match.group(1)))

        elif "pack opened" in title:
            cmd = "open-pack"

        elif "box opened" in title:
            cmd = "open-boxes"

        elif "auto summon" in title:
            found_rarity = None
            text_to_scan = [embed.title or "", embed.description or ""]
            if embed.fields:
                for field in embed.fields:
                    text_to_scan.append(field.name or "")
                    text_to_scan.append(field.value or "")
            if embed.footer and embed.footer.text:
                text_to_scan.append(embed.footer.text)

            for text in text_to_scan:
                matches = EMOJI_REGEX.findall(text)
                for emote_id in matches:
                    if emote_id in RARITY_EMOTES:
                        found_rarity = RARITY_EMOTES[emote_id]
                        break
                if found_rarity:
                    break

            if found_rarity:
                role = message.guild.get_role(ROLE_ID_E)
                if role:
                    msg = RARITY_MESSAGES.get(found_rarity, "A special card just spawned!")
                    embed_msg = discord.Embed(description=msg, color=discord.Color.gold())
                    await safe_send(message.channel, content=f"{role.mention}", embed=embed_msg)

    # ----------------
    # Application des cooldowns
    # ----------------
    if user and cmd in COOLDOWN_SECONDS:
        user_id = str(user.id)
        key = f"cooldown:{user_id}:{cmd}"

        ttl = await client.redis.ttl(key)
        if ttl > 0:
            await safe_send(
                message.channel,
                content=f"{user.mention}",
                embed=discord.Embed(description=f"⏳ You are still on cooldown for `/{cmd}` ({ttl}s left)!")
            )
            return

        cd_time = COOLDOWN_SECONDS[cmd]
        await client.redis.setex(key, cd_time, "1")

        log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await safe_send(
                log_channel,
                f"📌 Cooldown started for {user.mention} → `/{cmd}` ({cd_time}s)"
            )

        async def cooldown_task():
            await asyncio.sleep(cd_time)
            try:
                reminder_key = f"reminder:{user.id}:{cmd}"
                reminder_status = await client.redis.get(reminder_key)

                if reminder_status != "off":
                    end_embed = discord.Embed(
                        title="🌞 Cooldown finished!",
                        description=(
                            f"Your **/{cmd}** is available again.\n\n"
                            "Like a sunflower, enjoy this new light 🌻"
                        ),
                        color=discord.Color.from_rgb(255, 204, 0)
                    )
                    end_embed.set_footer(text="MoonQuill is watching over you ✨")
                    await safe_send(message.channel, content=f"{user.mention}", embed=end_embed)

                if log_channel:
                    await safe_send(
                        log_channel,
                        f"🕒 Cooldown ended for {user.mention} → `/{cmd}` (reminder={'sent' if reminder_status!='off' else 'skipped'})"
                    )
            except Exception:
                pass

        asyncio.create_task(cooldown_task())

# ----------------
# Entry point
# ----------------
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from environment variables.")
client.run(TOKEN)
