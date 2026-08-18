"""Unit tests for Pure Discord state storage (core/discord_db.py)."""
import pytest
from core.models import CharacterModel, StatBlock, ItemModel
from core.discord_db import (
    extract_json_from_message,
    inject_json_to_text,
    get_character_from_thread
)
from discord_ui.embeds import create_character_sheet_embed
from tests.mock_discord import MockForumChannel, MockGuild, MockUser


def test_extract_json_from_message_valid():
    msg = "Postać\n<!-- DATA_JSON: {\"name\": \"Gimli\", \"hp\": 30} -->"
    data = extract_json_from_message(msg)
    assert data is not None
    assert data["name"] == "Gimli"
    assert data["hp"] == 30


def test_extract_json_from_message_missing():
    msg = "Zwykła wiadomość bez danych"
    data = extract_json_from_message(msg)
    assert data is None


def test_inject_json_to_text_clean():
    base = "Wstępny opis postaci"
    data = {"level": 5, "class": "Paladin"}
    injected = inject_json_to_text(base, data)
    assert "<!-- DATA_JSON:" in injected
    assert base in injected


def test_inject_json_to_text_replaces_old_json():
    old_text = "Opis\n<!-- DATA_JSON: {\"hp\": 10} -->"
    new_data = {"hp": 20}
    updated = inject_json_to_text(old_text, new_data)
    assert updated.count("<!-- DATA_JSON:") == 1
    extracted = extract_json_from_message(updated)
    assert extracted["hp"] == 20


@pytest.mark.asyncio
async def test_get_character_from_thread_pinned():
    guild = MockGuild()
    forum = MockForumChannel(name="karty-postaci", guild=guild)
    char = CharacterModel(
        discord_user_id="101",
        name="Legolas",
        character_class="Ranger",
        race="Elf",
        stats=StatBlock(dexterity=18)
    )
    embed = create_character_sheet_embed(char)
    embed.description = inject_json_to_text("Elficki łucznik", char.model_dump())

    t_res = await forum.create_thread(name="Legolas", embed=embed)
    fetched = await get_character_from_thread(t_res.thread)

    assert fetched is not None
    assert fetched.name == "Legolas"
    assert fetched.stats.dexterity == 18
