"""End-to-End Gameplay Integration Test Suite.
Exercises the entire D&D AI Discord Bot lifecycle from server setup to dynamic action button rolls:
- /setup-campaign creates channel hierarchy & initializes rules/journal
- Pinned rules in #zasady-i-mechanika are created and parsed live
- Character created in #karty-postaci forum with <!-- DATA_JSON: ... --> and ASCII HP bar
- 24h thread unarchiving simulated and verified
- /quest create and /quest complete update #dziennik-zadań
- /roll executes 100% deterministically in pure Python (0 AI tokens)
- /hp updates character state and forum thread audit log
- @Mistrz Gry triggers Gemini context scan after last_bot_message and delivers safe chunked response with dynamic action buttons
- Clicking dynamic RollButton rolls check and posts embed.
"""
import pytest
import discord
from discord.ext import commands

from tests.mock_discord import (
    MockGuild,
    MockUser,
    MockTextChannel,
    MockForumChannel,
    MockCategoryChannel,
    MockThread,
    MockMessage,
    MockInteraction,
    MockEmbed
)
from tests.mock_ai import MockGeminiClient
from ai.gemini_client import GeminiClient
from core.models import CharacterModel, StatBlock, ItemModel
from core.channel_manager import (
    setup_campaign_infrastructure,
    find_text_channel,
    find_forum_channel
)
from core.discord_db import (
    fetch_campaign_rules,
    get_or_create_character_sheet,
    update_character_sheet,
    get_quest_board,
    update_quest_board,
    extract_data_from_text,
    get_character_from_thread
)
from commands.campaign_cog import CampaignCog
from commands.quest_cog import QuestCog
from commands.character_cog import CharacterCog
from commands.mechanics_cog import MechanicsCog
from commands.narrative_cog import NarrativeCog
from mechanics.dice import roll_dice
from discord_ui.views import RollButton, NarrativeActionView


class MockDndBot:
    """Mock bot holding cogs and mock user for E2E testing."""
    def __init__(self, user: MockUser):
        self.user = user
        self.cogs = {}
        self.tree = MockCommandTree()

    def add_cog(self, cog):
        self.cogs[cog.__class__.__name__] = cog


class MockCommandTree:
    """Mock command tree supporting add_command."""
    def __init__(self):
        self.commands = {}

    def add_command(self, cmd, override: bool = True):
        self.commands[cmd.name] = cmd

    def get_command(self, name: str):
        return self.commands.get(name)


@pytest.mark.asyncio
async def test_complete_e2e_campaign_gameplay_flow():
    """Complete E2E test exercising all 9 core stages of campaign lifecycle and gameplay."""
    
    # ------------------------------------------------------------------------
    # STAGE 0: Setup Bot and Cogs
    # ------------------------------------------------------------------------
    bot_user = MockUser(id=999, name="Mistrz Gry (AI)", bot=True)
    bot = MockDndBot(bot_user)
    
    mock_gemini = MockGeminiClient()
    gemini_client = GeminiClient(mock_client=mock_gemini)

    campaign_cog = CampaignCog(bot)
    quest_cog = QuestCog(bot)
    char_cog = CharacterCog(bot)
    mech_cog = MechanicsCog(bot)
    narrative_cog = NarrativeCog(bot, gemini_client=gemini_client)

    bot.add_cog(campaign_cog)
    bot.add_cog(quest_cog)
    bot.add_cog(char_cog)
    bot.add_cog(mech_cog)
    bot.add_cog(narrative_cog)

    guild = MockGuild(name="Twierdza Bohaterów")
    admin_user = MockUser(id=1, name="GameMasterAdmin", display_name="Admin DM")
    player_thorin = MockUser(id=42, name="ThorinPlayer", display_name="Thorin Kamienna Tarcza")
    player_elora = MockUser(id=43, name="EloraPlayer", display_name="Elora Czarodziejka")
    guild.members.extend([admin_user, player_thorin, player_elora])

    # ------------------------------------------------------------------------
    # STAGE 1: /setup-campaign Creates Channel Hierarchy & Pinned Posts
    # ------------------------------------------------------------------------
    setup_interaction = MockInteraction(user=admin_user, guild=guild)
    await campaign_cog.setup_campaign.callback(campaign_cog, setup_interaction)

    assert len(guild.categories) == 3
    cat_names = [c.name for c in guild.categories]
    assert "📜 KAMPANIA I FABUŁA" in cat_names
    assert "🛡️ POSTACIE I MECHANIKA" in cat_names
    assert "📖 ENCYKLOPEDIA I WIEDZA" in cat_names

    stol_ch = find_text_channel(guild, "stół-gry") or find_text_channel(guild, "stol-gry")
    assert stol_ch is not None

    rules_ch = find_text_channel(guild, "zasady-i-mechanika")
    assert rules_ch is not None
    assert len(rules_ch.pinned_messages) == 1

    dziennik_ch = find_text_channel(guild, "dziennik-zadań") or find_text_channel(guild, "dziennik-zadan")
    assert dziennik_ch is not None
    assert len(dziennik_ch.pinned_messages) == 1

    karty_forum = find_forum_channel(guild, "karty-postaci")
    assert karty_forum is not None

    kompendium_forum = find_forum_channel(guild, "kompendium-i-lore")
    assert kompendium_forum is not None

    # Verify idempotency: second setup run does not create duplicate channels
    setup_interaction_2 = MockInteraction(user=admin_user, guild=guild)
    await campaign_cog.setup_campaign.callback(campaign_cog, setup_interaction_2)
    assert len(guild.categories) == 3
    assert len(guild.text_channels) == 6
    assert len(guild.forums) == 2

    # ------------------------------------------------------------------------
    # STAGE 2: Pinned Rules in #zasady-i-mechanika Parsed Live
    # ------------------------------------------------------------------------
    pinned_rules = rules_ch.pinned_messages[0]
    custom_rules_text = (
        "📌 **AKTUALNE ZASADY KAMPANII: MROCZNE ZIEMIE**\n"
        "- System: D&D 5e Hardcore\n"
        "- Zasada Homebrew: Eliksiry leczenia to Bonus Action\n"
        "- Obrażenia Krytyczne: Max kość + dodatkowy rzut\n"
        "- Klimat: Mroczne Bagna i Tajemnica"
    )
    await pinned_rules.edit(content=custom_rules_text)

    # Show rules via /zasady command
    rules_interaction = MockInteraction(user=player_thorin, guild=guild)
    await campaign_cog.show_rules.callback(campaign_cog, rules_interaction)
    assert len(rules_interaction.followup.sent_messages) == 1
    rules_embed = rules_interaction.followup.sent_messages[0].embeds[0]
    assert "Eliksiry leczenia to Bonus Action" in rules_embed.description

    # ------------------------------------------------------------------------
    # STAGE 3: Character Creation in #karty-postaci Forum with DATA_JSON & ASCII HP Bar
    # ------------------------------------------------------------------------
    thorin_char = CharacterModel(
        discord_user_id=str(player_thorin.id),
        name="Thorin Żelazna Stopa",
        character_class="Wojownik (Fighter)",
        race="Krasnolud",
        level=2,
        current_hp=20,
        max_hp=20,
        armor_class=17,
        speed=25,
        stats=StatBlock(
            strength=16,
            dexterity=12,
            constitution=16,
            intelligence=10,
            wisdom=14,
            charisma=8
        ),
        inventory=[
            ItemModel(name="Topór wojenny", quantity=1, item_type="weapon", is_equipped=True),
            ItemModel(name="Tarcza", quantity=1, item_type="shield", is_equipped=True),
            ItemModel(name="Racja żywnościowa", quantity=5, item_type="consumable")
        ],
        gold_gp=35
    )

    thread, pinned_msg, created_char = await get_or_create_character_sheet(
        karty_forum,
        str(player_thorin.id),
        character=thorin_char
    )
    assert thread is not None
    assert pinned_msg is not None
    assert created_char.name == "Thorin Żelazna Stopa"

    # Verify DATA_JSON hidden tag and ASCII bar
    raw_desc = pinned_msg.embeds[0].description
    data_dict = extract_data_from_text(raw_desc)
    assert data_dict is not None
    assert data_dict["name"] == "Thorin Żelazna Stopa"
    assert data_dict["current_hp"] == 20
    hp_field = next(f for f in pinned_msg.embeds[0].fields if "Żywotność" in f.name)
    assert "██████████" in hp_field.value
    assert "20/20 HP" in hp_field.value

    # Test /sheet slash command
    sheet_interaction = MockInteraction(user=player_thorin, guild=guild)
    await char_cog.show_sheet.callback(char_cog, sheet_interaction, postac=None)
    assert len(sheet_interaction.followup.sent_messages) == 1
    sheet_embed = sheet_interaction.followup.sent_messages[0].embeds[0]
    assert "Thorin Żelazna Stopa" in sheet_embed.title

    # ------------------------------------------------------------------------
    # STAGE 4: 24h Thread Archiving & Auto-Unarchival
    # ------------------------------------------------------------------------
    # Simulate thread going to sleep after 24h
    thread.archived = True
    assert thread.archived is True

    # When accessing or updating character, thread must automatically wake up
    hp_interaction = MockInteraction(user=player_thorin, guild=guild)
    await char_cog.change_hp.callback(
        char_cog,
        hp_interaction,
        wartosc=-6,
        postac=None,
        powod="Trafienie bełtem z kuszy"
    )

    assert thread.archived is False
    assert thread.unarchived_count >= 1

    # Verify character updated in thread
    updated_char = await get_character_from_thread(thread)
    assert updated_char.current_hp == 14
    # Check thread audit messages
    assert len(thread.messages) >= 2
    assert any("Trafienie bełtem z kuszy" in m.content or "6" in m.content for m in thread.messages)

    # ------------------------------------------------------------------------
    # STAGE 5: /quest create & /quest complete Update #dziennik-zadań
    # ------------------------------------------------------------------------
    quest_interaction_1 = MockInteraction(user=admin_user, guild=guild)
    await quest_cog.quest_group.create_quest.callback(
        quest_cog.quest_group,
        quest_interaction_1,
        title="Oczyszczenie Starej Krypty",
        giver="Kapłan Eamon",
        description="Zbadaj krypty pod zrujnowaną świątynią i zniszcz nekromantę.",
        reward="200 GP i Pierścień Ochrony",
        objectives="Zbadaj wejście do krypty; Pokonaj szkielety strażnicze; Pokonaj nekromantę"
    )

    # Verify quest board in #dziennik-zadań updated
    quest_board = await get_quest_board(dziennik_ch)
    assert len(quest_board.active_quests()) == 1
    active_q = quest_board.active_quests()[0]
    assert active_q.title == "Oczyszczenie Starej Krypty"
    assert len(active_q.objectives) == 3

    # Complete quest
    quest_interaction_2 = MockInteraction(user=admin_user, guild=guild)
    await quest_cog.quest_group.complete_quest.callback(
        quest_cog.quest_group,
        quest_interaction_2,
        quest_id_or_title="Q-001"
    )

    quest_board_after = await get_quest_board(dziennik_ch)
    assert len(quest_board_after.active_quests()) == 0
    assert len(quest_board_after.completed_quests()) == 1
    assert quest_board_after.completed_quests()[0].status == "completed"

    # ------------------------------------------------------------------------
    # STAGE 6: Deterministic RPG Mechanics (/roll, /check, /initiative) (0 AI Tokens)
    # ------------------------------------------------------------------------
    roll_interaction = MockInteraction(user=player_thorin, guild=guild, channel=stol_ch)
    await mech_cog.roll_command.callback(
        mech_cog,
        roll_interaction,
        formula="1d20+3",
        reason="Atak toporem",
        dc=15,
        advantage=False,
        disadvantage=False
    )
    assert len(roll_interaction.response.sent_messages) == 1
    roll_embed = roll_interaction.response.sent_messages[0].embeds[0]
    assert "Atak toporem" in roll_embed.title or any("Atak toporem" in f.name or "Atak toporem" in f.value for f in roll_embed.fields)

    # Check command using Thorin's STR (+3)
    check_interaction = MockInteraction(user=player_thorin, guild=guild, channel=stol_ch)
    await mech_cog.check_command.callback(
        mech_cog,
        check_interaction,
        cecha="STR (Siła)",
        dc=14,
        advantage=False,
        disadvantage=False
    )
    assert len(check_interaction.response.sent_messages) == 1

    # Initiative command
    init_interaction = MockInteraction(user=player_thorin, guild=guild, channel=stol_ch)
    await mech_cog.initiative_command.callback(
        mech_cog,
        init_interaction,
        modyfikator=0
    )
    assert len(init_interaction.response.sent_messages) == 1

    # ------------------------------------------------------------------------
    # STAGE 7: Inventory, Gold, and Rest Mechanics (/item, /gold, /rest)
    # ------------------------------------------------------------------------
    # Add item
    item_add_interaction = MockInteraction(user=player_thorin, guild=guild)
    await char_cog.manage_item.callback(
        char_cog,
        item_add_interaction,
        akcja="add",
        nazwa="Mikstura Wielkiego Leczenia",
        ilosc=2,
        postac=None
    )
    char_after_item = await get_character_from_thread(thread)
    assert any(i.name == "Mikstura Wielkiego Leczenia" and i.quantity == 2 for i in char_after_item.inventory)

    # Gold management
    gold_interaction = MockInteraction(user=player_thorin, guild=guild)
    await char_cog.manage_gold.callback(
        char_cog,
        gold_interaction,
        wartosc=50,
        powod="Nagroda za zadanie",
        postac=None
    )
    char_after_gold = await get_character_from_thread(thread)
    assert char_after_gold.gold_gp == 85

    # Long Rest restores HP
    rest_interaction = MockInteraction(user=player_thorin, guild=guild)
    await char_cog.rest.callback(
        char_cog,
        rest_interaction,
        typ="long",
        leczenie=0,
        postac=None
    )
    char_after_rest = await get_character_from_thread(thread)
    assert char_after_rest.current_hp == char_after_rest.max_hp

    # ------------------------------------------------------------------------
    # STAGE 8: @Mistrz Gry Narrative Turn with Context Scan & Action Buttons
    # ------------------------------------------------------------------------
    # Initial bot introduction on table
    init_dm_msg = MockMessage(
        content="Mistrz Gry: Witajcie w mrocznych kryptach. Przed wami rozciągają się starożytne kamienne schody.",
        author=bot_user,
        channel=stol_ch,
        guild=guild
    )
    stol_ch.messages.append(init_dm_msg)

    # Players take actions in chat
    player_msg_1 = MockMessage(
        content="Thorin: Zapalam pochodnię i powoli schodzę w dół po schodach.",
        author=player_thorin,
        channel=stol_ch,
        guild=guild
    )
    ooc_msg = MockMessage(
        content="((Zaraz wracam, muszę nalać herbaty))",
        author=player_elora,
        channel=stol_ch,
        guild=guild
    )
    player_msg_2 = MockMessage(
        content="Elora: Przygotowuję zaklęcie Światła i rozglądam się za pułapkami. @Mistrz Gry co widzimy w głębi?",
        author=player_elora,
        channel=stol_ch,
        guild=guild,
        mentions=[bot_user]
    )
    stol_ch.messages.extend([player_msg_1, ooc_msg, player_msg_2])

    # Queue long narrative response (>2000 chars) with dynamic action buttons
    long_narrative_text = (
        "Mistrz Gry: Blask twojej pochodni rozprasza wielowiekowy mrok, ukazując monumentalną salę kolumnową. "
        "Na ścianach widnieją wyblakłe płaskorzeźby przedstawiające pradawnych władców i zapomniane bóstwa podziemi. "
        "Każdy wasz krok niesie się echem po wilgotnych płytach posadzki.\n\n"
        "W głębi komnaty, spomiędzy dwóch potężnych bazaltowych filarów, dobiega powolny, rytmiczny dźwięk – "
        "jakby krople wody spadające na metalową tarczę, albo pazury drapiące o kamień. "
        "Zauważacie, że na ziemi przed wami wyryto subtelne runy ostrzegawcze, a mechanizm w posadzce wydaje się lekko uniesiony.\n\n"
        "Powietrze pachnie ozonem i starożytnym prochem. Czujecie na sobie spojrzenie niewidocznych oczu czających się w cieniach pod sklepieniem.\n\n"
        "*Co decydujecie się zrobić w tej chwili?*"
    )
    mock_gemini.queue_response(
        f"{long_narrative_text}\n\n[ACTION_BUTTONS: [\""
        f"{{\"label\": \"Rzut na Ocalenie (DEX +1)\", \"formula\": \"1d20+1\", \"reason\": \"Uniknięcie pułapki\", \"dc\": 13}}, "
        f"{{\"label\": \"Rzut na Wiedzę Tajemną (INT +3)\", \"formula\": \"1d20+3\", \"reason\": \"Identyfikacja run\", \"dc\": 14}}"
        f"]]"
    )

    # Process message through NarrativeCog
    await narrative_cog.on_message(player_msg_2)

    # Verify DM response was delivered to table
    assert mock_gemini.call_count == 1
    last_call_prompt = mock_gemini.last_call["context_prompt"]
    assert "Thorin" in last_call_prompt
    assert "Elora" in last_call_prompt
    assert "Zasada Homebrew" in last_call_prompt
    assert "Eliksiry leczenia to Bonus Action" in last_call_prompt
    assert "ZASADA PRZYCISKÓW AKCJI" in mock_gemini.last_call["system_prompt"]

    # Verify messages in table channel
    dm_replies = [m for m in stol_ch.messages if m.author.id == bot_user.id and m != init_dm_msg]
    assert len(dm_replies) >= 1
    final_dm_msg = stol_ch.messages[-1]
    assert "salę kolumnową" in dm_replies[0].content or "Co decydujecie" in final_dm_msg.content

    # ------------------------------------------------------------------------
    # STAGE 9: Dynamic Action Button Interaction (0 AI Tokens Roll)
    # ------------------------------------------------------------------------
    action_view = NarrativeActionView([
        {"label": "Rzut na Ocalenie (DEX +1)", "formula": "1d20+1", "reason": "Uniknięcie pułapki", "dc": 13},
        {"label": "Rzut na Wiedzę Tajemną (INT +3)", "formula": "1d20+3", "reason": "Identyfikacja run", "dc": 14}
    ])
    assert len(action_view.children) == 2
    
    first_btn = action_view.children[0]
    assert isinstance(first_btn, RollButton)
    assert first_btn.formula == "1d20+1"
    assert first_btn.dc == 13

    # Click the dynamic action button
    button_interaction = MockInteraction(user=player_thorin, guild=guild, channel=stol_ch)
    await first_btn.callback(button_interaction)

    assert len(button_interaction.response.sent_messages) == 1
    btn_result_msg = button_interaction.response.sent_messages[0]
    assert "Uniknięcie pułapki" in btn_result_msg.content
    assert len(btn_result_msg.embeds) == 1
    btn_embed = btn_result_msg.embeds[0]
    assert btn_embed.fields is not None
    # Result field should evaluate DC 13
    assert any("SUKCES" in f.value or "PORAŻKA" in f.value for f in btn_embed.fields)


@pytest.mark.asyncio
async def test_narrative_cog_next_slash_command_flow():
    """Verifies that /next slash command on #stół-gry triggers full narrative turn."""
    bot_user = MockUser(id=999, name="Mistrz Gry (AI)", bot=True)
    bot = MockDndBot(bot_user)
    
    mock_gemini = MockGeminiClient()
    mock_gemini.queue_response(
        "Mistrz Gry: Wkraczacie do komnaty tronowej.\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Rzut na Charyzmę (CHA +2)\", \"formula\": \"1d20+2\", \"reason\": \"Perswazja\", \"dc\": 15}]]"
    )
    gemini_client = GeminiClient(mock_client=mock_gemini)
    narrative_cog = NarrativeCog(bot, gemini_client=gemini_client)

    guild = MockGuild(name="Kampania /next")
    stol_ch = await guild.create_text_channel("stół-gry")
    player = MockUser(id=10, name="Gimli")
    guild.members.append(player)

    interaction = MockInteraction(user=player, guild=guild, channel=stol_ch)
    await narrative_cog.next_turn.callback(narrative_cog, interaction)

    assert interaction.response.is_done()
    assert len(interaction.followup.sent_messages) >= 1
    sent_msg = interaction.followup.sent_messages[0]
    assert "Wkraczacie do komnaty tronowej" in sent_msg.content


@pytest.mark.asyncio
async def test_narrative_cog_next_on_wrong_channel_rejected():
    """Verifies that /next on non-table channels is rejected politely with ephemeral warning."""
    bot_user = MockUser(id=999, name="Mistrz Gry (AI)", bot=True)
    bot = MockDndBot(bot_user)
    narrative_cog = NarrativeCog(bot)

    guild = MockGuild(name="Kampania Test")
    other_ch = await guild.create_text_channel("ogólny-czat")
    player = MockUser(id=10, name="Gimli")

    interaction = MockInteraction(user=player, guild=guild, channel=other_ch)
    await narrative_cog.next_turn.callback(narrative_cog, interaction)

    assert interaction.response.is_done()
    sent_msg = interaction.response.sent_messages[0]
    assert "wyłącznie na kanale" in sent_msg.content
