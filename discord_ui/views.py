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


def compute_5e_character(
    name: str,
    race_and_class: str,
    stats_raw: Optional[str] = None,
    gear_and_gold_raw: Optional[str] = None,
    backstory: Optional[str] = None,
    user_id: str = "0"
) -> CharacterModel:
    """
    Tworzy zbalansowaną postać D&D 5e na 1 poziomie z automatycznym wyliczeniem reguł:
    - Hit Points: Max Hit Die klasy + modyfikator CON (min 1).
    - Armor Class: 10 + modyfikator DEX (lub pancerz początkowy).
    - Proficiency Bonus: +2 na 1 poziomie (2 + (level - 1) // 4).
    - Speed: 25 ft dla Krasnoluda/Niziołka/Gnoma, 30 ft dla pozostałych.
    - Spell Slots: 2 komórki poz. 1 dla pełnych klas czarujących, 1 dla Czarnoksiężnika.
    """
    import re
    from core.models import StatBlock, SpellSlots, ItemModel

    # 1. Parsowanie Rasy i Klasy
    rc_parts = race_and_class.strip().split()
    if len(rc_parts) == 1:
        race = "Człowiek"
        char_class = rc_parts[0].capitalize()
    elif len(rc_parts) >= 2:
        race = rc_parts[0].capitalize()
        char_class = " ".join(rc_parts[1:]).capitalize()
    else:
        race = "Człowiek"
        char_class = "Wojownik"

    class_lower = char_class.lower()
    race_lower = race.lower()

    # 2. Parsowanie Cech (STR, DEX, CON, INT, WIS, CHA)
    default_stats = [15, 14, 13, 12, 10, 8]
    parsed_nums = []
    if stats_raw:
        found_nums = re.findall(r"\b\d+\b", stats_raw)
        for n in found_nums:
            try:
                val = int(n)
                if 1 <= val <= 30:
                    parsed_nums.append(val)
            except ValueError:
                pass

    if len(parsed_nums) < 6:
        parsed_nums = (parsed_nums + default_stats[len(parsed_nums):])[:6]
    else:
        parsed_nums = parsed_nums[:6]

    stats = StatBlock(
        strength=parsed_nums[0],
        dexterity=parsed_nums[1],
        constitution=parsed_nums[2],
        intelligence=parsed_nums[3],
        wisdom=parsed_nums[4],
        charisma=parsed_nums[5]
    )

    con_mod = stats.get_modifier("constitution")
    dex_mod = stats.get_modifier("dexterity")

    # 3. Hit Die per Class & Max HP
    if "barbar" in class_lower:
        hit_die = 12
    elif any(k in class_lower for k in ["wojownik", "fighter", "paladyn", "paladin", "łowca", "tropiciel", "ranger"]):
        hit_die = 10
    elif any(k in class_lower for k in ["kleryk", "kapłan", "cleric", "druid", "łotr", "złodziej", "rogue", "bard", "mnich", "monk", "czarnoksiężnik", "warlock"]):
        hit_die = 8
    elif any(k in class_lower for k in ["mag", "czarodziej", "wizard", "zaklinacz", "sorcerer"]):
        hit_die = 6
    else:
        hit_die = 8

    max_hp = max(1, hit_die + con_mod)

    # 4. Armor Class
    if any(k in class_lower for k in ["paladyn", "paladin", "wojownik", "fighter"]):
        armor_class = max(10 + dex_mod, 14)
    elif "barbar" in class_lower:
        armor_class = 10 + dex_mod + con_mod
    elif "mnich" in class_lower or "monk" in class_lower:
        wis_mod = stats.get_modifier("wisdom")
        armor_class = 10 + dex_mod + wis_mod
    else:
        armor_class = 10 + dex_mod

    # 5. Speed per Race
    if any(r in race_lower for r in ["krasnolud", "dwarf", "niziołek", "halfling", "gnom", "gnome"]):
        speed = 25
    else:
        speed = 30

    # 6. Spell Slots
    spell_slots = SpellSlots()
    spells = []
    if any(k in class_lower for k in ["mag", "czarodziej", "wizard", "zaklinacz", "sorcerer", "kleryk", "kapłan", "cleric", "druid", "bard"]):
        spell_slots = SpellSlots(level_1=2, level_1_max=2)
        if "mag" in class_lower or "wizard" in class_lower:
            spells = ["Magiczny Pocisk", "Tarcza", "Promień Mrozu", "Światło"]
        elif "zaklinacz" in class_lower or "sorcerer" in class_lower:
            spells = ["Fala Dźwiękowa", "Tarcza", "Ognisty Pocisk"]
        elif "kleryk" in class_lower or "cleric" in class_lower:
            spells = ["Leczenie Ran", "Błogosławieństwo", "Święty Płomień"]
        elif "druid" in class_lower:
            spells = ["Leczenie Ran", "Splot Cierni", "Pochodnia"]
        elif "bard" in class_lower:
            spells = ["Leczenie Ran", "Drwiący Śmiech", "Światła Tańczące"]
    elif "czarnoksiężnik" in class_lower or "warlock" in class_lower:
        spell_slots = SpellSlots(level_1=1, level_1_max=1)
        spells = ["Mistyczny Pocisk", "Urok", "Znak Wiedźmy"]

    # 7. Inventory & Gold
    gold_gp = 15
    inventory = []
    if gear_and_gold_raw:
        gold_match = re.search(r"(\d+)\s*(?:gp|złot|sztuk złota|gold)", gear_and_gold_raw, re.IGNORECASE)
        if gold_match:
            gold_gp = int(gold_match.group(1))

        raw_items = re.split(r"[,;\n]+", gear_and_gold_raw)
        for itm in raw_items:
            itm_clean = itm.strip()
            if not itm_clean or re.match(r"^\d+\s*(?:gp|złot|sztuk złota|gold)$", itm_clean, re.IGNORECASE):
                continue
            qty_match = re.search(r"(?:x\s*(\d+)|\((\d+)\)|(\d+)\s*x)", itm_clean, re.IGNORECASE)
            quantity = 1
            if qty_match:
                q_str = qty_match.group(1) or qty_match.group(2) or qty_match.group(3)
                if q_str:
                    quantity = int(q_str)
                itm_clean = re.sub(r"(?:x\s*\d+|\(\d+\)|\d+\s*x)", "", itm_clean).strip()
            
            if itm_clean:
                inventory.append(ItemModel(name=itm_clean, quantity=quantity))

    if not inventory:
        if "mag" in class_lower or "wizard" in class_lower:
            inventory = [
                ItemModel(name="Kostur czarodzieja", quantity=1, item_type="weapon"),
                ItemModel(name="Księga zaklęć", quantity=1, item_type="equipment"),
                ItemModel(name="Pusty kałamarz i pióro", quantity=1, item_type="misc"),
                ItemModel(name="Zestaw uczonego", quantity=1, item_type="equipment")
            ]
        elif "wojownik" in class_lower or "fighter" in class_lower or "paladyn" in class_lower:
            inventory = [
                ItemModel(name="Miecz długi", quantity=1, item_type="weapon"),
                ItemModel(name="Tarcza", quantity=1, item_type="armor"),
                ItemModel(name="Pancerz łuskowy", quantity=1, item_type="armor"),
                ItemModel(name="Plecak podróżnika", quantity=1, item_type="equipment")
            ]
        elif "łotr" in class_lower or "rogue" in class_lower:
            inventory = [
                ItemModel(name="Rapier", quantity=1, item_type="weapon"),
                ItemModel(name="Krótki łuk", quantity=1, item_type="weapon"),
                ItemModel(name="Narzędzia złodziejskie", quantity=1, item_type="equipment"),
                ItemModel(name="Zbroja skórzana", quantity=1, item_type="armor")
            ]
        else:
            inventory = [
                ItemModel(name="Broń podstawowa", quantity=1, item_type="weapon"),
                ItemModel(name="Plecak podróżny", quantity=1, item_type="equipment"),
                ItemModel(name="Racje żywnościowe", quantity=5, item_type="consumable")
            ]

    clean_name = name.strip() or "Nieznany Bohater"
    clean_backstory = backstory.strip() if backstory and backstory.strip() else None

    return CharacterModel(
        discord_user_id=str(user_id),
        name=clean_name,
        character_class=char_class,
        race=race,
        level=1,
        xp=0,
        current_hp=max_hp,
        max_hp=max_hp,
        temp_hp=0,
        armor_class=armor_class,
        speed=speed,
        proficiency_bonus=2,
        stats=stats,
        spell_slots=spell_slots,
        inventory=inventory,
        gold_gp=gold_gp,
        conditions=[],
        backstory=clean_backstory,
        bio=clean_backstory,
        spells=spells
    )


class CharacterCreateModal(discord.ui.Modal, title="Kreator Postaci D&D 5e"):
    """Interaktywny formularz tworzenia nowej postaci gracza w Discordzie."""

    name_input = discord.ui.TextInput(
        label="Imię postaci",
        placeholder="np. Thorin Kamienna Tarcza, Elora, Gareth",
        required=True,
        max_length=100
    )
    race_class_input = discord.ui.TextInput(
        label="Rasa i Klasa",
        placeholder="np. Krasnolud Wojownik, Elf Mag, Człowiek Paladyn",
        required=True,
        max_length=100
    )
    stats_input = discord.ui.TextInput(
        label="Cechy: STR, DEX, CON, INT, WIS, CHA",
        placeholder="np. 15, 14, 13, 12, 10, 8 (puste = standard array)",
        required=False,
        max_length=100
    )
    gear_gold_input = discord.ui.TextInput(
        label="Ekwipunek i Złoto (opcjonalnie)",
        placeholder="np. Miecz długi, Tarcza, Kolczuga; 50 GP",
        required=False,
        max_length=300
    )
    backstory_input = discord.ui.TextInput(
        label="Historia / Opis postaci (Backstory)",
        style=discord.TextStyle.paragraph,
        placeholder="Krótki opis wyglądu, pochodzenia lub charakteru postaci...",
        required=False,
        max_length=1500
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=False)

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ Komenda dostępna wyłącznie na serwerze.")
            return

        from core.channel_manager import find_forum_channel
        from core.discord_db import get_or_create_character_sheet, update_character_sheet

        forum = find_forum_channel(guild, "karty-postaci")
        if not forum:
            await interaction.followup.send("❌ Nie znaleziono forum `#karty-postaci`. Użyj `/setup-campaign`.")
            return

        name_val = str(self.name_input.value or getattr(self.name_input, "_value", None) or getattr(self.name_input, "default", "") or "")
        race_class_val = str(self.race_class_input.value or getattr(self.race_class_input, "_value", None) or getattr(self.race_class_input, "default", "") or "")
        stats_val = str(self.stats_input.value or getattr(self.stats_input, "_value", None) or getattr(self.stats_input, "default", "") or "")
        gear_gold_val = str(self.gear_gold_input.value or getattr(self.gear_gold_input, "_value", None) or getattr(self.gear_gold_input, "default", "") or "")
        backstory_val = str(self.backstory_input.value or getattr(self.backstory_input, "_value", None) or getattr(self.backstory_input, "default", "") or "")

        char = compute_5e_character(
            name=name_val,
            race_and_class=race_class_val,
            stats_raw=stats_val,
            gear_and_gold_raw=gear_gold_val,
            backstory=backstory_val,
            user_id=str(interaction.user.id)
        )

        thread, msg, created_char = await get_or_create_character_sheet(forum, str(interaction.user.id), character=char)
        
        # Jeśli wątek już istniał pod inną nazwą lub inną postacią, zaktualizuj
        if created_char.name != char.name or created_char.character_class != char.character_class:
            await update_character_sheet(thread, char, reason="Utworzenie nowej postaci przez Kreator")
            try:
                await thread.edit(name=f"🛡️ {char.name} ({interaction.user.id})")
            except Exception:
                pass

        embed = create_character_sheet_embed(char)
        view = CharacterSheetView(character=char)
        await interaction.followup.send(
            content=f"🎉 **Postać {char.name} została pomyślnie utworzona!** Karta zapisana w wątku: #{thread.name}",
            embed=embed,
            view=view
        )


class CharacterEditModal(discord.ui.Modal, title="Edycja Postaci"):
    """Modal do szybkiej edycji podstawowych danych postaci."""

    name_input = discord.ui.TextInput(
        label="Imię postaci",
        required=False,
        max_length=100
    )
    race_input = discord.ui.TextInput(
        label="Rasa",
        required=False,
        max_length=50
    )
    class_input = discord.ui.TextInput(
        label="Klasa",
        required=False,
        max_length=50
    )
    hp_ac_speed_input = discord.ui.TextInput(
        label="Max HP, AC, Speed (np. 25, 16, 30)",
        required=False,
        max_length=50
    )
    backstory_input = discord.ui.TextInput(
        label="Historia / Opis (Backstory)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1500
    )

    def __init__(self, character: CharacterModel, thread: discord.Thread):
        super().__init__()
        self.character = character
        self.thread = thread
        self.name_input.default = character.name
        self.race_input.default = character.race
        self.class_input.default = character.character_class
        self.hp_ac_speed_input.default = f"{character.max_hp}, {character.armor_class}, {character.speed}"
        self.backstory_input.default = character.backstory or character.bio or ""

    async def on_submit(self, interaction: discord.Interaction):
        import re
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=False)

        name_val = str(self.name_input.value or getattr(self.name_input, "_value", None) or getattr(self.name_input, "default", "") or "")
        race_val = str(self.race_input.value or getattr(self.race_input, "_value", None) or getattr(self.race_input, "default", "") or "")
        class_val = str(self.class_input.value or getattr(self.class_input, "_value", None) or getattr(self.class_input, "default", "") or "")
        hp_speed_val = str(self.hp_ac_speed_input.value or getattr(self.hp_ac_speed_input, "_value", None) or getattr(self.hp_ac_speed_input, "default", "") or "")
        backstory_val = str(self.backstory_input.value or getattr(self.backstory_input, "_value", None) or getattr(self.backstory_input, "default", "") or "")

        changed = []
        if name_val and name_val.strip() != self.character.name:
            self.character.name = name_val.strip()
            changed.append(f"Imię -> {self.character.name}")
            try:
                await self.thread.edit(name=f"🛡️ {self.character.name} ({self.character.discord_user_id})")
            except Exception:
                pass

        if race_val and race_val.strip() != self.character.race:
            self.character.race = race_val.strip()
            changed.append(f"Rasa -> {self.character.race}")

        if class_val and class_val.strip() != self.character.character_class:
            self.character.character_class = class_val.strip()
            changed.append(f"Klasa -> {self.character.character_class}")

        if hp_speed_val:
            nums = [int(x) for x in re.findall(r"\b\d+\b", hp_speed_val)]
            if len(nums) >= 1:
                self.character.max_hp = max(1, nums[0])
                self.character.current_hp = min(self.character.current_hp, self.character.max_hp)
                changed.append(f"Max HP -> {self.character.max_hp}")
            if len(nums) >= 2:
                self.character.armor_class = max(1, nums[1])
                changed.append(f"AC -> {self.character.armor_class}")
            if len(nums) >= 3:
                self.character.speed = max(0, nums[2])
                changed.append(f"Speed -> {self.character.speed} ft")

        if backstory_val:
            self.character.backstory = backstory_val.strip()
            self.character.bio = self.character.backstory
            changed.append("Historia/Bio")

        reason_str = f"Edycja postaci: {', '.join(changed)}" if changed else "Edycja postaci (bez zmian)"
        from core.discord_db import update_character_sheet
        await update_character_sheet(self.thread, self.character, reason=reason_str)

        embed = create_character_sheet_embed(self.character)
        view = CharacterSheetView(character=self.character)
        await interaction.followup.send(
            content=f"✅ **Karta postaci {self.character.name} została zaktualizowana!**",
            embed=embed,
            view=view
        )

