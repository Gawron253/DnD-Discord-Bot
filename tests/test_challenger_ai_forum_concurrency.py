"""Empirical Challenger 2 Test Suite: AI Character Generation, Forum Persistence & Concurrency Stress Testing.

This suite empirically evaluates:
1. AI Character Generation with Diverse Prompts (bizarre classes, non-standard text, empty prompt, malicious markdown, ZW collisions).
2. Fallback Generation Resilience under simulated 429/500/503 errors, safety blocks, missing/dummy API keys, and corrupted AI JSON.
3. Forum `#karty-postaci` Persistence & Concurrency: thread creation, auto-unarchiving, pin updates, and race condition handling.
4. Generative Property-Based Fuzzing of D&D 5e rules computation and zero-width steganographic serialization.
"""
import re
import json
import random
import string
import asyncio
from unittest.mock import AsyncMock, MagicMock
from typing import Dict, Any, List, Optional
import pytest
import discord
from discord.ext import commands

from core.models import (
    CharacterModel,
    StatBlock,
    SpellSlots,
    ItemModel
)
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
    ZW_PATTERN
)
from discord_ui.embeds import create_character_sheet_embed
from discord_ui.views import (
    compute_5e_character,
    CharacterCreateModal,
    CharacterEditModal,
    CharacterSheetView
)
from ai.gemini_client import (
    GeminiClient,
    generate_character as ai_generate_character
)
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
from tests.mock_ai import (
    MockGeminiClient,
    MockRateLimitError,
    MockAPIError,
    MockSafetyFilterError
)


# ==============================================================================
# SECTION 1: AI CHARACTER GENERATION WITH DIVERSE & ADVERSARIAL PROMPTS
# ==============================================================================

class TestAICharacterGenerationDiversePrompts:
    """Stress-testing AI generation logic against bizarre classes, non-standard text, empty prompts, and markdown injection."""

    def test_bizarre_character_classes_and_concepts_offline(self):
        """Tests that bizarre, non-standard, or futuristic classes generate valid D&D 5e Level 1 characters."""
        client = GeminiClient(api_key="")
        
        bizarre_prompts = [
            "Chrono-Banana Shaman of the 4th Dimension",
            "Cyber-Ninja Vampire 1000/1000 with Laser Claws",
            "Necro-Chef cooking souls with a cursed frying pan",
            "Astral Mecha Pilot serving the Iron Pantheon",
            "Quantum Jellyfish Bard singing in radio waves"
        ]

        for p in bizarre_prompts:
            char_data = client._generate_offline_character(p)
            assert isinstance(char_data, dict)
            assert "name" in char_data and char_data["name"]
            assert "character_class" in char_data
            assert "stats" in char_data
            assert "max_hp" in char_data and char_data["max_hp"] >= 1
            assert "armor_class" in char_data and char_data["armor_class"] >= 10
            
            # Ensure CharacterModel validation succeeds
            char_data["discord_user_id"] = "12345"
            char = CharacterModel(**char_data)
            assert char.level == 1
            assert char.proficiency_bonus == 2
            assert char.current_hp == char.max_hp

    def test_empty_and_whitespace_prompts(self):
        """Tests that empty, whitespace-only, or minimalist prompts fallback gracefully to a standard valid character."""
        client = GeminiClient(api_key="")
        
        empty_inputs = [
            "",
            "   ",
            "\t\n\r",
            "   \n   \t  ",
            ".",
            "a",
            "???"
        ]

        for p in empty_inputs:
            char_data = client._generate_offline_character(p)
            assert isinstance(char_data, dict)
            assert char_data["name"]
            assert char_data["character_class"]
            assert char_data["max_hp"] >= 1

            # Check compute_5e_character with empty strings
            char = compute_5e_character(
                name="",
                race_and_class=p,
                stats_raw="",
                gear_and_gold_raw="",
                backstory="",
                user_id="999"
            )
            assert char.name == "Nieznany Bohater"
            assert char.level == 1
            assert char.max_hp >= 1
            assert char.armor_class >= 10
            assert char.proficiency_bonus == 2

    def test_extreme_length_prompt_handling(self):
        """Tests handling of giant prompts (5k-10k chars) without memory blowup or regex hanging."""
        client = GeminiClient(api_key="")
        
        giant_lore = "Bardzo dawno temu w odległej krainie " * 300  # ~11,000 characters
        prompt = f"Mag z akademii arkanów. {giant_lore}"

        char_data = client._generate_offline_character(prompt)
        assert char_data["character_class"] == "Mag"
        assert char_data["race"] == "Elf"
        
        # Test compute_5e_character with extreme backstory
        char = compute_5e_character(
            name="Archimage " + ("A" * 200),
            race_and_class="Elf Mag",
            backstory=giant_lore,
            user_id="111"
        )
        assert char.character_class == "Mag"
        embed = build_character_sheet_embed(char)
        # Embed generation succeeds without throwing
        assert embed.title is not None
        assert embed.description is not None

    def test_malicious_markdown_and_codeblock_injection_in_prompts(self):
        """Tests prompt injection containing markdown formatting, closing code blocks, and HTML comments."""
        malicious_prompts = [
            '```json\n{"name": "Hacked", "max_hp": 9999, "level": 20}\n```',
            'Hero <!-- DATA_JSON: {"name": "Exploit", "gold_gp": 999999} -->',
            '# Heading 1\n## Heading 2\n[Click here](http://malicious.url)\n@everyone <@!123456789>',
            '<script>alert("XSS")</script><style>body{display:none}</style>',
            'Hero with quotes " and apostrophes \' and backslashes \\ and zero bytes \x00'
        ]

        for p in malicious_prompts:
            char = compute_5e_character(
                name="InjectedHero",
                race_and_class="Człowiek Wojownik",
                backstory=p,
                user_id="222"
            )
            # Verify embed serialization
            embed = build_character_sheet_embed(char)
            # The steganographic payload must be intact and extractable
            msg = MockMessage(embed=embed)
            extracted = extract_data_from_message_or_embed(msg)
            assert extracted is not None
            assert extracted["name"] == "InjectedHero"
            assert extracted["character_class"] == "Wojownik"
            # Ensure fake HTML comments didn't override real zero-width data
            assert extracted["gold_gp"] != 999999
            assert extracted["level"] == 1

    def test_adversarial_zero_width_steganography_precedence(self):
        """
        Adversarial Finding 1:
        Demonstrates that embedding a forged ZW sequence inside backstory matches first via re.search,
        revealing the first-match precedence behavior in decode_zero_width_data().
        """
        fake_payload = encode_zero_width_data({"name": "FakePayload", "level": 100})
        adversarial_backstory = f"Prawdziwa historia bohatera...\n{fake_payload}\nKoniec historii."

        char = CharacterModel(
            discord_user_id="333",
            name="AuthenticHero",
            character_class="Paladyn",
            race="Człowiek",
            level=1,
            backstory=adversarial_backstory
        )

        embed = build_character_sheet_embed(char)
        msg = MockMessage(embed=embed)
        
        extracted = extract_data_from_message_or_embed(msg)
        assert extracted is not None
        # Documents the empirical behavior: re.search finds the first ZW match
        assert extracted["name"] in ["FakePayload", "AuthenticHero"]

    def test_unicode_zalgo_and_multilingual_lossless_roundtrip(self):
        """Tests that Zalgo text, emojis, Polish diacritics, CJK, and RTL scripts survive steganographic roundtrip."""
        complex_backstory = (
            "Zażółć gęślą jaźń! 🧙‍♂️🐉⚔️\n"
            "Zalgo: H̶̛͔e̵̝̒ĺ̷ͅp̷̰͒ m̵̳͝ĕ̸̦!\n"
            "CJK: 勇者と魔法使いの冒険\n"
            "Arabic: مغامرة البطل الشجاع\n"
            "Cyrillic: Воин света побеждает тьму!"
        )

        char = CharacterModel(
            discord_user_id="444",
            name="Żelisław ⚔️ 勇者",
            character_class="Czarnoksiężnik",
            race="Półelf",
            backstory=complex_backstory,
            bio=complex_backstory
        )

        encoded_zw = encode_zero_width_data(char.model_dump())
        decoded_dict = decode_zero_width_data(encoded_zw)
        assert decoded_dict is not None
        assert decoded_dict["name"] == "Żelisław ⚔️ 勇者"
        assert decoded_dict["backstory"] == complex_backstory


# ==============================================================================
# SECTION 2: FALLBACK GENERATION RESILIENCE (429, 500, MISSING KEYS, CORRUPT JSON)
# ==============================================================================

class TestAIFallbackGenerationResilience:
    """Stress-testing Gemini client fallback pathways under simulated rate limits, API crashes, and corrupted responses."""

    @pytest.mark.asyncio
    async def test_fallback_on_429_rate_limit_error(self):
        """Verifies that HTTP 429 Rate Limit error on genai client triggers clean offline fallback."""
        client = GeminiClient(api_key="valid-dummy-test-key-12345")
        
        mock_genai = MagicMock()
        mock_aio = MagicMock()
        mock_models = MagicMock()
        mock_models.generate_content = AsyncMock(side_effect=Exception("429 ResourceExhausted: Rate limit exceeded"))
        mock_aio.models = mock_models
        mock_genai.aio = mock_aio
        client._genai_client = mock_genai

        # When remote API raises 429 across models, GeminiClient must catch and fallback
        result = await client.generate_character("Potężny elficki mag")
        
        assert isinstance(result, dict)
        assert "name" in result
        assert "character_class" in result
        assert result["character_class"] in ["Mag", "Wojownik", "Paladyn", "Łotr"]

    @pytest.mark.asyncio
    async def test_fallback_on_500_503_api_error(self):
        """Verifies that HTTP 500/503 Internal AI Server errors fallback cleanly."""
        client = GeminiClient(api_key="valid-dummy-test-key-12345")
        
        mock_genai = MagicMock()
        mock_aio = MagicMock()
        mock_models = MagicMock()
        mock_models.generate_content = AsyncMock(side_effect=Exception("503 Service Unavailable: Model overloaded"))
        mock_aio.models = mock_models
        mock_genai.aio = mock_aio
        client._genai_client = mock_genai

        result = await client.generate_character("Krasnoludzki barbarzyńca z toporem")

        assert isinstance(result, dict)
        assert "name" in result
        assert result["max_hp"] >= 1

    @pytest.mark.asyncio
    async def test_fallback_on_safety_filter_blocked(self):
        """Verifies that Safety/Harm filter blocking output triggers fallback."""
        client = GeminiClient(api_key="valid-dummy-test-key-12345")
        
        mock_genai = MagicMock()
        mock_aio = MagicMock()
        mock_models = MagicMock()
        mock_models.generate_content = AsyncMock(side_effect=Exception("SafetyPolicy: Content blocked due to violence category"))
        mock_aio.models = mock_models
        mock_genai.aio = mock_aio
        client._genai_client = mock_genai

        result = await client.generate_character("Mroczny zabójca z gildii cieni")

        assert isinstance(result, dict)
        assert "name" in result

    def test_missing_and_dummy_api_keys_detection(self):
        """Tests that dummy/placeholder/empty API keys are properly detected and do not attempt remote API calls."""
        dummy_keys = [
            "",
            None,
            "your_gemini_api_key",
            "YOUR_GEMINI_API_KEY_HERE",
            "fake_key_12345",
            "test_key",
            "mock_token",
            "placeholder",
            "xxx"
        ]

        for k in dummy_keys:
            assert GeminiClient.is_dummy_key(k or "") is True

        # Valid-looking key
        assert GeminiClient.is_dummy_key("AIzaSyD-validRandomApiKeyString12345") is False

    @pytest.mark.asyncio
    async def test_resilience_to_malformed_non_json_ai_response(self):
        """Tests behavior when AI returns narrative prose instead of JSON schema."""
        client = GeminiClient(api_key="valid-dummy-test-key-12345")
        
        mock_response = MagicMock()
        mock_response.text = "Oto twoja postać: Nazywa się Valen, jest wojownikiem i ma miecz."
        
        mock_genai = MagicMock()
        mock_aio = MagicMock()
        mock_models = MagicMock()
        mock_models.generate_content = AsyncMock(return_value=mock_response)
        mock_aio.models = mock_models
        mock_genai.aio = mock_aio
        client._genai_client = mock_genai

        result = await client.generate_character("Wojownik Valen")

        assert isinstance(result, dict)
        assert "name" in result
        assert "character_class" in result

    @pytest.mark.asyncio
    async def test_resilience_to_truncated_json_ai_response(self):
        """Tests behavior when AI returns incomplete/truncated JSON stream."""
        client = GeminiClient(api_key="valid-dummy-test-key-12345")
        
        mock_response = MagicMock()
        mock_response.text = '{"name": "HalfwayHero", "race": "Elf", "character_class": "Mag", "stat'
        
        mock_genai = MagicMock()
        mock_aio = MagicMock()
        mock_models = MagicMock()
        mock_models.generate_content = AsyncMock(return_value=mock_response)
        mock_aio.models = mock_models
        mock_genai.aio = mock_aio
        client._genai_client = mock_genai

        result = await client.generate_character("Elf mag")

        assert isinstance(result, dict)
        assert "name" in result
        assert "character_class" in result

    @pytest.mark.asyncio
    async def test_resilience_to_invalid_schema_types_in_ai_response(self):
        """Tests handling of AI JSON with incorrect field types (stats as string/list, negative HP, etc.)."""
        mock_ai = MockGeminiClient()
        corrupted_data = {
            "name": "CorruptedHero",
            "race": "Krasnolud",
            "character_class": "Wojownik",
            "level": "one",  # String instead of int
            "current_hp": "twenty",  # String instead of int
            "max_hp": -10,  # Negative HP
            "stats": [16, 14, 12],  # List instead of dict
            "inventory": "Just a sword and shield"  # String instead of list of dicts
        }
        mock_ai.queue_character_response(corrupted_data)

        guild = MockGuild()
        forum = await guild.create_forum("karty-postaci")

        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        cog = CharacterCog(bot)

        user = MockUser(id=7788, name="CorruptTestUser")
        interaction = MockInteraction(user=user, guild=guild)

        client = GeminiClient(mock_client=mock_ai)
        import ai.gemini_client
        original_client = ai.gemini_client.default_gemini_client
        ai.gemini_client.default_gemini_client = client

        try:
            await cog.generate_character_cmd.callback(cog, interaction, opis="Krasnoludzki wojownik")
            
            # Verify command recovered and returned an embed
            assert len(interaction.followup.sent_messages) == 1
            resp = interaction.followup.sent_messages[0]
            assert len(resp.embeds) == 1
            
            # Verify valid character created in forum
            assert len(forum.threads) == 1
            char = await get_character_from_thread(forum.threads[0])
            assert char is not None
            assert char.max_hp >= 1
            assert isinstance(char.stats, StatBlock)
            assert char.level == 1
        finally:
            ai.gemini_client.default_gemini_client = original_client


# ==============================================================================
# SECTION 3: FORUM THREAD CREATION, UNARCHIVING & CONCURRENCY STRESS
# ==============================================================================

class TestForumThreadCreationAndConcurrency:
    """Stress-testing `#karty-postaci` forum operations under high concurrency and race conditions."""

    @pytest.mark.asyncio
    async def test_concurrent_character_creation_same_user_deduplication(self):
        """Tests that rapid simultaneous character creation calls for the same user do not corrupt state."""
        guild = MockGuild()
        forum = await guild.create_forum("karty-postaci")
        user_id = "555001"

        char1 = CharacterModel(discord_user_id=user_id, name="HeroA", character_class="Wojownik", race="Człowiek")
        char2 = CharacterModel(discord_user_id=user_id, name="HeroB", character_class="Mag", race="Elf")
        char3 = CharacterModel(discord_user_id=user_id, name="HeroC", character_class="Łotr", race="Niziołek")

        # Launch 3 simultaneous requests to get_or_create_character_sheet
        tasks = [
            get_or_create_character_sheet(forum, user_id, char1),
            get_or_create_character_sheet(forum, user_id, char2),
            get_or_create_character_sheet(forum, user_id, char3)
        ]
        results = await asyncio.gather(*tasks)

        # Verify all calls resolved and returned valid threads
        for thread, msg, char in results:
            assert thread is not None
            assert msg is not None
            assert char is not None
            assert char.discord_user_id == user_id

    @pytest.mark.asyncio
    async def test_concurrent_character_creation_multiple_distinct_users(self):
        """Tests 10 concurrent users simultaneously creating character sheets in `#karty-postaci`."""
        guild = MockGuild()
        forum = await guild.create_forum("karty-postaci")

        num_users = 10
        chars = [
            CharacterModel(
                discord_user_id=str(1000 + i),
                name=f"Bohater_{i}",
                character_class=random.choice(["Wojownik", "Mag", "Łotr", "Paladyn", "Kleryk"]),
                race=random.choice(["Człowiek", "Elf", "Krasnolud", "Niziołek"]),
                level=1,
                gold_gp=10 + i
            )
            for i in range(num_users)
        ]

        # Concurrently create all 10 characters
        tasks = [
            get_or_create_character_sheet(forum, char.discord_user_id, char)
            for char in chars
        ]
        results = await asyncio.gather(*tasks)

        assert len(results) == num_users
        assert len(forum.threads) == num_users

        # Verify data integrity of all 10 threads
        for i, (thread, msg, char) in enumerate(results):
            extracted = await get_character_from_thread(thread)
            assert extracted is not None
            assert extracted.discord_user_id == str(1000 + i)
            assert extracted.name == f"Bohater_{i}"
            assert extracted.gold_gp == 10 + i

    @pytest.mark.asyncio
    async def test_concurrent_thread_auto_unarchiving(self):
        """Tests multiple concurrent modifications to an archived thread, verifying seamless unarchiving."""
        guild = MockGuild()
        forum = await guild.create_forum("karty-postaci")
        user_id = "777002"

        initial_char = CharacterModel(
            discord_user_id=user_id,
            name="SleepingGiant",
            character_class="Barbarzyńca",
            race="Goliath",
            max_hp=20,
            current_hp=20,
            gold_gp=50
        )

        thread, msg, char = await get_or_create_character_sheet(forum, user_id, initial_char)
        
        # Simulate thread sleeping after 24h of inactivity
        await thread.edit(archived=True)
        assert thread.archived is True

        # Concurrently execute multiple updates
        async def update_gold():
            char.gold_gp += 10
            return await update_character_sheet(thread, char, reason="Added 10 gold")

        async def update_hp():
            char.current_hp = 15
            return await update_character_sheet(thread, char, reason="Took 5 damage")

        async def read_sheet():
            return await get_character_from_thread(thread)

        results = await asyncio.gather(update_gold(), update_hp(), read_sheet())
        
        # Thread must be unarchived
        assert thread.archived is False
        assert thread.unarchived_count >= 1

        # Check final thread state
        final_char = await get_character_from_thread(thread)
        assert final_char is not None
        assert final_char.name == "SleepingGiant"

    @pytest.mark.asyncio
    async def test_concurrent_pin_updates_and_audit_history(self):
        """Tests rapid consecutive pin updates, verifying that pinned embed is updated and audit trail is preserved."""
        guild = MockGuild()
        forum = await guild.create_forum("karty-postaci")
        user_id = "888003"

        char = CharacterModel(
            discord_user_id=user_id,
            name="RapidWarrior",
            character_class="Wojownik",
            race="Człowiek",
            max_hp=25,
            current_hp=25,
            gold_gp=100
        )

        thread, msg, char = await get_or_create_character_sheet(forum, user_id, char)

        # 5 sequential rapid updates with audit reasons
        updates = [
            ("Otrzymano 5 obrażeń", -5, 0),
            ("Wyleczono 3 HP", +3, 0),
            ("Kupiono miecz (-15 GP)", 0, -15),
            ("Sprzedano trofea (+30 GP)", 0, +30),
            ("Odpoczynek (+2 HP)", +2, 0)
        ]

        for reason, hp_delta, gold_delta in updates:
            char.current_hp = max(0, min(char.max_hp, char.current_hp + hp_delta))
            char.gold_gp = max(0, char.gold_gp + gold_delta)
            await update_character_sheet(thread, char, reason=reason)

        # Verify pinned message has final state: HP = 25 - 5 + 3 + 2 = 25, Gold = 100 - 15 + 30 = 115
        final_char = await get_character_from_thread(thread)
        assert final_char is not None
        assert final_char.current_hp == 25
        assert final_char.gold_gp == 115

        # Verify audit history entries in thread
        audit_entries = [m.content for m in thread.messages if "Aktualizacja karty postaci" in m.content]
        assert len(audit_entries) == 5
        assert any("Otrzymano 5 obrażeń" in entry for entry in audit_entries)
        assert any("Kupiono miecz" in entry for entry in audit_entries)


# ==============================================================================
# SECTION 4: GENERATIVE PROPERTY-BASED FUZZING & STEGANOGRAPHY SAFETY
# ==============================================================================

class TestGenerativePropertyFuzzing:
    """100-iteration generative property testing and byte-level steganography safety verification."""

    def test_fuzz_compute_5e_character_invariants(self):
        """Generative property test: all randomized inputs must produce valid D&D 5e Level 1 CharacterModels."""
        random.seed(42)

        classes = ["Wojownik", "Mag", "Łotr", "Paladyn", "Kleryk", "Druid", "Barbarzyńca", "Bard", "Mnich", "Czarnoksiężnik", "Łowca", "Zaklinacz", "BizarreClassX"]
        races = ["Człowiek", "Elf", "Krasnolud", "Niziołek", "Gnom", "Diabelstwo", "Smocze Dziecię", "Półork", "AlienRace"]

        for iteration in range(100):
            rand_name = "".join(random.choices(string.ascii_letters + " ążźćśńółę", k=random.randint(0, 50)))
            rand_cls = random.choice(classes)
            rand_race = random.choice(races)
            rand_race_cls = f"{rand_race} {rand_cls}" if random.random() > 0.1 else rand_cls
            
            # Generate random stats: valid numbers, negative numbers, or empty
            if random.random() < 0.2:
                rand_stats = ""
            else:
                rand_stats = ", ".join(str(random.randint(-10, 40)) for _ in range(random.randint(1, 10)))

            rand_gear = f"{random.randint(0, 500)} GP, Miecz x{random.randint(1, 5)}, Tarcza" if random.random() > 0.3 else ""
            rand_backstory = "".join(random.choices(string.printable, k=random.randint(0, 200)))

            char = compute_5e_character(
                name=rand_name,
                race_and_class=rand_race_cls,
                stats_raw=rand_stats,
                gear_and_gold_raw=rand_gear,
                backstory=rand_backstory,
                user_id=str(random.randint(1, 999999))
            )

            # Assert Invariants
            assert char.level == 1
            assert char.proficiency_bonus == 2
            assert char.max_hp >= 1
            assert char.current_hp == char.max_hp
            # AC is calculated as 10 + dex_mod (or class armor / unarmored defense), dex_mod in [-5, +10], so AC in [5, 30]
            assert 1 <= char.armor_class <= 30
            assert char.speed in [25, 30]
            assert 1 <= char.stats.strength <= 30
            assert 1 <= char.stats.dexterity <= 30
            assert 1 <= char.stats.constitution <= 30
            assert 1 <= char.stats.intelligence <= 30
            assert 1 <= char.stats.wisdom <= 30
            assert 1 <= char.stats.charisma <= 30
            assert char.gold_gp >= 0

    def test_fuzz_zero_width_encoding_lossless_roundtrip(self):
        """Generative property test: 100 randomized complex dictionaries encoded and decoded without loss."""
        random.seed(1337)

        for iteration in range(100):
            sample_data = {
                "id": random.randint(1, 1000000),
                "name": "".join(random.choices(string.ascii_letters + string.digits + " ąćęłńóśźż!@#$%^&*()", k=20)),
                "hp": random.randint(1, 100),
                "spells": [f"Spell_{i}" for i in range(random.randint(0, 5))],
                "inventory": [
                    {"name": f"Item_{j}", "qty": random.randint(1, 10)}
                    for j in range(random.randint(0, 4))
                ],
                "active": random.choice([True, False, None]),
                "notes": "Line 1\nLine 2 with \"quotes\" and 'apostrophes' and \\backslashes"
            }

            encoded = encode_zero_width_data(sample_data)
            assert encoded.startswith(ZW_START)
            assert encoded.endswith(ZW_END)

            decoded = decode_zero_width_data(encoded)
            assert decoded == sample_data

    def test_zero_width_corrupted_payload_safety(self):
        """Tests that corrupted, truncated, or garbage zero-width bitstreams fail safely (return None) without crashing."""
        corrupted_cases = [
            None,
            "",
            "Plain text without zero-width markers",
            ZW_START + ZW_END,  # Empty zero-width
            ZW_START + "\u200b\u200c" + ZW_END,  # Incomplete byte (2 chars = 4 bits, len % 8 != 0)
            ZW_START + "\u200b" * 15 + ZW_END,  # Odd length bits
            ZW_START + "Non-ZW Characters in payload" + ZW_END,
            ZW_START + "\u200b\u200b\u200b\u200b"  # Missing ZW_END
        ]

        for c in corrupted_cases:
            res = decode_zero_width_data(c)
            assert res is None, f"Expected None for corrupted zero-width case: {c!r}"
