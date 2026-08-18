"""Interaktywne komponenty UI (View, Button, Modal) dla Discord.py.
Umożliwiają natychmiastowe wykonywanie rzutów i akcji mechanicznych w 100% kodem Pythona.
"""
from typing import Optional, List, Dict, Any
import discord

from mechanics.dice import roll_dice
from discord_ui.embeds import create_dice_roll_embed, create_character_sheet_embed
from core.models import CharacterModel


class RollButton(discord.ui.Button):
    """Przycisk wykonujący deterministyczny rzut kością w czystym kodzie Pythona (0 tokenów AI)."""

    def __init__(
        self,
        label: str = "Rzut",
        formula: str = "1d20",
        reason: str = "Rzut testowy",
        dc: Optional[int] = None,
        advantage: bool = False,
        disadvantage: bool = False,
        style: discord.ButtonStyle = discord.ButtonStyle.primary,
        custom_id: Optional[str] = None
    ):
        super().__init__(label=label, style=style, emoji="🎲", custom_id=custom_id)
        self.formula = formula or "1d20"
        self.reason = reason or label or "Rzut testowy"
        self.dc = dc
        self.advantage = advantage
        self.disadvantage = disadvantage

    async def callback(self, interaction: discord.Interaction):
        # 100% deterministyczny losowy rzut kodem Pythona
        result = roll_dice(
            formula=self.formula,
            reason=self.reason,
            target_dc=self.dc,
            advantage=self.advantage,
            disadvantage=self.disadvantage
        )
        embed = create_dice_roll_embed(result, interaction.user.display_name)

        # Publikacja wyniku rzutu
        await interaction.response.send_message(
            f"🎲 **{interaction.user.display_name}** rzuca na `{self.reason}`:",
            embed=embed
        )


class NarrativeActionView(discord.ui.View):
    """Widok z dynamicznymi przyciskami sugerowanych akcji generowanymi przez AI lub DM pod narracją."""

    def __init__(self, action_buttons: Optional[List[Dict[str, Any]]] = None, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        if not action_buttons:
            return

        for idx, act in enumerate(action_buttons):
            if not isinstance(act, dict):
                continue
            
            # Bezpieczne wyciąganie pól z wartościami domyślnymi
            label = act.get("label") or "Rzut"
            formula = act.get("formula") or "1d20"
            reason = act.get("reason") or label or "Test"
            dc = act.get("dc")
            adv = act.get("advantage", False)
            disadv = act.get("disadvantage", False)

            # Rozmieszczenie w rzędach (maksymalnie 5 przycisków na rząd wg specyfikacji Discord)
            row = min(4, idx // 5)
            btn = RollButton(
                label=label[:80],  # Discord limit długości labela
                formula=formula,
                reason=reason,
                dc=dc,
                advantage=adv,
                disadvantage=disadv
            )
            btn.row = row
            self.add_item(btn)


class CharacterSheetView(discord.ui.View):
    """Widok interaktywny dołączany do karty postaci z przyciskami szybkich akcji."""

    def __init__(self, character: Optional[CharacterModel] = None, timeout: Optional[float] = 180):
        super().__init__(timeout=timeout)
        self.character = character

    @discord.ui.button(label="Inicjatywa (DEX)", style=discord.ButtonStyle.secondary, emoji="⚡", row=0)
    async def roll_initiative(self, interaction: discord.Interaction, button: discord.ui.Button):
        mod = self.character.stats.get_modifier("dexterity") if self.character else 0
        formula = f"1d20{mod:+d}" if mod != 0 else "1d20"
        result = roll_dice(formula=formula, reason="Inicjatywa")
        embed = create_dice_roll_embed(result, interaction.user.display_name)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Percepcja (WIS)", style=discord.ButtonStyle.secondary, emoji="👁️", row=0)
    async def roll_perception(self, interaction: discord.Interaction, button: discord.ui.Button):
        mod = self.character.stats.get_modifier("wisdom") if self.character else 0
        formula = f"1d20{mod:+d}" if mod != 0 else "1d20"
        result = roll_dice(formula=formula, reason="Test Percepcji")
        embed = create_dice_roll_embed(result, interaction.user.display_name)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Atak Bronią", style=discord.ButtonStyle.primary, emoji="⚔️", row=0)
    async def roll_attack(self, interaction: discord.Interaction, button: discord.ui.Button):
        mod = self.character.stats.get_modifier("strength") if self.character else 0
        prof = self.character.proficiency_bonus if self.character else 2
        total_mod = mod + prof
        formula = f"1d20{total_mod:+d}" if total_mod != 0 else "1d20"
        result = roll_dice(formula=formula, reason="Rzut na Atak")
        embed = create_dice_roll_embed(result, interaction.user.display_name)
        await interaction.response.send_message(embed=embed)
