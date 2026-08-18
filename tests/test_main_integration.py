"""Integration tests for main.py bot lifecycle, Cog loading, command tree synchronization, and error handling."""
import asyncio
import pytest
import discord
from discord import app_commands
from discord.ext import commands

import main
from main import DndAIBot, create_bot, INITIAL_EXTENSIONS
from tests.mock_discord import (
    MockGuild,
    MockUser,
    MockTextChannel,
    MockInteraction,
    MockMessage
)
from config.settings import settings


@pytest.mark.asyncio
async def test_bot_initialization_and_extensions_loading():
    """Verifies DndAIBot creates cleanly and loads all 5 initial extensions without syntax or import errors."""
    bot = create_bot()
    assert isinstance(bot, DndAIBot)
    assert len(bot.initial_extensions) == 5
    assert "commands.campaign_cog" in bot.initial_extensions
    assert "commands.quest_cog" in bot.initial_extensions
    assert "commands.character_cog" in bot.initial_extensions
    assert "commands.mechanics_cog" in bot.initial_extensions
    assert "commands.narrative_cog" in bot.initial_extensions

    # Load all extensions via setup_hook
    await bot.setup_hook()

    loaded_cogs = list(bot.cogs.keys())
    assert "CampaignCog" in loaded_cogs
    assert "QuestCog" in loaded_cogs
    assert "CharacterCog" in loaded_cogs
    assert "MechanicsCog" in loaded_cogs
    assert "NarrativeCog" in loaded_cogs

    await bot.close()


@pytest.mark.asyncio
async def test_bot_command_tree_registration():
    """Verifies that all required slash commands and groups are registered in bot.tree."""
    bot = create_bot()
    await bot.setup_hook()

    # Verify all expected slash commands exist in tree
    registered_command_names = [cmd.name for cmd in bot.tree.get_commands()]
    
    expected_commands = [
        "setup-campaign",
        "zasady",
        "quest",
        "sheet",
        "hp",
        "item",
        "gold",
        "rest",
        "roll",
        "check",
        "initiative",
        "next"
    ]

    for expected in expected_commands:
        assert expected in registered_command_names, f"Slash command /{expected} not found in bot.tree!"

    # Verify quest group subcommands
    quest_group = bot.tree.get_command("quest")
    assert isinstance(quest_group, app_commands.Group)
    quest_subcommands = [cmd.name for cmd in quest_group.commands]
    assert "create" in quest_subcommands
    assert "complete" in quest_subcommands
    assert "list" in quest_subcommands

    await bot.close()


@pytest.mark.asyncio
async def test_bot_tree_error_handler():
    """Verifies that global on_tree_error handles errors and sends user feedback."""
    bot = create_bot()
    interaction = MockInteraction()
    
    test_error = app_commands.AppCommandError("Test command exception")
    await bot.on_tree_error(interaction, test_error)

    # Verify response was sent
    assert interaction.response.is_done()
    assert len(interaction.response.sent_messages) == 1
    sent = interaction.response.sent_messages[0]
    assert "Test command exception" in sent.content

    # If response was already done, verify it uses followup
    interaction2 = MockInteraction()
    await interaction2.response.defer()
    await bot.on_tree_error(interaction2, test_error)
    assert len(interaction2.followup.sent_messages) == 1
    sent2 = interaction2.followup.sent_messages[0]
    assert "Test command exception" in sent2.content

    await bot.close()


@pytest.mark.asyncio
async def test_bot_command_error_handler():
    """Verifies that traditional on_command_error formats errors cleanly."""
    bot = create_bot()

    class MockContext:
        def __init__(self):
            self.command = "test_cmd"
            self.sent_messages = []

        async def send(self, content: str):
            self.sent_messages.append(content)

    ctx = MockContext()
    
    # CommandNotFound should be ignored silently
    await bot.on_command_error(ctx, commands.CommandNotFound("Unknown"))
    assert len(ctx.sent_messages) == 0

    # Other errors should send error message
    await bot.on_command_error(ctx, commands.CommandError("Custom error"))
    assert len(ctx.sent_messages) == 1
    assert "Custom error" in ctx.sent_messages[0]

    await bot.close()


@pytest.mark.asyncio
async def test_bot_on_ready_logging_and_sync(monkeypatch):
    """Verifies on_ready event handles sync without crashing."""
    bot = create_bot()
    bot._user = MockUser(id=999, name="TestBot", bot=True)

    # Test sync without guild id (global sync)
    monkeypatch.setattr(settings, "discord_guild_id", "")
    
    # Mock tree.sync to return a dummy list
    async def mock_sync(guild=None):
        return [1, 2, 3]

    monkeypatch.setattr(bot.tree, "sync", mock_sync)
    await bot.on_ready()

    # Test sync with specific guild id
    monkeypatch.setattr(settings, "discord_guild_id", "123456789")
    monkeypatch.setattr(bot.tree, "copy_global_to", lambda guild: None)
    await bot.on_ready()

    await bot.close()
