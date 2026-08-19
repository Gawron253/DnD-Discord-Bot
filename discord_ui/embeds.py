"""Moduł generatorów estetycznych Discord Rich Embeds dla postaci, rzutów i zadań."""
from typing import List, Optional
import discord

from core.models import CharacterModel, QuestModel, QuestList, CombatState, DiceRollResult
from mechanics.dice import create_health_bar
from core.discord_db import inject_data_into_text, build_quest_board_embed, encode_zero_width_data


def create_character_sheet_embed(char: CharacterModel) -> discord.Embed:
    """Generuje estetyczny embed karty postaci z paskiem zdrowia ASCII, czystym opisem i ukrytym DATA_JSON."""
    clean_desc = (char.backstory or char.bio or "").strip()
    zw_payload = encode_zero_width_data(char.model_dump())
    full_desc = f"{clean_desc}\n{zw_payload}".strip() if clean_desc else zw_payload

    embed = discord.Embed(
        title=f"🛡️ {char.name} – Poziom {char.level} {char.race} {char.character_class}",
        description=full_desc,
        color=discord.Color.dark_teal()
    )
    if char.avatar_url:
        embed.set_thumbnail(url=char.avatar_url)

    hp_bar = create_health_bar(char.current_hp, char.max_hp)
    hp_display = f"`{hp_bar}`"
    if char.temp_hp > 0:
        hp_display += f" *(+{char.temp_hp} Temp HP)*"

    embed.add_field(
        name="❤️ Żywotność",
        value=hp_display,
        inline=False
    )
    embed.add_field(name="🛡️ Klasa Pancerza (AC)", value=f"**{char.armor_class}**", inline=True)
    embed.add_field(name="⚡ Szybkość", value=f"{char.speed} ft", inline=True)
    embed.add_field(name="💰 Złoto", value=f"**{char.gold_gp}** GP", inline=True)

    s = char.stats
    stats_text = (
        f"**STR:** {s.strength} ({s.get_modifier('strength'):+d}) | "
        f"**DEX:** {s.dexterity} ({s.get_modifier('dexterity'):+d}) | "
        f"**CON:** {s.constitution} ({s.get_modifier('constitution'):+d})\n"
        f"**INT:** {s.intelligence} ({s.get_modifier('intelligence'):+d}) | "
        f"**WIS:** {s.wisdom} ({s.get_modifier('wisdom'):+d}) | "
        f"**CHA:** {s.charisma} ({s.get_modifier('charisma'):+d})"
    )
    embed.add_field(name="📊 Cechy i Modyfikatory", value=stats_text, inline=False)

    if char.inventory:
        inv_items = [f"• {item.name} (x{item.quantity})" for item in char.inventory]
        embed.add_field(name="🎒 Ekwipunek", value="\n".join(inv_items[:10]), inline=False)
    else:
        embed.add_field(name="🎒 Ekwipunek", value="*Pusty ekwipunek*", inline=False)

    # Komórki czarów jeśli postać posiada
    slots = char.spell_slots
    if slots.level_1_max > 0 or slots.level_2_max > 0 or slots.level_3_max > 0:
        slot_lines = []
        if slots.level_1_max > 0:
            slot_lines.append(f"Poz. 1: {'🔷' * slots.level_1}{'🔘' * (slots.level_1_max - slots.level_1)} ({slots.level_1}/{slots.level_1_max})")
        if slots.level_2_max > 0:
            slot_lines.append(f"Poz. 2: {'🔷' * slots.level_2}{'🔘' * (slots.level_2_max - slots.level_2)} ({slots.level_2}/{slots.level_2_max})")
        if slots.level_3_max > 0:
            slot_lines.append(f"Poz. 3: {'🔷' * slots.level_3}{'🔘' * (slots.level_3_max - slots.level_3)} ({slots.level_3}/{slots.level_3_max})")
        embed.add_field(name="✨ Komórki Czarów", value="\n".join(slot_lines), inline=False)

    if char.spells:
        embed.add_field(name="📜 Znane Czary / Sztuczki", value=", ".join(f"`{sp}`" for sp in char.spells), inline=False)

    if char.conditions:
        embed.add_field(name="⚠️ Aktywne Stany", value=", ".join(f"`{c}`" for c in char.conditions), inline=False)

    embed.set_footer(text=f"ID Gracza: {char.discord_user_id} | Synchronizacja Pure Discord DB")
    return embed


# Aliasy dla pełnej kompatybilności wstecznej
build_character_sheet_embed = create_character_sheet_embed


def create_dice_roll_embed(result: DiceRollResult, roller_name: str) -> discord.Embed:
    """Generuje estetyczny embed rzutu kością z odznakami krytycznymi i werdyktem DC."""
    # Kolorystyka: zielony dla sukcesu / krytyka, czerwony dla porażki / krytycznej porażki, niebieski domyślny
    if result.is_crit_success or result.is_success is True:
        color = discord.Color.green()
    elif result.is_crit_failure or result.is_success is False:
        color = discord.Color.red()
    else:
        color = discord.Color.blue()

    title_reason = result.reason or "Rzut kością"
    embed = discord.Embed(
        title=f"🎲 {roller_name} rzuca: {title_reason}",
        color=color
    )
    
    embed.add_field(name="Formuła", value=f"`{result.formula}`", inline=True)
    embed.add_field(name="Wynik", value=f"# **{result.total}**", inline=True)

    if result.is_crit_success:
        embed.add_field(name="Efekt Specjalny", value="🎯 **KRYTYCZNY SUKCES!**", inline=True)
    elif result.is_crit_failure:
        embed.add_field(name="Efekt Specjalny", value="💀 **KRYTYCZNA PORAŻKA!**", inline=True)

    embed.add_field(name="Rozbicie rzutu", value=f"`{result.breakdown}`", inline=False)

    effective_dc = result.dc if result.dc is not None else result.target_dc
    if effective_dc is not None:
        if result.is_success:
            verdict = f"✅ **SUKCES (DC {effective_dc})**"
        else:
            verdict = f"❌ **PORAŻKA (DC {effective_dc})**"
        embed.add_field(name="Stopień trudności (DC)", value=f"DC {effective_dc} ➔ {verdict}", inline=False)

    embed.set_footer(text="Pure Discord Deterministic Dice Engine • 0 AI Tokens")
    return embed


def create_quest_journal_embed(quest_list: QuestList) -> discord.Embed:
    """Generuje estetyczny embed tablicy zadań."""
    return build_quest_board_embed(quest_list)


# Alias
build_quest_board_embed_alias = create_quest_journal_embed
