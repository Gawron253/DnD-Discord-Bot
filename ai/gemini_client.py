"""Moduł integracji z modelem Google Gemini 3.7 Flash (google-genai SDK).
Obsługuje 4-warstwowe składanie promptu, hybrydowe wnioskowanie (ThinkingConfig / thinking_budget),
niestandardowe progi bezpieczeństwa dla RPG, temperaturę 0.70,
ekstrakcję przycisków akcji [ACTION_BUTTONS: [...]] oraz tryb offline/mock.
"""
from __future__ import annotations
import os
import re
import json
import logging
from typing import List, Dict, Any, Optional, Tuple

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai = None
    types = None

from config.settings import settings
from config.prompts import DUNGEON_MASTER_SYSTEM_PROMPT
from ai.message_splitter import split_long_message

logger = logging.getLogger("GeminiClient")

# Regex do wykrywania i parsowania bloku przycisków akcji z odpowiedzi AI
ACTION_BUTTON_PATTERN = re.compile(
    r"\[ACTION_BUTTONS:\s*(\[.*?\]|\{.*?\}|.*?\])\s*\]",
    re.DOTALL
)

# Rozszerzenie promptu systemowego o instrukcję generowania przycisków akcji
ACTION_BUTTONS_SYSTEM_INSTRUCTION = """
ZASADA PRZYCISKÓW AKCJI (ACTION BUTTONS):
Gdy opisana sytuacja wymaga od gracza lub drużyny wykonania rzutu (np. test umiejętności, rzut obronny, rzut na atak, percepcja, akrobatyka itp.), ZAWSZE na samym końcu odpowiedzi dołącz blok JSON w formacie:
[ACTION_BUTTONS: [
  {"label": "Rzut na Percepcję (WIS +2)", "formula": "1d20+2", "reason": "Test Percepcji", "dc": 13},
  {"label": "Rzut na Skradanie (DEX +3)", "formula": "1d20+3", "reason": "Test Skradania", "dc": 14}
]]
Jeśli żaden rzut nie jest wymagany (np. spokojny dialog, bezpieczny odpoczynek), NIE dodawaj bloku [ACTION_BUTTONS].
"""


def extract_action_buttons(raw_text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Wyodrębnia blok [ACTION_BUTTONS: [...]] z tekstu narracji.
    Zwraca czysty tekst narracji oraz listę słowników ze specyfikacją przycisków.
    """
    if not raw_text:
        return "", []

    match = ACTION_BUTTON_PATTERN.search(raw_text)
    if not match:
        return raw_text.strip(), []

    btn_json_str = match.group(1).strip()
    clean_text = ACTION_BUTTON_PATTERN.sub("", raw_text).strip()

    try:
        buttons = json.loads(btn_json_str)
        if isinstance(buttons, list):
            # Walidacja i normalizacja każdego przycisku
            validated = []
            for b in buttons:
                if isinstance(b, dict):
                    validated.append({
                        "label": str(b.get("label", "Rzut")),
                        "formula": str(b.get("formula", "1d20")),
                        "reason": str(b.get("reason", "Test")),
                        "dc": int(b["dc"]) if b.get("dc") is not None and str(b["dc"]).isdigit() else None
                    })
            return clean_text, validated
        elif isinstance(buttons, dict):
            return clean_text, [buttons]
    except Exception as e:
        logger.warning(f"Nie udało się sparsować bloku ACTION_BUTTONS JSON: {e}")

    return clean_text, []


def format_narrative_with_buttons(narrative: str, buttons: List[Dict[str, Any]]) -> str:
    """Pomocnik dołączający blok akcji do tekstu narracji w celach testowych / mockowych."""
    if not buttons:
        return narrative.strip()
    btn_json = json.dumps(buttons, ensure_ascii=False)
    return f"{narrative.strip()}\n\n[ACTION_BUTTONS: {btn_json}]"


def build_4layer_prompt(
    rules: str = "",
    characters: Optional[List[Dict[str, Any]]] = None,
    events: str = "",
    custom_system_prompt: Optional[str] = None
) -> Tuple[str, str]:
    """
    Składa hierarchiczny, 4-warstwowy prompt dla AI Dungeon Mastera:
    1. Warstwa 1: System Persona (Rola DM + zasady + format przycisków)
    2. Warstwa 2: Live Campaign Rules & World Lore (z #zasady-i-mechanika)
    3. Warstwa 3: Drużyna i karty postaci graczy (z #karty-postaci)
    4. Warstwa 4: Delta sesji / historia czatu i wyniki rzutów (z #stół-gry i #rzuty-kości)

    Returns:
        Tuple[system_instruction, context_prompt]
    """
    # 1. Warstwa 1: System Instruction
    base_system = custom_system_prompt or DUNGEON_MASTER_SYSTEM_PROMPT
    system_instruction = f"{base_system.strip()}\n\n{ACTION_BUTTONS_SYSTEM_INSTRUCTION.strip()}"

    # 2. Warstwa 2: Zasady i Mechanika
    rules_text = rules.strip() if rules else "Standardowe zasady D&D 5e."
    layer_2 = f"=== [WARSTWA 2: AKTUALNE ZASADY KAMPANII I HOMEBREW] ===\n{rules_text}"

    # 3. Warstwa 3: Karty Postaci
    char_lines = []
    if characters:
        for c in characters:
            name = c.get("name", "Bohater")
            cls_name = c.get("character_class", "Poszukiwacz")
            lvl = c.get("level", 1)
            hp = f"{c.get('current_hp', 10)}/{c.get('max_hp', 10)} HP"
            ac = c.get("armor_class", 10)
            stats = c.get("stats", {})
            stat_str = ", ".join(f"{k.upper()}:{v}" for k, v in stats.items()) if isinstance(stats, dict) else ""
            inv = ", ".join(i.get("name", "") for i in c.get("inventory", [])) if c.get("inventory") else "Standardowy"
            char_lines.append(f"• **{name}** (Poz. {lvl} {cls_name}) | HP: {hp} | AC: {ac} | Cechy: [{stat_str}] | Ekwipunek: [{inv}]")
    characters_text = "\n".join(char_lines) if char_lines else "*Brak zarejestrowanych kart postaci w forum.*"
    layer_3 = f"=== [WARSTWA 3: DRUŻYNA I AKTYWNE KARTY POSTACI] ===\n{characters_text}"

    # 4. Warstwa 4: Zdarzenia i deklaracje graczy od poprzedniej tury
    events_text = events.strip() if events else "*Brak nowych deklaracji graczy.*"
    layer_4 = f"=== [WARSTWA 4: NOWE ZDARZENIA, DEKLARACJE GRACZY I RZUTY KOŚĆMI] ===\n{events_text}"

    context_prompt = f"{layer_2}\n\n{layer_3}\n\n{layer_4}\n\n=== [POLECENIE DLA MISTRZA GRY] ===\nOpisz konsekwencje powyższych deklaracji i rzutów, rozwiń scenę i zakończ pytaniem do drużyny oraz odpowiednimi przyciskami rzutów [ACTION_BUTTONS], jeśli to konieczne."

    return system_instruction, context_prompt


def get_rpg_safety_settings() -> List[Any]:
    """
    Zwraca zoptymalizowane pod sesje RPG ustawienia filtrów bezpieczeństwa Gemini.
    Zapobiega blokowaniu opisów walki fantasy, obrażeń, potworów i mrocznego klimatu.
    """
    if not GENAI_AVAILABLE or not types:
        return []

    return [
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH
        ),
    ]


class GeminiClient:
    """
    Klient AI Gemini 3.7 Flash dla Discordowego Mistrza Gry.
    Obsługuje hybrydowe wnioskowanie (ThinkingConfig / thinking_budget),
    rzeczywiste wywołania API przez `google-genai` SDK,
    automatyczny fallback na offline mock przy braku klucza API,
    oraz testowe mocki.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        thinking_budget: Optional[int] = None,
        include_thoughts: Optional[bool] = None,
        mock_client: Optional[Any] = None
    ):
        self.api_key = api_key or settings.gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model or settings.default_ai_model or "gemini-3.7-flash"
        self.temperature = temperature if temperature is not None else settings.gemini_temperature
        self.thinking_budget = thinking_budget if thinking_budget is not None else settings.gemini_thinking_budget
        self.include_thoughts = include_thoughts if include_thoughts is not None else settings.gemini_include_thoughts
        self.mock_client = mock_client
        self._genai_client = None

        if self.api_key and GENAI_AVAILABLE and not self.is_dummy_key(self.api_key):
            try:
                self._genai_client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Nie udało się zainicjalizować klienta google.genai: {e}")

    @staticmethod
    def is_dummy_key(key: str) -> bool:
        """Sprawdza czy klucz API to atrapa/placeholder."""
        if not key:
            return True
        key_lower = key.lower().strip()
        dummy_markers = ["your_gemini_api_key", "fake_key", "test_key", "mock", "placeholder", "xxx"]
        return any(m in key_lower for m in dummy_markers)

    async def generate_narrative(
        self,
        context_prompt: str,
        system_prompt: Optional[str] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Generuje narrację Mistrza Gry na podstawie przekazanego kontekstu i promptu systemowego.
        Zwraca wyczyszczony tekst odpowiedzi oraz wyekstrahowaną listę dynamicznych przycisków akcji.
        """
        # 1. Sprawdzenie czy zarejestrowano dedykowany mock testowy
        if self.mock_client is not None:
            return await self.mock_client.generate_narrative(context_prompt, system_prompt)

        # 2. Rzeczywiste wywołanie Google Gemini 3.7 Flash przez google-genai SDK
        if self._genai_client is not None and GENAI_AVAILABLE:
            try:
                full_system = system_prompt or DUNGEON_MASTER_SYSTEM_PROMPT
                if "[ACTION_BUTTONS" not in full_system:
                    full_system = f"{full_system}\n\n{ACTION_BUTTONS_SYSTEM_INSTRUCTION}"

                # Konfiguracja ThinkingConfig dla Gemini 3.7 Flash
                thinking_config = None
                if types and hasattr(types, "ThinkingConfig"):
                    t_budget = self.thinking_budget if self.thinking_budget is not None else settings.gemini_thinking_budget
                    inc_thoughts = self.include_thoughts if self.include_thoughts is not None else settings.gemini_include_thoughts
                    if t_budget is not None:
                        thinking_config = types.ThinkingConfig(
                            thinking_budget=t_budget,
                            include_thoughts=inc_thoughts
                        )

                config = types.GenerateContentConfig(
                    system_instruction=full_system,
                    temperature=self.temperature,
                    safety_settings=get_rpg_safety_settings(),
                    thinking_config=thinking_config
                )

                # Asynchroniczne wywołanie Gemini 3.7 Flash
                response = await self._genai_client.aio.models.generate_content(
                    model=self.model,
                    contents=context_prompt,
                    config=config
                )

                raw_text = response.text or ""
                return extract_action_buttons(raw_text)

            except Exception as e:
                logger.error(f"Błąd podczas generowania narracji przez Gemini API ({self.model}): {e}. Używam fallbacku.")

        # 3. Deterministic Offline Fallback dla środowisk bez klucza Gemini / offline
        return self._generate_offline_fallback(context_prompt)

    def _generate_offline_fallback(self, context_prompt: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Generuje deterministyczną, klimatyczną odpowiedź offline DM z dopasowanymi przyciskami."""
        ctx_lower = context_prompt.lower()

        if "drzwi" in ctx_lower or "zamek" in ctx_lower or "otwier" in ctx_lower:
            text = (
                "**Mistrz Gry:** Zbliżasz się do ciężkich, okutych żelazem drzwi. "
                "Mechanizm zamka pokryty jest runami ochronnymi, a w szczelinie dostrzegasz delikatną zapadkę pułapki.\n\n"
                "*Co robicie dalej?*"
            )
            buttons = [
                {"label": "Otwórz zamek (DEX +2)", "formula": "1d20+2", "reason": "Otwieranie Zamka", "dc": 13},
                {"label": "Wyważ drzwi (STR +3)", "formula": "1d20+3", "reason": "Wyważanie Drzwi", "dc": 15}
            ]
        elif "atak" in ctx_lower or "goblin" in ctx_lower or "walka" in ctx_lower or "miecz" in ctx_lower:
            text = (
                "**Mistrz Gry:** Przeciwnik dostrzega Twój ruch i z gardłowym wrzaskiem unosi broń do uderzenia! "
                "W powietrzu unosi się zapach prochu i ozonu.\n\n"
                "*Jak reagujesz?*"
            )
            buttons = [
                {"label": "Atak bronią (STR +3)", "formula": "1d20+3", "reason": "Atak w walce", "dc": 12},
                {"label": "Unik i zasłona (DEX +2)", "formula": "1d20+2", "reason": "Obrona", "dc": 11}
            ]
        elif "percepcja" in ctx_lower or "rozgląd" in ctx_lower or "szuk" in ctx_lower or "badam" in ctx_lower:
            text = (
                "**Mistrz Gry:** Wytężasz wzrok i słuch. Wśród kapiących kropel wody i cieni rzucanych przez pochodnię "
                "zauważasz podejrzane zarysowania na kamiennej posadzce.\n\n"
                "*Co robicie?*"
            )
            buttons = [
                {"label": "Rzut na Percepcję (WIS +2)", "formula": "1d20+2", "reason": "Test Percepcji", "dc": 12},
                {"label": "Rzut na Śledztwo (INT +1)", "formula": "1d20+1", "reason": "Badanie Śladów", "dc": 13}
            ]
        else:
            text = (
                "**Mistrz Gry:** Rozglądacie się po otoczeniu. Płomienie pochodni tańczą na wilgotnych ścianach, "
                "a w powietrzu czuć chłód i echo minionych wieków.\n\n"
                "*Co robicie dalej?*"
            )
            buttons = [
                {"label": "Rzut na Percepcję (WIS +2)", "formula": "1d20+2", "reason": "Percepcja", "dc": 13}
            ]

        return text, buttons


# Instancja globalnego klienta domyślnego
default_gemini_client = GeminiClient()


async def generate_narrative(
    context_prompt: str,
    system_prompt: Optional[str] = None,
    client: Optional[GeminiClient] = None
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Główny interfejs generowania narracji z dynamicznymi przyciskami akcji.
    """
    active_client = client or default_gemini_client
    return await active_client.generate_narrative(context_prompt, system_prompt)
