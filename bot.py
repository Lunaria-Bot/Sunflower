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
LOG_CHANNEL_ID = 1420095365494866001   # Channel for logs
ROLE_ID_E = 1420099864548868167        # Special role (ping / autosummon)
ROLE_ID_SUNFLOWER = 1298320344037462177
CONTACT_ID = 801879772421423115

# Rare emojis
RARITY_EMOTES = {
    "1342202597389373530": "SR",
    "1342202212948115510": "SSR",
    "1342202203515125801": "UR"
}

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
        title="🌻 MoonQuill reminds you:",
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
        embed.description = "✅ No active cooldowns, enjoy the sunshine ☀️"
        embed.color = discord.Color.green()

    embed.set_footer(text="Like a sunflower, always turn towards the light 🌞")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.tree.command(name="force-clear", description="Reset a player's cooldowns (ADMIN only)")
@app_commands.describe(member="The member whose cooldowns you want to reset",
                       command="Optional: the command name to reset")
async def force_clear(interaction: discord.Interaction, member: discord.Member, command: str = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You must be an administrator.", ephemeral=True)
        return

    if not client.redis:
        await interaction.response.send_message("❌ Redis not connected.", ephemeral=True)
        return

    user_id = str(member.id)
    deleted = 0
    if command:
        if command not in COOLDOWN_SECONDS:
            await interaction.response.send_message(f"⚠️ Unknown command: `{command}`", ephemeral=True)
            return
        key = f"cooldown:{user_id}:{command}"
        deleted = await client.redis.delete(key)
    else:
        for cmd in COOLDOWN_SECONDS.keys():
            key = f"cooldown:{user_id}:{cmd}"
            deleted += await client.redis.delete(key)

    await interaction.response.send_message(
        f"✅ Cooldowns reset for {member.mention} ({deleted} removed).",
        ephemeral=True
    )


@client.tree.command(name="toggle-reminder", description="Enable or disable reminders for a specific command")
@app_commands.describe(command="The command to toggle reminders for")
async def toggle_reminder(interaction: discord.Interaction, command: str):
    if not client.redis:
        await interaction.response.send_message("❌ Redis not connected!", ephemeral=True)
        return
    if command not in COOLDOWN_SECONDS:
        await interaction.response.send_message(f"⚠️ Unknown command: `{command}`", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    key = f"reminder:{user_id}:{command}"
    current = await client.redis.get(key)
    if current == "off":
        await client.redis.set(key, "on")
        status = "✅ Reminders enabled"
    else:
        await client.redis.set(key, "off")
        status = "❌ Reminders disabled"

    embed = discord.Embed(
        title="🔔 Reminder preference updated",
        description=f"For **/{command}**: {status}",
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
# New Daily Reminder Command
# ----------------
@client.tree.command(name="togglereminder-daily", description="Toggle your daily Mazoku reminder")
async def toggle_reminder_daily(interaction: discord.Interaction):
    if not client.redis:
        await interaction.response.send_message("❌ Redis not connected!", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    key = f"dailyreminder:{user_id}"
    current = await client.redis.get(key)

    # Default is off if no key
    if current == "on":
        await client.redis.set(key, "off")
        status = "❌ Daily reminder disabled"
    else:
        await client.redis.set(key, "on")
        status = "✅ Daily reminder enabled"

    embed = discord.Embed(
        title="🔔 Daily Reminder Preference Updated",
        description=status,
        color=discord.Color.from_rgb(255, 204, 0)
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ----------------
# Events
# ----------------
@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user} ({client.user.id})")
    client.loop.create_task(rotate_status())
    client.loop.create_task(daily_reminder_task())  # seule la vraie tâche quotidienne

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

# Daily reminder task at the fixed <t:1758844801:T> time every day
async def daily_reminder_task():
    await client.wait_until_ready()
    target_time = datetime.datetime.utcfromtimestamp(1758844801).time()  # fixed daily time (UTC)

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

        # Send reminders to all opted-in users (stored in Redis)
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

                # Send DM
                try:
                    await user.send("🌻 Your Mazoku daily is ready!")
                except Exception:
                    continue

                # Styled log embed in the log channel
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

    # ✅ Utiliser interaction_metadata au lieu de interaction
    if getattr(message, "interaction_metadata", None):
        cmd = message.interaction_metadata.name
        user = message.author

    # Sinon, on parse les embeds Mazoku
    elif message.embeds:
        embed = message.embeds[0]
        title = (embed.title or "").lower()
        desc = embed.description or ""

        if "summon claimed" in title:
            cmd = "summon"
            match = re.search(r"Claimed By\s+<@!?(\d+)>", desc)
            if match:
                user = message.guild.get_member(int(match.group(1)))
            if not user and embed.fields:
                for field in embed.fields:
                    match = re.search(r"Claimed By\s+<@!?(\d+)>", field.value)
                    if match:
                        user = message.guild.get_member(int(match.group(1)))
                        break
            if not user and embed.footer and embed.footer.text:
                match = re.search(r"Claimed By\s+<@!?(\d+)>", embed.footer.text)
                if match:
                    user = message.guild.get_member(int(match.group(1)))

        elif "pack opened" in title:
            cmd = "open-pack"

        elif "box opened" in title:
            cmd = "open-boxes"

        elif "vote mazoku" in title:
            cmd = "vote"
            user = message.author

        elif "auto summon" in title:
            # Détection de rareté
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
    # Apply cooldowns
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
                embed=discord.Embed(
                    title="📌 Cooldown started",
                    description=f"For {user.mention} → `/{cmd}` ({cd_time}s)",
                    color=discord.Color.blue(),
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
            )

        async def cooldown_task():
            await asyncio.sleep(cd_time)
            try:
                reminder_key = f"reminder:{user.id}:{cmd}"
                reminder_status = await client.redis.get(reminder_key)

                if reminder_status != "off":
                    if cmd == "vote":
                        end_embed = discord.Embed(
                            title="🗳️ Vote reminder!",
                            description=(
                                f"Your **/{cmd}** cooldown is over.\n\n"
                                f"{ELAINA_YAY} You can support Mazoku again on top.gg!"
                            ),
                            color=discord.Color.from_rgb(255, 204, 0)
                        )
                    else:
                        end_embed = discord.Embed(
                            title="🌞 Cooldown finished!",
                            description=(
                                f"Your **/{cmd}** is available again.\n\n"
                                f"{ELAINA_YAY} Enjoy this new light\n"
                                "✨ MoonQuill is watching over you"
                            ),
                            color=discord.Color.from_rgb(255, 204, 0)
                        )
                        end_embed.set_footer(text="MoonQuill is watching over you ✨")

                    await safe_send(message.channel, content=f"{user.mention}", embed=end_embed)

                    # ✅ Log dans le channel de log
                    if log_channel:
                        log_embed = discord.Embed(
                            title="📩 Reminder sent",
                            description=f"Reminder for `{cmd}` sent to {user.mention} (ID: `{user.id}`)",
                            color=discord.Color.green(),
                            timestamp=datetime.datetime.now(datetime.timezone.utc)
                        )
                        await safe_send(log_channel, embed=log_embed)

            except Exception:
                pass

        asyncio.create_task(cooldown_task())


# ----------------
# Entry point
# ----------------
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from environment variables.")
client.run(TOKEN)

