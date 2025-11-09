import logging
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("cog-admin")


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- Slash command /sync ---
    @app_commands.command(name="sync", description="Resynchroniser les commandes slash (guild + global)")
    @app_commands.describe(scope="Choisir 'guild' ou 'global'")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="Guild only", value="guild"),
            app_commands.Choice(name="Global only", value="global"),
        ]
    )
    async def sync_cmd(self, interaction: discord.Interaction, scope: app_commands.Choice[str] = None):
        await interaction.response.defer(ephemeral=True)

        try:
            if scope is None:
                synced_guild = await self.bot.tree.sync(guild=interaction.guild)
                synced_global = await self.bot.tree.sync()
                await interaction.followup.send(
                    f"✅ {len(synced_guild)} commandes resynchronisées sur **{interaction.guild.name}**\n"
                    f"🌍 {len(synced_global)} commandes globales resynchronisées.",
                    ephemeral=True
                )
            elif scope.value == "guild":
                synced = await self.bot.tree.sync(guild=interaction.guild)
                await interaction.followup.send(
                    f"✅ {len(synced)} commandes resynchronisées uniquement sur **{interaction.guild.name}**.",
                    ephemeral=True
                )
            elif scope.value == "global":
                synced = await self.bot.tree.sync()
                await interaction.followup.send(
                    f"🌍 {len(synced)} commandes globales resynchronisées.",
                    ephemeral=True
                )
        except Exception as e:
            log.exception("❌ Sync failed", exc_info=e)
            await interaction.followup.send("❌ Une erreur est survenue pendant la synchronisation.", ephemeral=True)

    # --- Slash command /sync-clean ---
    @app_commands.command(name="sync-clean", description="Purge et republie toutes les commandes globales")
    async def sync_clean(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            self.bot.tree.clear_commands(guild=None)
            await self.bot.tree.sync(guild=None)

            synced = await self.bot.tree.sync()
            await interaction.followup.send(
                f"🧹 Purge terminée. 🌍 {len(synced)} commandes globales republisées depuis ton code.",
                ephemeral=True
            )
            log.info("🧹 Global commands purged and re-synced (%s commands)", len(synced))
        except Exception as e:
            log.exception("❌ Failed to clean global commands", exc_info=e)
            await interaction.followup.send("❌ Erreur lors du nettoyage global.", ephemeral=True)

    # --- Slash command /reminder ---
    @app_commands.command(name="reminder", description="Enable or disable summon reminders")
    @app_commands.describe(state="Enable or disable the summon reminder")
    @app_commands.choices(
        state=[
            app_commands.Choice(name="On", value="on"),
            app_commands.Choice(name="Off", value="off"),
        ]
    )
    async def reminder_cmd(self, interaction: discord.Interaction, state: app_commands.Choice[str]):
        if not getattr(self.bot, "redis", None):
            await interaction.response.send_message(
                "⚠️ Redis n’est pas configuré, reminders toujours activés.",
                ephemeral=True
            )
            return

        key = f"reminder:settings:{interaction.guild.id}:{interaction.user.id}:summon"
        if state.value == "on":
            await self.bot.redis.set(key, "1")
            await interaction.response.send_message("✅ Summon reminders activés.", ephemeral=True)
        else:
            await self.bot.redis.set(key, "0")
            await interaction.response.send_message("⏸️ Summon reminders désactivés.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot), override=True)
    log.info("⚙️ Admin cog loaded (sync, sync-clean, reminder)")
