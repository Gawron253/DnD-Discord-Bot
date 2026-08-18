"""Główny plik startowy bota Discord AI Dungeon Master (Pure Discord Architecture + Gemini 3.7 Flash)."""
from __future__ import annotations
import asyncio
import logging
import sys
from typing import List, Optional
import discord
from discord import app_commands
from discord.ext import commands

from config.settings import settings

# Konfiguracja logowania
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("DndAIBot")

# Lista wszystkich rozszerzeń / Cogów
INITIAL_EXTENSIONS: List[str] = [
    "commands.campaign_cog",
    "commands.quest_cog",
    "commands.character_cog",
    "commands.mechanics_cog",
    "commands.narrative_cog"
]


class DndAIBot(commands.Bot):
    """Główna klasa bota D&D AI Dungeon Master zarządzająca cyklem życia i Cogami."""

    def __init__(
        self,
        command_prefix: str = "!",
        intents: Optional[discord.Intents] = None,
        **kwargs
    ):
        if intents is None:
            intents = discord.Intents.default()
            intents.message_content = True
            intents.guilds = True
            intents.members = True

        super().__init__(
            command_prefix=command_prefix,
            intents=intents,
            help_command=None,
            **kwargs
        )
        self.initial_extensions = list(INITIAL_EXTENSIONS)

    async def setup_hook(self) -> None:
        """Ładowanie wszystkich rozszerzeń (Cogów) bota."""
        logger.info("Ładowanie rozszerzeń i modułów D&D...")
        for ext in self.initial_extensions:
            try:
                await self.load_extension(ext)
                logger.info(f"✅ Pomyślnie załadowano rozszerzenie: {ext}")
            except Exception as e:
                logger.error(f"❌ Błąd podczas ładowania rozszerzenia {ext}: {e}", exc_info=True)

    async def on_ready(self) -> None:
        """Wykonywane po pomyślnym zalogowaniu bota do Discorda."""
        if self.user:
            logger.info(f"🎭 Zalogowano jako {self.user.name}#{self.user.discriminator} (ID: {self.user.id})")
        logger.info(f"🌐 Połączono z {len(self.guilds)} serwerami Discord.")

        # Synchronizacja slash commands
        try:
            guild_id = settings.discord_guild_id.strip() if settings.discord_guild_id else None
            if guild_id and guild_id.isdigit():
                guild_obj = discord.Object(id=int(guild_id))
                self.tree.copy_global_to(guild=guild_obj)
                synced = await self.tree.sync(guild=guild_obj)
                logger.info(f"⚡ Zsynchronizowano {len(synced)} komend slash dla serwera ID: {guild_id}")
            else:
                synced = await self.tree.sync()
                logger.info(f"⚡ Globalnie zsynchronizowano {len(synced)} komend slash.")
        except Exception as e:
            logger.error(f"❌ Błąd podczas synchronizacji komend slash: {e}", exc_info=True)

    async def on_tree_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ) -> None:
        """Globalna obsługa błędów komend slash w CommandTree."""
        cmd = getattr(interaction, "command", None)
        cmd_name = getattr(cmd, "name", "unknown")
        logger.error(f"Błąd komendy slash [{cmd_name}]: {error}", exc_info=True)
        err_msg = f"❌ Wystąpił nieoczekiwany błąd podczas wykonywania komendy: `{error}`"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(err_msg, ephemeral=True)
            else:
                await interaction.response.send_message(err_msg, ephemeral=True)
        except Exception as send_err:
            logger.error(f"Nie udało się wysłać komunikatu błędu do użytkownika: {send_err}")

    async def on_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError
    ) -> None:
        """Globalna obsługa błędów tradycyjnych komend tekstowych."""
        if isinstance(error, commands.CommandNotFound):
            return
        logger.error(f"Błąd komendy prefiksowej [{ctx.command}]: {error}", exc_info=True)
        try:
            await ctx.send(f"❌ Błąd komendy: `{error}`")
        except Exception:
            pass

    async def close(self) -> None:
        """Czyszczenie zasobów przy zamykaniu bota."""
        logger.info("Zamykanie bota D&D AI Discord Bot...")
        await super().close()


def create_bot() -> DndAIBot:
    """Fabryka instancji bota Discord."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.members = True
    bot_instance = DndAIBot(command_prefix="!", intents=intents)
    
    # Podpięcie error handlera do drzewa komend
    bot_instance.tree.on_error = bot_instance.on_tree_error
    return bot_instance


bot = create_bot()


async def main() -> None:
    """Główna funkcja asynchroniczna uruchamiająca bota."""
    token = settings.discord_bot_token.strip() if settings.discord_bot_token else ""
    if not token or token == "your_discord_bot_token_here":
        logger.warning(
            "⚠️ Brak DISCORD_BOT_TOKEN w pliku konfiguracyjnym .env!\n"
            "   Uzupełnij DISCORD_BOT_TOKEN przed uruchomieniem w trybie produkcyjnym."
        )
        return

    logger.info("🚀 Uruchamianie bota D&D AI Discord...")
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot został zatrzymany przez użytkownika (KeyboardInterrupt).")
    except Exception as exc:
        logger.critical(f"Krytyczny błąd podczas pracy bota: {exc}", exc_info=True)
        sys.exit(1)
