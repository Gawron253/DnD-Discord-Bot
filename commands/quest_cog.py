"""Modul komend slash do zarzadzania zadaniami RPG w #dziennik-zadan."""
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from core.models import QuestItem, QuestObjective, QuestList
from core.discord_db import get_quest_board, update_quest_board
from core.channel_manager import find_text_channel


class QuestGroup(app_commands.Group):
    """Grupa komend slash /quest."""
    def __init__(self):
        super().__init__(name="quest", description="Zarządzanie zadaniami i dziennikiem przygód")

    @app_commands.command(name="create", description="Dodaje nowe zadanie do dziennika zadań")
    @app_commands.describe(
        title="Tytuł zadania",
        giver="Zleceniodawca zadania (np. Karczmarz, Mistrz Gry)",
        description="Szczegółowy opis zadania",
        reward="Nagroda za ukończenie (np. 100 GP, Magiczny Miecz)",
        objectives="Cele oddzielone średnikami (np. Znajdź jaskinię; Pokonaj gobliny)"
    )
    async def create_quest(
        self,
        interaction: discord.Interaction,
        title: str,
        giver: str = "Mistrz Gry",
        description: str = "",
        reward: Optional[str] = None,
        objectives: Optional[str] = None
    ):
        await interaction.response.defer(ephemeral=False)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ Komenda dostępna wyłącznie na serwerze.")
            return

        channel = find_text_channel(guild, "dziennik-zadań") or find_text_channel(guild, "dziennik-zadan")
        if not channel:
            await interaction.followup.send("❌ Nie znaleziono kanału `#dziennik-zadań`. Użyj `/setup-campaign`.")
            return

        quest_board = await get_quest_board(channel)
        
        # Generowanie ID zadania
        next_num = len(quest_board.quests) + 1
        quest_id = f"Q-{next_num:03d}"
        # Upewnij sie o unikalnosci
        existing_ids = {q.id for q in quest_board.quests}
        while quest_id in existing_ids:
            next_num += 1
            quest_id = f"Q-{next_num:03d}"

        # Parsowanie celow
        parsed_objectives = []
        if objectives:
            for obj_text in objectives.split(";"):
                clean = obj_text.strip()
                if clean:
                    parsed_objectives.append(QuestObjective(text=clean, is_completed=False))

        new_quest = QuestItem(
            id=quest_id,
            title=title.strip(),
            giver=giver.strip(),
            description=description.strip(),
            objectives=parsed_objectives,
            reward=reward.strip() if reward else None,
            status="active"
        )

        quest_board.add_quest(new_quest)
        await update_quest_board(channel, quest_board)

        embed = discord.Embed(
            title=f"📜 Nowe Zadanie Dodane: [{new_quest.id}] {new_quest.title}",
            description=new_quest.description or "Brak opisu",
            color=discord.Color.gold()
        )
        embed.add_field(name="Zleceniodawca", value=new_quest.giver, inline=True)
        if new_quest.reward:
            embed.add_field(name="Nagroda", value=new_quest.reward, inline=True)
        if new_quest.objectives:
            embed.add_field(
                name="Cele",
                value="\n".join(f"⬜ {o.text}" for o in new_quest.objectives),
                inline=False
            )
        embed.set_footer(text="Dziennik w #dziennik-zadań został zaktualizowany.")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="complete", description="Oznacza zadanie jako ukończone")
    @app_commands.describe(quest_id_or_title="ID zadania (np. Q-001) lub pełny tytuł")
    async def complete_quest(self, interaction: discord.Interaction, quest_id_or_title: str):
        await interaction.response.defer(ephemeral=False)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ Komenda dostępna wyłącznie na serwerze.")
            return

        channel = find_text_channel(guild, "dziennik-zadań") or find_text_channel(guild, "dziennik-zadan")
        if not channel:
            await interaction.followup.send("❌ Nie znaleziono kanału `#dziennik-zadań`.")
            return

        quest_board = await get_quest_board(channel)
        completed = quest_board.complete_quest(quest_id_or_title)
        if not completed:
            await interaction.followup.send(f"❌ Nie znaleziono zadania odpowiadającego `{quest_id_or_title}`.")
            return

        await update_quest_board(channel, quest_board)

        embed = discord.Embed(
            title=f"🏆 Zadanie Ukończone: [{completed.id}] {completed.title}",
            description=f"Wszystkie cele zadania zostały zrealizowane!",
            color=discord.Color.green()
        )
        if completed.reward:
            embed.add_field(name="💰 Odebrana Nagroda", value=completed.reward, inline=False)
        embed.set_footer(text="Tablica w #dziennik-zadań została zaktualizowana.")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="list", description="Wyświetla listę wszystkich aktywnych i ukończonych zadań")
    async def list_quests(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ Komenda dostępna wyłącznie na serwerze.")
            return

        channel = find_text_channel(guild, "dziennik-zadań") or find_text_channel(guild, "dziennik-zadan")
        if not channel:
            await interaction.followup.send("❌ Nie znaleziono kanału `#dziennik-zadań`.")
            return

        quest_board = await get_quest_board(channel)
        active = quest_board.active_quests()
        completed = quest_board.completed_quests()

        embed = discord.Embed(
            title="📜 Dziennik Zadań Kampanii",
            color=discord.Color.blue()
        )

        if active:
            act_text = []
            for q in active:
                objs = ", ".join(f"[{'x' if o.is_completed else ' '}] {o.text}" for o in q.objectives)
                act_text.append(f"**[{q.id}] {q.title}** (Zleca: *{q.giver}*)\n`Cele:` {objs or 'Brak'}")
            embed.add_field(name="⚔️ Aktywne Zadania", value="\n\n".join(act_text), inline=False)
        else:
            embed.add_field(name="⚔️ Aktywne Zadania", value="*Brak aktywnych zadań.*", inline=False)

        if completed:
            comp_text = [f"• ~~[{q.id}] {q.title}~~" for q in completed]
            embed.add_field(name="🏆 Ukończone Zadania", value="\n".join(comp_text), inline=False)

        await interaction.followup.send(embed=embed)


class QuestCog(commands.Cog):
    """Cog rejestrujacy grupe komend /quest."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.quest_group = QuestGroup()
        # Rejestracja grupy w drzewie komend
        self.bot.tree.add_command(self.quest_group)


async def setup(bot: commands.Bot):
    await bot.add_cog(QuestCog(bot))
