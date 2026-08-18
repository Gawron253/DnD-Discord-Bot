"""Tier 4 Test Suite: End-to-End Real-World Campaign Scenarios (>=5 complex scenarios).
Simulates multi-turn RPG campaign lifecycles from bootstrap to combat, quest completion, and session resumption.
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
# Scenario 1: Full Campaign Bootstrap & Character Onboarding
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_1_full_campaign_bootstrap_and_onboarding():
    """Scenario 1: Complete bootstrap flow creating guild structure, onboarding 2 characters,
    pinning custom homebrew rules, and creating the initial quest board.
    """
    # 1. Admin launches setup
    guild = MockGuild(name="Kroniki Zapomnianych Krain")
    admin_user = MockUser(id=1, name="AdminDM", display_name="Mistrz Gry (Admin)")
    interaction = MockInteraction(user=admin_user, guild=guild)
    
    await execute_setup_campaign(interaction)
    assert len(guild.categories) == 3
    assert len(guild.text_channels) == 6
    assert len(guild.forums) == 2

    # 2. DM customizes homebrew rules in #zasady-i-mechanika
    rules_ch = next(c for c in guild.text_channels if c.name == "zasady-i-mechanika")
    pinned_rules_msg = (await rules_ch.pins())[0]
    custom_rules = (
        "📌 **ZASADY KAMPANII: MROCZNE ZIEMIE**\n"
        "- System: D&D 5e Hardcore\n"
        "- Mikstury: Picie mikstury to Akcja Dodatkowa (Bonus Action)\n"
        "- Obrażenia krytyczne: Maksymalne obrażenia kości + standardowy rzut"
    )
    await pinned_rules_msg.edit(content=custom_rules)

    # 3. Player 1 (Thorin - Wojownik) joins and creates character thread in #karty-postaci
    forum_karty = next(f for f in guild.forums if f.name == "karty-postaci")
    char_thorin = CharacterModel(
        discord_user_id="101",
        name="Thorin Żelazny Bastion",
        character_class="Fighter",
        race="Dwarf",
        level=1,
        current_hp=13,
        max_hp=13,
        armor_class=16,
        stats=StatBlock(strength=16, dexterity=10, constitution=16, intelligence=10, wisdom=12, charisma=8),
        inventory=[ItemModel(name="Topór bojowy", quantity=1, item_type="weapon", is_equipped=True)],
        gold_gp=15
    )
    embed_thorin = create_character_sheet_embed(char_thorin)
    embed_thorin.description = inject_json_to_text("Karta postaci krasnoludzkiego wojownika.", char_thorin.model_dump())
    t1_res = await forum_karty.create_thread(name=f"🛡️ {char_thorin.name}", embed=embed_thorin)
    char_thorin.pinned_sheet_message_id = str(t1_res.message.id)

    # 4. Player 2 (Elora - Czarodziejka) joins and creates character thread
    char_elora = CharacterModel(
        discord_user_id="102",
        name="Elora Srebrny Blask",
        character_class="Wizard",
        race="Elf",
        level=1,
        current_hp=8,
        max_hp=8,
        armor_class=12,
        stats=StatBlock(strength=8, dexterity=14, constitution=12, intelligence=16, wisdom=13, charisma=12),
        spell_slots=SpellSlots(level_1=2, level_1_max=2),
        inventory=[ItemModel(name="Księga Zaklęć", quantity=1, item_type="misc")],
        gold_gp=25
    )
    embed_elora = create_character_sheet_embed(char_elora)
    embed_elora.description = inject_json_to_text("Karta postaci elfickiej czarodziejki.", char_elora.model_dump())
    t2_res = await forum_karty.create_thread(name=f"✨ {char_elora.name}", embed=embed_elora)
    char_elora.pinned_sheet_message_id = str(t2_res.message.id)

    # 5. DM creates initial quest in #dziennik-zadan
    quest_ch = next(c for c in guild.text_channels if c.name == "dziennik-zadan")
    initial_quest = QuestModel(
        id="q-init-rats",
        title="Tajemnica Piwnicy Pod Rozbrykanym Kucem",
        giver="Karczmarz Barnaba",
        description="Dziwne dźwięki i znikające zapasy w piwnicy karczmy.",
        objectives=[
            QuestObjective(text="Zbadaj wejście do piwnicy", is_completed=False),
            QuestObjective(text="Zneutralizuj źródło hałasu", is_completed=False)
        ],
        reward="25 GP i darmowy nocleg"
    )
    quest_desc = inject_json_to_text("📜 **TABLICA ZADAŃ KAMPANII**", {"quests": [initial_quest.model_dump()]})
    quest_msg = await quest_ch.send(embed=MockEmbed(title="📜 Dziennik Zadań", description=quest_desc))
    await quest_msg.pin()

    # Verification: Validate entire state is read back cleanly
    active_chars = await fetch_active_characters(guild)
    assert len(active_chars) == 2
    assert active_chars[0]["name"] == "Thorin Żelazny Bastion"
    assert active_chars[1]["name"] == "Elora Srebrny Blask"

    loaded_rules = await fetch_campaign_rules(guild)
    assert "D&D 5e Hardcore" in loaded_rules

    q_pins = await quest_ch.pins()
    q_data = extract_json_from_message(q_pins[0].embeds[0].description)
    assert q_data["quests"][0]["id"] == "q-init-rats"


# ============================================================================
# Scenario 2: Exploration Turn with Live Rules Adjustment
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_2_exploration_turn_with_live_rules_adjustment(
    populated_campaign: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser,
    mock_gemini: MockGeminiClient
):
    """Scenario 2: Exploration turn where players declare actions, invoke AI DM,
    receive narrative with action buttons, click roll, and mid-game rule change takes effect.
    """
    stol = next(c for c in populated_campaign.text_channels if c.name == "stol-gry")

    # Turn 1: Bot sets initial scene
    stol.messages.append(MockMessage(
        content="Wchodzicie do wilgotnego korytarza. Na końcu drogi widać żelazne wrota z runicznym zamkiem.",
        author=mock_bot_user,
        channel=stol
    ))

    # Players declare actions
    stol.messages.append(MockMessage(
        content="Podchodzę do zamka i sprawdzam mechanizm, @Mistrz Gry!",
        author=mock_player_user,
        channel=stol
    ))

    # Context scanning & AI generation
    events_t1 = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    rules_t1 = await fetch_campaign_rules(populated_campaign)

    mock_gemini.queue_response(
        "Zamek jest skomplikowany, zabezpieczony krasnoludzkim mechanizmem zapadkowym.\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Otwieranie Zamków (DEX +1)\", \"formula\": \"1d20+1\", \"reason\": \"Otwieranie Zamka\", \"dc\": 13}]]"
    )

    t1_text, t1_buttons = await mock_gemini.generate_narrative(f"ZASADY:\n{rules_t1}\n\nZDARZENIA:\n{events_t1}")
    view_t1 = NarrativeActionView(t1_buttons)
    bot_msg_t1 = await stol.send(t1_text, view=view_t1)

    assert "Zamek jest skomplikowany" in t1_text
    assert len(view_t1.children) == 1

    # Player clicks action button
    btn = view_t1.children[0]
    interaction = MockInteraction(user=mock_player_user, channel=stol)
    await btn.callback(interaction)

    # Mid-turn: DM updates rules in #zasady-i-mechanika
    rules_ch = next(c for c in populated_campaign.text_channels if c.name == "zasady-i-mechanika")
    pinned_rule = (await rules_ch.pins())[0]
    await pinned_rule.edit(content="📌 **ZASADY SWIATA**: Magiczna mgła blokuje widzenie powyżej 10 stóp.")

    # Next Turn: Player asks DM what happens next
    stol.messages.append(MockMessage(
        content="Otworzyłem zamek, zaglądam do środka! @Mistrz Gry",
        author=mock_player_user,
        channel=stol
    ))

    events_t2 = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    rules_t2 = await fetch_campaign_rules(populated_campaign)

    assert "Magiczna mgła blokuje widzenie" in rules_t2
    assert "rzuca: Otwieranie Zamka" in events_t2
    assert "Otworzyłem zamek" in events_t2


# ============================================================================
# Scenario 3: Combat Encounter with Dynamic Action Buttons & HP Delta
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_3_combat_encounter_with_action_buttons_and_hp_delta(
    populated_campaign: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser,
    mock_gemini: MockGeminiClient
):
    """Scenario 3: Combat encounter where players use dynamic action buttons for attacks,
    suffer enemy counterattack damage, mutate character sheet HP, and verify audit log.
    """
    stol = next(c for c in populated_campaign.text_channels if c.name == "stol-gry")
    forum_karty = next(f for f in populated_campaign.forums if f.name == "karty-postaci")
    thread_thorin = forum_karty.threads[0]

    # Initial bot turn starting combat
    stol.messages.append(MockMessage(
        content="Z cienia wyskakuje Goblin Berserker z zatrutym sztyletem!",
        author=mock_bot_user,
        channel=stol
    ))

    # AI generates attack buttons
    mock_gemini.queue_response(
        "Goblin szarżuje wprost na Ciebie!\n\n"
        "[ACTION_BUTTONS: ["
        "{\"label\": \"Atak Młotem (STR +3)\", \"formula\": \"1d20+3\", \"reason\": \"Atak na Goblina\", \"dc\": 12},"
        "{\"label\": \"Blok Tarczą (CON +3)\", \"formula\": \"1d20+3\", \"reason\": \"Obrona Tarczą\", \"dc\": 14}"
        "]]"
    )
    t1_text, t1_buttons = await mock_gemini.generate_narrative("Walka z goblinem")
    view_combat = NarrativeActionView(t1_buttons)
    await stol.send(t1_text, view=view_combat)

    # 1. Player clicks Atak Młotem
    attack_btn = view_combat.children[0]
    interaction_atk = MockInteraction(user=mock_player_user, channel=stol)
    await attack_btn.callback(interaction_atk)

    # 2. Goblin counterattacks and deals 9 damage -> Execute /hp -9 Thorin
    char = await get_character_from_thread(thread_thorin)
    assert char is not None
    damage_taken = 9
    char.current_hp = max(0, char.current_hp - damage_taken)

    # Update pinned sheet and log audit trail
    pinned_sheet = (await thread_thorin.pins())[0]
    updated_embed = create_character_sheet_embed(char)
    updated_embed.description = inject_json_to_text("Karta postaci", char.model_dump())
    await pinned_sheet.edit(embed=updated_embed)
    await thread_thorin.send(
        f"⚔️ **Walka**: Otrzymano {damage_taken} obrażeń od Goblina. "
        f"Aktualne HP: {char.current_hp}/{char.max_hp} `[███████░░░]`"
    )

    # 3. Verify character state in forum
    reloaded_char = await get_character_from_thread(thread_thorin)
    assert reloaded_char.current_hp == 19
    assert reloaded_char.max_hp == 28

    # 4. Next DM turn picks up combat events and damaged status
    stol.messages.append(MockMessage(
        content="Goblin drasnął mnie sztyletem, ale kontratakuję! @Mistrz Gry",
        author=mock_player_user,
        channel=stol
    ))
    combat_events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    assert "rzuca: Atak na Goblina" in combat_events
    assert "Goblin drasnął mnie" in combat_events


# ============================================================================
# Scenario 4: Long Inactive Session Resume (24h+ Thread Unarchive)
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_4_long_inactive_session_resume_unarchive(
    populated_campaign: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser,
    mock_gemini: MockGeminiClient
):
    """Scenario 4: Session paused for 48h; Discord archives forum threads in #karty-postaci.
    On session resume, bot automatically detects sleeping threads, wakes them up,
    mutates inventory, and resumes full DM interaction cycle without data loss.
    """
    forum_karty = next(f for f in populated_campaign.forums if f.name == "karty-postaci")
    stol = next(c for c in populated_campaign.text_channels if c.name == "stol-gry")

    # Simulate 48h passing: all character threads become archived
    for thread in forum_karty.all_threads:
        await thread.edit(archived=True)

    assert len(forum_karty.threads) == 0  # 0 active threads

    # Player resumes session and types on table
    stol.messages.append(MockMessage(
        content="Wracamy do gry po tygodniu przerwy! Sprawdzam ekwipunek i zapalam pochodnię. @Mistrz Gry",
        author=mock_player_user,
        channel=stol
    ))

    # Bot wakes up sleeping threads during state fetch
    active_characters = []
    async for archived_thread in forum_karty.archived_threads():
        await archived_thread.edit(archived=False)
        char = await get_character_from_thread(archived_thread)
        if char:
            active_characters.append(char)

    assert len(forum_karty.threads) == 2
    assert len(active_characters) == 2

    # Player uses a potion -> /item remove
    thorin_thread = forum_karty.threads[0]
    char_thorin = await get_character_from_thread(thorin_thread)
    assert char_thorin is not None
    
    char_thorin.inventory = [i for i in char_thorin.inventory if "Mikstura leczenia" not in i.name]
    char_thorin.current_hp = min(char_thorin.max_hp, char_thorin.current_hp + 10)

    pinned = (await thorin_thread.pins())[0]
    updated_embed = create_character_sheet_embed(char_thorin)
    updated_embed.description = inject_json_to_text("Karta postaci", char_thorin.model_dump())
    await pinned.edit(embed=updated_embed)
    await thorin_thread.send(f"🧪 Użyto Mikstury Leczenia (+10 HP). Stan: {char_thorin.current_hp}/{char_thorin.max_hp}")

    # Verify inventory updated
    verified_char = await get_character_from_thread(thorin_thread)
    assert not any("Mikstura leczenia" in i.name for i in verified_char.inventory)
    assert thorin_thread.archived is False


# ============================================================================
# Scenario 5: Multi-Quest Progression with Long DM Storytelling (>2000 chars)
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_5_quest_progression_and_long_dm_storytelling(
    populated_campaign: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser,
    mock_gemini: MockGeminiClient
):
    """Scenario 5: Players complete a major quest, journal updates to completed,
    and Gemini responds with a 3500+ char epic victory narrative split into
    sequential messages without HTTP 400 Bad Request, ending with action buttons.
    """
    ch_dziennik = next(c for c in populated_campaign.text_channels if c.name == "dziennik-zadan")
    stol = next(c for c in populated_campaign.text_channels if c.name == "stol-gry")

    # 1. Complete quest in journal
    pinned_quest_msg = (await ch_dziennik.pins())[0]
    quest_data = extract_json_from_message(pinned_quest_msg.embeds[0].description)
    quest = QuestModel(**quest_data["quests"][0])

    for obj in quest.objectives:
        obj.is_completed = True
    quest.status = "completed"

    updated_board = inject_json_to_text("📜 **DZIENNIK ZADAŃ (Zaktualizowany)**", {"quests": [quest.model_dump()]})
    await pinned_quest_msg.edit(embed=MockEmbed(title="📜 Dziennik Zadań", description=updated_board, color=discord.Color.green()))

    # 2. Player announces quest victory in table chat
    stol.messages.append(MockMessage(content="Wódz goblinów pokonany! Kopalnia jest bezpieczna! @Mistrz Gry", author=mock_player_user, channel=stol))

    # 3. Gemini crafts an expansive, epic victory monologue (3500+ chars)
    epic_p1 = "Rozdział I: Zwycięstwo w Ciemności.\n" + ("Głuche echo ostatnich ciosów powoli cichnie w korytarzach kopalni srebra. " * 30)
    epic_p2 = "Rozdział II: Odkrycie Dawnej Chwały.\n" + ("Promienie wschodzącego słońca przedzierają się przez szczeliny w sklepieniu, oświetlając zapomniane krasnoludzkie inskrypcje. " * 30)
    epic_p3 = "Rozdział III: Skarbiec Przodków.\n" + ("Przed wami stoi potężna, okuta mithrilem skrzynia wodza goblinów. " * 25)

    full_epic_narrative = (
        f"{epic_p1}\n\n{epic_p2}\n\n{epic_p3}\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Otwórz Skarbiec (Zwinność DEX +2)\", \"formula\": \"1d20+2\", \"reason\": \"Przeszukanie Skarbca\", \"dc\": 10}]]"
    )
    mock_gemini.queue_response(full_epic_narrative)

    # 4. Generate narrative and extract action buttons
    narrative_text, action_buttons = await mock_gemini.generate_narrative("Zwycięstwo nad bossem goblinów")
    assert len(narrative_text) > 3000

    # 5. Smart paragraph splitter divides into safe chunks (<1900 chars)
    chunks = split_long_message(narrative_text, limit=1900)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 1900
        assert "[ACTION_BUTTONS:" not in c

    # 6. Bot sequentially sends chunks, attaching NarrativeActionView only to the final message
    sent_bot_messages = []
    for i, chunk in enumerate(chunks):
        if i == len(chunks) - 1:
            view = NarrativeActionView(action_buttons)
            msg = await stol.send(chunk, view=view)
        else:
            msg = await stol.send(chunk)
        sent_bot_messages.append(msg)

    assert len(sent_bot_messages) == len(chunks)

    # 7. Player clicks the loot treasure button
    loot_btn = view.children[0]
    interaction_loot = MockInteraction(user=mock_player_user, channel=stol)
    await loot_btn.callback(interaction_loot)

    assert interaction_loot.response.is_done() is True
    loot_embed = interaction_loot.response.sent_messages[0].embeds[0]
    assert "Przeszukanie Skarbca" in (loot_embed.title or "")
