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
        synced = await self.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}")

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
    embed = discord.Embed(
        title="🌻 MoonQuill remind you :",
        description="Here are your remaining cooldowns before you can play again!",
        color=discord.Color.from_rgb(255, 204, 0)
    )
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)

    found = False
    for cmd in COOLDOWN_SECONDS.keys():
        key = f"cooldown:{user_id}:{cmd}"
        ttl = await client.redis.ttl(key)
        if ttl > 0:
            mins, secs = divmod(ttl, 60)
            embed.add_field(name=f"/{cmd}", value=f"⏱️ {mins}m {secs}s left", inline=False)
            found = True

    if not found:
        embed.description = "✅ No active cooldowns, enjoy the sunshine ☀️"
        embed.color = discord.Color.green()

    embed.set_footer(text="Like a sunflower, always turn towards the light 🌞")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.tree.command(name="force-clear", description="Reset a player's cooldowns (ADMIN only)")
@app_commands.describe(member="The member whose cooldowns you want to reset",
                       command="Optional: the command name to reset (summon, open-boxes)")
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
            deleted += await client.redis.delete(key)

    await interaction.response.send_message(f"✅ Cooldowns reset for {member.mention} ({deleted} removed).", ephemeral=True)


@client.tree.command(name="toggle-reminder", description="Enable or disable reminders for a specific command")
@app_commands.describe(command="The command to toggle reminders for (summon, open-boxes)")
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


@client.tree.command(name="leaderboard", description="Show the autosummon leaderboard")
async def leaderboard(interaction: discord.Interaction):
    if not client.redis:
        await interaction.response.send_message("❌ Redis not connected!", ephemeral=True)
        return

    keys = await client.redis.keys("leaderboard:*")
    scores = []
    for key in keys:
        if key.endswith(":paused"):
            continue
        parts = key.split(":")
        if len(parts) != 2:
            continue
        user_id = parts[1]
        score_val = await client.redis.get(key)
        if score_val:
            scores.append((user_id, int(score_val)))

    scores.sort(key=lambda x: x[1], reverse=True)
    top = scores[:10]
    embed = discord.Embed(title="🏆 Autosummon Leaderboard", color=discord.Color.gold())

    if not top:
        embed.description = "Aucun point pour l’instant 🌻"
    else:
        lines = []
        for i, (uid, score) in enumerate(top, start=1):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
            lines.append(f"**{i}. {name}** — {score} pts")
        embed.description = "\n".join(lines)

    await interaction.response.send_message(embed=embed)


@client.tree.command(name="leaderboard_reset", description="Reset the leaderboard (ADMIN only)")
async def leaderboard_reset(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return

    keys = await client.redis.keys("leaderboard:*")
    deleted = 0
    for key in keys:
        deleted += await client.redis.delete(key)

    await interaction.response.send_message(f"✅ Leaderboard reset ({deleted} entries removed).", ephemeral=True)


@client.tree.command(name="leaderboard_pause", description="Pause or resume the leaderboard scoring (ADMIN only)")
async def leaderboard_pause(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return

    paused = await client.redis.get("leaderboard:paused")
    if paused == "true":
        await client.redis.set("leaderboard:paused", "false")
        status = "▶️ Leaderboard resumed"
    else:
        await client.redis.set("leaderboard:paused", "true")
        status = "⏸️ Leaderboard paused"

    await interaction.response.send_message(status, ephemeral=True)

# ----------------
# Events
# ----------------
@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user} ({client.user.id})")
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

    # Only react to messages from the Mazoku bot
    if not (message.author.bot and message.author.id == MAZOKU_BOT_ID):
        return

    user = None
    cmd = None

    # Parse embeds from Mazoku
    if message.embeds:
        embed = message.embeds[0]
        title = (embed.title or "").lower()
        desc = embed.description or ""

        # Summon claimed (cooldown)
        if "summon claimed" in title:
            cmd = "summon"
            match = re.search(r"Claimed By\s+<@!?(\d+)>", desc, flags=re.IGNORECASE)
            if match:
                user = message.guild.get_member(int(match.group(1)))

            if not user and embed.fields:
                for field in embed.fields:
                    match = re.search(r"Claimed By\s+<@!?(\d+)>", field.value, flags=re.IGNORECASE)
                    if match:
                        user = message.guild.get_member(int(match.group(1)))
                        break

            if not user and embed.footer and embed.footer.text:
                match = re.search(r"Claimed By\s+<@!?(\d+)>", embed.footer.text, flags=re.IGNORECASE)
                if match:
                    user = message.guild.get_member(int(match.group(1)))

        # Boxes opened (cooldown)
        elif "box opened" in title:
            cmd = "open-boxes"

        # Autosummon (leaderboard scoring only)
        if "auto summon" in title:
            print("🔎 Autosummon detected, trying to identify claimer...")

            def resolve_member_by_name(name: str) -> discord.Member | None:
                if not name:
                    return None
                name = name.strip()
                # Exact display name
                for m in message.guild.members:
                    if m.display_name == name:
                        return m
                # Exact username
                for m in message.guild.members:
                    if m.name == name:
                        return m
                # Case-insensitive username
                name_lower = name.lower()
                for m in message.guild.members:
                    if m.name.lower() == name_lower:
                        return m
                return None

            auto_user = None

            # Try mention pattern in description
            m = re.search(r"Claimed By\s+<@!?(\d+)>", desc, flags=re.IGNORECASE)
            if m:
                auto_user = message.guild.get_member(int(m.group(1)))

            # Try plain text "Claimed By <name>" in description
            if not auto_user:
                m = re.search(r"Claimed By\s+([^\n<]+)", desc, flags=re.IGNORECASE)
                if m:
                    auto_user = resolve_member_by_name(m.group(1))

            # Try fields
            if not auto_user and embed.fields:
                for field in embed.fields:
                    m_id = re.search(r"Claimed By\s+<@!?(\d+)>", field.value, flags=re.IGNORECASE)
                    if m_id:
                        auto_user = message.guild.get_member(int(m_id.group(1)))
                        break
                    m_txt = re.search(r"Claimed By\s+([^\n<]+)", field.value, flags=re.IGNORECASE)
                    if m_txt:
                        auto_user = resolve_member_by_name(m_txt.group(1))
                        if auto_user:
                            break

            # Try footer
            if not auto_user and embed.footer and embed.footer.text:
                m_id = re.search(r"Claimed By\s+<@!?(\d+)>", embed.footer.text, flags=re.IGNORECASE)
                if m_id:
                    auto_user = message.guild.get_member(int(m_id.group(1)))
                else:
                    m_txt = re.search(r"Claimed By\s+([^\n<]+)", embed.footer.text, flags=re.IGNORECASE)
                    if m_txt:
                        auto_user = resolve_member_by_name(m_txt.group(1))

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
                print("⚠️ Autosummon detected but no claimer found (no mention and name resolution failed)")

    # Apply cooldowns for summon/open-boxes
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
            try:
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
            except Exception as e:
                print(f"⚠️ Cooldown end notification failed: {e}")

        asyncio.create_task(cooldown_task())

# ----------------
# Entry point
# ----------------
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from environment variables.")
client.run(TOKEN)
