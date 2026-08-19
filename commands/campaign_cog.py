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

    @app_commands.command(
        name="kronika",
        description="Generuje podsumowanie bieżących wydarzeń ze stołu gry i zapisuje wpis w #kronika-przygod"
    )
    async def chronicle_recap(self, interaction: discord.Interaction):
        """Generuje podsumowanie minionego rozdziału i zapisuje je w kronice bez duplikatów."""
        await interaction.response.defer(ephemeral=False)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ Ta komenda może być użyta tylko na serwerze.")
            return

        table_ch = None
        kronika_ch = None
        for ch in getattr(guild, "text_channels", []):
            norm = ch.name.replace("-", "").replace("_", "").replace("ó", "o").replace("ł", "l").lower()
            if "stol" in norm:
                table_ch = ch
            elif "kronika" in norm:
                kronika_ch = ch

        if not table_ch:
            await interaction.followup.send("❌ Nie znaleziono kanału `#stół-gry`.")
            return

        # 1. Sprawdź kotwicę ostatniego podsumowanego wpisu w kronice
        last_recorded_msg_id = None
        if kronika_ch and hasattr(kronika_ch, "history"):
            try:
                async for kmsg in kronika_ch.history(limit=5, oldest_first=False):
                    if getattr(kmsg, "embeds", None):
                        for emb in kmsg.embeds:
                            if getattr(emb, "footer", None) and getattr(emb.footer, "text", None) and "LAST_MSG_ID:" in emb.footer.text:
                                try:
                                    last_recorded_msg_id = int(emb.footer.text.split("LAST_MSG_ID:")[1].strip())
                                    break
                                except Exception:
                                    pass
                    if last_recorded_msg_id:
                        break
            except Exception:
                pass

        # 2. Pobierz nowe wiadomości ze stołu gry od ostatniej kotwicy
        msgs = []
        latest_msg_id = None
        if hasattr(table_ch, "history"):
            try:
                if last_recorded_msg_id:
                    after_obj = discord.Object(id=last_recorded_msg_id)
                    async for m in table_ch.history(limit=40, after=after_obj, oldest_first=True):
                        latest_msg_id = m.id
                        if m.content and not getattr(m.author, "bot", False):
                            msgs.append(f"[{m.author.display_name}]: {m.content}")
                        elif m.content and getattr(m.author, "bot", False):
                            msgs.append(f"[Mistrz Gry]: {m.content[:300]}")
                else:
                    async for m in table_ch.history(limit=30, oldest_first=True):
                        latest_msg_id = m.id
                        if m.content and not getattr(m.author, "bot", False):
                            msgs.append(f"[{m.author.display_name}]: {m.content}")
                        elif m.content and getattr(m.author, "bot", False):
                            msgs.append(f"[Mistrz Gry]: {m.content[:300]}")
            except Exception:
                pass

        # 3. Weryfikacja czy nastąpiły nowe akcje graczy
        player_actions_count = sum(1 for m in msgs if not m.startswith("[Mistrz Gry]"))
        if not msgs or player_actions_count < 1:
            await interaction.followup.send("ℹ️ Brak nowych wydarzeń na stole gry do podsumowania w Kronice (wszystko jest aktualne!).")
            return

        events_text = "\n".join(msgs)
        from config.prompts import CHRONICLER_SYSTEM_PROMPT
        from ai.gemini_client import default_gemini_client

        prompt = (
            f"Oto zapis nowych wydarzeń ze stołu gry:\n{events_text}\n\n"
            f"Stwórz epickie, podniosłe podsumowanie tego rozdziału dla Kroniki Przygód (główne wydarzenia, odkrycia, nowe lokacje i cele drużyny)."
        )
        recap_text, _ = await default_gemini_client.generate_narrative(
            context_prompt=prompt,
            system_prompt=CHRONICLER_SYSTEM_PROMPT
        )

        embed = discord.Embed(
            title="📖 Nowy Rozdział w Kronice Przygód",
            description=recap_text,
            color=discord.Color.gold()
        )
        footer_id = f"LAST_MSG_ID: {latest_msg_id}" if latest_msg_id else "LAST_MSG_ID: 0"
        embed.set_footer(text=f"Spisane przez Nadwornego Kronikarza • {footer_id}")

        if kronika_ch:
            await kronika_ch.send(embed=embed)
            await interaction.followup.send(f"✅ Podsumowanie rozdziału zostało pomyślnie zapisane w kanale {kronika_ch.mention}!", embed=embed)
        else:
            await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(CampaignCog(bot))
