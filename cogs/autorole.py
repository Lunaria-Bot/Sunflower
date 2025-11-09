import logging
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import redis.asyncio as redis

log = logging.getLogger("cog-autorole")

# Role IDs
LVL10_ROLE_ID = 1297161587744047106
CROSS_TRADE_ACCESS_ID = 1332804856918052914  # ✅ updated ID
CROSS_TRADE_BAN_ID = 1306954214106202144
MARKET_BAN_ID = 1306958134245457970

# Guild and channel IDs
GUILD_ID = 1293611593845706793
NOTIFY_CHANNEL_ID = 1421465080238964796

# Redis URL
REDIS_URL = "redis://default:WEQfFAaMkvNPFvEzOpAQsGdDTTbaFzOr@redis-436594b0.railway.internal:6379"

# TTL in seconds (7 days)
REDIS_TTL = 60 * 60 * 24 * 7


class AutoRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.scanning = False
        self.changed_members = []
        self.redis = None

    async def cog_load(self):
        # Connect to Redis when cog loads
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)

    async def cog_unload(self):
        if self.redis:
            await self.redis.close()

    async def update_cross_trade_access(self, member: discord.Member):
        guild = member.guild
        access_role = guild.get_role(CROSS_TRADE_ACCESS_ID)
        lvl10_role = guild.get_role(LVL10_ROLE_ID)
        ban_role = guild.get_role(CROSS_TRADE_BAN_ID)
        market_ban_role = guild.get_role(MARKET_BAN_ID)

        if not access_role:
            return

        # Desired state
        should_have = (
            lvl10_role in member.roles
            and ban_role not in member.roles
            and market_ban_role not in member.roles
        )

        key = f"autorole:{guild.id}:{member.id}"
        cached_state = await self.redis.get(key)

        if cached_state is not None and (cached_state == "1") == should_have:
            return  # Already correct, skip

        try:
            if should_have:
                if access_role not in member.roles:
                    await member.add_roles(access_role, reason="AutoRole: Lvl10 without ban")
                    log.info("✅ Added Cross Trade Access to %s", member.display_name)
                    self.changed_members.append(member)
            else:
                if access_role in member.roles:
                    await member.remove_roles(access_role, reason="AutoRole: Ban detected or not lvl10")
                    log.info("🚫 Removed Cross Trade Access from %s", member.display_name)
                    self.changed_members.append(member)

            # Update Redis with TTL
            await self.redis.set(key, "1" if should_have else "0", ex=REDIS_TTL)

            await asyncio.sleep(1.2)  # throttle

        except discord.Forbidden:
            log.error("❌ Missing permissions to modify roles for %s", member.display_name)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if self.scanning:
            return
        if before.roles != after.roles:
            await self.update_cross_trade_access(after)
            # Always refresh Redis state with TTL
            guild = after.guild
            key = f"autorole:{guild.id}:{after.id}"
            has_access = CROSS_TRADE_ACCESS_ID in [r.id for r in after.roles]
            await self.redis.set(key, "1" if has_access else "0", ex=REDIS_TTL)

    @app_commands.command(name="check_autorole_all", description="Force a global role check for all members")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    async def check_autorole_all(self, interaction: discord.Interaction):
        guild = interaction.guild
        access_role = guild.get_role(CROSS_TRADE_ACCESS_ID)
        if not access_role:
            await interaction.response.send_message(
                "⚠️ Cross Trade Access role not found in this server, skipping.", ephemeral=True
            )
            return

        # Acknowledge the command
        await interaction.response.send_message(
            "🔍 Starting global role check... Progress will be posted here.", ephemeral=True
        )

        total = len(guild.members)
        checked = 0
        self.scanning = True
        self.changed_members = []

        for member in guild.members:
            await self.update_cross_trade_access(member)
            checked += 1
            if checked % 25 == 0 or checked == total:
                await interaction.channel.send(f"Progress: {checked}/{total} members checked...")

        self.scanning = False
        await interaction.channel.send("✅ Global role check completed.")
        log.info("♻️ Manual global role check completed in %s", guild.name)

        # Notify in the dedicated channel with batched mentions
        if self.changed_members:
            channel = guild.get_channel(NOTIFY_CHANNEL_ID)
            if channel:
                await channel.send("Hey, I just finished my task! 🎉 Users concerned:")

                # Batch mentions into groups of 20
                batch_size = 20
                for i in range(0, len(self.changed_members), batch_size):
                    batch = self.changed_members[i:i + batch_size]
                    mentions = " ".join(m.mention for m in batch)
                    await channel.send(mentions)

                # ✅ Final summary count
                await channel.send(f"📊 Total users updated: **{len(self.changed_members)}**")


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRole(bot))
    log.info("⚙️ AutoRole cog loaded")
