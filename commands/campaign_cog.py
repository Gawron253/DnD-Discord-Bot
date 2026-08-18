"""Modul komend slash zwiazanych z zarzadzaniem kampania i zasadami."""
import discord
from discord import app_commands
from discord.ext import commands

from core.channel_manager import setup_campaign_infrastructure
from core.discord_db import fetch_campaign_rules


class CampaignCog(commands.Cog):
    """Cog obslugujacy komendy konfiguracji kampanii i podgladu zasad."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="setup-campaign",
        description="Automatycznie tworzy pełną strukturę kanałów, forów i zasad dla sesji RPG"
    )
    async def setup_campaign(self, interaction: discord.Interaction):
        """Tworzy lub synchronizuje hierarchie kanalow kampanii RPG."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ Ta komenda może być użyta tylko na serwerze (Guild).", ephemeral=True)
            return

        try:
            report = await setup_campaign_infrastructure(guild)
            embed = discord.Embed(
                title="🏰 Konfiguracja Kampanii D&D Zakończona Sukcesem!",
                color=discord.Color.green()
            )
            
            created_lines = []
            if report["categories_created"]:
                created_lines.extend([f"📁 **Kategoria:** {cat}" for cat in report["categories_created"]])
            if report["channels_created"]:
                created_lines.extend([f"  └ {ch}" for ch in report["channels_created"]])
            if report["forums_created"]:
                created_lines.extend([f"  └ {f}" for f in report["forums_created"]])

            if created_lines:
                embed.add_field(
                    name="✨ Nowo Utworzone Elementy",
                    value="\n".join(created_lines),
                    inline=False
                )

            if report["reused"]:
                embed.add_field(
                    name="♻️ Wykryte i Zachowane Elementy",
                    value="\n".join(report["reused"][:15]),
                    inline=False
                )

            if report["initialized_pins"]:
                embed.add_field(
                    name="📌 Zainicjalizowane Przypięcia",
                    value="\n".join(f"• {p}" for p in report["initialized_pins"]),
                    inline=False
                )

            embed.set_footer(text="Pure Discord State Architecture • Wszystkie stany zapisane w Discordzie")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Błąd podczas konfiguracji kampanii: {e}", ephemeral=True)

    @app_commands.command(
        name="zasady",
        description="Wyświetla aktualne reguły i zasady kampanii z kanału #zasady-i-mechanika"
    )
    async def show_rules(self, interaction: discord.Interaction):
        """Wyswietla biezace reguly kampanii odczytane w locie z Discorda."""
        await interaction.response.defer(ephemeral=False)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ Ta komenda może być użyta tylko na serwerze.")
            return

        rules_text = await fetch_campaign_rules(guild)
        embed = discord.Embed(
            title="📜 Aktualne Zasady Kampanii i Świata",
            description=rules_text,
            color=discord.Color.blue()
        )
        embed.set_footer(text="Edytuj przypięty post w #zasady-i-mechanika, aby zmienić reguły w locie!")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(CampaignCog(bot))
