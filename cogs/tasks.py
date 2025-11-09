import logging
import asyncio
import itertools
import discord
from discord.ext import commands

log = logging.getLogger("cog-tasks")

STATUSES = [
    discord.Activity(type=discord.ActivityType.watching, name="Lilac 🌸 "),
    discord.Activity(type=discord.ActivityType.playing, name="Silksong 🪡 "),
    discord.Activity(type=discord.ActivityType.listening, name="to K-Pop 🎵"),
]

class Tasks(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._status_task = None
        self._heartbeat_task = None

    @commands.Cog.listener()
    async def on_ready(self):
        if not self._status_task:
            self._status_task = asyncio.create_task(self.cycle_status())
        if not self._heartbeat_task:
            self._heartbeat_task = asyncio.create_task(self.heartbeat())
        log.info("✅ Background tasks launched")

    async def cycle_status(self):
        for activity in itertools.cycle(STATUSES):
            try:
                await self.bot.change_presence(activity=activity, status=discord.Status.online)
            except Exception:
                log.exception("Failed to change presence")
            await asyncio.sleep(300)

    async def heartbeat(self):
        while True:
            log.info("💓 Heartbeat: bot alive")
            await asyncio.sleep(60)

async def setup(bot: commands.Bot):
    await bot.add_cog(Tasks(bot))

