"""Moduł Cog dla Discorda obsługujący AI Mistrza Gry (Narrative Cog).
Wyzwalany wyłącznie na kanale #stół-gry po oznaczeniu @Mistrz Gry lub użyciu komendy /next.
Ignoruje pasywne rozmowy graczy, agreguje stan gry, wywołuje Gemini 3.7 Flash,
dzieli odpowiedzi na bezpieczne akapity i dołącza dynamiczne przyciski rzutów kośćmi.
"""
from __future__ import annotations
import logging
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List, Dict, Any

from ai.gemini_client import GeminiClient, split_long_message, default_gemini_client
from ai.context_builder import (
    build_full_dm_context,
    normalize_channel_name,
    fetch_messages_since_last_dm_response,
    fetch_campaign_rules,
    fetch_active_characters
)
from discord_ui.views import NarrativeActionView

logger = logging.getLogger("NarrativeCog")


def is_table_channel(channel: Any) -> bool:
    """Sprawdza, czy dany kanał to stół gry (#stół-gry / #stol-gry)."""
    if not channel:
        return False
    name = getattr(channel, "name", "")
    norm = normalize_channel_name(name)
    return norm in ("stolgry", "stołgry", "stol", "stoł", "stolgrydnd") or "stol" in norm or "stoł" in norm



def is_narrative_trigger(message: discord.Message, bot_user: Optional[discord.ClientUser]) -> bool:
    """
    Sprawdza, czy wiadomość powinna wyzwolić AI Mistrza Gry:
    - Oznaczenie @Mistrz Gry lub wzmianka bota (<@bot_id>)
    - Wzmianka roli 'Mistrz Gry'
    - Komenda tekstowa !next lub /next
    """
    if not message.content and not message.mentions and not getattr(message, "role_mentions", []):
        return False

    content = message.content or ""

    # 1. Sprawdzenie wzmianki bota przez bot_user.mentioned_in(message)
    if bot_user and hasattr(bot_user, "mentioned_in"):
        if bot_user.mentioned_in(message):
            return True

    # 2. Bezpośrednia wzmianka ID bota w tekście
    if bot_user:
        if f"<@{bot_user.id}>" in content or f"<@!{bot_user.id}>" in content:
            return True

    # 3. Wzmianka tekstowa @Mistrz Gry
    if "@Mistrz Gry" in content or "@MistrzGry" in content or "@DM" in content:
        return True

    # 4. Wzmianka roli Mistrz Gry
    for role in getattr(message, "role_mentions", []):
        if "mistrz" in normalize_channel_name(role.name) or "dm" in role.name.lower():
            return True

    # 5. Prefiks tekstowy
    if content.strip().startswith("!next") or content.strip().startswith("/next"):
        return True

    return False


import asyncio

class NarrativeCog(commands.Cog):
    """Cog odpowiedzialny za narrację AI Dungeon Mastera na kanale #stół-gry."""

    def __init__(self, bot: commands.Bot, gemini_client: Optional[GeminiClient] = None):
        self.bot = bot
        self.gemini_client = gemini_client or default_gemini_client
        self._channel_locks: Dict[int, asyncio.Lock] = {}

    def _get_lock(self, channel_id: int) -> asyncio.Lock:
        if channel_id not in self._channel_locks:
            self._channel_locks[channel_id] = asyncio.Lock()
        return self._channel_locks[channel_id]

    async def execute_narrative_turn(
        self,
        channel: discord.TextChannel,
        interaction: Optional[discord.Interaction] = None
    ) -> None:
        """
        Główna koordynacja tury narracyjnej:
        1. Budowanie pełnego kontekstu ze stanu Discorda (4 warstwy).
        2. Wywołanie modelu Gemini 3.7 Flash.
        3. Inteligentny podział odpowiedzi (>2000 znaków) na akapity.
        4. Sekwencyjne wysłanie wiadomości z dołączeniem NarrativeActionView do ostatniego fragmentu.
        """
        lock = self._get_lock(channel.id)
        async with lock:
            guild = getattr(channel, "guild", None)
            bot_user = self.bot.user or getattr(interaction, "client", self.bot).user

            # 1. Złożenie 4-warstwowego kontekstu kampanii
            system_prompt, context_prompt = await build_full_dm_context(
                guild=guild,
                table_channel=channel,
                bot_user=bot_user
            )

            logger.info(f"Rozpoczynam generowanie narracji AI dla kanału {getattr(channel, 'name', 'unknown')}")

            # 2. Wywołanie Gemini AI
            try:
                narrative_text, action_buttons = await self.gemini_client.generate_narrative(
                    context_prompt=context_prompt,
                    system_prompt=system_prompt
                )
            except Exception as e:
                logger.error(f"Błąd podczas wywołania Gemini: {e}")
                narrative_text = (
                    "**Mistrz Gry:** Cienie w komnacie gęstnieją na ułamek sekundy, "
                    "jakby sama magia splotu zawahała się w odpowiedzi na wasze czyny...\n\n*Co robicie dalej?*"
                )
                action_buttons = [
                    {"label": "Rzut na Percepcję (WIS +2)", "formula": "1d20+2", "reason": "Percepcja", "dc": 12}
                ]

            # 3. Podział na bezpieczne fragmenty (<1900 znaków)
            chunks = split_long_message(narrative_text, limit=1900)
            if not chunks:
                chunks = ["*Mistrz Gry przygląda się wam w milczeniu...*"]

            view = NarrativeActionView(action_buttons) if action_buttons else None

            # 4. Sekwencyjne doręczenie wiadomości
            if interaction and not interaction.response.is_done():
                # Interakcja jeszcze nie odpowiedziana
                if len(chunks) == 1:
                    await interaction.response.send_message(chunks[0], view=view)
                else:
                    await interaction.response.send_message(chunks[0])
                    for i, chunk in enumerate(chunks[1:], start=1):
                        if i == len(chunks) - 1:
                            await channel.send(chunk, view=view)
                        else:
                            await channel.send(chunk)
            elif interaction and interaction.response.is_done():
                # Interakcja była odroczona (defer)
                if len(chunks) == 1:
                    await interaction.followup.send(chunks[0], view=view)
                else:
                    await interaction.followup.send(chunks[0])
                    for i, chunk in enumerate(chunks[1:], start=1):
                        if i == len(chunks) - 1:
                            await channel.send(chunk, view=view)
                        else:
                            await channel.send(chunk)
            else:
                # Wywołanie z on_message
                for i, chunk in enumerate(chunks):
                    if i == len(chunks) - 1:
                        await channel.send(chunk, view=view)
                    else:
                        await channel.send(chunk)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Nasłuchuje wypowiedzi na czacie i reaguje wyłącznie po wywołaniu @Mistrz Gry na stole gry."""
        # 1. Ignoruj wiadomości botów (w tym własne)
        if getattr(message.author, "bot", False):
            return
        if self.bot.user and message.author.id == self.bot.user.id:
            return

        # 2. Ignoruj kanały inne niż #stół-gry
        if not is_table_channel(message.channel):
            return

        # 3. Sprawdź, czy bot został wywołany
        if not is_narrative_trigger(message, self.bot.user):
            return

        # 4. Wyzwolenie tury narracyjnej z wskaźnikiem pisania (typing)
        try:
            if hasattr(message.channel, "typing"):
                async with message.channel.typing():
                    await self.execute_narrative_turn(message.channel)
            else:
                await self.execute_narrative_turn(message.channel)
        except Exception as e:
            logger.error(f"Błąd podczas obsługi wiadomości narracyjnej: {e}")
            await message.channel.send(f"❌ Wystąpił błąd podczas generowania narracji Mistrza Gry: {e}")

    @app_commands.command(
        name="next",
        description="Wymusza wygenerowanie kolejnej tury narracji przez AI Mistrza Gry na stole gry"
    )
    async def next_turn(self, interaction: discord.Interaction):
        """Komenda slash /next wyzwalająca turę narracji."""
        # Walidacja kanału
        if not is_table_channel(interaction.channel):
            await interaction.response.send_message(
                "❌ Komendy `/next` można używać wyłącznie na kanale **#stół-gry**.",
                ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        try:
            await self.execute_narrative_turn(interaction.channel, interaction=interaction)
        except Exception as e:
            logger.error(f"Błąd komendy /next: {e}")
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ Wystąpił błąd podczas generowania narracji: {e}")
            else:
                await interaction.response.send_message(f"❌ Wystąpił błąd: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    """Rejestracja coga w instancji bota."""
    await bot.add_cog(NarrativeCog(bot))
