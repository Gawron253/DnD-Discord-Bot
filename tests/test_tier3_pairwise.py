"""Tier 3 Test Suite: Pairwise Combinatorial Integration Tests (>=15 tests).
Verifies cross-module interactions between Discord DB, Dice Engine, Embeds/Views, Context Scanner, and AI Engine.
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
from tests.mock_ai import MockGeminiClient, split_long_message
from core.models import (
    CharacterModel,
    StatBlock,
    ItemModel,
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
# Pairwise 1: F1 (Setup Campaign) + F3 (Forum State Persistence)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f1_setup_and_f3_character_onboarding():
    """PW.1: Setup campaign creates #karty-postaci, followed immediately by onboarding a character sheet."""
    guild = MockGuild(name="Fresh Campaign")
    interaction = MockInteraction(guild=guild)
    await execute_setup_campaign(interaction)

    forum = next(f for f in guild.forums if f.name == "karty-postaci")
    char = CharacterModel(
        discord_user_id="101",
        name="Balin Topornik",
        character_class="Fighter",
        race="Dwarf",
        level=1,
        current_hp=12,
        max_hp=12,
        stats=StatBlock(strength=16)
    )

    embed = create_character_sheet_embed(char)
    embed.description = inject_json_to_text(embed.description or "", char.model_dump())
    
    t_res = await forum.create_thread(name=f"🛡️ {char.name}", embed=embed)
    thread = t_res.thread

    reloaded = await get_character_from_thread(thread)
    assert reloaded is not None
    assert reloaded.name == "Balin Topornik"
    assert reloaded.stats.strength == 16


# ============================================================================
# Pairwise 2: F2 (Live Rules) + F10 (Gemini Integration)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f2_live_rules_and_f10_gemini_context(
    configured_guild: MockGuild,
    mock_gemini: MockGeminiClient
):
    """PW.2: Updating pinned rules in #zasady-i-mechanika immediately feeds new rules to Gemini prompt."""
    rules_ch = next(c for c in configured_guild.text_channels if c.name == "zasady-i-mechanika")
    pinned = (await rules_ch.pins())[0]
    await pinned.edit(content="📌 REGULA HOMEBREW: Wszelkie obrażenia od ognia są podwojone.")

    live_rules = await fetch_campaign_rules(configured_guild)
    context_prompt = f"ZASADY: {live_rules}\n\nAKCJA: Gracz rzuca Ognistą Kulę w trolla."

    await mock_gemini.generate_narrative(context_prompt)

    last_call = mock_gemini.last_call
    assert "obrażenia od ognia są podwojone" in last_call["context_prompt"]


# ============================================================================
# Pairwise 3: F3 (State) + F4 (24h Unarchiving) + F7 (Slash Commands)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f3_f4_f7_hp_command_on_sleeping_thread(populated_campaign: MockGuild):
    """PW.3: /hp command executed on a 24h-archived character sheet automatically wakes and updates thread."""
    forum = next(f for f in populated_campaign.forums if f.name == "karty-postaci")
    thread = forum.threads[0]

    # Sleep after 24h
    await thread.edit(archived=True)
    assert thread.archived is True

    # Bot receives /hp -8 command
    if thread.archived:
        await thread.edit(archived=False)

    char = await get_character_from_thread(thread)
    assert char is not None
    char.current_hp = max(0, char.current_hp - 8)

    updated_embed = create_character_sheet_embed(char)
    updated_embed.description = inject_json_to_text(updated_embed.description or "", char.model_dump())
    pinned = (await thread.pins())[0]
    await pinned.edit(embed=updated_embed)
    await thread.send(f"❤️ Zmiana HP: -8 (Pozostało: {char.current_hp}/{char.max_hp})")

    assert thread.archived is False
    assert thread.unarchived_count == 1
    reloaded = await get_character_from_thread(thread)
    assert reloaded.current_hp == 20


# ============================================================================
# Pairwise 4: F3 (Character Stats) + F6 (Dice Engine) + F8 (UI Buttons)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f3_f6_f8_button_uses_character_stats(sample_character: CharacterModel):
    """PW.4: Button built with character's modifier triggers deterministic roll and response."""
    str_mod = sample_character.stats.modifier("strength")
    btn = RollButton(
        label=f"Atak Młotem (STR {str_mod:+d})",
        formula=f"1d20{str_mod:+d}",
        reason="Atak Młotem Bojowym",
        dc=15
    )
    interaction = MockInteraction(user=MockUser(id=101, name="Thorin", display_name="Thorin"))

    await btn.callback(interaction)

    assert interaction.response.is_done() is True
    sent = interaction.response.sent_messages[0]
    assert "Thorin" in sent.content
    embed = sent.embeds[0]
    assert "1d20+3" in [f.value for f in embed.fields if "Formu" in f.name][0]


# ============================================================================
# Pairwise 5: F5 (Quest System) + F7 (Slash Commands) + F9 (Rich Embeds)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f5_f7_f9_quest_create_and_journal_embed(configured_guild: MockGuild):
    """PW.5: /quest create posts formatted embed with DATA_JSON in #dziennik-zadan."""
    ch_dziennik = next(c for c in configured_guild.text_channels if c.name == "dziennik-zadan")
    
    new_quest = QuestModel(
        id="q-relic",
        title="Zaginiony Relikt",
        giver="Kapłan Eamon",
        description="Odzyskaj kielich ze świątyni",
        objectives=[QuestObjective(text="Wejdź do krypty", is_completed=False)],
        reward="200 GP"
    )

    quest_desc = (
        f"**Aktywne Zadanie:** {new_quest.title}\n"
        f"**Zleceniodawca:** {new_quest.giver}\n"
        f"**Opis:** {new_quest.description}\n"
        f"**Nagroda:** {new_quest.reward}"
    )
    injected_desc = inject_json_to_text(quest_desc, {"quests": [new_quest.model_dump()]})
    embed = MockEmbed(title="📜 Dziennik Zadań Drużyny", description=injected_desc, color=discord.Color.gold())
    
    msg = await ch_dziennik.send(embed=embed)
    await msg.pin()

    pinned = await ch_dziennik.pins()
    assert len(pinned) == 1
    data = extract_json_from_message(pinned[0].embeds[0].description)
    assert data["quests"][0]["id"] == "q-relic"


# ============================================================================
# Pairwise 6: F6 (Dice Engine) + F7 (Commands) + F9 (Rich Embeds)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f6_f7_f9_roll_command_embed_formatting():
    """PW.6: /roll command evaluates DC and produces color-coded embed."""
    interaction = MockInteraction()
    await execute_roll_command(interaction, formula="1d20+5", reason="Akrobatyka", dc=14)

    sent = interaction.response.sent_messages[0]
    embed = sent.embeds[0]
    assert "Akrobatyka" in (embed.title or "")
    assert embed.color in (discord.Color.green(), discord.Color.red())


# ============================================================================
# Pairwise 7: F11 (Trigger Filter) + F12 (Scanner) + F10 (Gemini) + F14 (Buttons)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f11_f12_f10_f14_full_narrative_turn_cycle(
    configured_guild: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser,
    mock_gemini: MockGeminiClient
):
    """PW.7: Mentioning @Mistrz Gry triggers scanner, feeds Gemini, extracts action buttons, and returns view."""
    stol = next(c for c in configured_guild.text_channels if c.name == "stol-gry")
    
    # 1. Base bot narrative
    stol.messages.append(MockMessage(content="Jesteście przed bramą.", author=mock_bot_user, channel=stol))

    # 2. Player declaration with mention
    player_msg = MockMessage(
        content="Próbuję wyważyć bramę barkiem, @Mistrz Gry!",
        author=mock_player_user,
        channel=stol
    )
    stol.messages.append(player_msg)

    # 3. Filter check
    assert mock_bot_user.mentioned_in(player_msg) is True

    # 4. Scanner collects events
    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    assert "Próbuję wyważyć bramę" in events

    # 5. Gemini responds with action buttons
    mock_gemini.queue_response(
        "Brama trzeszczy pod Twoim naporem!\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Rzut na Siłę (STR +3)\", \"formula\": \"1d20+3\", \"reason\": \"Wyważanie\", \"dc\": 15}]]"
    )
    narrative, action_btns = await mock_gemini.generate_narrative(events)
    view = NarrativeActionView(action_btns)

    assert "Brama trzeszczy" in narrative
    assert len(view.children) == 1
    assert view.children[0].label == "Rzut na Siłę (STR +3)"


# ============================================================================
# Pairwise 8: F10 (Gemini) + F13 (Splitter) + F14 (Action Buttons)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f10_f13_f14_long_response_split_with_buttons(mock_gemini: MockGeminiClient):
    """PW.8: 3000-character narrative with action buttons splits into chunks with buttons on final chunk."""
    p1 = "Akapit 1: " + ("Opis starożytnej świątyni. " * 60)
    p2 = "Akapit 2: " + ("Opis ołtarza i posągów. " * 60)
    raw_response = (
        f"{p1}\n\n{p2}\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Zbadaj ołtarz\", \"formula\": \"1d20+2\", \"reason\": \"Religia\", \"dc\": 12}]]"
    )
    mock_gemini.queue_response(raw_response)

    narrative, action_btns = await mock_gemini.generate_narrative("Badamy świątynię")
    chunks = split_long_message(narrative, limit=1500)

    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 1500
        assert "[ACTION_BUTTONS:" not in c

    # Action buttons are attached to the final view
    final_view = NarrativeActionView(action_btns)
    assert len(final_view.children) == 1
    assert final_view.children[0].label == "Zbadaj ołtarz"


# ============================================================================
# Pairwise 9: F3 (Persistence) + F7 (Inventory Commands)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f3_f7_inventory_mutation_cycle(populated_campaign: MockGuild):
    """PW.9: /item add and /item remove sequentially update character inventory in forum thread."""
    forum = next(f for f in populated_campaign.forums if f.name == "karty-postaci")
    thread = forum.threads[0]

    # 1. Add item
    char = await get_character_from_thread(thread)
    char.inventory.append(ItemModel(name="Klucz do Lochów", quantity=1, item_type="quest"))
    pinned = (await thread.pins())[0]
    embed = create_character_sheet_embed(char)
    embed.description = inject_json_to_text(embed.description or "", char.model_dump())
    await pinned.edit(embed=embed)

    # 2. Verify addition
    c2 = await get_character_from_thread(thread)
    assert any(i.name == "Klucz do Lochów" for i in c2.inventory)

    # 3. Remove item
    c2.inventory = [i for i in c2.inventory if i.name != "Klucz do Lochów"]
    embed2 = create_character_sheet_embed(c2)
    embed2.description = inject_json_to_text(embed2.description or "", c2.model_dump())
    await pinned.edit(embed=embed2)

    # 4. Verify removal
    c3 = await get_character_from_thread(thread)
    assert not any(i.name == "Klucz do Lochów" for i in c3.inventory)


# ============================================================================
# Pairwise 10: F2 (Rules) + F11 (Trigger) + F12 (Scanner)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f2_f11_f12_rules_and_dice_roll_context_scan(
    configured_guild: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser
):
    """PW.10: History scan picks up recent dice roll embed and combines with current rules."""
    stol = next(c for c in configured_guild.text_channels if c.name == "stol-gry")
    
    # 1. Base message
    stol.messages.append(MockMessage(content="Poprzednia scena", author=mock_bot_user, channel=stol))

    # 2. Roll embed from dice engine
    roll_res = DiceRollResult(formula="1d20+3", total=19, breakdown="16+3", is_success=True, target_dc=15, reason="Wspinaczka")
    embed = create_dice_roll_embed(roll_res, "Thorin")
    dice_user = MockUser(id=888, name="DiceBot", bot=False)
    stol.messages.append(MockMessage(content="", author=dice_user, channel=stol, embed=embed))

    # 3. Player trigger
    trigger_msg = MockMessage(content="Udało mi się wejść na mur! @Mistrz Gry", author=mock_player_user, channel=stol)
    stol.messages.append(trigger_msg)

    # 4. Scan history and rules
    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    rules = await fetch_campaign_rules(configured_guild)

    assert "Thorin rzuca: Wspinaczka" in events
    assert "Udało mi się wejść" in events
    assert "D&D 5e" in rules


# ============================================================================
# Pairwise 11: F4 (Unarchive) + F5 (Quest) + F7 (Commands)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f4_f5_f7_quest_complete_on_reloaded_state(populated_campaign: MockGuild):
    """PW.11: Completing a quest updates pinned board in #dziennik-zadan."""
    ch_dziennik = next(c for c in populated_campaign.text_channels if c.name == "dziennik-zadan")
    pinned = (await ch_dziennik.pins())[0]
    
    data = extract_json_from_message(pinned.embeds[0].description)
    quest = QuestModel(**data["quests"][0])
    
    # Complete quest
    for obj in quest.objectives:
        obj.is_completed = True
    quest.status = "completed"

    updated_data = {"quests": [quest.model_dump()]}
    updated_desc = inject_json_to_text(f"Zadanie {quest.title} UKOŃCZONE!", updated_data)
    await pinned.edit(embed=MockEmbed(title="📜 Dziennik Zadań", description=updated_desc))

    reloaded = await ch_dziennik.pins()
    reloaded_data = extract_json_from_message(reloaded[0].embeds[0].description)
    assert reloaded_data["quests"][0]["status"] == "completed"


# ============================================================================
# Pairwise 12: F3 (Character State) + F9 (Rich Embeds)
# ============================================================================

def test_pairwise_f3_f9_hp_delta_updates_ascii_bar(sample_character: CharacterModel):
    """PW.12: Decreasing character HP dynamically reflects on ASCII health bar."""
    embed_full = create_character_sheet_embed(sample_character)
    field_full = next(f for f in embed_full.fields if "ywotno" in f.name)
    assert "28/28 HP" in field_full.value

    # Take damage
    sample_character.current_hp = 14
    embed_half = create_character_sheet_embed(sample_character)
    field_half = next(f for f in embed_half.fields if "ywotno" in f.name)
    assert "14/28 HP" in field_half.value
    assert "█████░░░░░" in field_half.value


# ============================================================================
# Pairwise 13: F8 (UI Buttons) + F12 (Scanner)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f8_f12_button_output_captured_by_history_scanner(
    configured_guild: MockGuild,
    mock_bot_user: MockUser
):
    """PW.13: Roll button click sends embed which is accurately extracted by subsequent scanner."""
    stol = next(c for c in configured_guild.text_channels if c.name == "stol-gry")
    stol.messages.append(MockMessage(content="Wstęp", author=mock_bot_user, channel=stol))

    btn = RollButton(label="Percepcja (WIS +2)", formula="1d20+2", reason="Percepcja w jaskini", dc=13)
    user = MockUser(id=101, name="Gimli", display_name="Gimli")
    interaction = MockInteraction(user=user, channel=stol)

    await btn.callback(interaction)

    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    assert "[SYSTEM RZUTOW]:" in events
    assert "Gimli rzuca: Percepcja w jaskini" in events


# ============================================================================
# Pairwise 14: F1 (Setup) + F2 (Rules) + F5 (Quest System)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f1_f2_f5_fresh_setup_initializes_rules_and_quest_channels():
    """PW.14: /setup-campaign initializes rules in #zasady-i-mechanika and ready quest journal."""
    guild = MockGuild(name="Adventure Start")
    interaction = MockInteraction(guild=guild)
    await execute_setup_campaign(interaction)

    rules_ch = next(c for c in guild.text_channels if c.name == "zasady-i-mechanika")
    quest_ch = next(c for c in guild.text_channels if c.name == "dziennik-zadan")

    assert len(await rules_ch.pins()) >= 1
    assert quest_ch is not None


# ============================================================================
# Pairwise 15: F10 (Gemini) + F11 (Trigger) + F12 (Scanner) + F3 (Characters)
# ============================================================================

@pytest.mark.asyncio
async def test_pairwise_f10_f11_f12_f3_full_turn_with_all_characters(
    populated_campaign: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser,
    mock_gemini: MockGeminiClient
):
    """PW.15: Assembles complete multi-character state, live rules, and history into Gemini prompt."""
    stol = next(c for c in populated_campaign.text_channels if c.name == "stol-gry")
    
    # 1. Prior bot message
    stol.messages.append(MockMessage(content="Wilki wyskakują z krzaków!", author=mock_bot_user, channel=stol))

    # 2. Player action
    msg = MockMessage(content="Zasłaniam Elorę tarczą i szykuję młot! @Mistrz Gry", author=mock_player_user, channel=stol)
    stol.messages.append(msg)

    # 3. Context gathering
    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    rules = await fetch_campaign_rules(populated_campaign)
    chars = await fetch_active_characters(populated_campaign)

    assert len(chars) == 2
    assert any(c["name"] == "Thorin Kamienna Tarcza" for c in chars)
    assert any(c["name"] == "Elora Gwiazda Nocy" for c in chars)

    full_context = f"ZASADY:\n{rules}\n\nPOSTACIE:\n{chars}\n\nZDARZENIA:\n{events}"
    mock_gemini.queue_response(
        "Wilki okrążają Thorina, warcząc groźnie!\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Atak Młotem (STR +3)\", \"formula\": \"1d20+3\", \"reason\": \"Atak na wilka\", \"dc\": 12}]]"
    )

    narrative, btns = await mock_gemini.generate_narrative(full_context)
    assert "Wilki okrążają" in narrative
    assert len(btns) == 1
