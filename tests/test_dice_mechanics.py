"""Unit and integration tests for RPG Dice Engine mechanics and Discord UI (Milestone 2)."""
import pytest
import discord
from mechanics.dice import roll_dice, DiceRollResult, create_health_bar
from mechanics.character_ops import (
    modify_hp,
    add_inventory_item,
    remove_inventory_item,
    modify_gold,
    short_rest,
    long_rest,
    add_condition,
    remove_condition
)
from core.models import CharacterModel, StatBlock, ItemModel, SpellSlots
from discord_ui.embeds import (
    create_character_sheet_embed,
    create_dice_roll_embed,
    create_quest_journal_embed
)
from discord_ui.views import RollButton, NarrativeActionView, CharacterSheetView
from commands.character_cog import CharacterCog
from commands.mechanics_cog import MechanicsCog
from tests.mock_discord import (
    MockGuild,
    MockUser,
    MockForumChannel,
    MockThread,
    MockMessage,
    MockInteraction
)


def test_roll_dice_standard():
    res = roll_dice("1d20+4", reason="Inicjatywa")
    assert 5 <= res.total <= 24
    assert res.formula == "1d20+4"
    assert res.reason == "Inicjatywa"


def test_roll_dice_with_dc_success():
    res = roll_dice("1d20+10", reason="Skok", target_dc=10)
    assert res.is_success is True
    assert res.target_dc == 10


def test_roll_dice_with_dc_failure():
    res = roll_dice("1d20-10", reason="Skok", target_dc=15)
    assert res.is_success is False


def test_roll_dice_advantage():
    res = roll_dice("1d20+3", advantage_disadvantage="advantage")
    assert "2d20kh1" in res.formula


def test_roll_dice_disadvantage():
    res = roll_dice("1d20+3", advantage_disadvantage="disadvantage")
    assert "2d20kl1" in res.formula


def test_roll_dice_breakdown_format():
    res = roll_dice("2d6+3", reason="Obrażenia")
    assert res.breakdown != ""
    assert res.total >= 5


def test_roll_dice_boolean_flags_advantage_disadvantage():
    res_adv = roll_dice("1d20+2", advantage=True)
    assert "2d20kh1" in res_adv.formula

    res_dis = roll_dice("1d20+2", disadvantage=True)
    assert "2d20kl1" in res_dis.formula


def test_roll_dice_dice_rolls_and_modifier_extraction():
    res = roll_dice("1d20+5")
    assert len(res.dice_rolls) >= 1
    assert res.modifier == res.total - sum(res.dice_rolls)


def test_character_ops_modify_hp_normal_damage_and_heal():
    char = CharacterModel(
        discord_user_id="111",
        name="Wojownik",
        character_class="Fighter",
        race="Human",
        current_hp=20,
        max_hp=20
    )
    # Damage 8
    hp, temp, msg = modify_hp(char, -8)
    assert hp == 12
    assert char.current_hp == 12
    assert "12/20 HP" in msg

    # Heal 5
    hp, temp, msg = modify_hp(char, 5)
    assert hp == 17
    assert char.current_hp == 17
    assert "17/20 HP" in msg


def test_character_ops_modify_hp_temp_hp_absorption():
    char = CharacterModel(
        discord_user_id="111",
        name="Czarodziej",
        character_class="Wizard",
        race="Elf",
        current_hp=10,
        max_hp=10,
        temp_hp=5
    )
    # Damage 3: fully absorbed by temp HP
    hp, temp, msg = modify_hp(char, -3)
    assert hp == 10
    assert temp == 2
    assert char.current_hp == 10
    assert char.temp_hp == 2

    # Damage 6: absorbs remaining 2 temp HP, 4 goes to current HP
    hp, temp, msg = modify_hp(char, -6)
    assert hp == 6
    assert temp == 0
    assert char.current_hp == 6
    assert char.temp_hp == 0


def test_character_ops_inventory_mutations():
    char = CharacterModel(
        discord_user_id="111",
        name="Łotrzyk",
        character_class="Rogue",
        race="Halfling"
    )
    # Add item
    item = add_inventory_item(char, "Wytrychy", quantity=2)
    assert item.quantity == 2
    assert len(char.inventory) == 1

    # Add same item stacks
    add_inventory_item(char, "Wytrychy", quantity=3)
    assert char.inventory[0].quantity == 5

    # Partial removal
    found, rem = remove_inventory_item(char, "Wytrychy", quantity=2)
    assert found is True
    assert rem.quantity == 3
    assert char.inventory[0].quantity == 3

    # Total removal
    found, rem = remove_inventory_item(char, "Wytrychy", quantity=3)
    assert found is True
    assert rem is None
    assert len(char.inventory) == 0

    # Nonexistent removal
    found, rem = remove_inventory_item(char, "Nieistniejący", quantity=1)
    assert found is False


def test_character_ops_gold_mutations():
    char = CharacterModel(
        discord_user_id="111",
        name="Kupiec",
        character_class="Bard",
        race="Human",
        gold_gp=50
    )
    # Spend gold
    success, new_gold, msg = modify_gold(char, -20)
    assert success is True
    assert new_gold == 30
    assert char.gold_gp == 30

    # Overspend gold
    success, new_gold, msg = modify_gold(char, -100)
    assert success is False
    assert new_gold == 30
    assert "Niewystarczająca ilość" in msg

    # Gain gold
    success, new_gold, msg = modify_gold(char, 100)
    assert success is True
    assert new_gold == 130
    assert char.gold_gp == 130


def test_character_ops_short_and_long_rest():
    char = CharacterModel(
        discord_user_id="111",
        name="Kleryk",
        character_class="Cleric",
        race="Dwarf",
        current_hp=5,
        max_hp=25,
        spell_slots=SpellSlots(level_1=0, level_1_max=4),
        conditions=["Exhaustion"]
    )
    # Short rest with hit dice
    msg_short = short_rest(char, hit_dice_heal=10)
    assert char.current_hp == 15
    assert "15/25 HP" in msg_short

    # Long rest
    msg_long = long_rest(char)
    assert char.current_hp == 25
    assert char.spell_slots.level_1 == 4
    assert len(char.conditions) == 0
    assert "pełni odnowione" in msg_long


def test_character_ops_conditions():
    char = CharacterModel(
        discord_user_id="111",
        name="Wojownik",
        character_class="Fighter",
        race="Human"
    )
    assert add_condition(char, "Oślepiony") is True
    assert add_condition(char, "Oślepiony") is False
    assert "Oślepiony" in char.conditions

    assert remove_condition(char, "Oślepiony") is True
    assert remove_condition(char, "Oślepiony") is False
    assert len(char.conditions) == 0


def test_embeds_dice_roll_embed_crit_badge():
    res_crit = DiceRollResult(
        formula="1d20+3",
        total=23,
        dice_rolls=[20],
        modifier=3,
        is_crit_success=True,
        breakdown="1d20 (20) + 3 = 23"
    )
    embed = create_dice_roll_embed(res_crit, "Artur")
    assert embed.color == discord.Color.green()
    field_names = [f.name for f in embed.fields]
    assert "Efekt Specjalny" in field_names
    special_field = next(f for f in embed.fields if f.name == "Efekt Specjalny")
    assert "KRYTYCZNY SUKCES" in special_field.value


def test_embeds_dice_roll_embed_fail_badge():
    res_fail = DiceRollResult(
        formula="1d20-1",
        total=0,
        dice_rolls=[1],
        modifier=-1,
        is_crit_failure=True,
        breakdown="1d20 (1) - 1 = 0"
    )
    embed = create_dice_roll_embed(res_fail, "Artur")
    assert embed.color == discord.Color.red()
    special_field = next(f for f in embed.fields if f.name == "Efekt Specjalny")
    assert "KRYTYCZNA PORAŻKA" in special_field.value


@pytest.mark.asyncio
async def test_character_sheet_view_buttons(sample_character: CharacterModel):
    view = CharacterSheetView(character=sample_character)
    assert len(view.children) >= 3

    # Test initiative button callback
    interaction = MockInteraction()
    init_btn = next(b for b in view.children if "Inicjatywa" in getattr(b, "label", ""))
    await init_btn.callback(interaction)

    assert interaction.response.is_done() is True
    assert len(interaction.response.sent_messages) == 1
    embed = interaction.response.sent_messages[0].embeds[0]
    assert "Inicjatywa" in embed.title


@pytest.mark.asyncio
async def test_character_cog_hp_and_item_commands(populated_campaign: MockGuild):
    cog = CharacterCog(bot=None)
    user = MockUser(id=101, name="Thorin", display_name="Thorin")
    interaction = MockInteraction(guild=populated_campaign, user=user)

    # Test /hp command
    await cog.change_hp.callback(cog, interaction, wartosc=-4, postac=user, powod="Pułapka")
    assert interaction.response.is_done() is True
    assert len(interaction.followup.sent_messages) == 1
    sent = interaction.followup.sent_messages[0]
    assert "Aktualizacja Zdrowia" in sent.embeds[0].title

    # Test /item add command
    interaction2 = MockInteraction(guild=populated_campaign, user=user)
    await cog.manage_item.callback(cog, interaction2, akcja="add", nazwa="Lochy i Smoki Podręcznik", ilosc=1, postac=user)
    assert interaction2.response.is_done() is True
    assert "Dodano do Ekwipunku" in interaction2.followup.sent_messages[0].embeds[0].title


@pytest.mark.asyncio
async def test_mechanics_cog_roll_and_check_commands(populated_campaign: MockGuild):
    cog = MechanicsCog(bot=None)
    user = MockUser(id=101, name="Thorin", display_name="Thorin")
    interaction = MockInteraction(guild=populated_campaign, user=user)

    # Test /roll command
    await cog.roll_command.callback(cog, interaction, formula="1d20+3", reason="Test Siły", dc=12)
    assert interaction.response.is_done() is True
    assert len(interaction.response.sent_messages) == 1
    embed = interaction.response.sent_messages[0].embeds[0]
    assert "Test Siły" in embed.title

    # Test /check command
    interaction2 = MockInteraction(guild=populated_campaign, user=user)
    await cog.check_command.callback(cog, interaction2, cecha="STR (Siła)", dc=14)
    assert interaction2.response.is_done() is True
    embed2 = interaction2.response.sent_messages[0].embeds[0]
    assert "Test cechy STR" in embed2.title
