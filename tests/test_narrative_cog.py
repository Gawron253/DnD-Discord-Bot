"""Unit and integration tests for Narrative Cog (commands/narrative_cog.py)."""
import pytest
import discord
from commands.narrative_cog import (
    NarrativeCog,
    is_table_channel,
    is_narrative_trigger
)
from tests.mock_discord import (
    MockGuild,
    MockUser,
    MockTextChannel,
    MockMessage,
    MockInteraction
)
from tests.mock_ai import MockGeminiClient
from ai.gemini_client import GeminiClient


class FakeBot:
    def __init__(self, user: MockUser):
        self.user = user


@pytest.mark.asyncio
async def test_narrative_cog_triggers_on_mention_in_stol_gry():
    guild = MockGuild()
    stol_ch = await guild.create_text_channel("stol-gry")
    bot_user = MockUser(id=999, name="DMBot", bot=True)
    player = MockUser(id=10, name="Thorin")
    fake_bot = FakeBot(bot_user)

    mock_gemini = MockGeminiClient()
    mock_gemini.queue_response(
        "Mistrz Gry: Widzicie starą kaplicę.\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Zbadaj ołtarz (WIS +2)\", \"formula\": \"1d20+2\", \"reason\": \"Religia\", \"dc\": 12}]]"
    )
    cog = NarrativeCog(bot=fake_bot, gemini_client=GeminiClient(mock_client=mock_gemini))

    msg = MockMessage(content="Co widzimy w sali, @Mistrz Gry?", author=player, channel=stol_ch, guild=guild)
    stol_ch.messages.append(msg)

    await cog.on_message(msg)

    # Sprawdzenie, czy bot odpowiedział na stole gry
    assert len(stol_ch.messages) >= 2
    last_msg = stol_ch.messages[-1]
    assert "Widzicie starą kaplicę." in last_msg.content


@pytest.mark.asyncio
async def test_narrative_cog_ignores_passive_chatter():
    guild = MockGuild()
    stol_ch = await guild.create_text_channel("stol-gry")
    bot_user = MockUser(id=999, name="DMBot", bot=True)
    player = MockUser(id=10, name="Thorin")
    fake_bot = FakeBot(bot_user)

    mock_gemini = MockGeminiClient()
    cog = NarrativeCog(bot=fake_bot, gemini_client=GeminiClient(mock_client=mock_gemini))

    msg = MockMessage(content="Gimli, podaj mi eliksir leczenia!", author=player, channel=stol_ch, guild=guild)
    stol_ch.messages.append(msg)

    await cog.on_message(msg)

    # Bot nie powinien odpowiedzieć (tylko 1 wiadomość gracza)
    assert len(stol_ch.messages) == 1
    assert mock_gemini.call_count == 0


@pytest.mark.asyncio
async def test_narrative_cog_ignores_other_channels():
    guild = MockGuild()
    szepty_ch = await guild.create_text_channel("szepty-dm")
    bot_user = MockUser(id=999, name="DMBot", bot=True)
    player = MockUser(id=10, name="Thorin")
    fake_bot = FakeBot(bot_user)

    mock_gemini = MockGeminiClient()
    cog = NarrativeCog(bot=fake_bot, gemini_client=GeminiClient(mock_client=mock_gemini))

    msg = MockMessage(content="Halo @Mistrz Gry, czy tu słychać?", author=player, channel=szepty_ch, guild=guild)
    szepty_ch.messages.append(msg)

    await cog.on_message(msg)

    # Ignorowane na kanałach innych niż stół gry
    assert len(szepty_ch.messages) == 1
    assert mock_gemini.call_count == 0


@pytest.mark.asyncio
async def test_narrative_cog_slash_next_command_on_table():
    guild = MockGuild()
    stol_ch = await guild.create_text_channel("stol-gry")
    bot_user = MockUser(id=999, name="DMBot", bot=True)
    player = MockUser(id=10, name="Thorin")
    fake_bot = FakeBot(bot_user)

    mock_gemini = MockGeminiClient()
    mock_gemini.queue_response(
        "Kolejna tura narracji.\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Rzut na Zręczność (DEX +1)\", \"formula\": \"1d20+1\", \"reason\": \"Zręczność\", \"dc\": 10}]]"
    )
    cog = NarrativeCog(bot=fake_bot, gemini_client=GeminiClient(mock_client=mock_gemini))

    interaction = MockInteraction(user=player, guild=guild, channel=stol_ch)

    await cog.next_turn.callback(cog, interaction)

    assert interaction.response.is_done() is True
    assert len(interaction.followup.sent_messages) == 1
    sent = interaction.followup.sent_messages[0]
    assert "Kolejna tura narracji." in sent.content


@pytest.mark.asyncio
async def test_narrative_cog_slash_next_rejected_on_wrong_channel():
    guild = MockGuild()
    dziennik_ch = await guild.create_text_channel("dziennik-zadan")
    bot_user = MockUser(id=999, name="DMBot", bot=True)
    player = MockUser(id=10, name="Thorin")
    fake_bot = FakeBot(bot_user)

    mock_gemini = MockGeminiClient()
    cog = NarrativeCog(bot=fake_bot, gemini_client=GeminiClient(mock_client=mock_gemini))

    interaction = MockInteraction(user=player, guild=guild, channel=dziennik_ch)

    await cog.next_turn.callback(cog, interaction)

    assert interaction.response.is_done() is True
    sent_msg = interaction.response.sent_messages[0]
    assert "wyłącznie na kanale" in sent_msg.content
    assert mock_gemini.call_count == 0


@pytest.mark.asyncio
async def test_narrative_cog_splits_long_response_sequentially():
    guild = MockGuild()
    stol_ch = await guild.create_text_channel("stol-gry")
    bot_user = MockUser(id=999, name="DMBot", bot=True)
    player = MockUser(id=10, name="Thorin")
    fake_bot = FakeBot(bot_user)

    # 3500 znaków narracji
    p1 = "Rozdział I: " + ("Opis pradawnego lochu i wilgotnych murów. " * 30)
    p2 = "Rozdział II: " + ("Światło pochodni powoli gaśnie wśród mroku. " * 30)
    full_text = (
        f"{p1}\n\n{p2}\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Zapal nową pochodnię\", \"formula\": \"1d20\", \"reason\": \"Pochodnia\"}]]"
    )

    mock_gemini = MockGeminiClient()
    mock_gemini.queue_response(full_text)
    cog = NarrativeCog(bot=fake_bot, gemini_client=GeminiClient(mock_client=mock_gemini))

    msg = MockMessage(content="Idziemy dalej! @Mistrz Gry", author=player, channel=stol_ch, guild=guild)
    stol_ch.messages.append(msg)

    await cog.on_message(msg)

    # Powinny zostać wysłane co najmniej 2 wiadomości bota
    bot_msgs = [m for m in stol_ch.messages if m.author.id == bot_user.id or m.author.bot]
    assert len(bot_msgs) >= 2
    for bm in bot_msgs:
        assert len(bm.content) <= 1900


def test_is_table_channel_helper():
    guild = MockGuild()
    ch1 = MockTextChannel(name="stol-gry", guild=guild)
    ch2 = MockTextChannel(name="stół-gry", guild=guild)
    ch3 = MockTextChannel(name="dziennik-zadan", guild=guild)

    assert is_table_channel(ch1) is True
    assert is_table_channel(ch2) is True
    assert is_table_channel(ch3) is False


def test_is_narrative_trigger_helper():
    bot_user = MockUser(id=999, name="DM", bot=True)

    m1 = MockMessage(content="Co widzimy, @Mistrz Gry?")
    assert is_narrative_trigger(m1, bot_user) is True

    m2 = MockMessage(content="Sprawdzam plecak, @DM")
    assert is_narrative_trigger(m2, bot_user) is True

    m3 = MockMessage(content="!next")
    assert is_narrative_trigger(m3, bot_user) is True

    m4 = MockMessage(content="Gimli, rzuć mi pochodnię")
    assert is_narrative_trigger(m4, bot_user) is False
