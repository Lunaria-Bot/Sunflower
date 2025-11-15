import logging
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncpg
from datetime import datetime, timedelta, timezone
import json

log = logging.getLogger("cog-votereminder-moonquil")

VOTE_COOLDOWN_HOURS = 12  # rappel toutes les 12h

class VoteReminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: asyncpg.Pool | None = None
        self.active_reminders = {}
        self.cleanup_task.start()
        self._restored = False

    async def cog_load(self):
        self.pool = self.bot.db_pool
        log.info("✅ Pool Postgres attachée pour VoteReminder (Moonquil)")

    def cog_unload(self):
        self.cleanup_task.cancel()

    async def publish_event(self, guild_id: int, user_id: int, event_type: str, details: dict | None = None):
        """Publie un événement vers Redis pour le Master avec bot_name=Moonquil."""
        if not getattr(self.bot, "redis", None):
            return
        event = {
            "bot_name": "Moonquil",
            "bot_id": self.bot.user.id,
            "guild_id": guild_id,
            "user_id": user_id,
            "event_type": event_type,
            "details": details or {}
        }
        try:
            await self.bot.redis.publish("bot_events", json.dumps(event))
            log.info("📡 VoteReminder Event publié: %s", event)
        except Exception as e:
            log.error("❌ Impossible de publier l'événement Redis: %s", e)

    async def send_vote_message(self, member: discord.Member, channel: discord.TextChannel):
        try:
            await channel.send(f"🗳️ Hey {member.mention}, don't forget to vote for Moonquil!")
            log.info("🔔 Vote reminder sent to %s", member.display_name)
            await self.publish_event(member.guild.id, member.id, "vote_triggered", {"channel": channel.id})
        except discord.Forbidden:
            log.warning("❌ Cannot send vote reminder in %s", channel.name)

    async def start_vote(self, member: discord.Member, channel: discord.TextChannel):
        key = f"{member.guild.id}:{member.id}"
        if key in self.active_reminders:
            return

        expire_at = datetime.now(timezone.utc) + timedelta(hours=VOTE_COOLDOWN_HOURS)
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO vote_reminders (guild_id, user_id, channel_id, expire_at) "
                "VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (guild_id, user_id) DO UPDATE SET channel_id=$3, expire_at=$4",
                member.guild.id, member.id, channel.id, expire_at
            )

        await self.publish_event(member.guild.id, member.id, "vote_started", {
            "channel": channel.id,
            "expire_at": expire_at.isoformat()
        })

        async def reminder_task():
            try:
                log.info("▶️ Vote task started for %s (%sh)", member.display_name, VOTE_COOLDOWN_HOURS)
                await asyncio.sleep(VOTE_COOLDOWN_HOURS * 3600)
                await self.send_vote_message(member, channel)
            finally:
                self.active_reminders.pop(key, None)
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM vote_reminders WHERE guild_id=$1 AND user_id=$2",
                        member.guild.id, member.id
                    )
                log.info("🗑️ Vote reminder deleted for %s", member.display_name)
                await self.publish_event(member.guild.id, member.id, "vote_deleted")

        task = asyncio.create_task(reminder_task())
        self.active_reminders[key] = task

    async def restore_reminders(self):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT guild_id, user_id, channel_id, expire_at FROM vote_reminders")
        now = datetime.now(timezone.utc)

        restored_count = 0
        for row in rows:
            guild = self.bot.get_guild(row["guild_id"])
            if not guild:
                continue
            member = guild.get_member(row["user_id"])
            if not member:
                continue
            channel = guild.get_channel(row["channel_id"])
            if not channel:
                continue

            remaining = (row["expire_at"] - now).total_seconds()
            if remaining <= 0:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM vote_reminders WHERE guild_id=$1 AND user_id=$2",
                        row["guild_id"], row["user_id"]
                    )
                continue

            async def reminder_task():
                try:
                    await asyncio.sleep(remaining)
                    await self.send_vote_message(member, channel)
                finally:
                    self.active_reminders.pop(f"{guild.id}:{member.id}", None)
                    async with self.pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM vote_reminders WHERE guild_id=$1 AND user_id=$2",
                            guild.id, member.id
                        )
                    await self.publish_event(guild.id, member.id, "vote_deleted")

            task = asyncio.create_task(reminder_task())
            self.active_reminders[f"{guild.id}:{member.id}"] = task
            restored_count += 1

            await self.publish_event(guild.id, member.id, "vote_restored", {
                "remaining": remaining,
                "channel": channel.id
            })

        log.info("📋 Checklist: %s Vote reminders restored after restart", restored_count)
        await self.publish_event(0, 0, "vote_checklist", {"restored_count": restored_count})

    @tasks.loop(hours=1)
    async def cleanup_task(self):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM vote_reminders WHERE expire_at <= $1", datetime.now(timezone.utc))
        log.info("🧹 Cleanup: expired Vote reminders deleted")

    @cleanup_task.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()
        if not self._restored:
            await self.restore_reminders()
            self._restored = True

    # --- Slash command /toggle-vote ---
    @app_commands.command(name="toggle-vote", description="Enable or disable your vote reminder")
    async def toggle_vote(self, interaction: discord.Interaction):
        member = interaction.user
        channel = interaction.channel
        key = f"{member.guild.id}:{member.id}"

        if key in self.active_reminders:
            # Désactivation
            task = self.active_reminders.pop(key)
            task.cancel()
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM vote_reminders WHERE guild_id=$1 AND user_id=$2",
                    member.guild.id, member.id
                )
            await interaction.response.send_message(
                "❌ Your vote reminder has been disabled.",
                ephemeral=True
            )
            log.info("🚫 Vote reminder disabled for %s", member.display_name)
            await self.publish_event(member.guild.id, member.id, "vote_disabled")
        else:
            # Activation
            await self.start_vote(member, channel)
            await interaction.response.send_message(
                f"🗳️ Vote reminder enabled for {member.mention}. You’ll be notified every {VOTE_COOLDOWN_HOURS}h.",
                ephemeral=True
            )
            log.info("✅ Vote reminder enabled for %s", member.display_name)
            await self.publish_event(member.guild.id, member.id, "vote_enabled")


async def setup(bot: commands.Bot):
    await bot.add_cog(VoteReminder(bot))
    log.info("⚙️ VoteReminder cog loaded (Moonquil + Postgres + Redis events + checklist + /toggle-vote)")
