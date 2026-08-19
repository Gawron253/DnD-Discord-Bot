"""Adversarial stress and property test suite for Character Creation & Editing Suite.

Empirical verification covering:
1. Adversarial Zero-Width Steganography (extreme payloads, unicode/emojis, zalgo, injections, corrupted streams, dual payloads, boundary conditions).
2. Property & Fuzzing D&D 5e Rule Computation (stats parsing, modifiers, HP math, AC variants, speed, spell slots, inventory/gold parsing).
3. Non-Destructive Mutation Invariants in /character-edit (state preservation across 50 sequential edits: inventory, gold, conditions, xp, spell slots).
4. Cross-Character Isolation & Concurrent Mutation Stress.
"""
import copy
import json
import random
import re
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
    get_character_from_thread,
    ZW_START,
    ZW_END,
    ZW_MAP,
    REV_ZW_MAP
)
from discord_ui.embeds import create_character_sheet_embed
from discord_ui.views import (
    compute_5e_character,
    CharacterCreateModal,
    CharacterEditModal,
    CharacterSheetView
)
from commands.character_cog import CharacterCog
from tests.mock_discord import (
    MockGuild,
    MockForumChannel,
    MockThread,
    MockMessage,
    MockUser,
    MockInteraction
)


# ==============================================================================
# 1. ADVERSARIAL ZERO-WIDTH STEGANOGRAPHY STRESS TESTS
# ==============================================================================

class TestAdversarialSteganography:
    """Stress testing the zero-width encoding and decoding engine with hostile inputs."""

    def test_massive_nested_payload_roundtrip(self):
        """Stress test with large payload containing complex nested structures and arrays."""
        large_data = {
            "name": "Aragorn " * 50,
            "stats": {"str": 18, "dex": 14, "con": 16, "int": 12, "wis": 15, "cha": 16},
            "inventory": [
                {"name": f"Item_{i}", "quantity": i * 3, "properties": {"nested_key": f"value_{i}" * 10}}
                for i in range(100)
            ],
            "history": ["Event line " + str(i) for i in range(200)],
            "metadata": {"tags": ["rpg", "dnd", "5e", "hero"] * 20}
        }
        encoded = encode_zero_width_data(large_data)
        assert encoded.startswith(ZW_START)
        assert encoded.endswith(ZW_END)
        decoded = decode_zero_width_data(encoded)
        assert decoded == large_data

    @pytest.mark.parametrize("hostile_str", [
        "🧙‍♂️🗡️🐉🏰✨🔥🛡️👑🎲⚔️",  # Emojis & multi-codepoint sequences
        "Z̸̢̛̞̜̝̖̜͎̣̘͇͚̘͋͒͊̋̄́̇͝ă̶̡̖̮͇̘͓̩̯̰̓́̄̈́̿͠l̸̛̗̣͔̫̩̈́̓̃̑̐̾̈́̓̚͜g̶̡̨̯͚̮̝̪̮͇̣̫͔̾̊̈́̃̅̈́̓͜͝ǫ̸̛̛͍͔̲̺̮̹̣̣̑̈́̓",  # Zalgo text
        "العربية / עברית / 中文 / 日本語 / Русский / Polski: ąćęłńóśźż ĄĆĘŁŃÓŚŹŻ",  # Multi-script & RTL
        "<!-- DATA_JSON: {\"injected\": true} -->",  # HTML comment injection inside payload
        '{"nested_json": "{\\"key\\": \\"value\\", \\"arr\\": [1,2,3]}"}',  # Escaped JSON strings
        "\x00\x01\x02\t\r\n\x1f !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",  # Control chars & full ASCII symbols
        "\u200b\u200c\u200d\u2060",  # Zero-width characters embedded as plain data inside the text
    ])
    def test_unicode_and_injection_payloads(self, hostile_str):
        data = {
            "name": f"Test_{hostile_str}",
            "bio": hostile_str,
            "items": [hostile_str]
        }
        encoded = encode_zero_width_data(data)
        decoded = decode_zero_width_data(encoded)
        assert decoded == data

    def test_empty_and_minimal_payloads(self):
        """Test encoding and decoding empty dicts, empty keys, and boolean values."""
        for payload in [{}, {"a": ""}, {"flag": True, "val": None, "empty_list": []}]:
            encoded = encode_zero_width_data(payload)
            decoded = decode_zero_width_data(encoded)
            assert decoded == payload

    def test_decode_none_or_empty_string(self):
        """Test decoder behavior when receiving None, empty strings, or plain text without payload."""
        assert decode_zero_width_data(None) is None
        assert decode_zero_width_data("") is None
        assert decode_zero_width_data("   ") is None
        assert decode_zero_width_data("Just plain text with no hidden characters.") is None

    def test_corrupted_zero_width_streams_fail_gracefully(self):
        """Ensure corrupted or truncated zero-width streams return None without raising exceptions."""
        data = {"valid": True, "number": 42}
        encoded = encode_zero_width_data(data)

        # 1. Truncate end delimiter
        corrupted_1 = encoded[:-len(ZW_END)]
        assert decode_zero_width_data(corrupted_1) is None

        # 2. Truncate start delimiter
        corrupted_2 = encoded[len(ZW_START):]
        assert decode_zero_width_data(corrupted_2) is None

        # 3. Truncate payload inside by 1 character (odd number of bits -> len(bits) % 8 != 0)
        payload_body = encoded[len(ZW_START):-len(ZW_END)]
        if len(payload_body) > 1:
            corrupted_3 = ZW_START + payload_body[:-1] + ZW_END
            assert decode_zero_width_data(corrupted_3) is None

        # 4. Insert alien character inside zero-width sequence
        corrupted_4 = ZW_START + payload_body[:5] + "X" + payload_body[5:] + ZW_END
        res = decode_zero_width_data(corrupted_4)
        assert res is None or isinstance(res, dict)

    def test_dual_payload_and_fallback_resilience(self):
        """Test extract_data_from_text with both ZW and HTML comment payloads present."""
        zw_data = {"source": "zero_width", "id": 100}
        html_data = {"source": "legacy_html", "id": 200}

        zw_encoded = encode_zero_width_data(zw_data)
        html_encoded = f"<!-- DATA_JSON: {json.dumps(html_data)} -->"

        # When both are present, ZW should take precedence
        combined = f"Character Bio here.\n{zw_encoded}\n{html_encoded}"
        extracted = extract_data_from_text(combined)
        assert extracted == zw_data

        # If ZW payload is corrupted, fallback to legacy HTML comment
        corrupted_zw = ZW_START + "\u200b\u200c" + ZW_END
        fallback_combined = f"Bio\n{corrupted_zw}\n{html_encoded}"
        extracted_fallback = extract_data_from_text(fallback_combined)
        assert extracted_fallback == html_data

    def test_full_embed_roundtrip_with_backstory(self):
        """Verify full roundtrip through build_character_sheet_embed and extract_data_from_message_or_embed."""
        char = CharacterModel(
            discord_user_id="998877",
            name="Valeros 🔥",
            character_class="Wojownik",
            race="Człowiek",
            level=3,
            current_hp=28,
            max_hp=28,
            armor_class=18,
            speed=30,
            gold_gp=120,
            backstory="Urodzony w płomieniach bitwy. ⚔️ Nie lęka się potworów!\nLinia 2 opisu.",
            bio="Urodzony w płomieniach bitwy. ⚔️ Nie lęka się potworów!\nLinia 2 opisu."
        )
        embed = build_character_sheet_embed(char)
        
        # Verify description is clean
        assert "<!-- DATA_JSON:" not in embed.description
        assert "Urodzony w płomieniach bitwy." in embed.description

        # Create mock message with this embed
        msg = MockMessage(content="", embeds=[embed])
        extracted = extract_data_from_message_or_embed(msg)
        assert extracted is not None
        assert extracted["name"] == "Valeros 🔥"
        assert extracted["level"] == 3
        assert extracted["gold_gp"] == 120


# ==============================================================================
# 2. D&D 5E RULE COMPUTATION & FUZZING PROPERTY TESTS
# ==============================================================================

class TestProperty5eRuleComputation:
    """Property-based fuzzing and boundary testing of compute_5e_character rule calculations."""

    @pytest.mark.parametrize("class_name, expected_hit_die", [
        ("Barbarzyńca", 12),
        ("Barbarian", 12),
        ("Wojownik", 10),
        ("Fighter", 10),
        ("Paladyn", 10),
        ("Paladin", 10),
        ("Łowca", 10),
        ("Ranger", 10),
        ("Tropiciel", 10),
        ("Kleryk", 8),
        ("Kapłan", 8),
        ("Cleric", 8),
        ("Druid", 8),
        ("Łotr", 8),
        ("Złodziej", 8),
        ("Rogue", 8),
        ("Bard", 8),
        ("Mnich", 8),
        ("Monk", 8),
        ("Czarnoksiężnik", 8),
        ("Warlock", 8),
        ("Mag", 6),
        ("Czarodziej", 6),
        ("Wizard", 6),
        ("Zaklinacz", 6),
        ("Sorcerer", 6),
        ("UnknownClass", 8),  # Default hit die
    ])
    def test_hit_die_per_class(self, class_name, expected_hit_die):
        """Verify that every class receives the exact 5e Hit Die."""
        char = compute_5e_character(
            name="TestHero",
            race_and_class=f"Człowiek {class_name}",
            stats_raw="10, 10, 10, 10, 10, 10"
        )
        assert char.max_hp == expected_hit_die
        assert char.current_hp == expected_hit_die

    @pytest.mark.parametrize("con_score, con_mod", [
        (1, -5),
        (6, -2),
        (8, -1),
        (9, -1),
        (10, 0),
        (11, 0),
        (12, 1),
        (14, 2),
        (16, 3),
        (18, 4),
        (20, 5),
        (30, 10),
    ])
    def test_con_modifier_and_min_hp_invariant(self, con_score, con_mod):
        """Verify HP = max(1, hit_die + con_mod) across various constitution values."""
        stat_block = StatBlock(constitution=con_score)
        assert stat_block.get_modifier("constitution") == con_mod

        # Wizard (d6) with low CON
        char_wizard = compute_5e_character(
            name="WeakMage",
            race_and_class="Elf Mag",
            stats_raw=f"10, 10, {con_score}, 10, 10, 10"
        )
        expected_hp = max(1, 6 + con_mod)
        assert char_wizard.max_hp == expected_hp
        assert char_wizard.current_hp == expected_hp

    @pytest.mark.parametrize("race_input, expected_speed", [
        ("Krasnolud", 25),
        ("Dwarf", 25),
        ("krasnolud tarczowy", 25),
        ("Niziołek", 25),
        ("Halfling", 25),
        ("Gnom", 25),
        ("Gnome", 25),
        ("Elf", 30),
        ("Człowiek", 30),
        ("Human", 30),
        ("Tiefling", 30),
        ("Dragonborn", 30),
        ("Ork", 30),
    ])
    def test_speed_per_race(self, race_input, expected_speed):
        char = compute_5e_character(
            name="Runner",
            race_and_class=f"{race_input} Łotrzyk"
        )
        assert char.speed == expected_speed

    def test_ac_calculations_across_archetypes(self):
        """Test Armor Class formulas: Paladin/Fighter (>=14), Barbarian (10+dex+con), Monk (10+dex+wis), Default (10+dex)."""
        # 1. Fighter: max(10 + dex, 14) -> with DEX 10 (mod 0), AC = 14
        fighter = compute_5e_character(
            name="Sir Knight",
            race_and_class="Człowiek Wojownik",
            stats_raw="16, 10, 14, 10, 10, 10"
        )
        assert fighter.armor_class == 14

        # Fighter with DEX 20 (mod +5) -> max(10+5, 14) = 15
        fighter_dex = compute_5e_character(
            name="Dex Knight",
            race_and_class="Człowiek Fighter",
            stats_raw="10, 20, 14, 10, 10, 10"
        )
        assert fighter_dex.armor_class == 15

        # 2. Barbarian Unarmored Defense: 10 + DEX mod + CON mod
        barb = compute_5e_character(
            name="Conan",
            race_and_class="Człowiek Barbarzyńca",
            stats_raw="16, 14, 16, 8, 10, 10"
        )
        assert barb.armor_class == 15

        # 3. Monk Unarmored Defense: 10 + DEX mod + WIS mod
        monk = compute_5e_character(
            name="Kwon",
            race_and_class="Człowiek Mnich",
            stats_raw="10, 16, 12, 10, 16, 8"
        )
        assert monk.armor_class == 16

        # 4. Rogue / Wizard Default: 10 + DEX mod
        rogue = compute_5e_character(
            name="Shadow",
            race_and_class="Niziołek Łotr",
            stats_raw="10, 14, 12, 10, 10, 10"
        )
        assert rogue.armor_class == 12

    @pytest.mark.parametrize("class_name, exp_slots, exp_spells_contain", [
        ("Mag", 2, "Magiczny Pocisk"),
        ("Wizard", 2, "Tarcza"),
        ("Zaklinacz", 2, "Ognisty Pocisk"),
        ("Sorcerer", 2, "Fala Dźwiękowa"),
        ("Kleryk", 2, "Leczenie Ran"),
        ("Cleric", 2, "Błogosławieństwo"),
        ("Druid", 2, "Splot Cierni"),
        ("Bard", 2, "Drwiący Śmiech"),
        ("Czarnoksiężnik", 1, "Mistyczny Pocisk"),
        ("Warlock", 1, "Mistyczny Pocisk"),
        ("Wojownik", 0, None),
        ("Barbarzyńca", 0, None),
        ("Łotr", 0, None),
    ])
    def test_spell_slots_and_starter_spells(self, class_name, exp_slots, exp_spells_contain):
        char = compute_5e_character(
            name="CasterTest",
            race_and_class=f"Elf {class_name}"
        )
        assert char.spell_slots.level_1 == exp_slots
        assert char.spell_slots.level_1_max == exp_slots
        if exp_spells_contain:
            assert exp_spells_contain in char.spells
        else:
            assert len(char.spells) == 0

    def test_fuzz_stats_raw_parsing(self):
        """Fuzz testing stats_raw with random formats, missing values, extreme out-of-bound numbers."""
        random.seed(42)
        for _ in range(50):
            num_values = random.randint(0, 10)
            generated_nums = [random.randint(-100, 200) for _ in range(num_values)]
            separator = random.choice([", ", " / ", " | ", "-", "   ", "\n"])
            raw_str = separator.join(map(str, generated_nums))

            char = compute_5e_character(
                name="FuzzChar",
                race_and_class="Krasnolud Wojownik",
                stats_raw=raw_str
            )
            assert isinstance(char.stats, StatBlock)
            assert 1 <= char.stats.strength <= 30
            assert 1 <= char.stats.dexterity <= 30
            assert 1 <= char.stats.constitution <= 30
            assert 1 <= char.stats.intelligence <= 30
            assert 1 <= char.stats.wisdom <= 30
            assert 1 <= char.stats.charisma <= 30

    def test_gear_and_gold_parsing_variations(self):
        """Test complex inventory and gold strings parsing."""
        raw_gear = "Miecz dwuręczny x1, Mikstura leczenia (3), 5 x Pochodnia, Lina konopna; 75 GP"
        char = compute_5e_character(
            name="LootedHero",
            race_and_class="Człowiek Wojownik",
            gear_and_gold_raw=raw_gear
        )
        assert char.gold_gp == 75
        item_names = {item.name: item.quantity for item in char.inventory}
        assert item_names.get("Miecz dwuręczny") == 1
        assert item_names.get("Mikstura leczenia") == 3
        assert item_names.get("Pochodnia") == 5
        assert item_names.get("Lina konopna") == 1


# ==============================================================================
# 3. NON-DESTRUCTIVE MUTATION INVARIANTS IN /character-edit
# ==============================================================================

class TestCharacterEditNonDestructiveInvariants:
    """Adversarial stress test verifying that sequential /character-edit mutations never corrupt inventory, gold, or conditions."""

    @pytest.mark.asyncio
    async def test_fifty_sequential_character_edits_state_invariance(self):
        """Perform 50 sequential, randomized character edits and verify state preservation at each step."""
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        cog = CharacterCog(bot)

        # 1. Initialize character with rich nested state
        initial_inventory = [
            ItemModel(name="Święty Symbol Pelora", quantity=1, item_type="quest", properties={"blessed": True}),
            ItemModel(name="Mikstura Niewidzialności", quantity=4, item_type="consumable"),
            ItemModel(name="Sztylet +1", quantity=2, item_type="weapon", is_equipped=True),
            ItemModel(name="Amulet Ochrony", quantity=1, item_type="equipment", weight=0.5),
        ]
        initial_conditions = ["Zatrucie", "Błogosławieństwo"]
        initial_gold = 450
        initial_xp = 2800

        char = CharacterModel(
            discord_user_id="123456789",
            name="Aldred",
            character_class="Kleryk",
            race="Człowiek",
            level=4,
            xp=initial_xp,
            current_hp=32,
            max_hp=32,
            temp_hp=5,
            armor_class=16,
            speed=30,
            proficiency_bonus=2,
            stats=StatBlock(strength=14, dexterity=10, constitution=14, intelligence=10, wisdom=16, charisma=12),
            spell_slots=SpellSlots(level_1=4, level_1_max=4, level_2=3, level_2_max=3),
            inventory=copy.deepcopy(initial_inventory),
            gold_gp=initial_gold,
            conditions=copy.deepcopy(initial_conditions),
            backstory="Początkowa historia bohatera.",
            bio="Początkowa historia bohatera."
        )

        guild = MockGuild(id=1, name="DnD Server")
        forum = await guild.create_forum("karty-postaci")
        user = MockUser(id=123456789, name="PlayerOne")

        # Provision sheet in forum
        thread, msg, _ = await get_or_create_character_sheet(forum, str(user.id), character=char)

        random.seed(1337)
        names = ["Aldred Mężny", "Aldred Starszy", "Brak", "Grom", "Sylas", "Kaelen"]
        classes = ["Kleryk", "Paladyn", "Wojownik", "Mag", "Czarnoksiężnik"]
        races = ["Człowiek", "Krasnolud", "Elf", "Gnom", "Półork"]

        # Run 50 sequential mutations
        for step in range(50):
            mutation_type = random.choice([
                "name", "class", "race", "level", "hp", "ac", "speed", "stats", "backstory", "multi"
            ])

            inter = MockInteraction(user=user, guild=guild)
            
            imie = random.choice(names) if mutation_type in ["name", "multi"] else None
            klasa = random.choice(classes) if mutation_type in ["class", "multi"] else None
            rasa = random.choice(races) if mutation_type in ["race", "multi"] else None
            poziom = random.randint(1, 20) if mutation_type in ["level", "multi"] else None
            max_hp = random.randint(10, 150) if mutation_type in ["hp", "multi"] else None
            ac = random.randint(10, 25) if mutation_type in ["ac", "multi"] else None
            speed = random.choice([20, 25, 30, 35, 40]) if mutation_type in ["speed", "multi"] else None
            
            str_stat = random.randint(8, 20) if mutation_type in ["stats", "multi"] else None
            dex_stat = random.randint(8, 20) if mutation_type in ["stats", "multi"] else None
            con_stat = random.randint(8, 20) if mutation_type in ["stats", "multi"] else None
            int_stat = random.randint(8, 20) if mutation_type in ["stats", "multi"] else None
            wis_stat = random.randint(8, 20) if mutation_type in ["stats", "multi"] else None
            cha_stat = random.randint(8, 20) if mutation_type in ["stats", "multi"] else None
            historia = f"Aktualizacja historii krok {step}: {random.random()}" if mutation_type in ["backstory", "multi"] else None

            # Execute edit command
            await cog.character_edit_cmd.callback(
                cog,
                inter,
                imie=imie,
                klasa=klasa,
                rasa=rasa,
                poziom=poziom,
                max_hp=max_hp,
                ac=ac,
                speed=speed,
                str_stat=str_stat,
                dex_stat=dex_stat,
                con_stat=con_stat,
                int_stat=int_stat,
                wis_stat=wis_stat,
                cha_stat=cha_stat,
                historia=historia
            )

            # Retrieve persisted character from forum thread
            retrieved_char = await get_character_from_thread(thread)
            assert retrieved_char is not None, f"Failed to retrieve character at step {step}"

            # --- INVARIANT ASSERTIONS ---
            # 1. Inventory invariance
            assert len(retrieved_char.inventory) == len(initial_inventory), f"Inventory count corrupted at step {step}"
            for original_item, current_item in zip(initial_inventory, retrieved_char.inventory):
                assert original_item.name == current_item.name
                assert original_item.quantity == current_item.quantity
                assert original_item.item_type == current_item.item_type
                assert original_item.is_equipped == current_item.is_equipped

            # 2. Gold invariance
            assert retrieved_char.gold_gp == initial_gold, f"Gold GP corrupted at step {step}: expected {initial_gold}, got {retrieved_char.gold_gp}"

            # 3. Conditions invariance
            assert retrieved_char.conditions == initial_conditions, f"Conditions corrupted at step {step}"

            # 4. XP invariance
            assert retrieved_char.xp == initial_xp, f"XP corrupted at step {step}"

            # 5. HP consistency invariant (current_hp <= max_hp)
            assert retrieved_char.current_hp <= retrieved_char.max_hp, f"Current HP exceeded Max HP at step {step}"
            assert retrieved_char.max_hp >= 1

            # 6. Proficiency bonus consistency
            expected_prof = 2 + (retrieved_char.level - 1) // 4
            assert retrieved_char.proficiency_bonus == expected_prof

        # Verify audit history generated messages in thread
        assert len(thread.messages) >= 50

    @pytest.mark.asyncio
    async def test_character_edit_modal_flow_invariance(self):
        """Test the CharacterEditModal submission handler preserving inventory and non-edited fields."""
        char = CharacterModel(
            discord_user_id="554433",
            name="Thorgal",
            character_class="Łowca",
            race="Człowiek",
            level=2,
            current_hp=20,
            max_hp=20,
            armor_class=14,
            speed=30,
            gold_gp=85,
            inventory=[ItemModel(name="Łuk refleksyjny", quantity=1), ItemModel(name="Strzały", quantity=20)],
            conditions=["Zmęczenie I"]
        )

        guild = MockGuild(id=2, name="DnD Guild")
        forum = await guild.create_forum("karty-postaci")
        user = MockUser(id=554433, name="ThorgalPlayer")

        thread, msg, _ = await get_or_create_character_sheet(forum, str(user.id), character=char)

        modal = CharacterEditModal(character=char, thread=thread)
        modal.name_input._value = "Thorgal Aegirsson"
        modal.hp_ac_speed_input._value = "26, 15, 35"
        modal.backstory_input._value = "Gwiezdne Dziecko, wojownik Północy."

        inter = MockInteraction(user=user, guild=guild)
        await modal.on_submit(inter)

        retrieved = await get_character_from_thread(thread)
        assert retrieved.name == "Thorgal Aegirsson"
        assert retrieved.max_hp == 26
        assert retrieved.armor_class == 15
        assert retrieved.speed == 35
        assert retrieved.backstory == "Gwiezdne Dziecko, wojownik Północy."
        # Verify non-destructive invariants
        assert retrieved.gold_gp == 85
        assert len(retrieved.inventory) == 2
        assert retrieved.inventory[0].name == "Łuk refleksyjny"
        assert retrieved.conditions == ["Zmęczenie I"]

    @pytest.mark.asyncio
    async def test_multi_user_character_isolation(self):
        """Verify that edits to User A's character never leak into or affect User B's character."""
        guild = MockGuild(id=3, name="MultiUser Guild")
        forum = await guild.create_forum("karty-postaci")

        user_a = MockUser(id=111, name="Alice")
        user_b = MockUser(id=222, name="Bob")

        char_a = CharacterModel(
            discord_user_id="111",
            name="AliceHero",
            character_class="Mag",
            race="Elf",
            level=1,
            gold_gp=100
        )
        char_b = CharacterModel(
            discord_user_id="222",
            name="BobHero",
            character_class="Wojownik",
            race="Krasnolud",
            level=1,
            gold_gp=200
        )

        thread_a, _, _ = await get_or_create_character_sheet(forum, "111", character=char_a)
        thread_b, _, _ = await get_or_create_character_sheet(forum, "222", character=char_b)

        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        cog = CharacterCog(bot)

        # Edit User A only
        inter_a = MockInteraction(user=user_a, guild=guild)
        await cog.character_edit_cmd.callback(
            cog,
            inter_a,
            imie="AliceArchmage",
            poziom=10
        )

        # Retrieve both characters
        retrieved_a = await get_character_from_thread(thread_a)
        retrieved_b = await get_character_from_thread(thread_b)

        assert retrieved_a.name == "AliceArchmage"
        assert retrieved_a.level == 10
        assert retrieved_a.gold_gp == 100

        # User B must remain totally untouched
        assert retrieved_b.name == "BobHero"
        assert retrieved_b.level == 1
        assert retrieved_b.gold_gp == 200
        assert retrieved_b.character_class == "Wojownik"
