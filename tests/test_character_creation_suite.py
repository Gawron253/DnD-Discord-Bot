"""Kompleksowy zestaw testów jednostkowych i integracyjnych dla pakietu tworzenia i edycji postaci (R1, R2, R3, R4).
Pokrywa:
- R1: Czyste embedy i ukrywanie DATA_JSON (Zero-Width steganografia, brak widocznych komentarzy technicznych, wsteczna kompatybilność)
- R2: Interaktywny Kreator Postaci (/create-character modal, obliczanie reguł D&D 5e: Hit Die, AC, Speed, Biegłość, Czary)
- R3: AI Generator Postaci (/generate-character <opis>, GeminiClient.generate_character, offline fallback, mocki)
- R4: Komenda Edycji Postaci (/character-edit, selektywna aktualizacja, zachowanie ekwipunku i złota, wpisy audytowe w wątku)
- Przypadki brzegowe, polskie znaki diakrytyczne, odarchiwizowywanie wątków i walidacja uprawnień.
"""
import json
import pytest
import discord
from discord.ext import commands

from core.models import CharacterModel, StatBlock, ItemModel, SpellSlots
from core.discord_db import (
    encode_zero_width_data,
    decode_zero_width_data,
    extract_data_from_text,
    inject_data_into_text,
    extract_data_from_message_or_embed,
    build_character_sheet_embed,
    get_or_create_character_sheet,
    update_character_sheet,
    get_character_from_thread
)
from discord_ui.embeds import create_character_sheet_embed
from discord_ui.views import (
    compute_5e_character,
    CharacterCreateModal,
    CharacterEditModal,
    CharacterSheetView
)
from config.prompts import CHARACTER_GENERATOR_SYSTEM_PROMPT
from ai.gemini_client import GeminiClient, generate_character as ai_generate_character
from commands.character_cog import CharacterCog
from tests.mock_discord import (
    MockGuild,
    MockForumChannel,
    MockTextChannel,
    MockThread,
    MockMessage,
    MockUser,
    MockEmbed,
    MockInteraction
)
from tests.mock_ai import MockGeminiClient


# ==============================================================================
# R1: Czyste Embedy & DATA_JSON Hiding (Zero-Width Steganography & Backwards Compat)
# ==============================================================================

class TestR1CleanEmbedsAndDataHiding:
    """Testy kodowania steganograficznego, eliminacji widocznego DATA_JSON oraz kompatybilności wstecznej."""

    def test_zero_width_roundtrip_simple(self):
        data = {"name": "Gimli", "hp": 25, "level": 3}
        encoded = encode_zero_width_data(data)
        assert "<!-- DATA_JSON:" not in encoded
        decoded = decode_zero_width_data(encoded)
        assert decoded == data

    def test_zero_width_roundtrip_with_polish_diacritics_and_special_chars(self):
        data = {
            "name": "Żelisław z Łodzi",
            "race": "Półelf",
            "character_class": "Czarnoksiężnik",
            "backstory": "„Gdy zapada zmrok, cienie budzą się do życia...” — rzekł mędrzec.\nLinia 2 z polskimi znakami: ąęćłńóśźż."
        }
        encoded = encode_zero_width_data(data)
        decoded = decode_zero_width_data(encoded)
        assert decoded == data
        assert decoded["name"] == "Żelisław z Łodzi"
        assert decoded["character_class"] == "Czarnoksiężnik"

    def test_extract_data_from_text_zero_width_priority(self):
        data = {"name": "Thorin", "gold": 100}
        zw_str = f"To jest widoczny opis postaci.\n{encode_zero_width_data(data)}"
        extracted = extract_data_from_text(zw_str)
        assert extracted is not None
        assert extracted["name"] == "Thorin"
        assert extracted["gold"] == 100

    def test_extract_data_from_text_legacy_backward_compatibility(self):
        legacy_data = {"name": "Legolas", "level": 5}
        legacy_text = f"Opis elfa\n<!-- DATA_JSON: {json.dumps(legacy_data)} -->"
        extracted = extract_data_from_text(legacy_text)
        assert extracted is not None
        assert extracted["name"] == "Legolas"
        assert extracted["level"] == 5

    def test_embed_description_does_not_contain_visible_html_comment(self):
        char = CharacterModel(
            discord_user_id="111",
            name="Aethelgard",
            character_class="Mag",
            race="Elf",
            backstory="Urodzony w wieży arkanów w Srebrzystym Lesie."
        )
        embed = create_character_sheet_embed(char)
        assert "<!-- DATA_JSON:" not in embed.description
        assert "Urodzony w wieży arkanów w Srebrzystym Lesie." in embed.description

        # Weryfikacja bezstratnego odczytu z embedu
        msg = MockMessage(embed=embed)
        extracted = extract_data_from_message_or_embed(msg)
        assert extracted is not None
        assert extracted["name"] == "Aethelgard"
        assert extracted["character_class"] == "Mag"
        assert extracted["backstory"] == "Urodzony w wieży arkanów w Srebrzystym Lesie."

    def test_character_model_extended_fields_defaults(self):
        char = CharacterModel(
            discord_user_id="222",
            name="Bezimienny",
            character_class="Wojownik",
            race="Człowiek"
        )
        assert char.backstory is None
        assert char.bio is None
        assert char.spells == []
        assert char.background is None
        assert char.alignment is None

    def test_embed_shows_known_spells_when_present(self):
        char = CharacterModel(
            discord_user_id="333",
            name="Elora",
            character_class="Mag",
            race="Elf",
            spells=["Magiczny Pocisk", "Tarcza", "Promień Mrozu"]
        )
        embed = create_character_sheet_embed(char)
        field_names = [f.name for f in embed.fields]
        assert any("Znane Czary" in f for f in field_names)
        spell_field = next(f for f in embed.fields if "Znane Czary" in f.name)
        assert "Magiczny Pocisk" in spell_field.value
        assert "Tarcza" in spell_field.value


# ==============================================================================
# R2: Interaktywny Kreator Postaci & Obliczanie Reguł D&D 5e
# ==============================================================================

class TestR2CharacterCreationModalAnd5eRules:
    """Testy automatycznego obliczania statystyk 5e i interakcji z modalem /create-character."""

    def test_compute_5e_barbarian_hit_die_12(self):
        char = compute_5e_character(
            name="Conan",
            race_and_class="Człowiek Barbarzyńca",
            stats_raw="16, 14, 16, 8, 12, 8",  # CON = 16 (mod +3)
            gear_and_gold_raw="Wielki topór; 20 GP",
            backstory="Wojownik z mroźnej północy.",
            user_id="1001"
        )
        # Barbarian: Hit Die 12 + CON mod (+3) = 15 HP
        assert char.max_hp == 15
        assert char.current_hp == 15
        assert char.character_class == "Barbarzyńca"
        # Barbarian Unarmored Defense: 10 + DEX mod (+2) + CON mod (+3) = 15 AC
        assert char.armor_class == 15
        assert char.speed == 30
        assert char.proficiency_bonus == 2
        assert char.gold_gp == 20
        assert char.backstory == "Wojownik z mroźnej północy."

    def test_compute_5e_fighter_hit_die_10(self):
        char = compute_5e_character(
            name="Thorin",
            race_and_class="Krasnolud Wojownik",
            stats_raw="16, 12, 16, 10, 12, 8",  # CON = 16 (+3), DEX = 12 (+1)
            gear_and_gold_raw="Topór bojowy, Tarcza; 30 GP",
            user_id="1002"
        )
        # Fighter: Hit Die 10 + CON mod (+3) = 13 HP
        assert char.max_hp == 13
        assert char.speed == 25  # Krasnolud = 25 ft
        assert char.armor_class >= 14  # Armor starter
        assert char.proficiency_bonus == 2
        assert char.gold_gp == 30

    def test_compute_5e_wizard_hit_die_6_and_spell_slots(self):
        char = compute_5e_character(
            name="Mordenkainen",
            race_and_class="Elf Mag",
            stats_raw="8, 14, 14, 16, 12, 10",  # CON = 14 (+2), DEX = 14 (+2)
            user_id="1003"
        )
        # Wizard: Hit Die 6 + CON mod (+2) = 8 HP
        assert char.max_hp == 8
        assert char.armor_class == 12  # 10 + DEX (+2)
        assert char.spell_slots.level_1 == 2
        assert char.spell_slots.level_1_max == 2
        assert len(char.spells) >= 2
        assert "Magiczny Pocisk" in char.spells

    def test_compute_5e_rogue_hit_die_8_and_halfling_speed(self):
        char = compute_5e_character(
            name="Bilbo",
            race_and_class="Niziołek Łotr",
            stats_raw="10, 16, 14, 12, 12, 10",
            user_id="1004"
        )
        # Rogue: Hit Die 8 + CON mod (+2) = 10 HP
        assert char.max_hp == 10
        assert char.speed == 25  # Niziołek = 25 ft
        assert char.spell_slots.level_1_max == 0

    def test_compute_5e_warlock_spell_slots(self):
        char = compute_5e_character(
            name="Malakor",
            race_and_class="Diabelstwo Czarnoksiężnik",
            stats_raw="10, 14, 14, 12, 10, 16",
            user_id="1005"
        )
        # Warlock: Hit Die 8 + CON (+2) = 10 HP
        assert char.max_hp == 10
        assert char.spell_slots.level_1 == 1
        assert char.spell_slots.level_1_max == 1

    def test_compute_5e_fallback_standard_array_when_stats_empty(self):
        char = compute_5e_character(
            name="Gareth",
            race_and_class="Człowiek Paladyn",
            stats_raw="",  # Standard array: 15, 14, 13, 12, 10, 8
            user_id="1006"
        )
        assert char.stats.strength == 15
        assert char.stats.dexterity == 14
        assert char.stats.constitution == 13
        assert char.stats.intelligence == 12
        assert char.stats.wisdom == 10
        assert char.stats.charisma == 8
        # Paladin Hit Die 10 + CON mod (+1) = 11 HP
        assert char.max_hp == 11

    @pytest.mark.asyncio
    async def test_slash_command_create_character_opens_modal(self):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        cog = CharacterCog(bot)

        user = MockUser(id=5555, name="Gracz1")
        interaction = MockInteraction(user=user)

        # Wywołanie komendy /create-character
        await cog.create_character.callback(cog, interaction)

        assert interaction.response.sent_modal is not None
        assert isinstance(interaction.response.sent_modal, CharacterCreateModal)

    @pytest.mark.asyncio
    async def test_character_create_modal_submit_creates_forum_thread(self):
        guild = MockGuild(name="Kampania RPG")
        forum = await guild.create_forum("karty-postaci")

        user = MockUser(id=7777, name="Alden", display_name="Alden")
        interaction = MockInteraction(user=user, guild=guild)

        modal = CharacterCreateModal()
        modal.name_input._value = "Alden Szybki"
        modal.race_class_input._value = "Elf Łowca"
        modal.stats_input._value = "12, 16, 14, 10, 14, 8"
        modal.gear_gold_input._value = "Długi łuk, 2x Sztylet; 25 GP"
        modal.backstory_input._value = "Strażnik leśnych traktów."

        await modal.on_submit(interaction)

        # Weryfikacja utworzenia wątku w forum #karty-postaci
        assert len(forum.threads) == 1
        thread = forum.threads[0]
        assert "Alden Szybki" in thread.name
        assert "7777" in thread.name

        # Weryfikacja odczytu postaci z wątku
        char_from_thread = await get_character_from_thread(thread)
        assert char_from_thread is not None
        assert char_from_thread.name == "Alden Szybki"
        assert char_from_thread.character_class == "Łowca"
        assert char_from_thread.race == "Elf"
        assert char_from_thread.gold_gp == 25
        assert char_from_thread.backstory == "Strażnik leśnych traktów."

        # Weryfikacja odpowiedzi do użytkownika
        assert len(interaction.followup.sent_messages) == 1
        resp_msg = interaction.followup.sent_messages[0]
        assert "Alden Szybki" in resp_msg.content


# ==============================================================================
# R3: AI Generator Postaci (/generate-character & GeminiClient)
# ==============================================================================

class TestR3AIAssistedCharacterGenerator:
    """Testy promptu AI, integracji klienta Gemini oraz slash command /generate-character."""

    def test_character_generator_prompt_structure(self):
        assert "D&D 5e" in CHARACTER_GENERATOR_SYSTEM_PROMPT
        assert "Standard Array" in CHARACTER_GENERATOR_SYSTEM_PROMPT
        assert "Hit Die" in CHARACTER_GENERATOR_SYSTEM_PROMPT
        assert "backstory" in CHARACTER_GENERATOR_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_gemini_client_offline_character_generator_wizard(self):
        client = GeminiClient(api_key="")  # Tryb offline
        res = await client.generate_character("Stwórz elfa maga specjalizującego się w magii światła")
        assert res["name"] == "Elora Gwiazda Zmierzchu"
        assert res["character_class"] == "Mag"
        assert res["race"] == "Elf"
        assert res["max_hp"] == 8
        assert res["spell_slots"]["level_1_max"] == 2
        assert "Magiczny Pocisk" in res["spells"]

    @pytest.mark.asyncio
    async def test_gemini_client_offline_character_generator_dwarf(self):
        client = GeminiClient(api_key="")
        res = await client.generate_character("Krasnolud z wielkim toporem wojennym")
        assert res["name"] == "Balgor Żelazny Topór"
        assert res["character_class"] == "Wojownik"
        assert res["race"] == "Krasnolud"
        assert res["max_hp"] == 13

    @pytest.mark.asyncio
    async def test_mock_gemini_client_custom_queued_character(self):
        mock_ai = MockGeminiClient()
        custom_char_dict = {
            "name": "Khelgar",
            "race": "Krasnolud",
            "character_class": "Mnich",
            "level": 1,
            "current_hp": 11,
            "max_hp": 11,
            "armor_class": 14,
            "speed": 25,
            "stats": {"strength": 14, "dexterity": 14, "constitution": 14, "intelligence": 10, "wisdom": 14, "charisma": 8},
            "backstory": "Mnich z klasztoru Żelaznej Pięści."
        }
        mock_ai.queue_character_response(custom_char_dict)

        client = GeminiClient(mock_client=mock_ai)
        result = await client.generate_character("Krasnoludzki mnich")

        assert result["name"] == "Khelgar"
        assert result["character_class"] == "Mnich"
        assert mock_ai.call_count == 1
        assert mock_ai.last_call["type"] == "character"

    @pytest.mark.asyncio
    async def test_slash_command_generate_character_creates_forum_thread(self):
        guild = MockGuild(name="Gildia Bohaterów")
        forum = await guild.create_forum("karty-postaci")

        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        cog = CharacterCog(bot)

        user = MockUser(id=8888, name="GraczMag", display_name="GraczMag")
        interaction = MockInteraction(user=user, guild=guild)

        # Wywołanie komendy /generate-character
        await cog.generate_character_cmd.callback(cog, interaction, opis="Potężny mag elficki")

        # Weryfikacja wątku w forum
        assert len(forum.threads) == 1
        thread = forum.threads[0]
        assert "Elora" in thread.name or "Mag" in thread.name or "8888" in thread.name

        char = await get_character_from_thread(thread)
        assert char is not None
        assert char.character_class == "Mag"
        assert char.spell_slots.level_1_max == 2

        # Weryfikacja odpowiedzi bota
        assert len(interaction.followup.sent_messages) == 1
        assert "Elora" in interaction.followup.sent_messages[0].embeds[0].title or "Mag" in interaction.followup.sent_messages[0].embeds[0].title


# ==============================================================================
# R4: Komenda Edycji Postaci (/character-edit & Audit Logging)
# ==============================================================================

class TestR4CharacterEditAndAuditLogging:
    """Testy selektywnej modyfikacji danych, zachowania ekwipunku/złota i audytu."""

    @pytest.mark.asyncio
    async def test_character_edit_selective_fields(self):
        guild = MockGuild()
        forum = await guild.create_forum("karty-postaci")

        user = MockUser(id=9999, name="Bohater", display_name="Bohater")

        # Początkowa postać z ekwipunkiem i złotem
        initial_char = CharacterModel(
            discord_user_id="9999",
            name="Stary Wojownik",
            character_class="Wojownik",
            race="Człowiek",
            level=1,
            current_hp=10,
            max_hp=10,
            gold_gp=100,
            inventory=[
                ItemModel(name="Magiczny Pierścień", quantity=1, item_type="quest"),
                ItemModel(name="Mikstura Leczenia", quantity=3, item_type="consumable")
            ],
            backstory="Dawny weteran wojenny."
        )

        embed = create_character_sheet_embed(initial_char)
        t_res = await forum.create_thread(name="🛡️ Stary Wojownik (9999)", embed=embed)
        thread = t_res.thread

        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        cog = CharacterCog(bot)
        interaction = MockInteraction(user=user, guild=guild)

        # Edytujemy tylko imię, klasę i max_hp
        await cog.character_edit_cmd.callback(
            cog,
            interaction,
            imie="Rycerz Roland",
            klasa="Paladyn",
            max_hp=15,
            ac=18,
            historia="Odrodzony rycerz światłości."
        )

        # Weryfikacja aktualizacji wątku
        updated_char = await get_character_from_thread(thread)
        assert updated_char is not None
        assert updated_char.name == "Rycerz Roland"
        assert updated_char.character_class == "Paladyn"
        assert updated_char.max_hp == 15
        assert updated_char.armor_class == 18
        assert updated_char.backstory == "Odrodzony rycerz światłości."

        # Krytyczne: Ekwipunek i złoto NIE zostały naruszone
        assert updated_char.gold_gp == 100
        assert len(updated_char.inventory) == 2
        assert updated_char.has_item("Magiczny Pierścień")
        assert updated_char.has_item("Mikstura Leczenia")

        # Weryfikacja zmiany nazwy wątku
        assert thread.name == "🛡️ Rycerz Roland (9999)"

        # Weryfikacja wpisu audytowego w historii wątku
        audit_msgs = [m.content for m in thread.messages if "Aktualizacja karty postaci" in m.content]
        assert len(audit_msgs) >= 1
        assert any("Edycja postaci" in m for m in audit_msgs)

    @pytest.mark.asyncio
    async def test_character_edit_no_fields_returns_warning(self):
        guild = MockGuild()
        forum = await guild.create_forum("karty-postaci")
        user = MockUser(id=1234, name="Gareth")

        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        cog = CharacterCog(bot)
        interaction = MockInteraction(user=user, guild=guild)

        # Wywołanie bez podania żadnych pól do zmiany
        await cog.character_edit_cmd.callback(cog, interaction)

        resp = interaction.followup.sent_messages[0]
        assert "Nie podano żadnych pól" in resp.content

    @pytest.mark.asyncio
    async def test_character_edit_modal_interactive_submit(self):
        guild = MockGuild()
        forum = await guild.create_forum("karty-postaci")
        user = MockUser(id=4321, name="Teresa")

        char = CharacterModel(
            discord_user_id="4321",
            name="Teresa",
            character_class="Łotr",
            race="Człowiek",
            max_hp=10,
            armor_class=13,
            speed=30
        )
        embed = create_character_sheet_embed(char)
        t_res = await forum.create_thread(name="🛡️ Teresa (4321)", embed=embed)

        modal = CharacterEditModal(character=char, thread=t_res.thread)
        modal.name_input._value = "Teresa Cień"
        modal.race_input._value = "Elf"
        modal.class_input._value = "Zabójca"
        modal.hp_ac_speed_input._value = "14, 15, 35"
        modal.backstory_input._value = "Mistrzyni cichego ostrza."

        interaction = MockInteraction(user=user, guild=guild)
        await modal.on_submit(interaction)

        updated_char = await get_character_from_thread(t_res.thread)
        assert updated_char.name == "Teresa Cień"
        assert updated_char.race == "Elf"
        assert updated_char.character_class == "Zabójca"
        assert updated_char.max_hp == 14
        assert updated_char.armor_class == 15
        assert updated_char.speed == 35
        assert updated_char.backstory == "Mistrzyni cichego ostrza."


# ==============================================================================
# Edge Cases & Boundaries
# ==============================================================================

class TestCharacterSuiteEdgeCases:
    """Przypadki brzegowe, obsługa uśpionych wątków i brakujących kanałów."""

    @pytest.mark.asyncio
    async def test_sleeping_forum_thread_auto_unarchived_during_edit(self):
        guild = MockGuild()
        forum = await guild.create_forum("karty-postaci")
        user = MockUser(id=6666, name="SpiacyBohater")

        char = CharacterModel(discord_user_id="6666", name="RipVanWinkle", character_class="Wojownik", race="Człowiek")
        embed = create_character_sheet_embed(char)
        t_res = await forum.create_thread(name="🛡️ RipVanWinkle (6666)", embed=embed)
        thread = t_res.thread

        # Uśpij wątek po 24h
        await thread.edit(archived=True)
        assert thread.archived is True

        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        cog = CharacterCog(bot)
        interaction = MockInteraction(user=user, guild=guild)

        # Edycja postaci powinna obudzić wątek
        await cog.character_edit_cmd.callback(cog, interaction, max_hp=20)

        assert thread.archived is False
        updated = await get_character_from_thread(thread)
        assert updated.max_hp == 20

    @pytest.mark.asyncio
    async def test_missing_forum_channel_returns_informative_error(self):
        guild = MockGuild()  # Brak forum karty-postaci
        user = MockUser(id=999, name="BrakForum")

        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        cog = CharacterCog(bot)
        interaction = MockInteraction(user=user, guild=guild)

        await cog.show_sheet.callback(cog, interaction)
        resp = interaction.followup.sent_messages[0]
        assert "Nie znaleziono forum" in resp.content
        assert "/setup-campaign" in resp.content
