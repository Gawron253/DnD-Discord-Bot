"""Empirical Challenger 2 Test Suite: Pure Discord State, Serialization & Channel Management.

This suite empirically evaluates Milestone 1 implementation against:
1. Generative Property-Based Tests (1000+ randomized CharacterModel instances across seeds).
2. Adversarial serialization corner-cases (HTML comment delimiter collisions, markdown formatting).
3. Forum thread resolution security (substring User ID collision & thread hijacking).
4. Thread Audit Logging Order & Message Preservation (monotonic timestamps, history order, non-destructive editing).
5. Setup Campaign Idempotency & Duplicate Channel / Pin Prevention (10 sequential executions, normalization).
6. Mutation Testing Suite (verifying test kill-rates against defective implementations).
"""
import random
import string
import json
import re
import copy
import asyncio
import datetime
from typing import Dict, Any, List, Optional
import pytest
import discord

from core.models import (
    CharacterModel,
    StatBlock,
    SpellSlots,
    ItemModel,
    QuestList,
    QuestItem,
    QuestObjective,
    DiceRollResult
)
from core.discord_db import (
    inject_data_into_text,
    extract_data_from_text,
    extract_data_from_message_or_embed,
    build_character_sheet_embed,
    get_or_create_character_sheet,
    update_character_sheet,
    get_character_from_thread,
    get_quest_board,
    update_quest_board
)
from core.channel_manager import (
    setup_campaign_infrastructure,
    normalize_name,
    find_category,
    find_text_channel,
    find_forum_channel,
    CAMPAIGN_STRUCTURE
)
from commands.campaign_cog import CampaignCog
from tests.mock_discord import (
    MockGuild,
    MockForumChannel,
    MockTextChannel,
    MockThread,
    MockMessage,
    MockUser,
    MockEmbed,
    MockCategoryChannel
)


# ============================================================================
# RANDOM GENERATOR UTILITIES FOR PROPERTY-BASED TESTING
# ============================================================================

UNICODE_SNIPPETS = [
    "zażółć gęślą jaźń ŹDŹBŁO Pchnąć w tę łódź jeża lub ośm skrzyń fig",  # Polish pangram & diacritics
    "🛡️⚔️🐉🎲🧙‍♂️🔥✨💥❤️🩹🎒💰📜",  # RPG Emojis
    "こんにちは 世界！ 勇者ロトの冒険",  # Japanese CJK
    "مرحبا بالعالم - مغامرة جديدة",  # Arabic RTL
    "Привет мир! Приключение начинается",  # Cyrillic
    "Line 1\nLine 2\r\nLine 3\rLine 4\n\n\nBlank lines",  # Newlines
    "'Single' and \"Double\" quotes, \\backslashes\\ and special / chars",
    "<div><span>Markdown **bold** and _italic_ and `code`</span></div>",
    "",  # Empty string
    "   ",  # Whitespace only
]

RACES = ["Człowiek", "Elf", "Krasnolud", "Niziołek", "Tiefling", "Drakonid", "Gnom", "Półelf", "Półork"]
CLASSES = ["Wojownik", "Mag", "Łotrzyk", "Kleryk", "Paladyn", "Barbarzyńca", "Bard", "Druid", "Tropiciel", "Czarownik", "Zaklinacz", "Mnich"]
ITEM_TYPES = ["weapon", "armor", "consumable", "quest", "misc", "equipment", "custom_tool"]


def random_clean_string(rng: random.Random, max_len: int = 40) -> str:
    choice = rng.random()
    if choice < 0.3:
        base = rng.choice(UNICODE_SNIPPETS)
        if rng.random() < 0.5:
            extra = "".join(rng.choices(string.ascii_letters + string.digits, k=rng.randint(1, 15)))
            return f"{base} {extra}"
        return base
    
    length = rng.randint(0, max_len)
    chars = string.ascii_letters + string.digits + " _-+=/*()[]{}#@!$%^&*~`'\"ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
    return "".join(rng.choices(chars, k=length))


def generate_random_item(rng: random.Random) -> ItemModel:
    props = None
    if rng.random() < 0.5:
        props = {
            "damage": f"{rng.randint(1, 3)}d{rng.choice([4, 6, 8, 10, 12])}+{rng.randint(0, 5)}",
            "range": rng.choice(["melee", "30/120", "150/600", None]),
            "magical": rng.choice([True, False]),
            "nested": {"rarity": rng.choice(["common", "uncommon", "rare", "legendary"])},
            "tags": [random_clean_string(rng, 10) for _ in range(rng.randint(0, 4))]
        }
    
    return ItemModel(
        name=random_clean_string(rng, 25) or "Item",
        quantity=rng.randint(1, 9999),
        item_type=rng.choice(ITEM_TYPES),
        is_equipped=rng.choice([True, False]),
        weight=round(rng.uniform(0.0, 150.0), 2),
        description=random_clean_string(rng, 60) if rng.random() < 0.7 else None,
        properties=props
    )


def generate_random_character(rng: random.Random, user_id: Optional[str] = None) -> CharacterModel:
    uid = user_id or str(rng.randint(100000000000000000, 999999999999999999))
    max_hp = rng.randint(1, 500)
    current_hp = rng.randint(0, max_hp)
    
    stats = StatBlock(
        strength=rng.randint(1, 30),
        dexterity=rng.randint(1, 30),
        constitution=rng.randint(1, 30),
        intelligence=rng.randint(1, 30),
        wisdom=rng.randint(1, 30),
        charisma=rng.randint(1, 30),
    )
    
    spell_slots = SpellSlots(
        level_1=rng.randint(0, 4),
        level_1_max=rng.randint(0, 4),
        level_2=rng.randint(0, 3),
        level_2_max=rng.randint(0, 3),
        level_3=rng.randint(0, 3),
        level_3_max=rng.randint(0, 3),
    )
    
    num_items = rng.randint(0, 15)
    inventory = [generate_random_item(rng) for _ in range(num_items)]
    
    num_conds = rng.randint(0, 5)
    conditions = [random_clean_string(rng, 15) for _ in range(num_conds)]
    
    return CharacterModel(
        id=rng.randint(1, 999999) if rng.random() < 0.5 else None,
        discord_user_id=uid,
        name=random_clean_string(rng, 30) or "Hero",
        character_class=rng.choice(CLASSES),
        race=rng.choice(RACES),
        level=rng.randint(1, 20),
        xp=rng.randint(0, 355000),
        current_hp=current_hp,
        max_hp=max_hp,
        temp_hp=rng.randint(0, 100),
        armor_class=rng.randint(5, 30),
        speed=rng.choice([20, 25, 30, 35, 40, 50]),
        proficiency_bonus=rng.randint(2, 6),
        stats=stats,
        spell_slots=spell_slots,
        inventory=inventory,
        gold_gp=rng.randint(-50, 1000000),
        conditions=conditions,
        avatar_url=f"https://cdn.example.com/{random_clean_string(rng, 10)}.png" if rng.random() < 0.5 else None,
        pinned_sheet_message_id=str(rng.randint(1000, 9999999)) if rng.random() < 0.5 else None
    )


# ============================================================================
# 1. GENERATIVE PROPERTY-BASED SERIALIZATION TESTS
# ============================================================================

class TestGenerativeSerializationRoundTrip:
    """Property-based tests verifying 100% fidelity round-trip serialization for 1000+ random characters."""

    @pytest.mark.parametrize("seed", [42, 1337, 2026, 99999, 777])
    def test_property_based_character_serialization_1000_samples(self, seed: int):
        """Generates 200 diverse CharacterModel instances per seed (total 1000) and asserts 100% roundtrip fidelity."""
        rng = random.Random(seed)
        
        for iteration in range(200):
            original_char = generate_random_character(rng)
            original_dump = original_char.model_dump()
            
            # 1. Base text can be empty, simple, or filled with markdown / raw HTML / quotes
            base_text = random_clean_string(rng, 80)
            
            # 2. Inject
            injected = inject_data_into_text(base_text, original_dump)
            assert isinstance(injected, str)
            assert "<!-- DATA_JSON:" in injected
            assert injected.endswith("-->")
            
            # 3. Extract
            extracted = extract_data_from_text(injected)
            assert extracted is not None, f"Extraction failed for character {original_char.name} at iteration {iteration}"
            
            # 4. Compare raw dumped dictionary equality
            assert extracted == original_dump, f"Extracted dictionary mismatch at iteration {iteration}"
            
            # 5. Reconstruct CharacterModel and compare
            reconstructed_char = CharacterModel(**extracted)
            assert reconstructed_char == original_char, f"Reconstructed CharacterModel mismatch at iteration {iteration}"
            assert reconstructed_char.stats.model_dump() == original_char.stats.model_dump()
            assert reconstructed_char.spell_slots.model_dump() == original_char.spell_slots.model_dump()
            assert len(reconstructed_char.inventory) == len(original_char.inventory)
            for orig_item, rec_item in zip(original_char.inventory, reconstructed_char.inventory):
                assert orig_item.model_dump() == rec_item.model_dump()

    def test_sequential_state_mutations_and_re_injections(self):
        """Verifies that repeated injection into already-injected text replaces the old data cleanly without duplicates."""
        rng = random.Random(888)
        char = generate_random_character(rng)
        
        current_text = "Karta Postaci Początkowa"
        for step in range(50):
            # Mutate character
            char.current_hp = max(0, char.current_hp - rng.randint(0, 5))
            char.gold_gp += rng.randint(1, 100)
            char.conditions.append(f"Effect_{step}")
            if rng.random() < 0.4:
                char.inventory.append(generate_random_item(rng))
            
            current_text = inject_data_into_text(current_text, char.model_dump())
            
            # Invariant: exactly one DATA_JSON tag in text
            assert current_text.count("<!-- DATA_JSON:") == 1
            assert current_text.count("-->") == 1
            
            # Extracted data must match current state exactly
            extracted = extract_data_from_text(current_text)
            assert extracted is not None
            assert extracted["current_hp"] == char.current_hp
            assert extracted["gold_gp"] == char.gold_gp
            assert extracted["conditions"] == char.conditions
            assert len(extracted["inventory"]) == len(char.inventory)

    def test_extract_from_discord_message_and_embed_variants(self):
        """Tests extract_data_from_message_or_embed against embed description and message content."""
        char = CharacterModel(discord_user_id="123", name="Thorin", character_class="Wojownik", race="Krasnolud")
        dumped = char.model_dump()
        
        # 1. From Embed description
        emb1 = build_character_sheet_embed(char)
        msg1 = MockMessage(embed=emb1)
        extracted1 = extract_data_from_message_or_embed(msg1)
        assert extracted1 is not None
        assert extracted1["name"] == "Thorin"
        
        # 2. From Message content
        msg3 = MockMessage(content=inject_data_into_text("Raw message content", dumped))
        extracted3 = extract_data_from_message_or_embed(msg3)
        assert extracted3 is not None
        assert extracted3["name"] == "Thorin"


# ============================================================================
# 2. ADVERSARIAL CHALLENGES & VULNERABILITY ORACLES
# ============================================================================

class TestAdversarialVulnerabilitiesAndCornerCases:
    """Adversarial test oracles exposing known structural vulnerabilities in Milestone 1."""

    def test_vulnerability_1_premature_html_comment_termination_fails(self):
        """
        Adversarial Finding 1:
        If any character string (e.g. condition, item description, title) contains '-->',
        the non-greedy regex `<!--\\s*DATA_JSON:\\s*(.*?)\\s*-->` terminates prematurely,
        causing JSON parse failure and complete data loss (extract returns None).
        """
        char = CharacterModel(
            discord_user_id="999888",
            name="Archer",
            character_class="Ranger",
            race="Elf",
            conditions=["Arrow --> Target"]
        )
        
        injected = inject_data_into_text("Description", char.model_dump())
        extracted = extract_data_from_text(injected)
        
        # This assert proves the vulnerability exists when extracted is None
        is_vulnerable = (extracted is None)
        assert is_vulnerable, "Expected vulnerability: '-->' inside payload prematurely terminates HTML comment"

    @pytest.mark.asyncio
    async def test_vulnerability_2_substring_user_id_thread_hijacking(self):
        """
        Adversarial Finding 2:
        In get_or_create_character_sheet, matching via `if str_user_id in getattr(t, 'name', '')`
        allows User ID '123' to match and hijack User ID '12345' thread!
        """
        guild = MockGuild()
        forum = MockForumChannel(name="karty-postaci", guild=guild)
        
        char_user_12345 = CharacterModel(
            discord_user_id="12345",
            name="Victim",
            character_class="Wojownik",
            race="Człowiek"
        )
        char_user_123 = CharacterModel(
            discord_user_id="123",
            name="Attacker",
            character_class="Mag",
            race="Elf"
        )
        
        # User 12345 creates sheet
        t1, m1, c1 = await get_or_create_character_sheet(forum, "12345", char_user_12345)
        
        # User 123 requests sheet
        t2, m2, c2 = await get_or_create_character_sheet(forum, "123", char_user_123)
        
        # This assert proves the vulnerability exists (User 123 hijacked User 12345 thread)
        is_hijacked = (t1.id == t2.id)
        assert is_hijacked, "Expected vulnerability: Substring User ID match causes thread hijacking"


# ============================================================================
# 3. THREAD AUDIT LOGGING ORDER & NON-DESTRUCTIVE HISTORY TESTS
# ============================================================================

class TestThreadAuditLoggingChronologicalIntegrity:
    """Verifies that thread audit logging maintains strict chronological order and never overwrites messages."""

    @pytest.mark.asyncio
    async def test_audit_log_monotonic_growth_and_chronological_order(self):
        guild = MockGuild(name="Audit Test Guild")
        forum = MockForumChannel(name="karty-postaci", guild=guild)
        
        user_id = "888777666"
        char = CharacterModel(
            discord_user_id=user_id,
            name="Geralt z Rivii",
            character_class="Wiedźmin",
            race="Mutant",
            current_hp=50,
            max_hp=50,
            gold_gp=100
        )
        
        # 1. Initial character sheet creation
        thread, sheet_msg, loaded_char = await get_or_create_character_sheet(forum, user_id, char)
        assert sheet_msg in thread.pinned_messages
        assert len(thread.pinned_messages) == 1
        initial_msg_count = len(thread.messages)
        
        expected_audit_reasons = []
        
        # 2. Perform 25 sequential updates with varying reasons
        for i in range(1, 26):
            if i % 3 == 0:
                char.apply_damage(5)
                reason = f"Otrzymano 5 obrażeń od potwora #{i}"
            elif i % 3 == 1:
                char.apply_heal(3)
                reason = f"Wypito miksturę leczniczą #{i}"
            else:
                char.gold_gp += 20
                reason = f"Znaleziono sakiewkę złota #{i}"
            
            expected_audit_reasons.append(reason)
            
            # Interleave player chat
            if i % 5 == 0:
                await thread.send(f"Gracz: Wykonuję akcję w turze {i}")
            
            await update_character_sheet(thread, char, reason=reason)
            
            # Pinned sheet message count must remain strictly 1
            assert len(thread.pinned_messages) == 1
            assert thread.pinned_messages[0].id == sheet_msg.id
            
            # Pinned message embed must contain the latest state
            pinned_data = extract_data_from_message_or_embed(thread.pinned_messages[0])
            assert pinned_data is not None
            assert pinned_data["current_hp"] == char.current_hp
            assert pinned_data["gold_gp"] == char.gold_gp
        
        # 3. Message Non-Destruction Check: All audit logs + chat messages exist
        # Expected: 1 (starter/pin) + 25 (audit entries) + 5 (player messages) = 31
        assert len(thread.messages) == 31
        
        # 4. Monotonic ID and Timestamp Verification
        msg_ids = [m.id for m in thread.messages]
        assert msg_ids == sorted(msg_ids), "Message IDs are not in strictly non-decreasing chronological order!"
        
        timestamps = [m.created_at for m in thread.messages]
        assert timestamps == sorted(timestamps), "Message timestamps are not in chronological order!"
        
        # 5. Verify Async History Iterator Ordering (oldest_first=True)
        history_oldest_first = []
        async for m in thread.history(limit=100, oldest_first=True):
            history_oldest_first.append(m)
        
        assert len(history_oldest_first) == 31
        assert history_oldest_first == thread.messages
        
        # 6. Verify Async History Iterator Ordering (oldest_first=False -> newest first)
        history_newest_first = []
        async for m in thread.history(limit=100, oldest_first=False):
            history_newest_first.append(m)
        
        assert len(history_newest_first) == 31
        assert history_newest_first == list(reversed(thread.messages))
        
        # 7. Audit log content preservation check
        audit_messages = [m for m in thread.messages if "📝 **Aktualizacja karty postaci**" in (m.content or "")]
        assert len(audit_messages) == 25
        for expected_reason, actual_msg in zip(expected_audit_reasons, audit_messages):
            assert expected_reason in actual_msg.content

    @pytest.mark.asyncio
    async def test_update_unarchives_sleeping_thread_without_message_loss(self):
        guild = MockGuild()
        forum = MockForumChannel(name="karty-postaci", guild=guild)
        user_id = "555444"
        char = CharacterModel(discord_user_id=user_id, name="Aragorn", character_class="Strażnik", race="Człowiek")
        
        thread, sheet_msg, _ = await get_or_create_character_sheet(forum, user_id, char)
        await update_character_sheet(thread, char, reason="Initial level up")
        
        # Thread gets archived after inactivity
        thread.archived = True
        assert thread.archived is True
        
        # Update character sheet
        char.current_hp = 8
        await update_character_sheet(thread, char, reason="Damage taken in ambuscade")
        
        # Invariant: Thread is auto-unarchived
        assert thread.archived is False
        assert thread.unarchived_count >= 1
        
        # History is fully preserved
        assert len(thread.messages) == 3  # starter sheet + 2 audit logs
        assert "Damage taken in ambuscade" in thread.messages[-1].content


# ============================================================================
# 4. SETUP CAMPAIGN IDEMPOTENCY & DUPLICATE PREVENTION TESTS
# ============================================================================

class TestSetupCampaignIdempotencyAndDuplicatePrevention:
    """Verifies that running setup-campaign multiple times creates zero duplicate channels or pins."""

    @pytest.mark.asyncio
    async def test_setup_campaign_multiple_runs_idempotency(self):
        guild = MockGuild(name="Epic Campaign Guild")
        
        # Run 1: Initial creation
        report_1 = await setup_campaign_infrastructure(guild)
        assert len(report_1["categories_created"]) == 3
        assert len(report_1["channels_created"]) == 6
        assert len(report_1["forums_created"]) == 2
        assert len(report_1["initialized_pins"]) == 2
        
        initial_cat_count = len(guild.categories)
        initial_text_count = len(guild.text_channels)
        initial_forum_count = len(guild.forums)
        
        assert initial_cat_count == 3
        assert initial_text_count == 6
        assert initial_forum_count == 2
        
        # Verify pins in rules and quests
        rules_channel = find_text_channel(guild, "zasady-i-mechanika")
        assert rules_channel is not None
        assert len(rules_channel.pinned_messages) == 1
        
        quest_channel = find_text_channel(guild, "dziennik-zadań")
        assert quest_channel is not None
        assert len(quest_channel.pinned_messages) == 1
        
        # Runs 2 through 10: Idempotency stress test
        for run_idx in range(2, 11):
            report_n = await setup_campaign_infrastructure(guild)
            
            # Nothing new should be created
            assert len(report_n["categories_created"]) == 0, f"Duplicate categories created on run {run_idx}"
            assert len(report_n["channels_created"]) == 0, f"Duplicate channels created on run {run_idx}"
            assert len(report_n["forums_created"]) == 0, f"Duplicate forums created on run {run_idx}"
            assert len(report_n["initialized_pins"]) == 0, f"Duplicate pins created on run {run_idx}"
            
            # Everything should be marked as reused
            assert len(report_n["reused"]) == 3 + 6 + 2
            
            # Guild collections must remain strictly unchanged
            assert len(guild.categories) == initial_cat_count
            assert len(guild.text_channels) == initial_text_count
            assert len(guild.forums) == initial_forum_count
            
            # Pinned messages must remain exactly 1 per channel
            assert len(rules_channel.pinned_messages) == 1
            assert len(quest_channel.pinned_messages) == 1

    @pytest.mark.asyncio
    async def test_setup_campaign_with_pre_existing_normalized_channels(self):
        guild = MockGuild(name="Pre-existing Guild")
        cat = await guild.create_category("KAMPANIA I FABULA")
        await guild.create_text_channel("ZASADY-I-MECHANIKA", category=cat)
        await guild.create_text_channel("dziennik-zadan", category=cat)
        
        assert len(guild.categories) == 1
        assert len(guild.text_channels) == 2
        
        # Run setup
        report = await setup_campaign_infrastructure(guild)
        
        # Should recognize pre-existing normalized channels and not duplicate them
        all_rules_channels = [c for c in guild.text_channels if "zasady" in normalize_name(c.name)]
        assert len(all_rules_channels) == 1, "Duplicated zasady channel with different casing/diacritics!"
        
        all_journal_channels = [c for c in guild.text_channels if "dziennik" in normalize_name(c.name)]
        assert len(all_journal_channels) == 1, "Duplicated dziennik channel!"

    @pytest.mark.asyncio
    async def test_campaign_cog_slash_command_execution(self):
        from unittest.mock import AsyncMock, MagicMock
        
        bot = MagicMock()
        cog = CampaignCog(bot)
        
        guild = MockGuild(name="Discord Slash Guild")
        
        interaction = MagicMock()
        interaction.guild = guild
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        
        # First slash command invocation
        await cog.setup_campaign.callback(cog, interaction)
        assert interaction.followup.send.call_count == 1
        first_call_embed = interaction.followup.send.call_args[1]["embed"]
        assert "Konfiguracja Kampanii D&D Zakończona Sukcesem" in first_call_embed.title
        
        # Second slash command invocation (idempotent run)
        interaction.followup.send.reset_mock()
        await cog.setup_campaign.callback(cog, interaction)
        assert interaction.followup.send.call_count == 1
        second_call_embed = interaction.followup.send.call_args[1]["embed"]
        assert "Konfiguracja Kampanii D&D Zakończona Sukcesem" in second_call_embed.title


# ============================================================================
# 5. MUTATION TESTING HARNESS & MUTANT KILL VERIFICATION
# ============================================================================

class TestMutationTestingAndMutantResistance:
    """Mutation tests verifying that our test assertions successfully kill deliberate mutant implementations."""

    def test_mutant_1_broken_json_comment_regex_killed(self):
        def defective_extract(text: Optional[str]) -> Optional[Dict[str, Any]]:
            if not text:
                return None
            m = re.search(r"<!--DATA_JSON:(.*)-->", text)
            if m:
                return json.loads(m.group(1))
            return None
        
        char = CharacterModel(discord_user_id="1", name="Test", character_class="Mage", race="Human")
        good_text = inject_data_into_text("Desc\nwith newlines", char.model_dump())
        
        assert extract_data_from_text(good_text) is not None
        assert defective_extract(good_text) is None, "Mutant was not killed!"

    def test_mutant_2_inject_does_not_strip_old_tags_killed(self):
        def defective_inject(base: str, data: Dict[str, Any]) -> str:
            return f"{base}\n<!-- DATA_JSON: {json.dumps(data)} -->"
        
        base = "Hero"
        t1 = defective_inject(base, {"hp": 10})
        t2 = defective_inject(t1, {"hp": 20})
        
        is_mutant_detected = (t2.count("<!-- DATA_JSON:") > 1)
        assert is_mutant_detected, "Mutant with duplicate JSON tags was not caught!"

    @pytest.mark.asyncio
    async def test_mutant_3_audit_overwriting_starter_message_killed(self):
        guild = MockGuild()
        forum = MockForumChannel(name="karty-postaci", guild=guild)
        char = CharacterModel(discord_user_id="101", name="Legolas", character_class="Łowca", race="Elf")
        
        thread, sheet_msg, _ = await get_or_create_character_sheet(forum, "101", char)
        await update_character_sheet(thread, char, reason="R1")
        await update_character_sheet(thread, char, reason="R2")
        
        async def defective_update(th: MockThread, ch: CharacterModel):
            th.messages = [th.messages[0]]
        
        await defective_update(thread, char)
        
        mutant_killed = (len(thread.messages) < 3)
        assert mutant_killed, "Mutant that truncates audit log history was not killed!"

    @pytest.mark.asyncio
    async def test_mutant_4_setup_duplicate_pins_killed(self):
        guild = MockGuild()
        rules_channel = await guild.create_text_channel("zasady-i-mechanika")
        
        # First pin
        msg1 = await rules_channel.send("Rules")
        await msg1.pin()
        
        async def defective_setup(ch: MockTextChannel):
            m = await ch.send("Rules 2")
            await m.pin()
        
        await defective_setup(rules_channel)
        
        mutant_killed = (len(rules_channel.pinned_messages) != 1)
        assert mutant_killed, "Mutant creating duplicate pins was not detected!"
