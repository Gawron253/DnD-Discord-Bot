"""Moduł komend slash mechaniki RPG i rzutów kośćmi (0 tokenów AI)."""
from typing import Optional, Literal
import discord
from discord import app_commands
from discord.ext import commands

from mechanics.dice import roll_dice
from discord_ui.embeds import create_dice_roll_embed
from core.channel_manager import find_forum_channel
from core.discord_db import get_character_from_thread, _get_all_forum_threads


class MechanicsCog(commands.Cog):
    """Cog obsługujący komendy slash rzutów kośćmi i mechaniki (/roll, /check, /initiative)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="roll",
        description="Deterministyczny rzut kośćmi w czystym kodzie Python (0 tokenów AI)"
    )
    @app_commands.describe(
        formula="Formuła rzutu (np. 1d20+5, 2d6+3, 2d20kh1+2)",
        reason="Powód rzutu (np. Atak mieczem, Test Percepcji)",
        dc="Opcjonalny stopień trudności (DC) do oceny sukcesu/porażki",
        advantage="Rzut z ułatwieniem (Advantage - 2d20kh1)",
        disadvantage="Rzut z utrudnieniem (Disadvantage - 2d20kl1)"
    )
    async def roll_command(
        self,
        interaction: discord.Interaction,
        formula: str,
        reason: Optional[str] = "Rzut testowy",
        dc: Optional[int] = None,
        advantage: Optional[bool] = False,
        disadvantage: Optional[bool] = False
    ):
        """Wykonuje deterministyczny rzut kością i publikuje estetyczny embed."""
        try:
            result = roll_dice(
                formula=formula,
                reason=reason or "Rzut kością",
                target_dc=dc,
                advantage=advantage or False,
                disadvantage=disadvantage or False
            )
            embed = create_dice_roll_embed(result, interaction.user.display_name)
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Błąd formuły rzutu kością `{formula}`: {e}",
                ephemeral=True
            )

    @app_commands.command(
        name="check",
        description="Wykonuje test cechy z modyfikatorem pobranym z Twojej karty postaci"
    )
    @app_commands.describe(
        cecha="Cecha do przetestowania (STR, DEX, CON, INT, WIS, CHA)",
        dc="Opcjonalny stopień trudności (DC)",
        advantage="Rzut z ułatwieniem (Advantage)",
        disadvantage="Rzut z utrudnieniem (Disadvantage)"
    )
    async def check_command(
        self,
        interaction: discord.Interaction,
        cecha: Literal["STR (Siła)", "DEX (Zręczność)", "CON (Kondycja)", "INT (Inteligencja)", "WIS (Mądrość)", "CHA (Charyzma)"],
        dc: Optional[int] = None,
        advantage: Optional[bool] = False,
        disadvantage: Optional[bool] = False
    ):
        """Pobiera modyfikator cechy postaci gracza i wykonuje test d20."""
        stat_name = cecha.split()[0].lower()
        stat_label = cecha.split()[0]
        
        mod = 0
        guild = interaction.guild
        if guild:
            forum = find_forum_channel(guild, "karty-postaci")
            if forum:
                all_threads = await _get_all_forum_threads(forum)
                for t in all_threads:
                    if str(interaction.user.id) in getattr(t, "name", ""):
                        char = await get_character_from_thread(t)
                        if char:
                            mod = char.stats.get_modifier(stat_name)
                        break

        formula = f"1d20{mod:+d}" if mod != 0 else "1d20"
        reason = f"Test cechy {stat_label}"
        
        result = roll_dice(
            formula=formula,
            reason=reason,
            target_dc=dc,
            advantage=advantage or False,
            disadvantage=disadvantage or False
        )
        embed = create_dice_roll_embed(result, interaction.user.display_name)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="initiative",
        description="Wykonuje rzut na inicjatywę z modyfikatorem Zręczności (DEX)"
    )
    @app_commands.describe(
        modyfikator="Opcjonalny dodatkowy modyfikator do inicjatywy"
    )
    async def initiative_command(
        self,
        interaction: discord.Interaction,
        modyfikator: Optional[int] = 0
    ):
        """Rzut na inicjatywę 1d20 + DEX."""
        mod = modyfikator or 0
        guild = interaction.guild
        if guild:
            forum = find_forum_channel(guild, "karty-postaci")
            if forum:
                all_threads = await _get_all_forum_threads(forum)
                for t in all_threads:
                    if str(interaction.user.id) in getattr(t, "name", ""):
                        char = await get_character_from_thread(t)
                        if char:
                            mod += char.stats.get_modifier("dexterity")
                        break

        formula = f"1d20{mod:+d}" if mod != 0 else "1d20"
        result = roll_dice(formula=formula, reason="Inicjatywa")
        embed = create_dice_roll_embed(result, interaction.user.display_name)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MechanicsCog(bot))
