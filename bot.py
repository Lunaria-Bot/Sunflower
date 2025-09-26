import warnings

# Ignore spammy DeprecationWarnings from discord.py
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=".*interaction is deprecated, use interaction_metadata instead.*"
)

import discord
from discord import app_commands
import asyncio
import os
import re
import redis.asyncio as aioredis
import datetime

TOKEN = os.getenv("DISCORD_TOKEN")
REDIS_URL = os.getenv("REDIS_URL")

# IDs
MAZOKU_BOT_ID = 1242388858897956906
GUILD_ID = 1196690004852883507
LOG_CHANNEL_ID = 1420095365494866001
ROLE_ID_E = 1420099864548868167
ROLE_ID_SUNFLOWER = 1298320344037462177
CONTACT_ID = 801879772421423115

# Emoji customisé
ELAINA_YAY = "<:ElainaYay:1336678776771186753>"

# Rare emojis
RARITY_EMOTES = {
    "1342202597389373530": "SR",
    "1342202212948115510": "SSR",
    "1342202203515125801": "UR"
}

RARITY_MESSAGES = {
    "UR":  f"{ELAINA_YAY} A Ultra Rare Flower just bloomed, grab it!",
    "SSR": f"{ELAINA_YAY} A Super Super Rare Flower just bloomed, catch it!",
    "SR":  f"{ELAINA_YAY} A Super Rare Flower just bloomed, catch it!"
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
# Utility safe_send
# ----------------
async def safe_send(channel: discord.TextChannel, *args, **kwargs):
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
# Slash commands
# ----------------
@client.tree.command(name="cooldowns", description="Check your active cooldowns")
async def cooldowns_cmd(interaction: discord.Interaction):
    if not client.redis:
        await interaction.response.send_message("❌ Redis not connected!", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    embed = discord.Embed(
        title=f"{ELAINA_YAY} MoonQuill reminds you:",
        description="Here are your remaining cooldowns before you can play again!",
        color=discord.Color.from_rgb(255, 204, 0)
    )
    embed.set_author(name=interaction.user.display_name,
                     icon_url=interaction.user.display_avatar.url)

    found = False
    for cmd in COOLDOWN_SECONDS.keys():
        key = f"cooldown:{user_id}:{cmd}"
        ttl = await client.redis.ttl(key)
        if ttl > 0:
            mins, secs = divmod(ttl, 60)
            embed.add_field(name=f"/{cmd}",
                            value=f"⏱️ {mins}m {secs}s left",
                            inline=False)
            found = True

    if not found:
        embed.description = f"✅ No active cooldowns, enjoy the sunshine {ELAINA_YAY}"
        embed.color = discord.Color.green()

    embed.set_footer(text=f"Like {ELAINA_YAY}, always turn towards the light 🌞")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.tree.command(name="togglereminder-daily", description="Toggle your daily Mazoku reminder")
async def toggle_reminder_daily(interaction: discord.Interaction):
    if not client.redis:
        await interaction.response.send_message("❌ Redis not connected!", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    key = f"dailyreminder:{user_id}"
    current = await client.redis.get(key)

    if current == "on":
        await client.redis.set(key, "off")
        status = "❌ Daily reminder disabled"
    else:
        await client.redis.set(key, "on")
        status = f"✅ Daily reminder enabled {ELAINA_YAY}"

    embed = discord.Embed(
        title="🔔 Daily Reminder Preference Updated",
        description=status,
        color=discord.Color.from_rgb(255, 204, 0)
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


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
                f"{ELAINA_YAY} {member.mention}, you have received the role **{special_role.name}**!",
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
    client.loop.create_task(daily_reminder_task())

async def rotate_status():
    activities = [
        discord.Game("MoonQuill is sleeping 😴"),
        discord.Activity(type=discord.ActivityType.watching, name=f"the sunflowers {ELAINA_YAY}"),
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

# Daily reminder task
async def daily_reminder_task():
    await client.wait_until_ready()
    target_time = datetime.datetime.utcfromtimestamp(1758844801).time()

    while not client.is_closed():
        now = datetime.datetime.now(datetime.timezone.utc)
        today_target = now.replace(
            hour=target_time.hour,
            minute=target_time.minute,
            second=target_time.second,
            microsecond=0
        )
        if now >= today_target:
            today_target += datetime.timedelta(days=1)

        wait_seconds = (today_target - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        try:
            keys = await client.redis.keys("dailyreminder:*")
        except Exception:
            keys = []

        for key in keys:
            try:
                val = await client.redis.get(key)
                if val != "on":
                    continue

                user_id = int(key.split(":")[1])
                user = client.get_user(user_id)
                if not user:
                    continue

                try:
                    await user.send(f"{ELAINA_YAY} Your Mazoku daily is ready!")
                except Exception:
                    continue

                log_channel = client.get_channel(LOG_CHANNEL_ID)
                if log_channel:
                    embed = discord.Embed(
                        title="📩 Daily reminder sent",
                        description=f"Sent to {user.mention} (ID: `{user.id}`)",
                        color=discord.Color.from_rgb(255, 204, 0),
                        timestamp=datetime.datetime.now(datetime.timezone.utc)
                    )
                    embed.set_footer(text="MoonQuill daily scheduler")
                    await safe_send(log_channel, embed=embed)
            except Exception:
                continue

# ----------------
# Entry point
# ----------------
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from environment variables.")
client.run(TOKEN)
``
