"""Unit tests for Dynamic Context Builder (ai/context_builder.py)."""
import pytest
import discord
from ai.context_builder import (
    fetch_messages_since_last_dm_response,
    fetch_campaign_rules,
    fetch_active_characters,
    build_full_dm_context,
    is_ooc_message,
    normalize_channel_name
)
from tests.mock_discord import (
    MockGuild,
    MockUser,
    MockTextChannel,
    MockMessage,
    MockEmbed
)
from mechanics.dice import DiceRollResult
from discord_ui.embeds import create_dice_roll_embed
from core.models import CharacterModel, StatBlock
from core.discord_db import inject_json_to_text, create_character_sheet_embed


@pytest.mark.asyncio
async def test_fetch_messages_filters_ooc():
    guild = MockGuild()
    ch = MockTextChannel(name="stol-gry", guild=guild)
    bot = MockUser(id=999, name="DM", bot=True)
    player = MockUser(id=10, name="Player", display_name="Aragorn")

    ch.messages.append(MockMessage(content="Poprzednia narracja", author=bot, channel=ch))
    ch.messages.append(MockMessage(content="((Zaraz wracam))", author=player, channel=ch))
    ch.messages.append(MockMessage(content="// Przerwa na herbatę", author=player, channel=ch))
    ch.messages.append(MockMessage(content="/* Komentarz OOC */", author=player, channel=ch))
    ch.messages.append(MockMessage(content="Wyciągam miecz!", author=player, channel=ch))

    events = await fetch_messages_since_last_dm_response(ch, bot)
    assert "Wyciągam miecz!" in events
    assert "Zaraz wracam" not in events
    assert "Przerwa na herbatę" not in events
    assert "Komentarz OOC" not in events


@pytest.mark.asyncio
async def test_fetch_campaign_rules_reads_channel():
    guild = MockGuild()
    rules_ch = await guild.create_text_channel("zasady-i-mechanika")
    msg = await rules_ch.send("Zasada 1: Krytyki podwajają kości.")
    await msg.pin()

    rules = await fetch_campaign_rules(guild)
    assert "Krytyki podwajają kości" in rules


@pytest.mark.asyncio
async def test_fetch_campaign_rules_direct_channel():
    guild = MockGuild()
    rules_ch = await guild.create_text_channel("zasady-i-mechanika")
    await rules_ch.send("Zasada domowa: Mikstury jako Bonus Action.")

    rules = await fetch_campaign_rules(rules_ch)
    assert "Bonus Action" in rules


@pytest.mark.asyncio
async def test_fetch_campaign_rules_fallback_when_missing():
    guild = MockGuild()
    rules = await fetch_campaign_rules(guild)
    assert "System bazowy: Standardowe D&D 5e." in rules


@pytest.mark.asyncio
async def test_fetch_active_characters_empty_forum():
    guild = MockGuild()
    await guild.create_forum("karty-postaci")
    chars = await fetch_active_characters(guild)
    assert chars == []


@pytest.mark.asyncio
async def test_fetch_active_characters_with_auto_unarchive():
    guild = MockGuild()
    forum = await guild.create_forum("karty-postaci")
    
    char = CharacterModel(
        discord_user_id="12345",
        name="Gimli",
        character_class="Fighter",
        race="Dwarf",
        level=2,
        current_hp=20,
        max_hp=20,
        stats=StatBlock(strength=16, dexterity=12, constitution=16, intelligence=10, wisdom=10, charisma=8)
    )
    embed = create_character_sheet_embed(char)
    embed.description = inject_json_to_text("Karta postaci Gimli", char.model_dump())
    
    thread_res = await forum.create_thread(name="🛡️ Gimli", embed=embed)
    thread = thread_res.thread
    # Uśpij wątek po 24h
    await thread.edit(archived=True)
    assert thread.archived is True

    # fetch_active_characters powinno automatycznie odarchiwizować wątek i wczytać postać
    chars = await fetch_active_characters(guild)
    assert len(chars) == 1
    assert chars[0]["name"] == "Gimli"
    assert thread.archived is False


@pytest.mark.asyncio
async def test_fetch_messages_aggregates_dice_rolls_from_separate_channel():
    guild = MockGuild()
    stol_ch = await guild.create_text_channel("stol-gry")
    dice_ch = await guild.create_text_channel("rzuty-kostkami")
    bot = MockUser(id=999, name="DM", bot=True)
    player = MockUser(id=10, name="Thorin")

    stol_ch.messages.append(MockMessage(content="Poprzednia odpowiedź bota", author=bot, channel=stol_ch))
    stol_ch.messages.append(MockMessage(content="Atakuję goblina!", author=player, channel=stol_ch))

    # Rzut wykonany na osobnym kanale rzutów
    res = DiceRollResult(formula="1d20+4", total=19, breakdown="15+4", is_success=True, target_dc=13, reason="Atak toporem")
    roll_embed = create_dice_roll_embed(res, "Thorin")
    dice_ch.messages.append(MockMessage(content="", author=bot, channel=dice_ch, embed=roll_embed))

    events = await fetch_messages_since_last_dm_response(stol_ch, bot, guild=guild)
    assert "Atakuję goblina!" in events
    assert "[SYSTEM RZUTOW]:" in events
    assert "Thorin rzuca: Atak toporem" in events


@pytest.mark.asyncio
async def test_build_full_dm_context_assembles_4_layers():
    guild = MockGuild()
    stol_ch = await guild.create_text_channel("stol-gry")
    rules_ch = await guild.create_text_channel("zasady-i-mechanika")
    forum = await guild.create_forum("karty-postaci")
    bot = MockUser(id=999, name="DM", bot=True)
    player = MockUser(id=20, name="Elora")

    # Layer 2: Zasady
    msg = await rules_ch.send("Zasada kampanii: Magia cienia wymaga podwójnej koncentracji.")
    await msg.pin()

    # Layer 3: Postać
    char = CharacterModel(
        discord_user_id="20",
        name="Elora",
        character_class="Wizard",
        race="Elf",
        level=3,
        current_hp=15,
        max_hp=15
    )
    embed = create_character_sheet_embed(char)
    embed.description = inject_json_to_text("Karta", char.model_dump())
    await forum.create_thread(name="✨ Elora", embed=embed)

    # Layer 4: Zdarzenia
    stol_ch.messages.append(MockMessage(content="Rzucam czar światła na kostur!", author=player, channel=stol_ch))

    sys_prompt, ctx_prompt = await build_full_dm_context(guild, stol_ch, bot)

    assert "ACTION_BUTTONS" in sys_prompt
    assert "Magia cienia wymaga podwójnej koncentracji" in ctx_prompt
    assert "Elora" in ctx_prompt
    assert "Rzucam czar światła" in ctx_prompt


def test_is_ooc_message_detection():
    assert is_ooc_message("((Muszę iść na kolację))") is True
    assert is_ooc_message("// zaraz wracam") is True
    assert is_ooc_message("/* test */") is True
    assert is_ooc_message("OOC: szybkie pytanie") is True
    assert is_ooc_message("Wchodzę do jaskini i zapalam pochodnię") is False


def test_normalize_channel_name():
    assert normalize_channel_name("stół-gry") == "stolgry"
    assert normalize_channel_name("stol-gry") == "stolgry"
    assert normalize_channel_name("RZUTY-KOŚCI") == "rzutykosci"
    assert normalize_channel_name("zasady_i_mechanika") == "zasadyimechanika"
