# main.py
import os
import logging
import asyncio
import glob
import discord
from discord.ext import commands
import redis.asyncio as redis

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("main")

# --- Token, Redis, Prefix ---
TOKEN = os.getenv("DISCORD_TOKEN")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "m?")  # ← prefix configurable (default: m?)

# --- Intents ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.messages = True

# --- Bot ---
bot = commands.Bot(
    command_prefix=COMMAND_PREFIX,
    intents=intents,
    case_insensitive=True
)

# --- Setup hook ---
async def setup_hook():
    # Connexion Redis partagée pour tous les cogs
    try:
        bot.redis = redis.from_url(REDIS_URL, decode_responses=True)
        await bot.redis.ping()
        log.info("✅ Connected to Redis at %s", REDIS_URL)
    except Exception as e:
        bot.redis = None
        log.error("❌ Redis connection failed: %s", e)

    # --- Auto‑load de tous les cogs dans /cogs ---
    cog_files = glob.glob("cogs/*.py")
    results = []

    for file in cog_files:
        cog_name = file.replace("/", ".").replace("\\", ".")[:-3]  # ex: cogs.admin
        try:
            await bot.load_extension(cog_name)
            results.append((cog_name, "✅"))
        except Exception as e:
            results.append((cog_name, f"❌ ({type(e).__name__})"))
            log.exception("❌ Failed to load cog %s", cog_name, exc_info=e)

    # --- Affichage tableau clair ---
    log.info("📦 Cogs loading summary:")
    for name, status in results:
        log.info("   %s %s", status, name)

    # 🔑 Sync global une seule fois au démarrage (slash commands)
    try:
        synced = await bot.tree.sync()
        log.info("🌍 Global slash commands synced (%s commandes)", len(synced))
    except Exception as e:
        log.exception("❌ Failed to sync global slash commands:", exc_info=e)

bot.setup_hook = setup_hook

# --- Events ---
@bot.event
async def on_ready():
    log.info("🤖 Bot connecté en tant que %s (ID: %s)", bot.user, bot.user.id)
    log.info("🌍 Connecté sur %s serveurs", len(bot.guilds))
    log.info("⌨️ Prefix actif: %s (slash toujours disponible)", COMMAND_PREFIX)

# --- Run ---
if __name__ == "__main__":
    if not TOKEN:
        log.error("❌ DISCORD_TOKEN manquant dans les variables d'environnement")
    else:
        bot.run(TOKEN)
