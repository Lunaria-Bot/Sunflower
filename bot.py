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
LOG_CHANNEL_ID = 1420095365494866001  # Channel for logs

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

    # Sunflower-themed embed
    embed = discord.Embed(
        title="🌻 MoonQuill remind you :",
        description="Here are your remaining cooldowns before you can play again!",
        color=discord.Color.from_rgb(255, 204, 0)  # sunflower yellow
    )
    embed.set_author(
        name=interaction.user.display_name,
        icon_url=interaction.user.display_avatar.url
    )

    found = False

    # Summon
    key = f"cooldown:{user_id}:summon"
    ttl = await client.redis.ttl(key)
    if ttl > 0:
        mins, secs = divmod(ttl, 60)
        embed.add_field(
            name="✨ Summon",
            value=f"⏱️ {mins}m {secs}s left",
            inline=False
        )
        found = True

    # Premium Packs
    key = f"cooldown:{user_id}:open-pack"
    ttl = await client.redis.ttl(key)
    if ttl > 0:
        mins, secs = divmod(ttl, 60)
        embed.add_field(
            name="🎁 Premium Packs",
            value=f"⏱️ {mins}m {secs}s left",
            inline=False
        )
        found = True

    # Boxes
    key = f"cooldown:{user_id}:open-boxes"
    ttl = await client.redis.ttl(key)
    if ttl > 0:
        mins, secs = divmod(ttl, 60)
        embed.add_field(
            name="📦 Boxes",
            value=f"⏱️ {mins}m {secs}s left",
            inline=False
        )
        found = True

    if not found:
        embed.description = "✅ No active cooldowns, enjoy the sunshine ☀️"
        embed.color = discord.Color.green()

    # Inspiring footer
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

    if message.author.bot and message.author.id == MAZOKU_BOT_ID:
        user = None
        cmd = None

        # --- Case 1: via interaction (direct slash command) ---
        if getattr(message, "interaction", None):
            cmd = message.interaction.name
            user = message.interaction.user
            print(f"🎯 Detected /{cmd} by {user} ({user.id})")

        # --- Case 2: fallback via embed ---
        elif message.embeds:
            embed = message.embeds[0]
            title = embed.title.lower() if embed.title else ""
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
                cmd = None

        # --- Apply cooldown ---
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

            # Log start
            log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(
                    f"📌 Cooldown started for {user.mention} → `/{cmd}` ({cd_time}s)"
                )

            async def cooldown_task():
                await asyncio.sleep(cd_time)
                try:
                    # Public message with Sunflower theme
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

                    # Log end
                    if log_channel:
                        await log_channel.send(
                            f"🕒 Cooldown ended for {user.mention} → `/{cmd}`"
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
