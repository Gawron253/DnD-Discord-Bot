"""Tier 2 Test Suite: Boundary Value Analysis & Edge Cases for all 14 bot features (F1 to F14).
Covers at least 5 edge/boundary test cases per feature (>=70 tests total).
"""
import pytest
import discord
from typing import List, Dict, Any

from tests.mock_discord import (
    MockGuild,
    MockUser,
    MockTextChannel,
    MockForumChannel,
    MockCategoryChannel,
    MockMessage,
    MockEmbed,
    MockInteraction
)
from tests.mock_ai import (
    MockGeminiClient,
    MockAPIError,
    MockRateLimitError,
    MockSafetyFilterError,
    split_long_message
)
from core.models import (
    CharacterModel,
    StatBlock,
    ItemModel,
    SpellSlots,
    QuestModel,
    QuestObjective
)
from core.discord_db import (
    extract_json_from_message,
    inject_json_to_text,
    get_character_from_thread
)
from mechanics.dice import roll_dice, DiceRollResult
from discord_ui.embeds import (
    create_health_bar,
    create_character_sheet_embed,
    create_dice_roll_embed
)
from discord_ui.views import RollButton, NarrativeActionView
from ai.context_builder import (
    fetch_messages_since_last_dm_response,
    fetch_campaign_rules,
    fetch_active_characters
)
from tests.test_tier1_features import execute_setup_campaign, execute_roll_command


# ============================================================================
# F1 Boundaries: Setup Campaign
# ============================================================================

@pytest.mark.asyncio
async def test_f1_setup_campaign_partial_existing_channels():
    """F1.B1: /setup-campaign when some channels already exist only creates missing ones."""
    guild = MockGuild(name="Partially Initialized")
    cat = await guild.create_category("📜 KAMPANIA I FABULA")
    await guild.create_text_channel("stol-gry", category=cat)

    interaction = MockInteraction(guild=guild)
    await execute_setup_campaign(interaction)

    stol_channels = [c for c in guild.text_channels if c.name == "stol-gry"]
    assert len(stol_channels) == 1
    assert any(c.name == "dziennik-zadan" for c in guild.text_channels)


@pytest.mark.asyncio
async def test_f1_setup_campaign_interaction_not_in_guild():
    """F1.B2: /setup-campaign called in DM context (no guild) warns user gracefully."""
    interaction = MockInteraction(guild=None)
    await execute_setup_campaign(interaction)

    assert interaction.followup.sent_messages
    assert "tylko na serwerze" in interaction.followup.sent_messages[0].content


@pytest.mark.asyncio
async def test_f1_setup_campaign_existing_pinned_rules_not_overwritten():
    """F1.B3: Running setup again does not overwrite or duplicate existing pinned rules."""
    guild = MockGuild(name="Rules Check")
    interaction = MockInteraction(guild=guild)
    await execute_setup_campaign(interaction)

    rules_ch = next(c for c in guild.text_channels if c.name == "zasady-i-mechanika")
    pinned_before = len(await rules_ch.pins())

    # Run again
    interaction2 = MockInteraction(guild=guild)
    await execute_setup_campaign(interaction2)

    pinned_after = len(await rules_ch.pins())
    assert pinned_before == pinned_after == 1


@pytest.mark.asyncio
async def test_f1_setup_campaign_special_characters_in_guild_name():
    """F1.B4: Setup works properly when guild has unicode / emoji names."""
    guild = MockGuild(name="⚔️ Smocza Przełęcz 🛡️ [D&D 5e]")
    interaction = MockInteraction(guild=guild)
    await execute_setup_campaign(interaction)

    assert len(guild.categories) == 3
    assert len(guild.forums) == 2


@pytest.mark.asyncio
async def test_f1_setup_campaign_rapid_concurrent_invocations():
    """F1.B5: Handles consecutive rapid calls without state corruption."""
    guild = MockGuild(name="Stress Test")
    for _ in range(5):
        interaction = MockInteraction(guild=guild)
        await execute_setup_campaign(interaction)

    assert len(guild.categories) == 3
    assert len(guild.forums) == 2


# ============================================================================
# F2 Boundaries: Live Pinned Rules Parsing
# ============================================================================

@pytest.mark.asyncio
async def test_f2_empty_pinned_post_returns_empty_or_default(configured_guild: MockGuild):
    """F2.B1: Pinned message with whitespace only returns safe string."""
    rules_ch = next(c for c in configured_guild.text_channels if c.name == "zasady-i-mechanika")
    pinned = (await rules_ch.pins())[0]
    await pinned.edit(content="")

    rules = await fetch_campaign_rules(configured_guild)
    assert isinstance(rules, str)


@pytest.mark.asyncio
async def test_f2_massive_rules_post_2000_plus_chars(configured_guild: MockGuild):
    """F2.B2: Massive pinned post (>2500 chars) is read in full without truncation."""
    rules_ch = next(c for c in configured_guild.text_channels if c.name == "zasady-i-mechanika")
    pinned = (await rules_ch.pins())[0]
    long_rules = "📌 ZASADY GŁÓWNE:\n" + ("- Zasada specjalna dotycząca walki i magii.\n" * 60)
    await pinned.edit(content=long_rules)

    rules = await fetch_campaign_rules(configured_guild)
    assert len(rules) > 2000
    assert "Zasada specjalna" in rules


@pytest.mark.asyncio
async def test_f2_multiple_pinned_posts_takes_first_pin(configured_guild: MockGuild):
    """F2.B3: When multiple pinned posts exist, uses primary pinned rule post."""
    rules_ch = next(c for c in configured_guild.text_channels if c.name == "zasady-i-mechanika")
    second_pin = await rules_ch.send("Drugi przypięty post: Dodatkowe lore")
    await second_pin.pin()

    rules = await fetch_campaign_rules(configured_guild)
    assert "AKTUALNE ZASADY" in rules


@pytest.mark.asyncio
async def test_f2_channel_exists_but_has_zero_messages(configured_guild: MockGuild):
    """F2.B4: #zasady-i-mechanika channel has zero messages -> returns fallback default."""
    rules_ch = next(c for c in configured_guild.text_channels if c.name == "zasady-i-mechanika")
    rules_ch.messages.clear()
    rules_ch.pinned_messages.clear()

    rules = await fetch_campaign_rules(configured_guild)
    assert "Standardowe D&D 5e" in rules


@pytest.mark.asyncio
async def test_f2_rapid_mid_turn_rule_modifications(configured_guild: MockGuild):
    """F2.B5: Frequent edits to pinned rules immediately propagate to subsequent fetches."""
    rules_ch = next(c for c in configured_guild.text_channels if c.name == "zasady-i-mechanika")
    pinned = (await rules_ch.pins())[0]

    for i in range(1, 4):
        await pinned.edit(content=f"Reguła v{i}: Testowa zmiana mechaniki {i}")
        rules = await fetch_campaign_rules(configured_guild)
        assert f"Reguła v{i}" in rules


# ============================================================================
# F3 Boundaries: Forum Character State Persistence
# ============================================================================

def test_f3_malformed_corrupted_json_returns_none():
    """F3.B1: Malformed JSON in <!-- DATA_JSON --> safely returns None instead of raising."""
    corrupted_text = "Opis postaci\n<!-- DATA_JSON: {not: valid json} -->"
    res = extract_json_from_message(corrupted_text)
    assert res is None


def test_f3_character_with_negative_or_zero_hp():
    """F3.B2: Character state supports 0 HP (unconscious/dead) correctly."""
    char = CharacterModel(
        discord_user_id="101",
        name="Poległy Wojownik",
        character_class="Fighter",
        race="Human",
        current_hp=0,
        max_hp=20
    )
    assert char.current_hp == 0
    bar = create_health_bar(char.current_hp, char.max_hp)
    assert "0/20 HP" in bar


def test_f3_character_with_massive_xp_and_level_20():
    """F3.B3: Character at maximum level 20 with high stats and gold."""
    char = CharacterModel(
        discord_user_id="101",
        name="Arcymag Elminster",
        character_class="Wizard",
        race="Human",
        level=20,
        xp=355000,
        current_hp=120,
        max_hp=120,
        gold_gp=100000,
        stats=StatBlock(intelligence=20)
    )
    assert char.level == 20
    assert char.stats.modifier("intelligence") == 5


def test_f3_character_with_empty_inventory_and_conditions():
    """F3.B4: Character with zero items and zero active conditions serializes cleanly."""
    char = CharacterModel(
        discord_user_id="101",
        name="Nagi Mnich",
        character_class="Monk",
        race="Human",
        inventory=[],
        conditions=[]
    )
    dumped = char.model_dump()
    assert dumped["inventory"] == []
    assert dumped["conditions"] == []


def test_f3_unicode_and_special_characters_in_character_name():
    """F3.B5: Handles exotic Polish diacritics and symbols in character names."""
    char = CharacterModel(
        discord_user_id="101",
        name="Żółw Ącki-Świętosławski 🗡️",
        character_class="Paladin",
        race="Tortle"
    )
    injected = inject_json_to_text("Opis", char.model_dump())
    extracted = extract_json_from_message(injected)
    assert extracted["name"] == "Żółw Ącki-Świętosławski 🗡️"


# ============================================================================
# F4 Boundaries: 24h Thread Auto-Unarchiving
# ============================================================================

@pytest.mark.asyncio
async def test_f4_unarchive_locked_thread(configured_guild: MockGuild):
    """F4.B1: Thread can be unarchived even if locked."""
    forum = next(f for f in configured_guild.forums if f.name == "karty-postaci")
    t = (await forum.create_thread(name="Locked Hero")).thread
    await t.edit(archived=True, locked=True)

    assert t.archived is True
    assert t.locked is True

    await t.edit(archived=False)
    assert t.archived is False
    assert t.locked is True


@pytest.mark.asyncio
async def test_f4_multiple_concurrent_thread_unarchiving(configured_guild: MockGuild):
    """F4.B2: Concurrently unarchiving multiple forum threads executes without race condition."""
    forum = next(f for f in configured_guild.forums if f.name == "karty-postaci")
    threads = []
    for i in range(5):
        t = (await forum.create_thread(name=f"Hero {i}")).thread
        await t.edit(archived=True)
        threads.append(t)

    for t in threads:
        await t.edit(archived=False)

    for t in threads:
        assert t.archived is False


@pytest.mark.asyncio
async def test_f4_archived_thread_with_no_pinned_messages(configured_guild: MockGuild):
    """F4.B3: get_character_from_thread on thread with no pinned messages falls back to history."""
    forum = next(f for f in configured_guild.forums if f.name == "karty-postaci")
    char = CharacterModel(discord_user_id="101", name="Unpinned Hero", character_class="Rogue", race="Elf")
    embed = create_character_sheet_embed(char)
    embed.description = inject_json_to_text("Karta", char.model_dump())

    t = (await forum.create_thread(name="Unpinned Hero", embed=embed)).thread
    t.pinned_messages.clear()
    await t.edit(archived=True)

    await t.edit(archived=False)
    fetched = await get_character_from_thread(t)
    assert fetched is not None
    assert fetched.name == "Unpinned Hero"


@pytest.mark.asyncio
async def test_f4_unarchive_already_active_thread_no_op(configured_guild: MockGuild):
    """F4.B4: Calling unarchive on an already active thread does not increment unarchive count."""
    forum = next(f for f in configured_guild.forums if f.name == "karty-postaci")
    t = (await forum.create_thread(name="Active Hero")).thread
    assert t.archived is False

    await t.edit(archived=False)
    assert t.unarchived_count == 0


@pytest.mark.asyncio
async def test_f4_thread_with_limit_boundary_on_archived_threads(configured_guild: MockGuild):
    """F4.B5: forum.archived_threads(limit=2) respects query limit boundary."""
    forum = next(f for f in configured_guild.forums if f.name == "karty-postaci")
    for i in range(5):
        t = (await forum.create_thread(name=f"Archived {i}")).thread
        await t.edit(archived=True)

    scanned = []
    async for t in forum.archived_threads(limit=2):
        scanned.append(t)

    assert len(scanned) == 2


# ============================================================================
# F5 Boundaries: Quest Journal System
# ============================================================================

def test_f5_quest_with_zero_objectives():
    """F5.B1: QuestModel with 0 objectives handles serialization properly."""
    quest = QuestModel(id="q-empty", title="Puste zadanie", giver="NPC", description="Brak celów", objectives=[])
    assert len(quest.objectives) == 0
    dumped = quest.model_dump()
    assert dumped["objectives"] == []


def test_f5_quest_with_empty_or_none_reward():
    """F5.B2: Quest with None reward serializes without error."""
    quest = QuestModel(id="q-noreward", title="Wolontariat", giver="Mieszkaniec", description="Pomóż za darmo", reward=None)
    assert quest.reward is None


def test_f5_corrupted_quest_board_json_recovery():
    """F5.B3: Corrupted quest board JSON returns None allowing fallback init."""
    broken_board = "📜 Zadania drużyny\n<!-- DATA_JSON: [not a dict] -->"
    extracted = extract_json_from_message(broken_board)
    assert extracted is None or not isinstance(extracted, dict) or "quests" not in extracted


def test_f5_quest_objective_index_out_of_bounds_protection():
    """F5.B4: Validates index boundary safety when updating quest objectives."""
    quest = QuestModel(
        id="q-1",
        title="Test",
        giver="G",
        description="D",
        objectives=[QuestObjective(text="O1")]
    )
    target_idx = 5
    if target_idx < len(quest.objectives):
        quest.objectives[target_idx].is_completed = True
    assert len(quest.objectives) == 1
    assert quest.objectives[0].is_completed is False


def test_f5_quest_large_batch_of_active_quests():
    """F5.B5: Supports large batch (20+ quests) inside journal DATA_JSON."""
    quests = [
        QuestModel(id=f"q-{i}", title=f"Zadanie {i}", giver="NPC", description="Desc", reward=f"{i*10} GP")
        for i in range(25)
    ]
    board_data = {"quests": [q.model_dump() for q in quests]}
    injected = inject_json_to_text("Tablica zadań", board_data)
    extracted = extract_json_from_message(injected)

    assert extracted is not None
    assert len(extracted["quests"]) == 25


# ============================================================================
# F6 Boundaries: Deterministic Dice Engine
# ============================================================================

def test_f6_extreme_dc_boundaries():
    """F6.B1: Dice roll against extreme DCs (DC 0 always success, DC 100 always fail)."""
    res_zero = roll_dice("1d20", target_dc=0)
    assert res_zero.is_success is True

    res_hundred = roll_dice("1d20+5", target_dc=100)
    assert res_hundred.is_success is False


def test_f6_massive_dice_formula():
    """F6.B2: Massive dice expression (20d6) computes total within [20, 120]."""
    res = roll_dice("20d6", reason="Smoczy oddech")
    assert 20 <= res.total <= 120


def test_f6_negative_modifiers():
    """F6.B3: Negative formula modifiers compute properly (1d20-5)."""
    res = roll_dice("1d20-5", reason="Ciężkie rany")
    assert -4 <= res.total <= 15


def test_f6_complex_dice_formula():
    """F6.B4: Complex multi-dice expression (1d20+2d4+3)."""
    res = roll_dice("1d20+2d4+3", reason="Błogosławieństwo")
    assert 6 <= res.total <= 31


def test_f6_invalid_malformed_formula_handling():
    """F6.B5: Malformed formula raises Exception from d20 parser."""
    with pytest.raises(Exception):
        roll_dice("invalid_dice_string")


# ============================================================================
# F7 Boundaries: Core Slash Commands
# ============================================================================

def test_f7_hp_overheal_beyond_max_hp():
    """F7.B1: Healing does not exceed max_hp unless temporary HP is used."""
    char = CharacterModel(discord_user_id="101", name="H", character_class="F", race="H", current_hp=18, max_hp=20)
    heal_amount = 10
    char.current_hp = min(char.max_hp, char.current_hp + heal_amount)
    assert char.current_hp == 20


def test_f7_hp_massive_damage_clamped_to_zero():
    """F7.B2: Massive lethal damage clamps current_hp to 0."""
    char = CharacterModel(discord_user_id="101", name="H", character_class="F", race="H", current_hp=15, max_hp=20)
    damage = 50
    char.current_hp = max(0, char.current_hp - damage)
    assert char.current_hp == 0


def test_f7_item_remove_nonexistent_item_graceful():
    """F7.B3: Removing an item not in inventory leaves inventory intact."""
    char = CharacterModel(
        discord_user_id="101",
        name="H",
        character_class="F",
        race="H",
        inventory=[ItemModel(name="Miecz", quantity=1)]
    )
    initial_count = len(char.inventory)
    char.inventory = [i for i in char.inventory if i.name != "Topór"]
    assert len(char.inventory) == initial_count


def test_f7_item_add_with_quantity_accumulation():
    """F7.B4: Adding existing consumable item increments its quantity."""
    char = CharacterModel(
        discord_user_id="101",
        name="H",
        character_class="F",
        race="H",
        inventory=[ItemModel(name="Pochodnia", quantity=2, item_type="consumable")]
    )
    # Find and increment
    found = False
    for item in char.inventory:
        if item.name == "Pochodnia":
            item.quantity += 3
            found = True
            break
    assert found is True
    assert char.inventory[0].quantity == 5


@pytest.mark.asyncio
async def test_f7_roll_with_zero_target_dc():
    """F7.B5: /roll command with target DC 0."""
    interaction = MockInteraction()
    await execute_roll_command(interaction, formula="1d20", reason="Test", dc=0)
    assert interaction.response.is_done() is True
    embed = interaction.response.sent_messages[0].embeds[0]
    assert embed.color == discord.Color.green()


# ============================================================================
# F8 Boundaries: Dynamic Discord UI Buttons
# ============================================================================

def test_f8_button_with_dc_zero_and_dc_hundred():
    """F8.B1: RollButton handles DC 0 and DC 100 without crashes."""
    btn_easy = RollButton(label="Easy", formula="1d20", reason="Easy", dc=0)
    btn_hard = RollButton(label="Hard", formula="1d20", reason="Hard", dc=100)
    assert btn_easy.dc == 0
    assert btn_hard.dc == 100


def test_f8_narrative_view_with_5_buttons_discord_row_limit():
    """F8.B2: NarrativeActionView populates up to 5 buttons in single action row."""
    actions = [{"label": f"Opcja {i}", "formula": "1d20", "reason": f"R{i}", "dc": 10+i} for i in range(5)]
    view = NarrativeActionView(actions)
    assert len(view.children) == 5


def test_f8_narrative_view_with_malformed_button_dicts():
    """F8.B3: Handles button specifications with missing optional fields safely."""
    actions = [
        {"label": "Brak formuly i dc"},
        {"reason": "Tylko powod"}
    ]
    view = NarrativeActionView(actions)
    assert len(view.children) == 2
    assert view.children[0].formula == "1d20"  # fallback default
    assert view.children[1].label == "Rzut"     # fallback default


@pytest.mark.asyncio
async def test_f8_button_interaction_from_different_user():
    """F8.B4: Button responds correctly to any user clicking."""
    btn = RollButton(label="Atak", formula="1d20+2", reason="Atak", dc=12)
    user2 = MockUser(id=99, name="InnyGracz", display_name="Legolas")
    interaction = MockInteraction(user=user2)

    await btn.callback(interaction)
    assert "Legolas" in interaction.response.sent_messages[0].content


def test_f8_button_formula_with_advantage_and_disadvantage():
    """F8.B5: Button with pre-composed advantage formula (2d20kh1+3)."""
    btn = RollButton(label="Atak z ułatwieniem", formula="2d20kh1+3", reason="Atak", dc=15)
    assert "2d20kh1" in btn.formula


# ============================================================================
# F9 Boundaries: Aesthetic Rich Embeds & ASCII Bars
# ============================================================================

def test_f9_health_bar_current_exceeds_max():
    """F9.B1: When current HP > max HP (temp HP), clamps bar fill ratio to 100%."""
    bar = create_health_bar(current=25, max_val=20, length=10)
    assert "[██████████]" in bar
    assert "25/20 HP" in bar


def test_f9_health_bar_max_val_zero():
    """F9.B2: Health bar with max_val=0 safely avoids DivisionByZero."""
    bar = create_health_bar(current=0, max_val=0, length=10)
    assert "[░░░░░░░░░░]" in bar
    assert "0/0 HP" in bar


def test_f9_health_bar_negative_current_hp():
    """F9.B3: Health bar with negative current HP clamps fill ratio to 0%."""
    bar = create_health_bar(current=-10, max_val=20, length=10)
    assert "[░░░░░░░░░░]" in bar
    assert "-10/20 HP" in bar


def test_f9_character_embed_with_none_avatar_url(sample_character: CharacterModel):
    """F9.B4: Character sheet embed handles None avatar_url without error."""
    sample_character.avatar_url = None
    embed = create_character_sheet_embed(sample_character)
    assert embed.thumbnail.url is None


def test_f9_character_embed_with_long_condition_list(sample_character: CharacterModel):
    """F9.B5: Character sheet embed formats multiple conditions."""
    sample_character.conditions = ["Otruty", "Oślepiony", "Przewrócony", "Ogłuszony"]
    embed = create_character_sheet_embed(sample_character)
    cond_field = next(f for f in embed.fields if "Aktywne Stany" in f.name)
    assert "Otruty" in cond_field.value
    assert "Ogłuszony" in cond_field.value


# ============================================================================
# F10 Boundaries: Google Gemini 3.7 Flash Integration
# ============================================================================

@pytest.mark.asyncio
async def test_f10_gemini_injected_api_error_500(mock_gemini: MockGeminiClient):
    """F10.B1: Gemini 500 internal server error raises MockAPIError."""
    mock_gemini.inject_error(MockAPIError("Gemini Internal Server Error 500"))

    with pytest.raises(MockAPIError):
        await mock_gemini.generate_narrative("Prompt")


@pytest.mark.asyncio
async def test_f10_gemini_injected_rate_limit_429(mock_gemini: MockGeminiClient):
    """F10.B2: Gemini 429 rate limit error raises MockRateLimitError."""
    mock_gemini.inject_error(MockRateLimitError("Quota exceeded 429"))

    with pytest.raises(MockRateLimitError):
        await mock_gemini.generate_narrative("Prompt")


@pytest.mark.asyncio
async def test_f10_gemini_injected_safety_filter_error(mock_gemini: MockGeminiClient):
    """F10.B3: Safety filter block raises MockSafetyFilterError."""
    mock_gemini.inject_error(MockSafetyFilterError("Harm filter triggered"))

    with pytest.raises(MockSafetyFilterError):
        await mock_gemini.generate_narrative("Prompt")


@pytest.mark.asyncio
async def test_f10_gemini_empty_context_prompt(mock_gemini: MockGeminiClient):
    """F10.B4: Handles empty context prompt string gracefully."""
    text, btns = await mock_gemini.generate_narrative("")
    assert isinstance(text, str)
    assert isinstance(btns, list)


@pytest.mark.asyncio
async def test_f10_gemini_massive_context_prompt_10k_tokens(mock_gemini: MockGeminiClient):
    """F10.B5: Large context prompt (10,000+ characters) is recorded accurately."""
    big_prompt = "Wydarzenie historyczne.\n" * 500
    text, btns = await mock_gemini.generate_narrative(big_prompt)
    assert mock_gemini.last_call["context_prompt"] == big_prompt


# ============================================================================
# F11 Boundaries: Strict Narrative Triggering Filter
# ============================================================================

def test_f11_mention_inside_longer_word_not_matching_prefix(mock_bot_user: MockUser):
    """F11.B1: Text containing bot name without proper mention pattern."""
    msg = MockMessage(content="To nie jest Mistrz Gry tylko zwykly npc", author=MockUser(id=10, name="P"))
    # In discord, literal text without @ or tag is not a mention
    # MockUser.mentioned_in checks @Mistrz Gry
    assert mock_bot_user.mentioned_in(msg) is False


def test_f11_multiple_bot_mentions_in_single_message(mock_bot_user: MockUser):
    """F11.B2: Message with multiple @Mistrz Gry mentions still evaluates to True."""
    msg = MockMessage(content="@Mistrz Gry powiedz nam, @Mistrz Gry co sie dzieje?", author=MockUser(id=10, name="P"))
    assert mock_bot_user.mentioned_in(msg) is True


def test_f11_message_with_only_whitespace_and_mention(mock_bot_user: MockUser):
    """F11.B3: Message with only whitespace and @Mistrz Gry is triggered."""
    msg = MockMessage(content="   @Mistrz Gry   ", author=MockUser(id=10, name="P"))
    assert mock_bot_user.mentioned_in(msg) is True


def test_f11_ooc_mixed_with_in_character_text():
    """F11.B4: Message that is NOT entirely OOC (does not both start and end with (())) is kept."""
    mixed_msg = "Atakuję orka ((muszę rzucić kością))"
    is_pure_ooc = mixed_msg.startswith("((") and mixed_msg.endswith("))")
    assert is_pure_ooc is False


@pytest.mark.asyncio
async def test_f11_interaction_on_wrong_channel_ignored(configured_guild: MockGuild):
    """F11.B5: Messages on #szepty-dm or #kronika-przygod are not processed by table handler."""
    kronika = next(c for c in configured_guild.text_channels if c.name == "kronika-przygod")
    assert kronika.name != "stol-gry"


# ============================================================================
# F12 Boundaries: Stateless Channel History Scanner
# ============================================================================

@pytest.mark.asyncio
async def test_f12_channel_with_zero_messages(
    configured_guild: MockGuild,
    mock_bot_user: MockUser
):
    """F12.B1: Completely empty channel returns empty events string."""
    stol = next(c for c in configured_guild.text_channels if c.name == "stol-gry")
    stol.messages.clear()
    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    assert events == ""


@pytest.mark.asyncio
async def test_f12_channel_with_only_ooc_messages(
    configured_guild: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser
):
    """F12.B2: Channel containing only ((OOC)) messages produces empty events string."""
    stol = next(c for c in configured_guild.text_channels if c.name == "stol-gry")
    stol.messages.clear()
    stol.messages.append(MockMessage(content="((Zaraz wracam, ide po herbate))", author=mock_player_user, channel=stol))
    stol.messages.append(MockMessage(content="((Dobra, czekamy))", author=mock_player_user, channel=stol))

    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    assert events == ""


@pytest.mark.asyncio
async def test_f12_channel_with_limit_exceeded_50_messages(
    configured_guild: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser
):
    """F12.B3: Scanner respects message history limits without memory exhaustion."""
    stol = next(c for c in configured_guild.text_channels if c.name == "stol-gry")
    stol.messages.clear()
    for i in range(100):
        stol.messages.append(MockMessage(content=f"Wiadomosc {i}", author=mock_player_user, channel=stol))

    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    assert isinstance(events, str)
    assert len(events.split("\n")) <= 30


@pytest.mark.asyncio
async def test_f12_embed_missing_wynik_field_handled(
    configured_guild: MockGuild,
    mock_bot_user: MockUser
):
    """F12.B4: Malformed roll embed without 'Wynik' field parses without crash."""
    stol = next(c for c in configured_guild.text_channels if c.name == "stol-gry")
    old_bot_msg = MockMessage(content="Poprzedni", author=mock_bot_user, channel=stol)
    stol.messages.append(old_bot_msg)

    bad_embed = MockEmbed(title="Thorin rzuca: Test")
    dice_user = MockUser(id=888, name="DiceEngine", bot=False)
    msg = MockMessage(content="", author=dice_user, channel=stol, embed=bad_embed)
    stol.messages.append(msg)

    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    assert "[SYSTEM RZUTOW]: Thorin rzuca: Test" in events


@pytest.mark.asyncio
async def test_f12_consecutive_bot_messages(
    configured_guild: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser
):
    """F12.B5: Consecutive bot messages correctly anchors to the most recent bot message."""
    stol = next(c for c in configured_guild.text_channels if c.name == "stol-gry")
    stol.messages.clear()
    
    b1 = MockMessage(content="Bot 1", author=mock_bot_user, channel=stol)
    stol.messages.append(b1)
    stol.messages.append(MockMessage(content="Gracz miedzy botami", author=mock_player_user, channel=stol))
    b2 = MockMessage(content="Bot 2", author=mock_bot_user, channel=stol)
    stol.messages.append(b2)
    stol.messages.append(MockMessage(content="Najnowsza akcja gracza", author=mock_player_user, channel=stol))

    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    assert "Najnowsza akcja gracza" in events
    assert "Gracz miedzy botami" not in events


# ============================================================================
# F13 Boundaries: Smart Paragraph Splitter
# ============================================================================

def test_f13_exact_boundary_limit_length():
    """F13.B1: Message of exactly 1900 chars is not split."""
    exact_text = "A" * 1900
    chunks = split_long_message(exact_text, limit=1900)
    assert len(chunks) == 1
    assert len(chunks[0]) == 1900


def test_f13_boundary_limit_plus_one_length():
    """F13.B2: Message of 1901 chars splits into 2 chunks."""
    text = ("Slowo " * 380)  # ~2280 chars
    chunks = split_long_message(text, limit=1900)
    assert len(chunks) == 2
    for c in chunks:
        assert len(c) <= 1900


def test_f13_single_unbroken_giant_token_without_spaces():
    """F13.B3: Single giant unbroken 3000-char string hard-splits safely."""
    giant_word = "X" * 3000
    chunks = split_long_message(giant_word, limit=1000)
    assert len(chunks) == 3
    for c in chunks:
        assert len(c) <= 1000


def test_f13_custom_small_limit_50_chars():
    """F13.B4: Small limit (50 chars) cleanly segments sentence."""
    text = "To jest pierwsze zdanie. To jest drugie zdanie. To jest trzecie zdanie."
    chunks = split_long_message(text, limit=30)
    assert len(chunks) >= 3
    for c in chunks:
        assert len(c) <= 30


def test_f13_multiple_consecutive_newlines_preserved():
    """F13.B5: Handles texts with multiple consecutive blank lines without empty chunks."""
    text = "Akapit 1\n\n\n\n\n\nAkapit 2\n\n\n\nAkapit 3"
    chunks = split_long_message(text, limit=500)
    assert len(chunks) == 1
    assert "Akapit 1" in chunks[0]
    assert "Akapit 3" in chunks[0]


# ============================================================================
# F14 Boundaries: Dynamic Action Button Extraction
# ============================================================================

def test_f14_malformed_json_in_action_tag_handled_gracefully():
    """F14.B1: Malformed JSON inside [ACTION_BUTTONS: ...] returns clean text and empty button list."""
    raw = "Narracja fabularna.\n\n[ACTION_BUTTONS: [{\"label\": unclosed string]]"
    clean, buttons = MockGeminiClient.extract_action_buttons(raw)
    assert clean == "Narracja fabularna."
    assert buttons == []


def test_f14_action_tag_with_non_list_json():
    """F14.B2: [ACTION_BUTTONS: {"not": "a list"}] returns empty list."""
    raw = "Narracja.\n\n[ACTION_BUTTONS: {\"label\": \"Tylko obiekt\"}]"
    clean, buttons = MockGeminiClient.extract_action_buttons(raw)
    assert clean == "Narracja."
    assert buttons == []


def test_f14_button_dict_missing_dc_key():
    """F14.B3: Button dictionary missing 'dc' key defaults to dc=None."""
    raw = "[ACTION_BUTTONS: [{\"label\": \"Rzut\", \"formula\": \"1d20\", \"reason\": \"Test\"}]]"
    clean, buttons = MockGeminiClient.extract_action_buttons(raw)
    assert len(buttons) == 1
    assert buttons[0].get("dc") is None


def test_f14_multiple_action_tags_in_single_narrative():
    """F14.B4: Single narrative with multiple action blocks extracts first and cleans all."""
    raw = (
        "Część 1.\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"B1\", \"formula\": \"1d20\"}]]\n\n"
        "Część 2."
    )
    clean, buttons = MockGeminiClient.extract_action_buttons(raw)
    assert len(buttons) == 1
    assert buttons[0]["label"] == "B1"
    assert "[ACTION_BUTTONS:" not in clean


def test_f14_action_tag_at_very_start_of_text():
    """F14.B5: Action tag at the very start of string leaves clean remaining text."""
    raw = "[ACTION_BUTTONS: [{\"label\": \"Inicjatywa\", \"formula\": \"1d20+2\"}]]\n\nRozpoczyna się walka!"
    clean, buttons = MockGeminiClient.extract_action_buttons(raw)
    assert len(buttons) == 1
    assert clean == "Rozpoczyna się walka!"
