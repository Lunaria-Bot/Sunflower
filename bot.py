import discord
from discord import app_commands
import asyncio
import os
import json

TOKEN = os.getenv("DISCORD_TOKEN")
MAZOKU_BOT_ID = 1242388858897956906
GUILD_ID = 1196690004852883507

# Cooldown times per command
COOLDOWN_SECONDS = {
    "summon": 1800,   # 30 min
    "open-boxes": 60  # 1 min
}

PERSIST_FILE = "cooldowns.json"

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

class CooldownBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.cooldowns = {}

    async def setup_hook(self):
        # Sync slash commands to your guild only
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    def load_cooldowns(self):
        if os.path.exists(PERSIST_FILE):
            try:
                with open(PERSIST_FILE, "r") as f:
                    self.cooldowns = json.load(f)
            except:
                self.cooldowns = {}
        else:
            self.cooldowns = {}

    def save_cooldowns(self):
        with open(PERSIST_FILE, "w") as f:
            json.dump(self.cooldowns, f)

client = CooldownBot()

# ----------------
# Slash Commands
# ----------------
@client.tree.command(name="cooldowns", description="Check your active cooldowns")
async def cooldowns_cmd(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id not in client.cooldowns or not client.cooldowns[user_id]:
        await interaction.response.send_message("✅ You have no active cooldowns!", ephemeral=True)
        return

    lines = []
    for cmd, ts in client.cooldowns[user_id].items():
        remaining = int(ts - asyncio.get_event_loop().time())
        if remaining > 0:
            mins, secs = divmod(remaining, 60)
            lines.append(f"`/{cmd}` → {mins}m {secs}s left")

    if not lines:
        await interaction.response.send_message("✅ You have no active cooldowns!", ephemeral=True)
    else:
        await interaction.response.send_message("⏳ Active cooldowns:\n" + "\n".join(lines), ephemeral=True)

# ----------------
# Shared cooldown handler
# ----------------
async def handle_cooldown(cmd: str, user: discord.User, message: discord.Message):
    if cmd not in COOLDOWN_SECONDS:
        return

    user_id = str(user.id)
    now = asyncio.get_event_loop().time()

    if user_id not in client.cooldowns:
        client.cooldowns[user_id] = {}

    if cmd in client.cooldowns[user_id] and client.cooldowns[user_id][cmd] > now:
        await message.channel.send(
            f"⏳ {user.mention}, you are still on cooldown for `/{cmd}`!"
        )
        return

    # Start cooldown
    cd_time = COOLDOWN_SECONDS[cmd]
    client.cooldowns[user_id][cmd] = now + cd_time
    client.save_cooldowns()

    await message.channel.send(
        f"⚡ {user.mention}, cooldown started for `/{cmd}`! "
        f"I’ll remind you in {cd_time // 60 if cd_time >= 60 else cd_time} "
        f"{'minutes' if cd_time >= 60 else 'seconds'}."
    )

    async def cooldown_task():
        await asyncio.sleep(cd_time)
        if user_id in client.cooldowns and cmd in client.cooldowns[user_id]:
            del client.cooldowns[user_id][cmd]
            if not client.cooldowns[user_id]:
                del client.cooldowns[user_id]
            client.save_cooldowns()

        await message.channel.send(
            f"✅ {user.mention}, Hey just to remind you that `/{cmd}` is over!"
        )

    asyncio.create_task(cooldown_task())

# ----------------
# Events
# ----------------
@client.event
async def on_ready():
    client.load_cooldowns()
    print(f"✅ Logged in as {client.user} ({client.user.id})")

@client.event
async def on_message(message: discord.Message):
    if message.author.id == client.user.id:
        return

    if message.guild and message.guild.id != GUILD_ID:
        return  # only work in your server

    if not (message.author.bot and message.author.id == MAZOKU_BOT_ID):
        return

    # --- Try interaction-based detection first ---
    if message.interaction:
        cmd = message.interaction.name
        user = message.interaction.user
        print(f"🎯 Interaction detected: /{cmd} by {user} ({user.id})")
        await handle_cooldown(cmd, user, message)
        return

    # --- Fallback: embed-based detection ---
    if message.embeds:
        embed = message.embeds[0]
        command = None

        if embed.title and "Summon" in embed.title:
            command = "summon"
        elif embed.title and "Card" in embed.title:
            command = "open-boxes"

        if not command:
            return

        user = message.mentions[0] if message.mentions else None
        if not user:
            return

        print(f"📦 Embed detected: /{command} by {user} ({user.id})")
        await handle_cooldown(command, user, message)

client.run(TOKEN)
