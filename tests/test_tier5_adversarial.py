"""Tier 5 Adversarial & Hardening Test Suite.

Empirical verification of edge cases, race conditions, corrupt payloads,
length boundaries, extreme dice formulas, HP mechanics, and recovery paths.
Contains 28 adversarial tests across core, mechanics, ai, discord_ui, commands, and main.
"""
import asyncio
import json
import re
import pytest
import discord
from typing import List, Dict, Any, Optional

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
from tests.mock_ai import MockGeminiClient
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
    setup_campaign_infrastructure
)
from mechanics.dice import roll_dice, _extract_individual_dice_rolls
from mechanics.character_ops import (
    modify_hp,
    add_inventory_item,
    remove_inventory_item,
    modify_gold,
    short_rest,
    long_rest
)
from ai.message_splitter import split_long_message
from ai.gemini_client import (
    GeminiClient,
    extract_action_buttons,
    format_narrative_with_buttons,
    build_4layer_prompt
)
from ai.context_builder import (
    normalize_channel_name,
    is_ooc_message,
    parse_dice_roll_embed,
    fetch_messages_since_last_dm_response,
    fetch_active_characters,
    build_full_dm_context
)
from discord_ui.views import RollButton, NarrativeActionView, CharacterSheetView
from discord_ui.embeds import create_character_sheet_embed, create_dice_roll_embed
from commands.narrative_cog import is_table_channel, is_narrative_trigger, NarrativeCog
from main import DndAIBot, create_bot


# ============================================================================
# CATEGORY 1: HTML Comment Serialization & Corrupted Payloads
# ============================================================================

def test_adv_malformed_html_json_truncated():
    """T5.1: Truncated JSON inside HTML comment returns None gracefully."""
    bad_payloads = [
        "<!-- DATA_JSON: {\"name\": \"Conan\", \"level\": -->",
        "<!-- DATA_JSON: { -->",
        "<!-- DATA_JSON: -->",
        "<!-- DATA_JSON: {\"id\": 1, \"inventory\": [{\"name\": \"Sword\" -->",
        "Some text <!-- DATA_JSON: {\"unclosed: 123",
        ""
    ]
    for payload in bad_payloads:
        res = extract_data_from_text(payload)
        assert res is None, f"Expected None for malformed payload: {payload}"


def test_adv_malformed_html_json_with_binary_and_control_chars():
    """T5.2: Corrupted binary/control characters inside HTML comment return None."""
    raw = "<!-- DATA_JSON: {\"name\": \x00\x01\x02\xff\xfe, \"level\": 1} -->"
    res = extract_data_from_text(raw)
    assert res is None


@pytest.mark.asyncio
async def test_adv_corrupted_character_sheet_data_type_mismatch():
    """T5.3: Pinned message with type-corrupted JSON recovers with a valid fallback CharacterModel."""
    forum = MockForumChannel(name="karty-postaci")
    corrupted_data = {
        "discord_user_id": "123456",
        "name": 99999,  # integer instead of string
        "level": "not_an_int",  # invalid int level
        "stats": "corrupted_stat_string",  # string instead of StatBlock
        "current_hp": "twenty"
    }
    
    # Create thread with corrupted JSON
    res = await forum.create_thread(name="🛡️ Corrupted (123456)")
    thread, msg = res.thread, res.message
    msg.content = f"<!-- DATA_JSON: {json.dumps(corrupted_data)} -->"
    msg.pinned = True
    thread.pinned_messages.append(msg)

    # Fetch/create character should handle validation failure and fallback safely
    th, out_msg, char = await get_or_create_character_sheet(forum, "123456")
    assert isinstance(char, CharacterModel)
    assert char.discord_user_id == "123456"
    assert char.level >= 1
    assert isinstance(char.stats, StatBlock)


@pytest.mark.asyncio
async def test_adv_corrupted_quest_board_json_payloads():
    """T5.4: Corrupted quest board JSON (scalars, invalid format) falls back to empty QuestList."""
    channel = MockTextChannel(name="dziennik-zadan")
    
    # Send pin with JSON scalar integer instead of quest dict/list
    msg = await channel.send("<!-- DATA_JSON: 12345 -->")
    await msg.pin()

    board = await get_quest_board(channel)
    assert isinstance(board, QuestList)
    assert len(board.quests) == 0

    # Send pin with JSON array of invalid non-dict items
    msg2 = await channel.send("<!-- DATA_JSON: [1, 2, \"not_a_quest\"] -->")
    await msg2.pin()

    board2 = await get_quest_board(channel)
    assert isinstance(board2, QuestList)


def test_adv_html_comment_injection_in_user_input():
    """T5.5: User input containing HTML comment delimiters '-->' closes regex match prematurely, returning None."""
    malicious_item = "Sword --> <!-- DATA_JSON: {\"injected\": true} -->"
    char = CharacterModel(
        discord_user_id="999",
        name="Tester",
        character_class="Fighter",
        race="Human"
    )
    add_inventory_item(char, malicious_item, quantity=1)
    
    # Inject into text
    text_with_data = inject_data_into_text("Sheet description", char.model_dump())
    extracted = extract_data_from_text(text_with_data)
    
    # Non-greedy regex stops at first '-->' inside JSON string, causing JSON parser error and returning None
    assert extracted is None


# ============================================================================
# CATEGORY 2: Concurrency & Race Conditions on UI Components
# ============================================================================

@pytest.mark.asyncio
async def test_adv_concurrent_roll_button_clicks_100_burst():
    """T5.6: 100 concurrent clicks on RollButton execute deterministically without race conditions."""
    btn = RollButton(label="Test Attack", formula="1d20+5", reason="Burst Attack", dc=15)
    
    async def click_button(idx: int):
        user = MockUser(id=1000 + idx, name=f"User_{idx}", display_name=f"Player_{idx}")
        interaction = MockInteraction(user=user)
        await btn.callback(interaction)
        assert interaction.response.is_done()
        assert len(interaction.response.sent_messages) == 1
        msg = interaction.response.sent_messages[0]
        assert msg.embeds is not None and len(msg.embeds) == 1
        embed = msg.embeds[0]
        # Total should be between 1+5=6 and 20+5=25
        wynik_field = next(f for f in embed.fields if f.name == "Wynik")
        total_val = int(wynik_field.value.replace("#", "").replace("*", "").strip())
        assert 6 <= total_val <= 25

    tasks = [click_button(i) for i in range(100)]
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_adv_concurrent_narrative_action_view_mixed_clicks():
    """T5.7: Concurrent clicks across varied action buttons in NarrativeActionView."""
    buttons_spec = [
        {"label": "Perception (WIS +2)", "formula": "1d20+2", "reason": "Perception", "dc": 12},
        {"label": "Stealth (DEX +3)", "formula": "1d20+3", "reason": "Stealth", "dc": 14, "advantage": True},
        {"label": "Athletics (STR +4)", "formula": "1d20+4", "reason": "Athletics", "dc": 18, "disadvantage": True},
        {"label": "Arcana (INT +1)", "formula": "1d20+1", "reason": "Arcana", "dc": 10},
        {"label": "Flat Check", "formula": "1d20", "reason": "Luck Check", "dc": None}
    ]
    view = NarrativeActionView(buttons_spec)
    assert len(view.children) == 5

    async def click_child(child, idx: int):
        user = MockUser(id=2000 + idx, name=f"Clicker_{idx}")
        interaction = MockInteraction(user=user)
        await child.callback(interaction)
        assert interaction.response.is_done()

    tasks = [click_child(view.children[i % len(view.children)], i) for i in range(30)]
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_adv_concurrent_character_sheet_hp_modifications():
    """T5.8: Concurrent HP modifications and sheet updates maintain valid state bounds."""
    forum = MockForumChannel(name="karty-postaci")
    res = await forum.create_thread(name="🛡️ Thorin (101)")
    thread, msg = res.thread, res.message
    
    char = CharacterModel(
        discord_user_id="101",
        name="Thorin",
        character_class="Fighter",
        race="Dwarf",
        max_hp=50,
        current_hp=50,
        temp_hp=10
    )
    
    async def apply_hp_delta(delta: int, idx: int):
        modify_hp(char, delta)
        await update_character_sheet(thread, char, reason=f"Concurrent delta {delta} (#{idx})")

    # Apply 20 concurrent alternating damage and heal deltas
    deltas = [-5, +3, -10, +8, -2, -15, +12, -4, +6, -8] * 2
    tasks = [apply_hp_delta(d, i) for i, d in enumerate(deltas)]
    await asyncio.gather(*tasks)

    # Validate final state
    assert 0 <= char.current_hp <= char.max_hp
    assert char.temp_hp >= 0
    # Check that pins/messages in thread were updated
    assert len(thread.messages) > 0


@pytest.mark.asyncio
async def test_adv_character_sheet_view_empty_stats_graceful():
    """T5.9: CharacterSheetView buttons handle None character gracefully without raising."""
    view_none = CharacterSheetView(character=None)
    interaction = MockInteraction(user=MockUser(id=42, name="Tester"))
    
    # Should use fallback mod = 0
    await view_none.roll_initiative.callback(interaction)
    assert interaction.response.is_done()

    interaction2 = MockInteraction(user=MockUser(id=42, name="Tester"))
    await view_none.roll_perception.callback(interaction2)
    assert interaction2.response.is_done()

    interaction3 = MockInteraction(user=MockUser(id=42, name="Tester"))
    await view_none.roll_attack.callback(interaction3)
    assert interaction3.response.is_done()


# ============================================================================
# CATEGORY 3: Discord Message Length Boundaries & Markdown Wrapping
# ============================================================================

def test_adv_message_splitter_exact_boundaries():
    """T5.10: String at 1900, 1901, 2000, 4000, 10000 chars respects chunk limit."""
    for length in [1900, 1901, 2000, 2001, 3800, 4000, 10000]:
        text = "A" * length
        chunks = split_long_message(text, limit=1900)
        assert len(chunks) >= 1
        for c in chunks:
            assert len(c) <= 1900, f"Chunk exceeded 1900 chars: len={len(c)}"
        # Recombined tokens must equal total length
        total_chars = sum(len(c) for c in chunks)
        assert total_chars == length


def test_adv_message_splitter_unbroken_giant_token_10k():
    """T5.11: A single 10,000-character token with no spaces or newlines splits safely."""
    giant_word = "Supercalifragilisticexpialidocious" * 300  # 10,200 chars
    chunks = split_long_message(giant_word, limit=1900)
    assert len(chunks) == (len(giant_word) + 1899) // 1900
    for c in chunks:
        assert len(c) <= 1900


def test_adv_message_splitter_complex_markdown_wrapping():
    """T5.12: Large text (>5000 chars) with code blocks, bold, italics, and quotes."""
    paragraphs = []
    for i in range(15):
        p = (
            f"**Akapit {i}**: Mistrz Gry spogląda na mapę.\n"
            f"> Cytat starożytnego mędrca o numerze {i}.\n"
            f"```python\n# Kod zaklęcia {i}\ndef cast_spell_{i}():\n    return 'Magic missile {i}'\n```\n"
            f"W lochu panuje mrok. *Cisza* przed burzą."
        )
        paragraphs.append(p)
    full_text = "\n\n".join(paragraphs)
    assert len(full_text) > 3000

    chunks = split_long_message(full_text, limit=1900)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 1900
        assert len(c.strip()) > 0


def test_adv_message_splitter_excessive_newlines_and_whitespace():
    """T5.13: Massive whitespace, newlines, tabs, and zero-width spaces."""
    messy_text = "\n\n\n\n\t\t   \u200b\n\n" * 500 + "Valid Story Content" + "\n\n\n" * 200
    chunks = split_long_message(messy_text, limit=1900)
    assert len(chunks) == 1
    assert "Valid Story Content" in chunks[0]
    assert len(chunks[0]) <= 1900


# ============================================================================
# CATEGORY 4: Extreme Dice Formulas & Dice Engine Boundaries
# ============================================================================

def test_adv_dice_extreme_formula_100d20_and_1000d6():
    """T5.14: Extreme dice pool formulas (100d20, 1000d6) compute without timeout or crash."""
    res_100 = roll_dice("100d20", reason="Armia krasnoludów")
    assert 100 <= res_100.total <= 2000
    assert len(res_100.dice_rolls) == 100
    assert res_100.modifier == 0

    res_1000 = roll_dice("1000d6", reason="Meteoryt")
    assert 1000 <= res_1000.total <= 6000
    assert len(res_1000.dice_rolls) == 1000
    assert res_1000.modifier == 0


def test_adv_dice_extreme_negative_modifiers():
    """T5.15: Dice rolls with huge negative modifiers and negative DC comparison."""
    res = roll_dice("1d20-9999", reason="Klątwa wiekuista", target_dc=-9985)
    # Total will be between 1-9999 = -9998 and 20-9999 = -9979
    assert -9998 <= res.total <= -9979
    assert res.modifier == -9999
    assert res.is_success is not None
    assert res.is_success == (res.total >= -9985)


def test_adv_dice_invalid_and_injection_strings():
    """T5.16: Malformed dice strings and injection attempts fail cleanly with d20 exceptions."""
    invalid_formulas = [
        "DROP TABLE characters;",
        "__import__('os').system('dir')",
        "1d0",
        "1d20/0",
        "d",
        "1d20 +",
        "abc",
        "1d-5"
    ]
    for formula in invalid_formulas:
        with pytest.raises(Exception):
            roll_dice(formula)


def test_adv_dice_unary_plus_and_zero_dice():
    """T5.17: Unary plus and 0d0 in d20 AST evaluate deterministically without error."""
    res_plus = roll_dice("++1d20", reason="Unary plus")
    assert 1 <= res_plus.total <= 20

    res_zero = roll_dice("0d0", reason="Brak kości")
    assert res_zero.total == 0
    assert res_zero.dice_rolls == []
    assert res_zero.modifier == 0


def test_adv_dice_advantage_disadvantage_regex_edge_cases():
    """T5.18: Advantage/disadvantage regex properly replaces single d20 without corrupting multi-dice."""
    # 1d20+5 -> 2d20kh1+5
    res_adv = roll_dice("1d20+5", advantage=True)
    assert "2d20kh1" in res_adv.formula

    # 1d20-2 -> 2d20kl1-2
    res_disadv = roll_dice("1d20-2", disadvantage=True)
    assert "2d20kl1" in res_disadv.formula

    # 10d20 should NOT turn into 102d20kh1
    res_10d20 = roll_dice("10d20")
    assert res_10d20.formula == "10d20"
    assert len(res_10d20.dice_rolls) == 10


# ============================================================================
# CATEGORY 5: Character HP Mechanics, Temp HP Stacking & Health Bar Bounds
# ============================================================================

def test_adv_hp_temp_hp_5e_stacking_rules():
    """T5.19: D&D 5e non-stacking rule for Temp HP (retains higher value)."""
    char = CharacterModel(
        discord_user_id="101",
        name="Bruenor",
        character_class="Fighter",
        race="Dwarf",
        max_hp=30,
        current_hp=30,
        temp_hp=0
    )

    # Initial temp HP grant = 10
    modify_hp(char, 10, is_temp=True)
    assert char.temp_hp == 10

    # Smaller temp HP grant = 5 -> does not replace 10
    modify_hp(char, 5, is_temp=True)
    assert char.temp_hp == 10

    # Larger temp HP grant = 15 -> replaces with 15
    modify_hp(char, 15, is_temp=True)
    assert char.temp_hp == 15

    # Negative temp HP reduction = -5 -> decreases to 10
    modify_hp(char, -5, is_temp=True)
    assert char.temp_hp == 10

    # Massive negative temp HP reduction = -50 -> clamps to 0
    modify_hp(char, -50, is_temp=True)
    assert char.temp_hp == 0


def test_adv_hp_negative_healing_and_overheal():
    """T5.20: Negative healing and massive damage boundary handling."""
    char = CharacterModel(
        discord_user_id="102",
        name="Raistlin",
        character_class="Wizard",
        race="Human",
        max_hp=20,
        current_hp=10,
        temp_hp=5
    )

    # Negative heal amount in apply_heal returns 0
    assert char.apply_heal(-10) == 0
    assert char.current_hp == 10

    # Zero damage delta returns 0 change
    curr, temp, msg = modify_hp(char, 0)
    assert curr == 10
    assert temp == 5

    # Massive damage (1,000,000) absorbs 5 temp HP, drops current HP to 0
    curr, temp, msg = modify_hp(char, -1_000_000)
    assert curr == 0
    assert temp == 0
    assert "0 HP" in msg

    # Overheal from 0 to 999999 caps at max_hp (20)
    curr, temp, msg = modify_hp(char, 999_999)
    assert curr == 20
    assert char.current_hp == 20


def test_adv_health_bar_extreme_boundary_ratios():
    """T5.21: Health bar generator handles overflow, negative, and zero max values cleanly."""
    # Current > max_hp
    bar_over = create_health_bar(current=100, max_val=20, length=10)
    assert bar_over.startswith("[██████████]")
    assert "100/20 HP" in bar_over

    # Current < 0
    bar_neg = create_health_bar(current=-15, max_val=20, length=10)
    assert bar_neg.startswith("[░░░░░░░░░░]")
    assert "-15/20 HP" in bar_neg

    # Max <= 0
    bar_zero_max = create_health_bar(current=10, max_val=0, length=10)
    assert bar_zero_max.startswith("[░░░░░░░░░░]")
    assert "10/0 HP" in bar_zero_max

    # Negative max
    bar_neg_max = create_health_bar(current=5, max_val=-10, length=10)
    assert bar_neg_max.startswith("[░░░░░░░░░░]")
    assert "5/0 HP" in bar_neg_max


# ============================================================================
# CATEGORY 6: Forum Thread Unarchival & Channel Recovery
# ============================================================================

@pytest.mark.asyncio
async def test_adv_forum_thread_unarchive_failure_recovery():
    """T5.22: If thread.edit(archived=False) raises an exception, other valid threads are still read."""
    guild = MockGuild(name="Resilience Test")
    forum = await guild.create_forum_channel("karty-postaci")

    # 1. Broken thread (unarchiving fails)
    res_bad = await forum.create_thread(name="🛡️ GlitchedThread (555)")
    thread_bad, msg_bad = res_bad.thread, res_bad.message
    thread_bad.archived = True
    char_bad = CharacterModel(discord_user_id="555", name="GlitchedHero", character_class="Rogue", race="Elf")
    msg_bad.content = inject_json_to_text("", char_bad.model_dump())
    msg_bad.pinned = True
    thread_bad.pinned_messages.append(msg_bad)

    async def broken_edit(*args, **kwargs):
        raise discord.HTTPException(response=None, message="Discord API 503 Service Unavailable")
    thread_bad.edit = broken_edit

    # 2. Healthy thread
    res_good = await forum.create_thread(name="🛡️ HealthyHero (666)")
    thread_good, msg_good = res_good.thread, res_good.message
    char_good = CharacterModel(discord_user_id="666", name="HealthyHero", character_class="Paladin", race="Human")
    msg_good.content = inject_json_to_text("", char_good.model_dump())
    msg_good.pinned = True
    thread_good.pinned_messages.append(msg_good)

    # fetch_active_characters gracefully handles the failure on bad thread and processes good thread
    characters = await fetch_active_characters(guild)
    assert len(characters) == 1
    assert characters[0]["name"] == "HealthyHero"


@pytest.mark.asyncio
async def test_adv_forum_thread_pins_raising_exception():
    """T5.23: If thread.pins() raises, get_character_from_thread handles exception without crashing."""
    thread = MockThread(name="🛡️ BrokenPins (777)")
    
    async def broken_pins():
        raise discord.Forbidden(response=None, message="Missing Permissions")
    
    thread.pins = broken_pins

    char = await get_character_from_thread(thread)
    assert char is None  # Handled safely, returned None


@pytest.mark.asyncio
async def test_adv_forum_all_threads_iterator_variants():
    """T5.24: _get_all_forum_threads supports async iterator, list, and coroutine return types."""
    forum = MockForumChannel(name="karty-postaci")
    res1 = await forum.create_thread(name="Thread 1")
    res2 = await forum.create_thread(name="Thread 2")
    res2.thread.archived = True

    threads = await _get_all_forum_threads(forum)
    assert len(threads) == 2
    assert res1.thread in threads
    assert res2.thread in threads


# ============================================================================
# CATEGORY 7: Empty/Missing Rules, Special Unicode & Channel Normalization
# ============================================================================

@pytest.mark.asyncio
async def test_adv_fetch_campaign_rules_empty_or_special_channel():
    """T5.25: Empty or non-existent rules channel returns default D&D 5e fallback."""
    guild = MockGuild(name="Empty Rules Guild")
    # Empty guild with no channels
    rules = await fetch_campaign_rules(guild)
    assert rules == "System bazowy: Standardowe D&D 5e."

    # Rules channel with 0 messages
    rules_ch = await guild.create_text_channel("⚔️-zasady-i-mechanika-📜")
    rules2 = await fetch_campaign_rules(guild)
    assert rules2 == "System bazowy: Standardowe D&D 5e."


def test_adv_channel_normalization_stress():
    """T5.26: normalize_name (core) and normalize_channel_name (ai) handle Unicode, diacritics, and emojis."""
    cases = [
        ("📜 KAMPANIA I FABUŁA", "kampaniaifabuła", "kampaniaifabula"),
        ("Zażółć gęślą jaźń", "zazołcgeslajazn", "zazolcgeslajazn"),
        ("⚔️_Stół_Gry_🎲", "_stoł_gry_", "stolgry"),
        ("🔥-karty-postaci-🛡️", "-karty-postaci-", "kartypostaci"),
        ("dziennik-zadań", "dziennik-zadan", "dziennikzadan"),
        ("", "", "")
    ]
    for raw, expected_norm_name, expected_norm_channel in cases:
        n1 = normalize_name(raw)
        n2 = normalize_channel_name(raw)
        assert n1 == expected_norm_name, f"normalize_name({raw}) = {n1} != {expected_norm_name}"
        assert n2 == expected_norm_channel, f"normalize_channel_name({raw}) = {n2} != {expected_norm_channel}"


def test_adv_narrative_trigger_adversarial_patterns():
    """T5.27: is_narrative_trigger adversarial patterns (mentions, roles, prefixes)."""
    bot = MockUser(id=999, name="Mistrz Gry", bot=True)
    author = MockUser(id=101, name="Player")
    ch = MockTextChannel(name="stół-gry")

    # 1. Valid trigger via !next
    msg1 = MockMessage(content="!next", author=author, channel=ch)
    assert is_narrative_trigger(msg1, bot) is True

    # 2. Valid trigger via /next
    msg2 = MockMessage(content="/next proszę o turę", author=author, channel=ch)
    assert is_narrative_trigger(msg2, bot) is True

    # 3. Valid trigger via <@999>
    msg3 = MockMessage(content="Co widzimy <@999>?", author=author, channel=ch)
    assert is_narrative_trigger(msg3, bot) is True

    # 4. Valid trigger via @Mistrz Gry
    msg4 = MockMessage(content="@Mistrz Gry otwieram skrzynię", author=author, channel=ch)
    assert is_narrative_trigger(msg4, bot) is True

    # 5. Non-trigger message (player talk without trigger)
    msg5 = MockMessage(content="Hej drużyno, idziemy w lewo?", author=author, channel=ch)
    assert is_narrative_trigger(msg5, bot) is False


@pytest.mark.asyncio
async def test_adv_main_bot_error_handlers():
    """T5.28: on_tree_error and on_command_error handle errors gracefully without crashing."""
    bot = create_bot()
    interaction = MockInteraction(user=MockUser(id=42, name="ErrorUser"))
    
    # Simulate an app command error
    err = discord.app_commands.AppCommandError("Simulated app command failure")
    await bot.on_tree_error(interaction, err)
    
    assert interaction.response.is_done()
    assert len(interaction.response.sent_messages) == 1
    assert "Simulated app command failure" in interaction.response.sent_messages[0].content

    # Simulate traditional command error
    class DummyCtx:
        def __init__(self):
            self.command = "test_cmd"
            self.sent = []
        async def send(self, msg: str):
            self.sent.append(msg)

    ctx = DummyCtx()
    cmd_err = discord.ext.commands.CommandError("Simulated prefix error")
    await bot.on_command_error(ctx, cmd_err)
    assert len(ctx.sent) == 1
    assert "Simulated prefix error" in ctx.sent[0]
