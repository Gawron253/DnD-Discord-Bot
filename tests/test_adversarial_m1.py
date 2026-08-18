"""Adversarial stress and edge-case test suite for Milestone 1 (R1).
Empirically challenges core/models.py, core/discord_db.py, and core/channel_manager.py.
"""
import asyncio
import json
import pytest
import discord
from typing import Dict, Any, List

from core.models import (
    CharacterModel,
    StatBlock,
    ItemModel,
    SpellSlots,
    QuestItem,
    QuestObjective,
    QuestList,
    DiceRollResult
)
from core.discord_db import (
    extract_data_from_text,
    extract_json_from_message,
    inject_data_into_text,
    inject_json_to_text,
    extract_data_from_message_or_embed,
    create_health_bar,
    build_character_sheet_embed,
    build_quest_board_embed,
    get_or_create_character_sheet,
    update_character_sheet,
    get_character_from_thread,
    get_quest_board,
    update_quest_board,
    fetch_campaign_rules,
    _get_all_forum_threads
)
from core.channel_manager import (
    normalize_name,
    find_category,
    find_text_channel,
    find_forum_channel,
    setup_campaign_infrastructure,
    CAMPAIGN_STRUCTURE,
    DEFAULT_RULES_CONTENT
)
from tests.mock_discord import (
    MockGuild,
    MockUser,
    MockTextChannel,
    MockForumChannel,
    MockCategoryChannel,
    MockThread,
    MockMessage,
    MockEmbed,
    MockInteraction
)


# ============================================================================
# 1. Stress Tests for <!-- DATA_JSON: ... --> Parser
# ============================================================================

class TestAdversarialDataJsonParser:
    """Stress tests for HTML comment JSON serialization/deserialization."""

    def test_nested_quotes_and_escaped_strings(self):
        """Payload with nested double quotes, escaped characters, and backslashes."""
        raw_data = {
            "name": 'Gracz "Zabójca Smoków" O\'Connor',
            "bio": 'Cytat: \\"Witaj w ciemności!\\" Powiedział: \'Biegnij!\\\\\'',
            "notes": "Linia 1\nLinia 2\r\nLinia 3\tTabulator",
            "symbols": "<xml>tag</xml> & and / slash \\ backslash",
        }
        injected = inject_data_into_text("Przykładowy opis karty", raw_data)
        extracted = extract_data_from_text(injected)

        assert extracted is not None
        assert extracted["name"] == raw_data["name"]
        assert extracted["bio"] == raw_data["bio"]
        assert extracted["notes"] == raw_data["notes"]
        assert extracted["symbols"] == raw_data["symbols"]

    def test_unicode_polish_characters_and_emojis(self):
        """Payload with extensive Polish diacritics and multi-byte emojis."""
        raw_data = {
            "polish_lower": "zażółć gęślą jaźń ąćęłńóśźż",
            "polish_upper": "ZAŻÓŁĆ GĘŚLĄ JAŹŃ ĄĆĘŁŃÓŚŹŻ",
            "complex_text": "Ciemiężca z Wąchocka płacze rzęsiście pod dębem.",
            "emojis": "⚔️🛡️❤️🎲🔥🐉✨👑🏰🧙‍♂️🧝‍♀️",
            "mixed": "Bohater 🧙‍♂️: Chrząszcz brzmi w trzcinie w Szczebrzeszynie! ⚔️",
        }
        injected = inject_data_into_text("Tło fabularne", raw_data)
        extracted = extract_data_from_text(injected)

        assert extracted is not None
        for key, val in raw_data.items():
            assert extracted[key] == val

    def test_markdown_formatting_around_comment(self):
        """JSON comment surrounded by bold, code block, quote block, or headers."""
        data = {"hp": 45, "level": 7, "class": "Paladyn"}
        json_str = json.dumps(data)

        # 1. Bolded comment
        msg_bold = f"Opis postaci\n\n**<!-- DATA_JSON: {json_str} -->**"
        assert extract_data_from_text(msg_bold) == data

        # 2. Blockquote comment
        msg_quote = f"Opis postaci\n\n> <!-- DATA_JSON: {json_str} -->"
        assert extract_data_from_text(msg_quote) == data

        # 3. Inside code markdown block
        msg_code = f"Opis:\n```\n<!-- DATA_JSON: {json_str} -->\n```"
        assert extract_data_from_text(msg_code) == data

        # 4. Trailing spaces and newlines inside the comment tags
        msg_loose = f"Opis\n<!--   \n  DATA_JSON:   \n{json_str}\n   -->"
        assert extract_data_from_text(msg_loose) == data

    def test_large_payload_stress(self):
        """Large payload with 1,000 inventory items and 100 conditions."""
        items = [
            {"name": f"Magiczny Przedmiot #{i}", "quantity": i * 2, "item_type": "weapon", "weight": 2.5}
            for i in range(1000)
        ]
        large_data = {
            "discord_user_id": "999888777",
            "name": "Archiwista Wielkich Danych",
            "inventory": items,
            "conditions": [f"Status-{i}" for i in range(100)],
            "long_bio": "A" * 10000,
        }

        injected = inject_data_into_text("Wielka postać", large_data)
        extracted = extract_data_from_text(injected)

        assert extracted is not None
        assert extracted["name"] == "Archiwista Wielkich Danych"
        assert len(extracted["inventory"]) == 1000
        assert extracted["inventory"][999]["name"] == "Magiczny Przedmiot #999"
        assert len(extracted["conditions"]) == 100
        assert len(extracted["long_bio"]) == 10000

    def test_malformed_corrupted_json_returns_none(self):
        """Malformed or broken JSON syntax returns None without raising unhandled exceptions."""
        broken_cases = [
            "<!-- DATA_JSON: {broken json without closing -->",
            "<!-- DATA_JSON: { 'name': 'invalid single quotes' } -->",
            "<!-- DATA_JSON: {\"hp\": 20, } -->",  # trailing comma
            "<!-- DATA_JSON: undefined -->",
            "<!-- DATA_JSON: -->",  # empty
            "<!-- DATA_JSON:    -->",  # whitespace only
            "Zwykły tekst bez tagu danych",
        ]
        for case in broken_cases:
            assert extract_data_from_text(case) is None

    def test_none_and_empty_inputs(self):
        """extract_data_from_text handles None, empty strings, and non-string types safely."""
        assert extract_data_from_text(None) is None
        assert extract_data_from_text("") is None
        assert extract_data_from_text("   ") is None

    def test_multiple_data_json_tags_in_same_text(self):
        """When multiple DATA_JSON tags are present, inject cleanses all and leaves 1."""
        text_with_two = (
            "Opis\n"
            "<!-- DATA_JSON: {\"version\": 1} -->\n"
            "Środek tekstu\n"
            "<!-- DATA_JSON: {\"version\": 2} -->"
        )
        new_data = {"version": 3}
        injected = inject_data_into_text(text_with_two, new_data)

        assert injected.count("<!-- DATA_JSON:") == 1
        extracted = extract_data_from_text(injected)
        assert extracted is not None
        assert extracted["version"] == 3
        assert "Środek tekstu" in injected

    def test_extract_data_from_message_or_embed_precedence(self):
        """Extracts JSON from embed description first, then message content."""
        user = MockUser(id=1, name="Tester")

        # 1. Embedded in description
        emb1 = MockEmbed(title="Sheet 1", description="<!-- DATA_JSON: {\"source\": \"embed_desc\"} -->")
        msg1 = MockMessage(content="<!-- DATA_JSON: {\"source\": \"content\"} -->", embed=emb1, author=user)
        assert extract_data_from_message_or_embed(msg1) == {"source": "embed_desc"}

        # 2. Embedded in real discord.Embed footer
        emb2 = discord.Embed(title="Sheet 2", description="Opis bez jsona")
        emb2.set_footer(text="<!-- DATA_JSON: {\"source\": \"footer\"} -->")
        msg2 = MockMessage(content="Brak json", embed=emb2, author=user)
        assert extract_data_from_message_or_embed(msg2) == {"source": "footer"}

        # 3. Embedded in content only
        msg3 = MockMessage(content="Tekst <!-- DATA_JSON: {\"source\": \"content_only\"} -->", author=user)
        assert extract_data_from_message_or_embed(msg3) == {"source": "content_only"}

        # 4. None message
        assert extract_data_from_message_or_embed(None) is None


# ============================================================================
# 2. Stress Tests for Thread Auto-Unarchiving & API Exceptions
# ============================================================================

class TestAdversarialThreadUnarchiving:
    """Stress tests for thread unarchiving with simulated Discord API delays and errors."""

    @pytest.mark.asyncio
    async def test_get_or_create_unarchives_archived_thread(self):
        """get_or_create_character_sheet finds sleeping thread and sets archived=False."""
        guild = MockGuild(name="RPG")
        forum = MockForumChannel(name="karty-postaci", guild=guild)

        # Create thread for user 12345
        char = CharacterModel(discord_user_id="12345", name="Arak", character_class="Łowca", race="Człowiek")
        created_t, created_m, _ = await get_or_create_character_sheet(forum, "12345", char)

        # Put thread to sleep (archived=True)
        await created_t.edit(archived=True)
        assert created_t.archived is True

        # Fetch character sheet -> must auto-unarchive
        t, m, c = await get_or_create_character_sheet(forum, "12345")
        assert t.id == created_t.id
        assert t.archived is False
        assert c.name == "Arak"

    @pytest.mark.asyncio
    async def test_update_character_sheet_unarchives_archived_thread(self):
        """update_character_sheet unarchives sleeping thread before editing sheet."""
        guild = MockGuild(name="RPG")
        forum = MockForumChannel(name="karty-postaci", guild=guild)

        char = CharacterModel(discord_user_id="12345", name="Arak", character_class="Łowca", race="Człowiek")
        thread, msg, _ = await get_or_create_character_sheet(forum, "12345", char)

        await thread.edit(archived=True)
        assert thread.archived is True

        char.current_hp = 5
        await update_character_sheet(thread, char, reason="Otrzymano obrażenia")

        assert thread.archived is False
        assert thread.unarchived_count >= 1

    @pytest.mark.asyncio
    async def test_thread_unarchive_with_simulated_api_latency(self):
        """Simulate high Discord API latency during unarchive / edit operations."""
        guild = MockGuild(name="RPG")
        forum = MockForumChannel(name="karty-postaci", guild=guild)

        char = CharacterModel(discord_user_id="777", name="Gildor", character_class="Czarodziej", race="Elf")
        thread, msg, _ = await get_or_create_character_sheet(forum, "777", char)
        await thread.edit(archived=True)

        original_edit = thread.edit

        async def slow_edit(*args, **kwargs):
            await asyncio.sleep(0.05)  # 50ms simulated latency
            return await original_edit(*args, **kwargs)

        thread.edit = slow_edit

        fetched = await get_character_from_thread(thread)
        assert fetched is not None
        assert fetched.name == "Gildor"
        assert thread.archived is False

    @pytest.mark.asyncio
    async def test_thread_unarchive_with_transient_exception_handled_gracefully(self):
        """If thread.edit raises an unexpected exception in get_character_from_thread, handles gracefully."""
        guild = MockGuild(name="RPG")
        forum = MockForumChannel(name="karty-postaci", guild=guild)

        char = CharacterModel(discord_user_id="888", name="Boromir", character_class="Wojownik", race="Człowiek")
        thread, msg, _ = await get_or_create_character_sheet(forum, "888", char)
        await thread.edit(archived=True)

        async def failing_edit(*args, **kwargs):
            raise discord.HTTPException(response=None, message="Discord API 503 Service Unavailable")

        thread.edit = failing_edit

        # get_character_from_thread catches exception and returns None
        result = await get_character_from_thread(thread)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_forum_threads_handles_both_active_and_archived(self):
        """_get_all_forum_threads returns comprehensive list with 50+ mixed threads."""
        guild = MockGuild(name="RPG")
        forum = MockForumChannel(name="karty-postaci", guild=guild)

        created_threads = []
        for i in range(50):
            res = await forum.create_thread(name=f"Hero-{i} ({i})")
            t = res.thread
            if i % 2 == 0:
                await t.edit(archived=True)
            created_threads.append(t)

        all_threads = await _get_all_forum_threads(forum)
        assert len(all_threads) == 50


# ============================================================================
# 3. Stress Tests for ASCII Health Bar & Health Calculations
# ============================================================================

class TestAdversarialHealthBarAndHpMechanics:
    """Stress tests for health bar rendering and HP manipulation edge cases."""

    def test_health_bar_negative_current_hp(self):
        """Negative current HP clamps ratio to 0.0 without crash."""
        bar = create_health_bar(current=-15, max_val=30, length=10)
        assert "[░░░░░░░░░░]" in bar
        assert "-15/30 HP" in bar

    def test_health_bar_zero_max_hp(self):
        """Zero max HP does not cause ZeroDivisionError, clamps to safe max 0."""
        bar = create_health_bar(current=0, max_val=0, length=10)
        assert "[░░░░░░░░░░]" in bar
        assert "0/0 HP" in bar

    def test_health_bar_negative_max_hp(self):
        """Negative max HP is safely handled without division errors."""
        bar = create_health_bar(current=10, max_val=-5, length=10)
        assert "[░░░░░░░░░░]" in bar
        assert "10/0 HP" in bar

    def test_health_bar_massive_hp_values(self):
        """Massive HP values (e.g. 1,000,000 HP or overhealed current > max)."""
        # Current greater than max
        bar_over = create_health_bar(current=150, max_val=100, length=10)
        assert "[██████████]" in bar_over
        assert "150/100 HP" in bar_over

        # 1 Billion HP
        bar_huge = create_health_bar(current=500_000_000, max_val=1_000_000_000, length=10)
        assert "[█████░░░░░]" in bar_huge
        assert "500000000/1000000000 HP" in bar_huge

    def test_health_bar_custom_length_zero_or_negative(self):
        """Custom lengths like 0 or negative lengths render safely without error."""
        bar_zero = create_health_bar(current=10, max_val=20, length=0)
        assert "[] 10/20 HP" in bar_zero

        bar_neg = create_health_bar(current=10, max_val=20, length=-5)
        assert "[] 10/20 HP" in bar_neg

    def test_character_apply_damage_with_massive_temp_hp(self):
        """apply_damage absorbs entirely into temp_hp when temp_hp is large."""
        char = CharacterModel(discord_user_id="1", name="Tank", character_class="Barbarzyńca", race="Krasnolud", current_hp=20, max_hp=20, temp_hp=1000)
        
        hp_lost = char.apply_damage(300)
        assert hp_lost == 0
        assert char.temp_hp == 700
        assert char.current_hp == 20

    def test_character_apply_damage_overflowing_temp_hp_to_current_hp(self):
        """apply_damage exhausts temp_hp and deducts remainder from current_hp down to 0."""
        char = CharacterModel(discord_user_id="1", name="Tank", character_class="Barbarzyńca", race="Krasnolud", current_hp=20, max_hp=20, temp_hp=10)

        hp_lost = char.apply_damage(25)  # 10 absorbs temp, 15 from current_hp
        assert hp_lost == 15
        assert char.temp_hp == 0
        assert char.current_hp == 5

        # Overkill damage
        hp_lost_overkill = char.apply_damage(50)
        assert hp_lost_overkill == 5
        assert char.current_hp == 0

    def test_character_apply_damage_negative_or_zero(self):
        """apply_damage with 0 or negative values does nothing and returns 0."""
        char = CharacterModel(discord_user_id="1", name="Tank", character_class="Barbarzyńca", race="Krasnolud", current_hp=20, max_hp=20, temp_hp=5)
        assert char.apply_damage(0) == 0
        assert char.apply_damage(-10) == 0
        assert char.current_hp == 20
        assert char.temp_hp == 5

    def test_character_apply_heal_caps_at_max_hp(self):
        """apply_heal increases current_hp up to max_hp and returns actual healed amount."""
        char = CharacterModel(discord_user_id="1", name="Tank", character_class="Barbarzyńca", race="Krasnolud", current_hp=12, max_hp=20)
        healed = char.apply_heal(50)
        assert healed == 8
        assert char.current_hp == 20

    def test_character_apply_heal_negative_or_zero(self):
        """apply_heal with 0 or negative values returns 0."""
        char = CharacterModel(discord_user_id="1", name="Tank", character_class="Barbarzyńca", race="Krasnolud", current_hp=10, max_hp=20)
        assert char.apply_heal(0) == 0
        assert char.apply_heal(-20) == 0
        assert char.current_hp == 10


# ============================================================================
# 4. Stress Tests for Quest Journal & Quest Completion Edge Cases
# ============================================================================

class TestAdversarialQuestBoardAndQuests:
    """Stress tests for quest journal completion, edge cases, and deduplication."""

    def test_complete_non_existent_quest_id(self):
        """Completing a quest ID that does not exist returns None and does not mutate list."""
        qlist = QuestList(quests=[
            QuestItem(id="Q-001", title="Zadanie 1"),
            QuestItem(id="Q-002", title="Zadanie 2")
        ])
        result = qlist.complete_quest("Q-999")
        assert result is None
        assert len(qlist.active_quests()) == 2
        assert len(qlist.completed_quests()) == 0

    def test_complete_quest_with_empty_or_whitespace_id(self):
        """Completing a quest with empty string or whitespace does not match existing quests."""
        qlist = QuestList(quests=[
            QuestItem(id="Q-001", title="Zadanie 1")
        ])
        assert qlist.complete_quest("") is None
        assert qlist.complete_quest("   ") is None
        assert qlist.quests[0].status == "active"

    def test_complete_quest_case_insensitive_matching(self):
        """Matching quest ID or title works across case variations and whitespace."""
        qlist = QuestList(quests=[
            QuestItem(id="Q-001", title="Oczyszczenie Krypt")
        ])

        # Match by lowercase ID with whitespace
        res1 = qlist.complete_quest("  q-001  ")
        assert res1 is not None
        assert res1.id == "Q-001"
        assert res1.status == "completed"

        # Match by title
        qlist.quests[0].status = "active"
        res2 = qlist.complete_quest("oczyszczenie krypt")
        assert res2 is not None
        assert res2.status == "completed"

    def test_duplicate_quest_ids_completion_behavior(self):
        """If duplicate quest IDs exist in the board, complete_quest completes the first match."""
        q1 = QuestItem(id="Q-001", title="Zadanie A", status="active")
        q2 = QuestItem(id="Q-001", title="Zadanie B (Duplikat)", status="active")
        qlist = QuestList(quests=[q1, q2])

        completed = qlist.complete_quest("Q-001")
        assert completed is not None
        assert completed.title == "Zadanie A"
        assert q1.status == "completed"
        assert q2.status == "active"

    def test_quest_with_empty_objectives_list(self):
        """A quest with zero objectives transitions to completed cleanly without index errors."""
        quest = QuestItem(id="Q-EMPTY", title="Zadanie bez celów", objectives=[])
        qlist = QuestList(quests=[quest])

        res = qlist.complete_quest("Q-EMPTY")
        assert res is not None
        assert res.status == "completed"
        assert res.objectives == []

    def test_quest_board_embed_rendering_empty_list(self):
        """Empty QuestList renders an embed with fallback placeholder message."""
        empty_qlist = QuestList(quests=[])
        embed = build_quest_board_embed(empty_qlist)

        assert "Tablica Zadań" in embed.title
        active_field = next(f for f in embed.fields if "Aktywne Zadania" in f.name)
        assert "Brak aktywnych zadań" in active_field.value

    def test_quest_board_embed_rendering_50_plus_quests(self):
        """Rendering a large quest list with 50+ quests builds embed without crashing."""
        quests = [
            QuestItem(
                id=f"Q-{i:03d}",
                title=f"Wyprawa do Lochu #{i}",
                status="completed" if i % 2 == 0 else "active",
                objectives=[QuestObjective(text=f"Cel 1 dla zadania {i}", is_completed=(i % 2 == 0))]
            )
            for i in range(60)
        ]
        qlist = QuestList(quests=quests)
        embed = build_quest_board_embed(qlist)

        assert embed.title is not None
        assert len(embed.fields) >= 1
        # Check that DATA_JSON was injected into description
        data = extract_data_from_text(embed.description)
        assert data is not None
        assert len(data["quests"]) == 60

    @pytest.mark.asyncio
    async def test_get_and_update_quest_board_roundtrip(self):
        """get_quest_board and update_quest_board maintain state in #dziennik-zadan channel."""
        guild = MockGuild(name="RPG")
        ch = MockTextChannel(name="dziennik-zadan", guild=guild)

        # 1. Empty board
        qlist = await get_quest_board(ch)
        assert len(qlist.quests) == 0

        # 2. Add quest and update
        new_q = QuestItem(id="Q-001", title="Polowanie na orków", giver="Wójt", reward="50 GP")
        qlist.add_quest(new_q)
        await update_quest_board(ch, qlist)

        # 3. Retrieve updated board
        reloaded = await get_quest_board(ch)
        assert len(reloaded.quests) == 1
        assert reloaded.quests[0].id == "Q-001"
        assert reloaded.quests[0].reward == "50 GP"


# ============================================================================
# 5. Stress Tests for Models, StatBlock & Inventory
# ============================================================================

class TestAdversarialModelsAndStatBlock:
    """Stress tests for D&D 5e StatBlock modifier calculation and inventory handling."""

    def test_statblock_all_polish_and_english_aliases(self):
        """StatBlock modifier lookup supports all standard aliases in Polish and English."""
        stats = StatBlock(
            strength=18,      # +4
            dexterity=14,     # +2
            constitution=15,  # +2
            intelligence=8,   # -1
            wisdom=10,        # +0
            charisma=3        # -4
        )

        assert stats.get_modifier("strength") == 4
        assert stats.get_modifier("str") == 4
        assert stats.get_modifier("siła") == 4
        assert stats.get_modifier("sila") == 4
        assert stats.get_modifier("  STR  ") == 4

        assert stats.get_modifier("dexterity") == 2
        assert stats.get_modifier("zręczność") == 2
        assert stats.get_modifier("zrecznosc") == 2

        assert stats.get_modifier("constitution") == 2
        assert stats.get_modifier("kondycja") == 2
        assert stats.get_modifier("budowa") == 2

        assert stats.get_modifier("intelligence") == -1
        assert stats.get_modifier("inteligencja") == -1

        assert stats.get_modifier("wisdom") == 0
        assert stats.get_modifier("mądrość") == 0
        assert stats.get_modifier("madrosc") == 0

        assert stats.get_modifier("charisma") == -4
        assert stats.get_modifier("charyzma") == -4

    def test_statblock_unknown_stat_fallback(self):
        """Unknown stat names default safely to value 10 -> modifier 0."""
        stats = StatBlock(strength=20)
        assert stats.get_modifier("unknown_attribute") == 0
        assert stats.get_modifier("") == 0

    def test_statblock_extreme_values(self):
        """Stat values from 0 up to 100 calculate correct mathematical D&D 5e modifiers."""
        # Value 0: (0 - 10) // 2 = -5
        s_zero = StatBlock(strength=0)
        assert s_zero.get_modifier("str") == -5

        # Value 1: (1 - 10) // 2 = -5
        s_one = StatBlock(strength=1)
        assert s_one.get_modifier("str") == -5

        # Value 30: (30 - 10) // 2 = +10
        s_god = StatBlock(strength=30)
        assert s_god.get_modifier("str") == 10

        # Value 100: (100 - 10) // 2 = +45
        s_huge = StatBlock(strength=100)
        assert s_huge.get_modifier("str") == 45

    def test_character_inventory_item_deduplication_and_partial_removal(self):
        """add_item aggregates quantities; remove_item decrements or removes."""
        char = CharacterModel(discord_user_id="1", name="Kupiec", character_class="Łotrzyk", race="Niziołek")

        # 1. Add item
        char.add_item(ItemModel(name="Mikstura Leczenia", quantity=2, item_type="consumable"))
        assert len(char.inventory) == 1
        assert char.inventory[0].quantity == 2

        # 2. Add same item (case insensitive)
        char.add_item(ItemModel(name="mikstura leczenia", quantity=3, item_type="consumable"))
        assert len(char.inventory) == 1
        assert char.inventory[0].quantity == 5

        # 3. Partial removal
        assert char.remove_item("Mikstura Leczenia", quantity=2) is True
        assert char.inventory[0].quantity == 3

        # 4. Total removal
        assert char.remove_item("mikstura leczenia", quantity=3) is True
        assert len(char.inventory) == 0

        # 5. Remove non-existent
        assert char.remove_item("Nieistniejący Przedmiot") is False

    def test_character_level_validation_minimum_1(self):
        """CharacterModel validates level to be at least 1."""
        char_neg = CharacterModel(discord_user_id="1", name="Nowicjusz", character_class="Mag", race="Gnom", level=-5)
        assert char_neg.level == 1

        char_zero = CharacterModel(discord_user_id="1", name="Nowicjusz", character_class="Mag", race="Gnom", level=0)
        assert char_zero.level == 1

        char_valid = CharacterModel(discord_user_id="1", name="Weteran", character_class="Mag", race="Gnom", level=12)
        assert char_valid.level == 12


# ============================================================================
# 6. Stress Tests for Channel Manager & Infrastructure Idempotency
# ============================================================================

class TestAdversarialChannelManager:
    """Stress tests for channel hierarchy setup, Unicode normalization, and idempotency."""

    def test_normalize_name_with_extreme_unicode_and_symbols(self):
        """normalize_name handles symbols, accents, Polish characters, and spaces."""
        assert normalize_name("📜 KAMPANIA I FABUŁA") == "kampaniaifabuła"
        assert normalize_name("🛡️ POSTACIE I MECHANIKA") == "postacieimechanika"
        assert normalize_name("#zasady-i-mechanika") == "zasady-i-mechanika"
        assert normalize_name("  dziennik _ zadań  ") == "dziennik_zadan"
        assert normalize_name("") == ""
        assert normalize_name(None) == ""

    @pytest.mark.asyncio
    async def test_setup_campaign_idempotency_triple_run(self):
        """Running setup_campaign_infrastructure 3 times produces identical hierarchy with 0 duplicate channels."""
        guild = MockGuild(name="Epik Kampania")

        report1 = await setup_campaign_infrastructure(guild)
        assert len(report1["categories_created"]) == 3
        assert len(report1["channels_created"]) == 6
        assert len(report1["forums_created"]) == 2

        cat_count_1 = len(guild.categories)
        text_count_1 = len(guild.text_channels)
        forum_count_1 = len(guild.forums)

        # Second run
        report2 = await setup_campaign_infrastructure(guild)
        assert len(report2["categories_created"]) == 0
        assert len(report2["channels_created"]) == 0
        assert len(report2["forums_created"]) == 0
        assert len(report2["reused"]) == (cat_count_1 + text_count_1 + forum_count_1)

        # Third run
        report3 = await setup_campaign_infrastructure(guild)
        assert len(report3["categories_created"]) == 0
        assert len(guild.categories) == cat_count_1
        assert len(guild.text_channels) == text_count_1
        assert len(guild.forums) == forum_count_1

    @pytest.mark.asyncio
    async def test_setup_campaign_with_preexisting_partial_channels(self):
        """If some channels pre-exist outside or inside categories, setup reuses them gracefully."""
        guild = MockGuild(name="Częściowy Serwer")
        # Pre-create category and one channel manually
        cat = await guild.create_category("📜 KAMPANIA I FABUŁA")
        await guild.create_text_channel("stół-gry", category=cat)

        report = await setup_campaign_infrastructure(guild)
        assert "📜 KAMPANIA I FABUŁA" not in report["categories_created"]
        assert len(report["categories_created"]) == 2
        assert len(guild.categories) == 3
        assert any("stół-gry" in r for r in report["reused"])

    @pytest.mark.asyncio
    async def test_fetch_campaign_rules_returns_default_when_empty_or_missing(self):
        """fetch_campaign_rules returns safe fallback when channel has no messages or pins."""
        guild = MockGuild(name="Pusty")
        res = await fetch_campaign_rules(guild)
        assert "System bazowy: Standardowe D&D 5e." in res
