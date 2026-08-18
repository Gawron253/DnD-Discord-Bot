"""Unit and integration tests for Google Gemini 2.0 Flash Client (ai/gemini_client.py)."""
import pytest
from ai.gemini_client import (
    GeminiClient,
    extract_action_buttons,
    format_narrative_with_buttons,
    build_4layer_prompt,
    get_rpg_safety_settings,
    generate_narrative
)
from tests.mock_ai import MockGeminiClient


def test_extract_action_buttons_valid_single():
    raw = (
        "Widzisz zarys potwora w mroku.\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Rzut na Inicjatywę (DEX +2)\", \"formula\": \"1d20+2\", \"reason\": \"Inicjatywa\", \"dc\": 10}]]"
    )
    clean, btns = extract_action_buttons(raw)
    assert clean == "Widzisz zarys potwora w mroku."
    assert len(btns) == 1
    assert btns[0]["label"] == "Rzut na Inicjatywę (DEX +2)"
    assert btns[0]["formula"] == "1d20+2"
    assert btns[0]["dc"] == 10


def test_extract_action_buttons_multiple():
    raw = (
        "Przed tobą rozpościera się przepaść.\n\n"
        "[ACTION_BUTTONS: ["
        "{\"label\": \"Skok (STR +3)\", \"formula\": \"1d20+3\", \"reason\": \"Skok\", \"dc\": 14},"
        "{\"label\": \"Rzut liną (DEX +1)\", \"formula\": \"1d20+1\", \"reason\": \"Lina\", \"dc\": 12}"
        "]]"
    )
    clean, btns = extract_action_buttons(raw)
    assert len(btns) == 2
    assert btns[0]["label"] == "Skok (STR +3)"
    assert btns[1]["label"] == "Rzut liną (DEX +1)"
    assert "[ACTION_BUTTONS:" not in clean


def test_extract_action_buttons_no_tag():
    raw = "Karczmarz nalewa wam zimnego piwa i opowiada o smokach."
    clean, btns = extract_action_buttons(raw)
    assert clean == raw
    assert btns == []


def test_extract_action_buttons_malformed_json():
    raw = "Coś się dzieje.\n\n[ACTION_BUTTONS: {niepoprawny json}]"
    clean, btns = extract_action_buttons(raw)
    assert clean == "Coś się dzieje."
    assert btns == []


def test_format_narrative_with_buttons():
    narrative = "Spotykacie strażnika."
    buttons = [{"label": "Perswazja (CHA +3)", "formula": "1d20+3", "reason": "Perswazja", "dc": 15}]
    formatted = format_narrative_with_buttons(narrative, buttons)
    assert "[ACTION_BUTTONS:" in formatted
    assert "Perswazja (CHA +3)" in formatted

    clean, parsed = extract_action_buttons(formatted)
    assert clean == narrative
    assert len(parsed) == 1


def test_build_4layer_prompt_structure():
    rules = "D&D 5e Hardcore, brak wskrzeszania."
    characters = [
        {"name": "Thorin", "character_class": "Wojownik", "level": 3, "current_hp": 28, "max_hp": 28, "armor_class": 16}
    ]
    events = "[Thorin]: Wchodzę pierwszy z uniesionym toporem."

    sys_prompt, ctx_prompt = build_4layer_prompt(rules, characters, events)

    # Sprawdzenie warstw w promptach
    assert "Dungeon Master" in sys_prompt
    assert "ACTION_BUTTONS" in sys_prompt
    assert "WARSTWA 2" in ctx_prompt
    assert "D&D 5e Hardcore" in ctx_prompt
    assert "WARSTWA 3" in ctx_prompt
    assert "Thorin" in ctx_prompt
    assert "WARSTWA 4" in ctx_prompt
    assert "Wchodzę pierwszy" in ctx_prompt


def test_rpg_safety_settings_configured():
    settings_list = get_rpg_safety_settings()
    assert isinstance(settings_list, list)
    if settings_list:
        assert len(settings_list) >= 4


@pytest.mark.asyncio
async def test_gemini_client_with_mock_client():
    mock = MockGeminiClient()
    mock.queue_response(
        "Mistrz Gry: Smok zieje ogniem!\n\n"
        "[ACTION_BUTTONS: [{\"label\": \"Rzut obronny na Zręczność (DEX +2)\", \"formula\": \"1d20+2\", \"reason\": \"Obrona przed Ogniem\", \"dc\": 15}]]"
    )
    client = GeminiClient(mock_client=mock)
    text, buttons = await client.generate_narrative("Smok atakuje!")

    assert "Smok zieje ogniem!" in text
    assert len(buttons) == 1
    assert buttons[0]["label"] == "Rzut obronny na Zręczność (DEX +2)"
    assert buttons[0]["dc"] == 15


@pytest.mark.asyncio
async def test_gemini_client_offline_fallback_door_context():
    # Test klienta bez klucza API w trybie offline fallback
    client = GeminiClient(api_key="")
    text, buttons = await client.generate_narrative("Próbujemy otworzyć żelazne drzwi do lochu.")

    assert "drzwi" in text.lower() or "zamek" in text.lower() or "Mistrz Gry" in text
    assert len(buttons) >= 1
    assert any("drzwi" in b.get("reason", "").lower() or "zamek" in b.get("reason", "").lower() for b in buttons)


@pytest.mark.asyncio
async def test_gemini_client_offline_fallback_combat_context():
    client = GeminiClient(api_key="")
    text, buttons = await client.generate_narrative("Goblin wyciąga miecz i szykuje atak!")

    assert len(buttons) >= 1
    assert any("atak" in b.get("reason", "").lower() or "obrona" in b.get("reason", "").lower() for b in buttons)


@pytest.mark.asyncio
async def test_generate_narrative_wrapper_function():
    mock = MockGeminiClient()
    mock.queue_response("Narracja testowa z funkcji pomocniczej.")
    custom_client = GeminiClient(mock_client=mock)

    text, btns = await generate_narrative("Idziemy dalej.", client=custom_client)
    assert text == "Narracja testowa z funkcji pomocniczej."


def test_gemini_3_7_flash_default_model():
    client = GeminiClient()
    assert client.model == "gemini-3.7-flash"
    assert client.thinking_budget == 0
    assert client.include_thoughts is False


def test_gemini_3_7_flash_custom_thinking_budget():
    client_dynamic = GeminiClient(thinking_budget=-1, include_thoughts=True)
    assert client_dynamic.thinking_budget == -1
    assert client_dynamic.include_thoughts is True

    client_deep = GeminiClient(thinking_budget=2048)
    assert client_deep.thinking_budget == 2048


def test_gemini_3_7_flash_custom_model_and_temperature():
    client = GeminiClient(model="gemini-3.7-flash", temperature=0.85)
    assert client.model == "gemini-3.7-flash"
    assert client.temperature == 0.85
