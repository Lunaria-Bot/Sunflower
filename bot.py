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
LOG_CHANNEL_ID = 1420095365494866001  # Channel for logs
ROLE_ID_E = 1420099864548868167       # Rôle à ping

# Emojis rares Mazoku (IDs)
RARITY_EMOTES = {
    "1342202597389373530": "SR",   # Super Rare
    "1342202212948115510": "SSR",  # Super Super Rare
    "1342202203515125801": "UR"    # Ultra Rare
}

# Messages associés
RARITY_MESSAGES = {
    "UR":  "Eh a Ultra Rare Flower just bloomed  grab it !",
    "SSR": "Eh a Super Super Rare Flower just bloomed catch it !",
    "SR":  "Eh a Super Rare Flower just bloomed catch it !"
}

# Regex pour extraire les IDs d'émojis (<:name:id> ou <a:name:id>)
EMOJI_REGEX = re.compile(r"<a?:\w+:(\d+)>")

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
# Slash commands
# ----------------
@client.tree.command(name="cooldowns", description="Check your active cooldowns")
async def cooldowns_cmd(interaction: discord.Interaction):
    if not client.redis:
        await interaction.response.send_message("❌ Redis not connected!", ephemeral=True)
        return

    user_id = str(interaction.user.id)

    embed = discord.Embed(
        title="🌻 MoonQuill remind you :",
        description="Here are your remaining cooldowns before you can play again!",
        color=discord.Color.from_rgb(255, 204, 0)
    )
    embed.set_author(
        name=interaction.user.display_name,
        icon_url=interaction.user.display_avatar.url
    )

    found = False

    for cmd in COOLDOWN_SECONDS.keys():
        key = f"cooldown:{user_id}:{cmd}"
        ttl = await client.redis.ttl(key)
        if ttl > 0:
            mins, secs = divmod(ttl, 60)
            embed.add_field(
                name=f"/{cmd}",
                value=f"⏱️ {mins}m {secs}s left",
                inline=False
            )
            found = True

    if not found:
        embed.description = "✅ No active cooldowns, enjoy the sunshine ☀️"
        embed.color = discord.Color.green()

    embed.set_footer(text="Like a sunflower, always turn towards the light 🌞")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.tree.command(name="force-clear", description="Reset a player's cooldowns (ADMIN only)")
@app_commands.describe(member="The member whose cooldowns you want to reset",
                       command="Optional: the command name to reset (e.g. summon, open-boxes, open-pack)")
async def force_clear(interaction: discord.Interaction, member: discord.Member, command: str = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
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
            result = await client.redis.delete(key)
            deleted += result

    await interaction.response.send_message(
        f"✅ Cooldowns reset for {member.mention} ({deleted} removed).",
        ephemeral=True
    )


@client.tree.command(name="toggle-reminder", description="Enable or disable reminders for a specific command")
@app_commands.describe(command="The command to toggle reminders for (summon, open-pack, open-boxes)")
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
    embed.set_footer(text="You can toggle again anytime with /toggle-reminder")
    await interaction.response.send_message(embed=embed, ephemeral=True)

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
        except Exception as e:
            print(f"⚠️ Failed to change presence: {e}")
        i += 1
        await asyncio.sleep(300)  # change every 5 minutes

@client.event
async def on_message(message: discord.Message):
    if not client.redis:
        return
    if message.author.id == client.user.id:
        return
    if message.guild and message.guild.id != GUILD_ID:
        return

    # Only react to messages from the Mazoku bot
    if not (message.author.bot and message.author.id == MAZOKU_BOT_ID):
        return

    user = None
    cmd = None

    # Case 1: direct slash interaction (if available)
    if getattr(message, "interaction", None):
        cmd = message.interaction.name
        user = message.interaction.user
        print(f"🎯 Detected /{cmd} by {user} ({user.id})")

    # Case 2: parse Mazoku embeds
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

            if not user:
                print("⚠️ No user found in Summon Claimed")

        elif "pack opened" in title:
            cmd = "open-pack"

        elif "box opened" in title:
            cmd = "open-boxes"

        elif "auto summon" in title:
            # Détection par ID d'émoji (SR/SSR/UR) dans tout l’embed
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

            # Si une rareté haute est détectée → ping le rôle avec le bon message
            if found_rarity:
                role = message.guild.get_role(ROLE_ID_E)
                if role:
                    msg = RARITY_MESSAGES.get(found_rarity, "A special card just spawned!")
                    await message.channel.send(f"{role.mention} {msg}")

    # ----------------
    # Application des cooldowns
    # ----------------
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
        print(f"✅ Cooldown set: {key} TTL={cd_time}")

        log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(
                f"📌 Cooldown started for {user.mention} → `/{cmd}` ({cd_time}s)"
            )

        async def cooldown_task():
            await asyncio.sleep(cd_time)
            try:
                print(f"⏰ Cooldown finished for {user} → /{cmd}")  # Debug

                # Check reminder preference
                reminder_key = f"reminder:{user.id}:{cmd}"
                reminder_status = await client.redis.get(reminder_key)

                if reminder_status != "off":
                    end_embed = discord.Embed(
                        title="🌞 Cooldown finished!",
                        description=(
                            f"{user.mention}, your **/{cmd}** is available again.\n\n"
                            "Like a sunflower, enjoy this new light 🌻"
                        ),
                        color=discord.Color.from_rgb(255, 204, 0)
                    )
                    end_embed.set_footer(text="MoonQuill is watching over you ✨")
                    await message.channel.send(embed=end_embed)

                # Log end (always)
                if log_channel:
                    await log_channel.send(
                        f"🕒 Cooldown ended for {user.mention} → `/{cmd}` (reminder={'sent' if reminder_status!='off' else 'skipped'})"
                    )
            except Exception as e:
                print(f"⚠️ Cooldown end notification failed: {e}")

        asyncio.create_task(cooldown_task())

# ----------------
# Entry point
# ----------------
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from environment variables.")
client.run(TOKEN)
