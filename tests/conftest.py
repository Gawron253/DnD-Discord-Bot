"""Pytest fixtures for D&D AI Discord Bot test suite.
Provides realistic mock guild, campaign channels, characters, quests, and mock Gemini engine.
"""
from __future__ import annotations
import pytest
import pytest_asyncio
from typing import AsyncGenerator, Dict, Any

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
from tests.mock_ai import MockGeminiClient
from core.models import CharacterModel, StatBlock, ItemModel, SpellSlots, QuestModel, QuestObjective
from core.discord_db import inject_json_to_text
from discord_ui.embeds import create_character_sheet_embed


@pytest.fixture
def mock_bot_user() -> MockUser:
    """Mock Discord Bot user (Mistrz Gry)."""
    return MockUser(id=999, name="Mistrz Gry", display_name="Mistrz Gry (AI DM)", bot=True)


@pytest.fixture
def mock_player_user() -> MockUser:
    """Mock player user."""
    return MockUser(id=101, name="PlayerThorin", display_name="Thorin Kamienna Tarcza", bot=False)


@pytest.fixture
def mock_player_mage() -> MockUser:
    """Mock second player user (Mage)."""
    return MockUser(id=102, name="PlayerElora", display_name="Elora Gwiazda Nocy", bot=False)


@pytest.fixture
def mock_dm_user() -> MockUser:
    """Mock human DM / Admin."""
    return MockUser(id=201, name="HumanDM", display_name="Mistrz Sali", bot=False)


@pytest.fixture
def sample_character(mock_player_user: MockUser) -> CharacterModel:
    """Sample Dwarf Fighter character."""
    return CharacterModel(
        discord_user_id=str(mock_player_user.id),
        name="Thorin Kamienna Tarcza",
        character_class="Fighter",
        race="Dwarf",
        level=3,
        xp=900,
        current_hp=28,
        max_hp=28,
        temp_hp=0,
        armor_class=16,
        speed=25,
        proficiency_bonus=2,
        stats=StatBlock(
            strength=16,
            dexterity=12,
            constitution=16,
            intelligence=10,
            wisdom=14,
            charisma=8
        ),
        inventory=[
            ItemModel(name="Młot bojowy (Warhammer)", quantity=1, item_type="weapon", is_equipped=True),
            ItemModel(name="Tarcza (Shield)", quantity=1, item_type="armor", is_equipped=True),
            ItemModel(name="Mikstura leczenia (Potion of Healing)", quantity=2, item_type="consumable")
        ],
        gold_gp=45,
        conditions=[]
    )


@pytest.fixture
def sample_mage_character(mock_player_mage: MockUser) -> CharacterModel:
    """Sample Elf Wizard character."""
    return CharacterModel(
        discord_user_id=str(mock_player_mage.id),
        name="Elora Gwiazda Nocy",
        character_class="Wizard",
        race="Elf",
        level=3,
        xp=900,
        current_hp=18,
        max_hp=18,
        temp_hp=0,
        armor_class=12,
        speed=30,
        proficiency_bonus=2,
        stats=StatBlock(
            strength=8,
            dexterity=14,
            constitution=12,
            intelligence=17,
            wisdom=13,
            charisma=12
        ),
        spell_slots=SpellSlots(
            level_1=4,
            level_1_max=4,
            level_2=2,
            level_2_max=2
        ),
        inventory=[
            ItemModel(name="Laska czarodzieja (Quarterstaff)", quantity=1, item_type="weapon"),
            ItemModel(name="Księga zaklęć (Spellbook)", quantity=1, item_type="misc"),
            ItemModel(name="Zwój Magicznego Pocisku", quantity=1, item_type="consumable")
        ],
        gold_gp=30,
        conditions=[]
    )


@pytest.fixture
def sample_quest() -> QuestModel:
    """Sample active quest."""
    return QuestModel(
        id="q-goblin-mine",
        title="Oczyszczenie Starej Kopalni",
        giver="Kapitan Straży Roderick",
        description="Goblini zajęli opuszczoną kopalnię srebra i napadają na kupców.",
        objectives=[
            QuestObjective(text="Zbadaj wejście do kopalni", is_completed=True),
            QuestObjective(text="Pokonaj przywódcę goblinów", is_completed=False),
            QuestObjective(text="Odzyskaj skradzioną skrzynię kupca", is_completed=False)
        ],
        reward="100 GP oraz Złoty Medal Straży",
        status="active"
    )


@pytest.fixture
def mock_gemini() -> MockGeminiClient:
    """Configured Mock Gemini AI client."""
    client = MockGeminiClient()
    yield client
    client.reset()


@pytest_asyncio.fixture
async def configured_guild(
    mock_bot_user: MockUser,
    mock_player_user: MockUser,
    mock_player_mage: MockUser,
    mock_dm_user: MockUser
) -> MockGuild:
    """Fully configured Mock Guild with standard categories, channels, and pinned rules."""
    guild = MockGuild(name="Epika Kampania D&D", id=777)
    guild.members.extend([mock_bot_user, mock_player_user, mock_player_mage, mock_dm_user])

    # 1. Kategoria: KAMPANIA I FABULA
    cat_story = await guild.create_category("📜 KAMPANIA I FABULA")
    ch_stol = await guild.create_text_channel("stol-gry", category=cat_story)
    ch_dziennik = await guild.create_text_channel("dziennik-zadan", category=cat_story)
    ch_kronika = await guild.create_text_channel("kronika-przygod", category=cat_story)
    ch_zasady = await guild.create_text_channel("zasady-i-mechanika", category=cat_story)

    # Initial pinned rules
    rules_msg = await ch_zasady.send(
        "📌 **AKTUALNE ZASADY KAMPANII I SWIATA (Edytowalne w locie)**\n"
        "- **System**: D&D 5e (Dungeons & Dragons 5. edycja)\n"
        "- **Klimat**: Dark Fantasy / Mroczne Tajemnice\n"
        "- **Reguły domowe**: Zmęczenie obniża rzuty obronne o -1."
    )
    await rules_msg.pin()

    # 2. Kategoria: POSTACIE I MECHANIKA
    cat_chars = await guild.create_category("🛡️ POSTACIE I MECHANIKA")
    ch_rzuty = await guild.create_text_channel("rzuty-kostkami", category=cat_chars)
    ch_szepty = await guild.create_text_channel("szepty-dm", category=cat_chars)
    forum_karty = await guild.create_forum_channel("karty-postaci", category=cat_chars)

    # 3. Kategoria: ENCYKLOPEDIA I WIEDZA
    cat_lore = await guild.create_category("📖 ENCYKLOPEDIA I WIEDZA")
    forum_lore = await guild.create_forum_channel("kompendium-i-lore", category=cat_lore)

    return guild


@pytest_asyncio.fixture
async def populated_campaign(
    configured_guild: MockGuild,
    sample_character: CharacterModel,
    sample_mage_character: CharacterModel,
    sample_quest: QuestModel,
    mock_bot_user: MockUser
) -> MockGuild:
    """Guild with registered character sheets in #karty-postaci and pinned quests in #dziennik-zadan."""
    # 1. Onboard character 1 (Thorin)
    forum_karty = next(f for f in configured_guild.forums if f.name == "karty-postaci")
    embed_thorin = create_character_sheet_embed(sample_character)
    embed_thorin.description = inject_json_to_text(embed_thorin.description or "", sample_character.model_dump())
    
    t1_res = await forum_karty.create_thread(
        name=f"🛡️ {sample_character.name}",
        embed=embed_thorin
    )
    thread_thorin, msg_thorin = t1_res.thread, t1_res.message
    sample_character.pinned_sheet_message_id = str(msg_thorin.id)

    # 2. Onboard character 2 (Elora)
    embed_elora = create_character_sheet_embed(sample_mage_character)
    embed_elora.description = inject_json_to_text(embed_elora.description or "", sample_mage_character.model_dump())
    t2_res = await forum_karty.create_thread(
        name=f"✨ {sample_mage_character.name}",
        embed=embed_elora
    )
    thread_elora, msg_elora = t2_res.thread, t2_res.message
    sample_mage_character.pinned_sheet_message_id = str(msg_elora.id)

    # 3. Setup initial quest in #dziennik-zadan
    ch_dziennik = next(c for c in configured_guild.text_channels if c.name == "dziennik-zadan")
    quest_desc = (
        f"**Aktywne Zadanie:** {sample_quest.title}\n"
        f"**Zleceniodawca:** {sample_quest.giver}\n"
        f"**Opis:** {sample_quest.description}\n"
        f"**Nagroda:** {sample_quest.reward}"
    )
    quest_desc_with_json = inject_json_to_text(quest_desc, {"quests": [sample_quest.model_dump()]})
    quest_embed = MockEmbed(
        title="📜 Dziennik Zadań Drużyny",
        description=quest_desc_with_json
    )
    quest_msg = await ch_dziennik.send(embed=quest_embed)
    await quest_msg.pin()

    return configured_guild
