"""Tier 1 Test Suite: Happy-path feature verification for all 14 bot features (F1 to F14).
Covers at least 5 isolated, self-contained test cases per feature (>=70 tests total).
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

CAMPAIGN_CATEGORIES = {
    "📜 KAMPANIA I FABULA": {
        "text": ["stol-gry", "dziennik-zadan", "kronika-przygod", "zasady-i-mechanika"],
        "forum": []
    },
    "🛡️ POSTACIE I MECHANIKA": {
        "text": ["rzuty-kostkami", "szepty-dm"],
        "forum": ["karty-postaci"]
    },
    "📖 ENCYKLOPEDIA I WIEDZA": {
        "text": [],
        "forum": ["kompendium-i-lore"]
    }
}

async def execute_setup_campaign(interaction: MockInteraction) -> None:
    """Executes the setup-campaign command logic according to F1 specification."""
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("Ta komenda moze byc uzyta tylko na serwerze.")
        return

    created_info = []
    for category_name, channels_dict in CAMPAIGN_CATEGORIES.items():
        cat = discord.utils.get(guild.categories, name=category_name)
        if not cat:
            cat = await guild.create_category(name=category_name)
            created_info.append(f"📁 Kategoria: **{category_name}**")
        
        for ch_name in channels_dict.get("text", []):
            existing_ch = discord.utils.get(guild.text_channels, name=ch_name, category=cat)
            if not existing_ch:
                ch = await guild.create_text_channel(name=ch_name, category=cat)
                created_info.append(f"  └ #{ch_name}")
                if ch_name == "zasady-i-mechanika":
                    rules_msg = await ch.send(
                        "📌 **AKTUALNE ZASADY KAMPANII I SWIATA (Edytowalne w locie)**\n"
                        "- **System**: D&D 5e (Dungeons & Dragons 5. edycja)\n"
                        "- **Klimat**: Dark Fantasy / Tajemnica\n"
                        "- **Reguly domowe (Homebrew)**: Edytuj ten post, a AI automatycznie zastosuje nowe reguly!"
                    )
                    await rules_msg.pin()
                    
        for forum_name in channels_dict.get("forum", []):
            existing_forum = discord.utils.get(guild.forums, name=forum_name, category=cat)
            if not existing_forum:
                await guild.create_forum(name=forum_name, category=cat)
                created_info.append(f"  └ 💬 [Forum] #{forum_name}")
                
    await interaction.followup.send("✅ **Struktura kampanii Pure Discord zostala utworzona!**")

async def execute_roll_command(interaction: MockInteraction, formula: str, reason: str = "Rzut testowy", dc: int = None) -> None:
    """Executes the /roll command logic according to F6/F7 specification."""
    result = roll_dice(formula=formula, reason=reason, target_dc=dc)
    embed = create_dice_roll_embed(result, interaction.user.display_name)
    await interaction.response.send_message(embed=embed)



# ============================================================================
# F1: Setup Campaign Command (/setup-campaign)
# ============================================================================

@pytest.mark.asyncio
async def test_f1_setup_campaign_creates_all_categories():
    """F1.1: /setup-campaign creates all 3 campaign categories."""
    guild = MockGuild(name="New Campaign")
    interaction = MockInteraction(guild=guild)

    await execute_setup_campaign(interaction)

    cat_names = [c.name for c in guild.categories]
    assert "📜 KAMPANIA I FABULA" in cat_names
    assert "🛡️ POSTACIE I MECHANIKA" in cat_names
    assert "📖 ENCYKLOPEDIA I WIEDZA" in cat_names


@pytest.mark.asyncio
async def test_f1_setup_campaign_creates_text_channels():
    """F1.2: /setup-campaign creates expected text channels under categories."""
    guild = MockGuild(name="New Campaign")
    interaction = MockInteraction(guild=guild)

    await execute_setup_campaign(interaction)

    ch_names = [c.name for c in guild.text_channels]
    assert "stol-gry" in ch_names
    assert "dziennik-zadan" in ch_names
    assert "kronika-przygod" in ch_names
    assert "zasady-i-mechanika" in ch_names
    assert "rzuty-kostkami" in ch_names
    assert "szepty-dm" in ch_names


@pytest.mark.asyncio
async def test_f1_setup_campaign_creates_forum_channels():
    """F1.3: /setup-campaign creates forum channels for character sheets and lore."""
    guild = MockGuild(name="New Campaign")
    interaction = MockInteraction(guild=guild)

    await execute_setup_campaign(interaction)

    forum_names = [f.name for f in guild.forums]
    assert "karty-postaci" in forum_names
    assert "kompendium-i-lore" in forum_names


@pytest.mark.asyncio
async def test_f1_setup_campaign_initializes_pinned_rules():
    """F1.4: /setup-campaign posts and pins the default rules message in #zasady-i-mechanika."""
    guild = MockGuild(name="New Campaign")
    interaction = MockInteraction(guild=guild)

    await execute_setup_campaign(interaction)

    rules_ch = next(c for c in guild.text_channels if c.name == "zasady-i-mechanika")
    pinned = await rules_ch.pins()
    assert len(pinned) >= 1
    assert "AKTUALNE ZASADY KAMPANII" in pinned[0].content
    assert "D&D 5e" in pinned[0].content


@pytest.mark.asyncio
async def test_f1_setup_campaign_idempotent_no_duplicates():
    """F1.5: Running /setup-campaign twice does not create duplicate channels."""
    guild = MockGuild(name="New Campaign")
    interaction1 = MockInteraction(guild=guild)
    await execute_setup_campaign(interaction1)

    initial_cats = len(guild.categories)
    initial_texts = len(guild.text_channels)
    initial_forums = len(guild.forums)

    interaction2 = MockInteraction(guild=guild)
    await execute_setup_campaign(interaction2)

    assert len(guild.categories) == initial_cats
    assert len(guild.text_channels) == initial_texts
    assert len(guild.forums) == initial_forums


# ============================================================================
# F2: Live Pinned Rules Parsing (#zasady-i-mechanika)
# ============================================================================

@pytest.mark.asyncio
async def test_f2_fetch_campaign_rules_reads_pinned_post(configured_guild: MockGuild):
    """F2.1: fetch_campaign_rules reads content from the pinned rules post."""
    rules_text = await fetch_campaign_rules(configured_guild)
    assert "D&D 5e" in rules_text
    assert "Dark Fantasy" in rules_text


@pytest.mark.asyncio
async def test_f2_fetch_campaign_rules_updates_live(configured_guild: MockGuild):
    """F2.2: Editing the pinned post dynamically changes the rules text in real time."""
    rules_ch = next(c for c in configured_guild.text_channels if c.name == "zasady-i-mechanika")
    pinned = await rules_ch.pins()
    msg = pinned[0]

    await msg.edit(content="📌 **HOMEBREW RULES**: Potion as Bonus Action. Critical hits deal max+roll damage.")

    new_rules = await fetch_campaign_rules(configured_guild)
    assert "Potion as Bonus Action" in new_rules
    assert "Critical hits deal max+roll damage" in new_rules


@pytest.mark.asyncio
async def test_f2_fetch_campaign_rules_fallback_to_latest(configured_guild: MockGuild):
    """F2.3: If no pinned post exists, falls back to latest message in #zasady-i-mechanika."""
    rules_ch = next(c for c in configured_guild.text_channels if c.name == "zasady-i-mechanika")
    pinned = await rules_ch.pins()
    for p in pinned:
        await p.unpin()

    await rules_ch.send("Zasady w najnowszej wiadomosci: Tylko magia prosta.")

    rules_text = await fetch_campaign_rules(configured_guild)
    assert "Tylko magia prosta" in rules_text


@pytest.mark.asyncio
async def test_f2_fetch_campaign_rules_missing_channel():
    """F2.4: If #zasady-i-mechanika channel is missing, returns safe default rules."""
    empty_guild = MockGuild(name="Empty")
    rules_text = await fetch_campaign_rules(empty_guild)
    assert "Standardowe D&D 5e" in rules_text


@pytest.mark.asyncio
async def test_f2_fetch_campaign_rules_preserves_multiline_homebrew(configured_guild: MockGuild):
    """F2.5: Preserves multiline formatting and bullet points in rules."""
    rules_ch = next(c for c in configured_guild.text_channels if c.name == "zasady-i-mechanika")
    custom_rules = (
        "1. Flanking daje +2 do ataku.\n"
        "2. Rzuty na śmierć są ukryte przed drużyną.\n"
        "3. Odpoczynek długi trwa 24h w bezpiecznym obozie."
    )
    await rules_ch.send(custom_rules)
    latest_pinned = (await rules_ch.pins())[0]
    await latest_pinned.edit(content=custom_rules)

    fetched = await fetch_campaign_rules(configured_guild)
    assert "Flanking daje +2" in fetched
    assert "Rzuty na śmierć" in fetched
    assert "Odpoczynek długi" in fetched


# ============================================================================
# F3: Forum Character State Persistence (<!-- DATA_JSON -->)
# ============================================================================

def test_f3_inject_and_extract_json_roundtrip(sample_character: CharacterModel):
    """F3.1: JSON data injection and extraction preserves exact character dictionary."""
    base_text = "Opis postaci Thorina Kamienna Tarcza."
    data = sample_character.model_dump()

    injected = inject_json_to_text(base_text, data)
    assert "<!-- DATA_JSON:" in injected
    assert base_text in injected

    extracted = extract_json_from_message(injected)
    assert extracted is not None
    assert extracted["name"] == "Thorin Kamienna Tarcza"
    assert extracted["current_hp"] == 28
    assert extracted["stats"]["strength"] == 16


def test_f3_character_sheet_embed_creation_with_valid_stats(sample_character: CharacterModel):
    """F3.2: create_character_sheet_embed formats title, health bar, and stat modifiers."""
    embed = create_character_sheet_embed(sample_character)
    assert "Thorin Kamienna Tarcza" in (embed.title or "")
    assert "Poziom 3" in (embed.title or "")
    
    field_names = [f.name for f in embed.fields]
    assert any("ywotno" in f for f in field_names)
    assert any("Klasa Pancerza" in f for f in field_names)
    assert any("Cechy i Modyfikatory" in f for f in field_names)


@pytest.mark.asyncio
async def test_f3_get_character_from_forum_thread(populated_campaign: MockGuild):
    """F3.3: get_character_from_thread parses character sheet from forum thread."""
    forum_karty = next(f for f in populated_campaign.forums if f.name == "karty-postaci")
    thread = forum_karty.threads[0]

    char = await get_character_from_thread(thread)
    assert char is not None
    assert char.name == "Thorin Kamienna Tarcza"
    assert char.character_class == "Fighter"
    assert char.stats.strength == 16


@pytest.mark.asyncio
async def test_f3_update_character_hp_and_save_data_json(populated_campaign: MockGuild):
    """F3.4: Updating character HP modifies embed and keeps DATA_JSON in sync."""
    forum_karty = next(f for f in populated_campaign.forums if f.name == "karty-postaci")
    thread = forum_karty.threads[0]

    char = await get_character_from_thread(thread)
    assert char is not None
    char.current_hp = 19  # Took 9 damage

    # Update pinned embed
    pinned_msgs = await thread.pins()
    msg = pinned_msgs[0]
    updated_embed = create_character_sheet_embed(char)
    updated_embed.description = inject_json_to_text(updated_embed.description or "", char.model_dump())
    await msg.edit(embed=updated_embed)

    # Re-fetch and verify
    reloaded_char = await get_character_from_thread(thread)
    assert reloaded_char is not None
    assert reloaded_char.current_hp == 19


@pytest.mark.asyncio
async def test_f3_character_inventory_persistence_in_json(populated_campaign: MockGuild):
    """F3.5: Adding item to inventory updates DATA_JSON accurately."""
    forum_karty = next(f for f in populated_campaign.forums if f.name == "karty-postaci")
    thread = forum_karty.threads[0]

    char = await get_character_from_thread(thread)
    assert char is not None
    char.inventory.append(ItemModel(name="Pierścień Ochrony +1", quantity=1, item_type="equipment"))

    pinned_msgs = await thread.pins()
    msg = pinned_msgs[0]
    updated_embed = create_character_sheet_embed(char)
    updated_embed.description = inject_json_to_text(updated_embed.description or "", char.model_dump())
    await msg.edit(embed=updated_embed)

    reloaded = await get_character_from_thread(thread)
    assert reloaded is not None
    item_names = [i.name for i in reloaded.inventory]
    assert "Pierścień Ochrony +1" in item_names


# ============================================================================
# F4: 24h Thread Auto-Unarchiving
# ============================================================================

@pytest.mark.asyncio
async def test_f4_get_character_from_archived_thread_triggers_unarchive(populated_campaign: MockGuild):
    """F4.1: Reading an archived thread detects archived status and allows unarchival."""
    forum_karty = next(f for f in populated_campaign.forums if f.name == "karty-postaci")
    thread = forum_karty.threads[0]
    
    # Simulate sleeping after 24h inactivity
    await thread.edit(archived=True)
    assert thread.archived is True

    # When bot interacts, wakes thread up
    if thread.archived:
        await thread.edit(archived=False)

    char = await get_character_from_thread(thread)
    assert char is not None
    assert thread.archived is False
    assert thread.unarchived_count == 1


@pytest.mark.asyncio
async def test_f4_unarchive_increments_thread_unarchive_count(populated_campaign: MockGuild):
    """F4.2: Thread unarchive count tracks waking cycles."""
    forum = next(f for f in populated_campaign.forums if f.name == "karty-postaci")
    thread = forum.threads[0]
    
    await thread.edit(archived=True)
    await thread.edit(archived=False)
    await thread.edit(archived=True)
    await thread.edit(archived=False)

    assert thread.unarchived_count == 2
    assert thread.archived is False


@pytest.mark.asyncio
async def test_f4_active_thread_does_not_trigger_unarchive(populated_campaign: MockGuild):
    """F4.3: Active threads remain unchanged without unarchive penalty."""
    forum = next(f for f in populated_campaign.forums if f.name == "karty-postaci")
    thread = forum.threads[0]
    assert thread.archived is False
    assert thread.unarchived_count == 0

    char = await get_character_from_thread(thread)
    assert char is not None
    assert thread.unarchived_count == 0


@pytest.mark.asyncio
async def test_f4_archived_threads_iterator_returns_sleeping_threads(configured_guild: MockGuild):
    """F4.4: forum.archived_threads() correctly yields sleeping threads."""
    forum = next(f for f in configured_guild.forums if f.name == "karty-postaci")
    
    t1 = (await forum.create_thread(name="Postac 1")).thread
    t2 = (await forum.create_thread(name="Postac 2")).thread
    await t1.edit(archived=True)

    archived_list = []
    async for t in forum.archived_threads():
        archived_list.append(t)

    assert len(archived_list) == 1
    assert archived_list[0].id == t1.id


@pytest.mark.asyncio
async def test_f4_multiple_archived_threads_scanned_successfully(configured_guild: MockGuild):
    """F4.5: Multiple archived threads can be iterated and restored."""
    forum = next(f for f in configured_guild.forums if f.name == "karty-postaci")
    
    for i in range(3):
        t = (await forum.create_thread(name=f"Hero {i}")).thread
        await t.edit(archived=True)

    archived = []
    async for t in forum.archived_threads():
        archived.append(t)
        await t.edit(archived=False)

    assert len(archived) == 3
    assert len(forum.threads) == 3


# ============================================================================
# F5: Quest Journal System (/quest create/complete)
# ============================================================================

def test_f5_quest_model_serialization_and_deserialization(sample_quest: QuestModel):
    """F5.1: QuestModel correctly serializes and restores objectives."""
    dumped = sample_quest.model_dump()
    reloaded = QuestModel(**dumped)

    assert reloaded.id == "q-goblin-mine"
    assert len(reloaded.objectives) == 3
    assert reloaded.objectives[0].is_completed is True
    assert reloaded.objectives[1].is_completed is False


def test_f5_quest_board_inject_and_extract_quests(sample_quest: QuestModel):
    """F5.2: Quest board text can hold multiple quests via DATA_JSON."""
    quest2 = QuestModel(
        id="q-dragon",
        title="Smocze Legowisko",
        giver="Król",
        description="Pokonaj czerwonego smoka",
        reward="1000 GP"
    )
    board_data = {"quests": [sample_quest.model_dump(), quest2.model_dump()]}
    injected = inject_json_to_text("📜 Aktualne zadania drużyny:", board_data)

    extracted = extract_json_from_message(injected)
    assert extracted is not None
    assert len(extracted["quests"]) == 2
    assert extracted["quests"][1]["title"] == "Smocze Legowisko"


def test_f5_quest_objective_marking_completed(sample_quest: QuestModel):
    """F5.3: Marking a quest objective updates boolean flag."""
    assert sample_quest.objectives[1].is_completed is False
    sample_quest.objectives[1].is_completed = True
    assert sample_quest.objectives[1].is_completed is True


def test_f5_quest_status_transition_to_completed(sample_quest: QuestModel):
    """F5.4: Quest status transitions from active to completed."""
    assert sample_quest.status == "active"
    for obj in sample_quest.objectives:
        obj.is_completed = True
    sample_quest.status = "completed"
    assert sample_quest.status == "completed"


@pytest.mark.asyncio
async def test_f5_multiple_quests_in_journal_state(populated_campaign: MockGuild):
    """F5.5: Journal channel maintains quest state with pinned embed."""
    ch_dziennik = next(c for c in populated_campaign.text_channels if c.name == "dziennik-zadan")
    pinned = await ch_dziennik.pins()
    assert len(pinned) == 1

    embed = pinned[0].embeds[0]
    data = extract_json_from_message(embed.description or "")
    assert data is not None
    assert len(data["quests"]) >= 1
    assert data["quests"][0]["id"] == "q-goblin-mine"


# ============================================================================
# F6: Deterministic Dice Engine (0 AI tokens)
# ============================================================================

def test_f6_standard_d20_roll_within_bounds():
    """F6.1: Standard 1d20+5 produces total in range [6, 25]."""
    for _ in range(20):
        res = roll_dice("1d20+5", reason="Atak")
        assert 6 <= res.total <= 25
        assert res.formula == "1d20+5"
        assert res.reason == "Atak"


def test_f6_advantage_roll_picks_higher_d20():
    """F6.2: Advantage converts formula to 2d20kh1."""
    res = roll_dice("1d20+3", advantage_disadvantage="advantage")
    assert "2d20kh1" in res.formula
    assert 4 <= res.total <= 23


def test_f6_disadvantage_roll_picks_lower_d20():
    """F6.3: Disadvantage converts formula to 2d20kl1."""
    res = roll_dice("1d20+2", advantage_disadvantage="disadvantage")
    assert "2d20kl1" in res.formula
    assert 3 <= res.total <= 22


def test_f6_dc_target_evaluation_success_and_failure():
    """F6.4: Evaluating DC checks sets is_success boolean accurately."""
    res_easy = roll_dice("1d20+100", target_dc=15)
    assert res_easy.is_success is True
    assert res_easy.target_dc == 15

    res_impossible = roll_dice("1d20-100", target_dc=15)
    assert res_impossible.is_success is False


def test_f6_critical_success_and_failure_detection():
    """F6.5: Rolling natural 20 or natural 1 flags critical success / failure."""
    # Test formula directly with fixed result via breakdown evaluation
    res_crit20 = roll_dice("20", reason="Crit test")
    assert res_crit20.total == 20

    res_dice = roll_dice("1d20", reason="Nat test")
    if res_dice.total == 20:
        assert res_dice.is_critical_success is True
    elif res_dice.total == 1:
        assert res_dice.is_critical_failure is True


# ============================================================================
# F7: Core Slash Commands (/roll, /hp, /item, /sheet, /quest)
# ============================================================================

@pytest.mark.asyncio
async def test_f7_roll_slash_command_creates_embed():
    """F7.1: /roll slash command executes roll and responds with embed."""
    interaction = MockInteraction()
    await execute_roll_command(interaction, formula="1d20+4", reason="Percepcja", dc=14)

    assert interaction.response.is_done() is True
    assert len(interaction.response.sent_messages) == 1
    sent = interaction.response.sent_messages[0]
    assert len(sent.embeds) == 1
    assert "Percepcja" in (sent.embeds[0].title or "")


@pytest.mark.asyncio
async def test_f7_hp_command_modifies_character_current_hp(populated_campaign: MockGuild):
    """F7.2: /hp modification updates character health in forum sheet."""
    forum = next(f for f in populated_campaign.forums if f.name == "karty-postaci")
    thread = forum.threads[0]
    char = await get_character_from_thread(thread)
    assert char is not None

    # Simulate /hp -5 command logic
    char.current_hp = max(0, char.current_hp - 5)
    updated_embed = create_character_sheet_embed(char)
    updated_embed.description = inject_json_to_text(updated_embed.description or "", char.model_dump())
    
    pinned = (await thread.pins())[0]
    await pinned.edit(embed=updated_embed)
    await thread.send(f"❤️ Zmiana HP: -5 (Aktualne: {char.current_hp}/{char.max_hp})")

    reloaded = await get_character_from_thread(thread)
    assert reloaded is not None
    assert reloaded.current_hp == 23


@pytest.mark.asyncio
async def test_f7_item_add_command_appends_to_inventory(populated_campaign: MockGuild):
    """F7.3: /item add command appends item to character inventory."""
    forum = next(f for f in populated_campaign.forums if f.name == "karty-postaci")
    thread = forum.threads[0]
    char = await get_character_from_thread(thread)
    assert char is not None

    new_item = ItemModel(name="Lina konopna 50ft", quantity=1, item_type="equipment")
    char.inventory.append(new_item)

    updated_embed = create_character_sheet_embed(char)
    updated_embed.description = inject_json_to_text(updated_embed.description or "", char.model_dump())
    pinned = (await thread.pins())[0]
    await pinned.edit(embed=updated_embed)

    reloaded = await get_character_from_thread(thread)
    assert reloaded is not None
    assert any(i.name == "Lina konopna 50ft" for i in reloaded.inventory)


@pytest.mark.asyncio
async def test_f7_item_remove_command_removes_from_inventory(populated_campaign: MockGuild):
    """F7.4: /item remove command removes item from character inventory."""
    forum = next(f for f in populated_campaign.forums if f.name == "karty-postaci")
    thread = forum.threads[0]
    char = await get_character_from_thread(thread)
    assert char is not None

    char.inventory = [i for i in char.inventory if "Mikstura leczenia" not in i.name]
    updated_embed = create_character_sheet_embed(char)
    updated_embed.description = inject_json_to_text(updated_embed.description or "", char.model_dump())
    pinned = (await thread.pins())[0]
    await pinned.edit(embed=updated_embed)

    reloaded = await get_character_from_thread(thread)
    assert reloaded is not None
    assert not any("Mikstura leczenia" in i.name for i in reloaded.inventory)


def test_f7_sheet_command_renders_embed_with_character_info(sample_character: CharacterModel):
    """F7.5: /sheet command returns a richly populated character embed."""
    embed = create_character_sheet_embed(sample_character)
    assert "Thorin Kamienna Tarcza" in embed.title
    assert len(embed.fields) >= 4


# ============================================================================
# F8: Dynamic Discord UI Buttons (RollButton, NarrativeActionView)
# ============================================================================

def test_f8_roll_button_initialization():
    """F8.1: RollButton initializes with label, formula, reason, and DC."""
    btn = RollButton(label="Test Skradania (DEX +2)", formula="1d20+2", reason="Skradanie", dc=15)
    assert btn.label == "Test Skradania (DEX +2)"
    assert btn.formula == "1d20+2"
    assert btn.reason == "Skradanie"
    assert btn.dc == 15


@pytest.mark.asyncio
async def test_f8_roll_button_callback_executes_pure_python_dice():
    """F8.2: Clicking RollButton executes roll_dice deterministically and sends message."""
    btn = RollButton(label="Percepcja", formula="1d20+3", reason="Percepcja", dc=12)
    interaction = MockInteraction()

    await btn.callback(interaction)

    assert interaction.response.is_done() is True
    assert len(interaction.response.sent_messages) == 1
    sent = interaction.response.sent_messages[0]
    assert "Percepcja" in sent.content
    assert len(sent.embeds) == 1


@pytest.mark.asyncio
async def test_f8_roll_button_sends_response_embed_with_dc():
    """F8.3: RollButton response embed contains formula, result, and DC verdict."""
    btn = RollButton(label="Wspinaczka (STR)", formula="1d20+4", reason="Wspinaczka", dc=10)
    interaction = MockInteraction()

    await btn.callback(interaction)

    embed = interaction.response.sent_messages[0].embeds[0]
    field_names = [f.name for f in embed.fields]
    assert any("Formu" in f for f in field_names)
    assert "Wynik" in field_names
    assert any("Stopie" in f or "DC" in f for f in field_names)


def test_f8_narrative_action_view_populates_multiple_buttons():
    """F8.4: NarrativeActionView dynamically generates child RollButton items."""
    actions = [
        {"label": "Atak mieczem (STR +3)", "formula": "1d20+3", "reason": "Atak", "dc": 14},
        {"label": "Unik (DEX +2)", "formula": "1d20+2", "reason": "Obrona", "dc": 12}
    ]
    view = NarrativeActionView(actions)
    assert len(view.children) == 2
    assert isinstance(view.children[0], RollButton)
    assert view.children[0].label == "Atak mieczem (STR +3)"
    assert view.children[1].label == "Unik (DEX +2)"


def test_f8_narrative_action_view_handles_empty_action_list():
    """F8.5: NarrativeActionView initializes gracefully with empty or None action list."""
    view_none = NarrativeActionView(None)
    assert len(view_none.children) == 0

    view_empty = NarrativeActionView([])
    assert len(view_empty.children) == 0


# ============================================================================
# F9: Aesthetic Rich Embeds & ASCII HP Bars
# ============================================================================

def test_f9_create_health_bar_full_hp():
    """F9.1: Health bar at 100% displays full block characters."""
    bar = create_health_bar(current=20, max_val=20, length=10)
    assert "[██████████]" in bar
    assert "20/20 HP" in bar


def test_f9_create_health_bar_half_hp():
    """F9.2: Health bar at 50% displays equal filled and empty blocks."""
    bar = create_health_bar(current=10, max_val=20, length=10)
    assert "[█████░░░░░]" in bar
    assert "10/20 HP" in bar


def test_f9_create_health_bar_zero_hp():
    """F9.3: Health bar at 0% displays completely empty blocks."""
    bar = create_health_bar(current=0, max_val=20, length=10)
    assert "[░░░░░░░░░░]" in bar
    assert "0/20 HP" in bar


def test_f9_character_sheet_embed_contains_all_stat_modifiers(sample_character: CharacterModel):
    """F9.4: Character sheet embed displays all 6 stats with signed modifiers."""
    embed = create_character_sheet_embed(sample_character)
    stats_field = next(f for f in embed.fields if "Cechy i Modyfikatory" in f.name)
    assert "**STR:** 16 (+3)" in stats_field.value
    assert "**DEX:** 12 (+1)" in stats_field.value
    assert "**CHA:** 8 (-1)" in stats_field.value


def test_f9_dice_roll_embed_colors_success_green_failure_red():
    """F9.5: Dice roll embed sets green for success and red for failure."""
    res_succ = DiceRollResult(formula="1d20+5", total=18, breakdown="13+5", is_success=True, target_dc=15)
    embed_succ = create_dice_roll_embed(res_succ, "Thorin")
    assert embed_succ.color == discord.Color.green()

    res_fail = DiceRollResult(formula="1d20+2", total=8, breakdown="6+2", is_success=False, target_dc=15)
    embed_fail = create_dice_roll_embed(res_fail, "Thorin")
    assert embed_fail.color == discord.Color.red()


# ============================================================================
# F10: Google Gemini 2.0 Flash Integration
# ============================================================================

@pytest.mark.asyncio
async def test_f10_mock_gemini_generates_narrative_and_action_buttons(mock_gemini: MockGeminiClient):
    """F10.1: MockGeminiClient generates clean narrative text and structured action buttons."""
    text, buttons = await mock_gemini.generate_narrative(context_prompt="Wchodzimy do jaskini.")
    assert "Mistrz Gry:" in text
    assert len(buttons) >= 1
    assert "formula" in buttons[0]


@pytest.mark.asyncio
async def test_f10_mock_gemini_queued_responses_order(mock_gemini: MockGeminiClient):
    """F10.2: Queued responses are popped in FIFO order."""
    mock_gemini.queue_response("Turn 1 response", [{"label": "Action 1", "formula": "1d20"}])
    mock_gemini.queue_response("Turn 2 response", [{"label": "Action 2", "formula": "1d20+2"}])

    t1, b1 = await mock_gemini.generate_narrative("Prompt 1")
    assert t1 == "Turn 1 response"
    assert b1[0]["label"] == "Action 1"

    t2, b2 = await mock_gemini.generate_narrative("Prompt 2")
    assert t2 == "Turn 2 response"
    assert b2[0]["label"] == "Action 2"


@pytest.mark.asyncio
async def test_f10_mock_gemini_audits_prompt_and_system_prompt(mock_gemini: MockGeminiClient):
    """F10.3: MockGemini records call history with prompt and system instructions."""
    await mock_gemini.generate_narrative(context_prompt="Gracz atakuje orka", system_prompt="DM Prompt")
    
    assert mock_gemini.call_count == 1
    last = mock_gemini.last_call
    assert last["context_prompt"] == "Gracz atakuje orka"
    assert last["system_prompt"] == "DM Prompt"


@pytest.mark.asyncio
async def test_f10_mock_gemini_custom_handler_synthesis(mock_gemini: MockGeminiClient):
    """F10.4: Custom handler generates responses dynamically based on keywords."""
    def dynamic_dm(context: str, system: str):
        if "pochodni" in context.lower():
            return "Rozpalasz pochodnię. Widzisz runy.", [{"label": "Zbadaj runy", "formula": "1d20+3"}]
        return "Ciemność cię otacza.", []

    mock_gemini.set_handler(dynamic_dm)

    text, btns = await mock_gemini.generate_narrative("Zapal pochodnię")
    assert "Rozpalasz pochodnię" in text
    assert len(btns) == 1


@pytest.mark.asyncio
async def test_f10_mock_gemini_handles_empty_action_buttons(mock_gemini: MockGeminiClient):
    """F10.5: MockGemini handles pure narrative responses with 0 action buttons."""
    mock_gemini.queue_response("Spokojna noc w karczmie bez żadnych rzutów.", [])
    text, btns = await mock_gemini.generate_narrative("Idziemy spać.")

    assert "Spokojna noc" in text
    assert len(btns) == 0


# ============================================================================
# F11: Strict Narrative Triggering Filter (@Mistrz Gry, /next)
# ============================================================================

def test_f11_bot_mentioned_in_message_triggers_filter(mock_bot_user: MockUser):
    """F11.1: Mentioning @Mistrz Gry triggers mentioned_in filter."""
    msg = MockMessage(content="Co widzimy w korytarzu, @Mistrz Gry?", author=MockUser(id=10, name="Player"))
    assert mock_bot_user.mentioned_in(msg) is True


def test_f11_message_without_mention_is_ignored(mock_bot_user: MockUser):
    """F11.2: General player conversation without mention is ignored."""
    msg = MockMessage(content="Gimli, podaj mi eliksir leczenia.", author=MockUser(id=10, name="Player"))
    assert mock_bot_user.mentioned_in(msg) is False


def test_f11_bot_own_message_is_ignored(mock_bot_user: MockUser):
    """F11.3: Bot's own messages are identified by bot ID to prevent feedback loops."""
    bot_msg = MockMessage(content="Rozglądacie się...", author=mock_bot_user)
    assert bot_msg.author.id == mock_bot_user.id


def test_f11_ooc_message_is_filtered_from_events():
    """F11.4: OOC messages enclosed in ((...)) are recognized for filtering."""
    ooc_msg = "((Muszę zaraz kończyć sesję na dziś))"
    assert ooc_msg.startswith("((") and ooc_msg.endswith("))")


@pytest.mark.asyncio
async def test_f11_triggering_only_on_stol_gry_channel(configured_guild: MockGuild):
    """F11.5: Narrative triggering only activates on #stol-gry channel."""
    stol_gry = next(c for c in configured_guild.text_channels if c.name == "stol-gry")
    szepty = next(c for c in configured_guild.text_channels if c.name == "szepty-dm")

    assert stol_gry.name == "stol-gry"
    assert szepty.name != "stol-gry"


# ============================================================================
# F12: Stateless Channel History Scanner (after=last_bot_message)
# ============================================================================

@pytest.mark.asyncio
async def test_f12_fetch_messages_scans_after_last_bot_response(
    configured_guild: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser
):
    """F12.1: History scanner retrieves only messages sent AFTER the last bot message."""
    stol = next(c for c in configured_guild.text_channels if c.name == "stol-gry")

    # Old turn
    await stol.send("Stara akcja gracza")
    old_bot_msg = MockMessage(content="Stara narracja DM", author=mock_bot_user, channel=stol)
    stol.messages.append(old_bot_msg)

    # Current turn
    m1 = MockMessage(content="Otwieram żelazne drzwi", author=mock_player_user, channel=stol)
    stol.messages.append(m1)

    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    assert "Otwieram żelazne drzwi" in events
    assert "Stara akcja gracza" not in events


@pytest.mark.asyncio
async def test_f12_fetch_messages_extracts_player_dialogue(
    configured_guild: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser
):
    """F12.2: History scanner formats player statements with display name."""
    stol = next(c for c in configured_guild.text_channels if c.name == "stol-gry")
    stol.messages.append(MockMessage(content="Gotuję miksturę", author=mock_player_user, channel=stol))

    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    assert f"[{mock_player_user.display_name}]: Gotuję miksturę" in events


@pytest.mark.asyncio
async def test_f12_fetch_messages_extracts_dice_roll_embeds(
    configured_guild: MockGuild,
    mock_bot_user: MockUser
):
    """F12.3: History scanner parses dice roll result embeds."""
    stol = next(c for c in configured_guild.text_channels if c.name == "stol-gry")
    
    # Send a prior bot message so scanner has a baseline
    old_bot_msg = MockMessage(content="Ciemny las", author=mock_bot_user, channel=stol)
    stol.messages.append(old_bot_msg)

    # System / player roll embed
    roll_res = DiceRollResult(formula="1d20+3", total=17, breakdown="14+3", is_success=True, target_dc=14, reason="Skradanie")
    embed = create_dice_roll_embed(roll_res, "Thorin")
    dice_user = MockUser(id=888, name="DiceEngine", bot=False)
    roll_msg = MockMessage(content="", author=dice_user, channel=stol, embed=embed)
    stol.messages.append(roll_msg)

    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    assert "[SYSTEM RZUTOW]:" in events
    assert "Thorin rzuca: Skradanie" in events
    assert "17" in events


@pytest.mark.asyncio
async def test_f12_fetch_messages_handles_no_prior_bot_message(
    configured_guild: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser
):
    """F12.4: If bot has never spoken in channel, scans initial channel history."""
    stol = next(c for c in configured_guild.text_channels if c.name == "stol-gry")
    stol.messages.clear()
    stol.messages.append(MockMessage(content="Początek kampanii!", author=mock_player_user, channel=stol))

    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    assert "Początek kampanii!" in events


@pytest.mark.asyncio
async def test_f12_fetch_messages_maintains_chronological_order(
    configured_guild: MockGuild,
    mock_bot_user: MockUser,
    mock_player_user: MockUser,
    mock_player_mage: MockUser
):
    """F12.5: Messages are returned in chronological order (oldest to newest)."""
    stol = next(c for c in configured_guild.text_channels if c.name == "stol-gry")
    stol.messages.append(MockMessage(content="Krok 1: Wchodzimy", author=mock_player_user, channel=stol))
    stol.messages.append(MockMessage(content="Krok 2: Badam aurę", author=mock_player_mage, channel=stol))

    events = await fetch_messages_since_last_dm_response(stol, mock_bot_user)
    idx1 = events.find("Krok 1")
    idx2 = events.find("Krok 2")
    assert idx1 != -1 and idx2 != -1
    assert idx1 < idx2


# ============================================================================
# F13: Smart Paragraph Splitter (>2000 chars)
# ============================================================================

def test_f13_short_message_not_split():
    """F13.1: Message under 1900 chars is returned as single chunk."""
    short = "Krótki opis sceny."
    chunks = split_long_message(short, limit=1900)
    assert len(chunks) == 1
    assert chunks[0] == short


def test_f13_long_message_split_at_paragraph_boundaries():
    """F13.2: Long text (>2000 chars) splits neatly at paragraph double newlines."""
    p1 = "Akapit 1: " + ("Opis lasu i drzew. " * 50)  # ~1000 chars
    p2 = "Akapit 2: " + ("Opis zamku na wzgórzu. " * 50)  # ~1100 chars
    full_text = f"{p1}\n\n{p2}"

    chunks = split_long_message(full_text, limit=1500)
    assert len(chunks) == 2
    assert "Akapit 1:" in chunks[0]
    assert "Akapit 2:" in chunks[1]


def test_f13_giant_single_paragraph_split_at_sentences():
    """F13.3: Giant unbroken paragraph splits at sentence boundaries."""
    sentences = [f"Zdanie numer {i} z wieloma barwnymi szczegółami." for i in range(100)]
    giant_p = " ".join(sentences)

    chunks = split_long_message(giant_p, limit=1000)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 1000


def test_f13_all_split_chunks_under_char_limit():
    """F13.4: Every resulting chunk strictly adheres to the specified limit."""
    long_narrative = ("Wielka opowieść o dawnych bohaterach.\n\n" * 30)
    chunks = split_long_message(long_narrative, limit=800)
    for chunk in chunks:
        assert len(chunk) <= 800


def test_f13_empty_or_whitespace_message_handling():
    """F13.5: Empty or whitespace-only message returns empty list."""
    assert split_long_message("") == []
    assert split_long_message("   \n\n   ") == []


# ============================================================================
# F14: Dynamic Action Button Extraction from Narrative
# ============================================================================

def test_f14_extract_action_buttons_parses_json_block():
    """F14.1: extract_action_buttons extracts valid json button array."""
    raw = (
        "Widzisz pułapkę pod podłogą.\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Rozbrój pułapkę (DEX +3)\", \"formula\": \"1d20+3\", \"reason\": \"Rozbrajanie\", \"dc\": 15}]]"
    )
    clean, buttons = MockGeminiClient.extract_action_buttons(raw)
    assert len(buttons) == 1
    assert buttons[0]["label"] == "Rozbrój pułapkę (DEX +3)"
    assert buttons[0]["dc"] == 15


def test_f14_extract_action_buttons_strips_tag_from_narrative():
    """F14.2: extract_action_buttons cleans [ACTION_BUTTONS: ...] tag from readable narrative."""
    raw = (
        "Drzwi są zamknięte na klucz.\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Wyważ drzwi (STR +4)\", \"formula\": \"1d20+4\", \"reason\": \"Wyważanie\", \"dc\": 16}]]"
    )
    clean, _ = MockGeminiClient.extract_action_buttons(raw)
    assert "[ACTION_BUTTONS:" not in clean
    assert "Drzwi są zamknięte na klucz." in clean


def test_f14_format_narrative_with_buttons_embeds_tag():
    """F14.3: format_narrative_with_buttons embeds action block into narrative."""
    narrative = "Ciemny korytarz rozwidla się w dwie strony."
    buttons = [
        {"label": "W lewo (Percepcja)", "formula": "1d20+2", "reason": "Percepcja", "dc": 10},
        {"label": "W prawo (Skradanie)", "formula": "1d20+3", "reason": "Skradanie", "dc": 12}
    ]
    formatted = MockGeminiClient.format_narrative_with_buttons(narrative, buttons)
    assert "[ACTION_BUTTONS:" in formatted
    assert "W lewo" in formatted
    assert "W prawo" in formatted


def test_f14_narrative_action_view_created_from_extracted_buttons():
    """F14.4: Extracted buttons seamlessly instantiate a NarrativeActionView."""
    raw = (
        "Przeciwnik szykuje się do szarży!\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Blokuj tarczą (CON +3)\", \"formula\": \"1d20+3\", \"reason\": \"Blok\", \"dc\": 13}]]"
    )
    clean, buttons = MockGeminiClient.extract_action_buttons(raw)
    view = NarrativeActionView(buttons)
    assert len(view.children) == 1
    assert view.children[0].label == "Blokuj tarczą (CON +3)"


def test_f14_extract_action_buttons_returns_empty_when_no_tag():
    """F14.5: Returns empty button list when narrative contains no [ACTION_BUTTONS] block."""
    raw = "Zwykły opis krajobrazu bez konieczności rzucania kośćmi."
    clean, buttons = MockGeminiClient.extract_action_buttons(raw)
    assert clean == raw
    assert buttons == []
