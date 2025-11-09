import os
import logging
import discord
from discord.ext import commands

log = logging.getLogger("cog-log")

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
MAZOKU_BOT_ID = int(os.getenv("MAZOKU_BOT_ID", "0"))

class MazokuLog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        log.info("⚙️ MazokuLog loaded (GUILD_ID=%s, MAZOKU_BOT_ID=%s)", GUILD_ID, MAZOKU_BOT_ID)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.id != MAZOKU_BOT_ID:
            return
        if not message.guild or message.guild.id != GUILD_ID:
            return

        log.info("📩 Mazoku message (ID=%s): %s", message.id, message.content)
        if message.embeds:
            for i, e in enumerate(message.embeds):
                log.info("Embed %s:", i)
                log.info("  Title: %s", e.title)
                log.info("  Desc: %s", e.description)
                log.info("  Footer: %s", e.footer.text if e.footer else "")

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.id != MAZOKU_BOT_ID:
            return
        if not after.guild or after.guild.id != GUILD_ID:
            return
        if not after.embeds:
            return

        embed = after.embeds[0]
        log.info("✏️ Mazoku message edited (ID=%s)", after.id)
        log.info("  Title: %s", embed.title)
        log.info("  Desc: %s", embed.description)
        log.info("  Footer: %s", embed.footer.text if embed.footer else "")

# --- Extension setup ---
async def setup(bot: commands.Bot):
    await bot.add_cog(MazokuLog(bot))
