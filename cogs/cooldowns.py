import os
import re
import logging
import discord
from discord.ext import commands

log = logging.getLogger("cog-cooldowns")

# --- Env IDs ---
GUILD_IDS = [int(x) for x in os.getenv("GUILD_IDS", "").split(",") if x]
MAZOKU_BOT_ID = int(os.getenv("MAZOKU_BOT_ID", "0"))
HIGHTIER_ROLE_ID = int(os.getenv("HIGHTIER_ROLE_ID", "0"))

# --- Rarity emojis ---
RARITY_EMOTES = {
    "1342202597389373530": "SR",
    "1342202212948115510": "SSR",
    "1342202203515125801": "UR"
}
EMOJI_REGEX = re.compile(r"<a?:\w+:(\d+)>")

async def safe_send(channel: discord.TextChannel, *args, **kwargs):
    try:
        return await channel.send(*args, **kwargs)
    except Exception:
        pass

class Cooldowns(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- Events ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not getattr(self.bot, "redis", None):
            return
        if not message.guild or message.guild.id not in GUILD_IDS:
            return
        if message.author.id == self.bot.user.id:
            return
        if not (message.author.bot and message.author.id == MAZOKU_BOT_ID):
            return
        if not message.embeds:
            return

        embed = message.embeds[0]
        title = (embed.title or "").lower()

        # Auto Summon spawn
        if "auto summon" in title and "claimed" not in title:
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
            # Ici on ne fait plus rien si une rareté est trouvée

async def setup(bot: commands.Bot):
    await bot.add_cog(Cooldowns(bot))
    log.info("⚙️ Cooldowns cog loaded (events only, no slash command)")
