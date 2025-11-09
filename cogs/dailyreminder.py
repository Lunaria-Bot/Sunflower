import logging
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone
import redis.asyncio as redis

log = logging.getLogger("cog-dailyreminder")

GUILD_ID = 1293611593845706793  # your server ID
LOG_CHANNEL_ID = 1421465080238964796  # log channel
REDIS_URL = "redis://default:WEQfFAaMkvNPFvEzOpAQsGdDTTbaFzOr@redis-436594b0.railway.internal:6379"

DAILY_KEY = "dailyreminder:subscribers"
DAILY_MESSAGE = "Hello just to remind you that your Mazoku Daily is ready !"


class DailyReminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.redis = None
        self.daily_task.start()

    async def cog_load(self):
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)

    async def cog_unload(self):
        if self.redis:
            await self.redis.close()
        self.daily_task.cancel()

    # --- Toggle subscription ---
    @app_commands.command(name="toggle-daily", description="Toggle daily Mazoku reminder on/off")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def toggle_daily(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        subscribed = await self.redis.sismember(DAILY_KEY, user_id)

        if subscribed:
            await self.redis.srem(DAILY_KEY, user_id)
            await interaction.response.send_message("❌ You will no longer receive daily reminders.", ephemeral=True)
        else:
            await self.redis.sadd(DAILY_KEY, user_id)
            await interaction.response.send_message("✅ You will now receive daily reminders.", ephemeral=True)

    # --- List subscribers (admin only) ---
    @app_commands.command(name="list-daily", description="List all users subscribed to daily reminders")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def list_daily(self, interaction: discord.Interaction):
        # Restrict to admins
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ You don’t have permission to use this command.", ephemeral=True)
            return

        subscribers = await self.redis.smembers(DAILY_KEY)
        if not subscribers:
            await interaction.response.send_message("📭 No one is currently subscribed.", ephemeral=True)
            return

        guild = interaction.guild
        mentions = []
        for uid in subscribers:
            member = guild.get_member(int(uid))
            if member:
                mentions.append(member.mention)
            else:
                mentions.append(f"<@{uid}>")  # fallback mention

        # Send as ephemeral to admin
        await interaction.response.send_message(
            f"👥 Subscribers ({len(subscribers)}):\n" + ", ".join(mentions),
            ephemeral=True
        )

    # --- Daily task ---
    @tasks.loop(hours=24)
    async def daily_task(self):
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return

        subscribers = await self.redis.smembers(DAILY_KEY)
        if not subscribers:
            return

        success = 0
        failed = 0

        for uid in subscribers:
            member = guild.get_member(int(uid))
            if member:
                try:
                    await member.send(DAILY_MESSAGE)
                    success += 1
                except discord.Forbidden:
                    failed += 1

        # Log summary in the log channel
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            await log_channel.send(
                f"📊 Daily reminder summary at {now}:\n"
                f"✅ Sent: {success}\n"
                f"❌ Failed: {failed}\n"
                f"👥 Total subscribers: {len(subscribers)}"
            )

    @daily_task.before_loop
    async def before_daily_task(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc)
        target = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await discord.utils.sleep_until(target)


async def setup(bot: commands.Bot):
    await bot.add_cog(DailyReminder(bot))
    log.info("⚙️ DailyReminder cog loaded")
