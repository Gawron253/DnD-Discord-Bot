"""Moduł integracji z modelem Google Gemini 3.7 Flash (google-genai SDK).
Obsługuje 4-warstwowe składanie promptu, hybrydowe wnioskowanie (ThinkingConfig / thinking_budget),
niestandardowe progi bezpieczeństwa dla RPG, temperaturę 0.70,
ekstrakcję przycisków akcji [ACTION_BUTTONS: [...]] oraz tryb offline/mock.
"""
from __future__ import annotations
import os
import re
import json
import asyncio
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
from config.prompts import DUNGEON_MASTER_SYSTEM_PROMPT, CHARACTER_GENERATOR_SYSTEM_PROMPT
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
    layer_4 = f"=== [WARSTWA 4: HISTORIA SESJI, NOWE ZDARZENIA, DEKLARACJE GRACZY I RZUTY KOŚĆMI] ===\n{events_text}"

    context_prompt = (
        f"{layer_2}\n\n{layer_3}\n\n{layer_4}\n\n"
        f"=== [INSTRUKCJE DLA MISTRZA GRY] ===\n"
        f"1. Jeśli w Warstwie 4 znajduje się rzut kością (sukces lub porażka), opisz NATYCHMIAST efekt tego rzutu (co bohater dostrzegł, czy zdołał się ukryć/obronić/wyważyć drzwi). Zgodnie z wynikiem rzutu rozstrzygnij tę akcję i NIE każ graczowi powtarzać tego samego rzutu!\n"
        f"2. Płynnie kontynuuj scenę i rozwijaj sytuację na podstawie poprzedniej narracji (nie zaczynaj nowej opowieści od zera, chyba że nastąpiła wyraźna zmiana lokacji/czasu).\n"
        f"3. Zakończ turę pytaniem 'Co robicie?' i zaproponuj kolejne opcje działania z przyciskami [ACTION_BUTTONS] dla NOWYCH możliwych testów (np. Inicjatywa, Atak, Skradanie, Otwieranie zamka)."
    )

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
        self.api_key = api_key if api_key is not None else (settings.gemini_api_key or os.getenv("GEMINI_API_KEY", ""))
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

        # 2. Rzeczywiste wywołanie Google Gemini przez google-genai SDK
        if self._genai_client is not None and GENAI_AVAILABLE:
            models_to_try = [self.model]
            for fallback_cand in ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash"]:
                if fallback_cand not in models_to_try:
                    models_to_try.append(fallback_cand)

            last_error = None
            for current_model in models_to_try:
                for attempt in range(2):
                    try:
                        full_system = system_prompt or DUNGEON_MASTER_SYSTEM_PROMPT
                        if "[ACTION_BUTTONS" not in full_system:
                            full_system = f"{full_system}\n\n{ACTION_BUTTONS_SYSTEM_INSTRUCTION}"

                        # Konfiguracja ThinkingConfig dla modeli wspierających (np. Gemini 3.x / 2.5)
                        thinking_config = None
                        if ("3." in current_model or "2.5" in current_model) and types and hasattr(types, "ThinkingConfig"):
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

                        # Asynchroniczne wywołanie Gemini API
                        response = await self._genai_client.aio.models.generate_content(
                            model=current_model,
                            contents=context_prompt,
                            config=config
                        )

                        raw_text = response.text or ""
                        if raw_text:
                            return extract_action_buttons(raw_text)

                    except Exception as e:
                        last_error = e
                        err_str = str(e)
                        logger.warning(f"Próba {attempt+1} z modelem {current_model} napotkała błąd: {e}")
                        # W przypadku przeciążenia serwera (503 / 429) poczekaj przed ponowieniem
                        if "503" in err_str or "429" in err_str or "unavailable" in err_str.lower():
                            await asyncio.sleep(1.0)
                            continue
                        else:
                            # Inny błąd (np. brak uprawnień 403 do danego modelu) - wypróbuj kolejny model z listy
                            break

            if last_error:
                logger.error(f"Wszystkie próby wywołania modeli Gemini zakończone błędem: {last_error}. Używam fallbacku.")

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

    def _generate_offline_character(self, prompt: str) -> Dict[str, Any]:
        """Generuje deterministyczną, poprawną postać D&D 5e Level 1 dla środowisk offline."""
        p_lower = prompt.lower()
        if "mag" in p_lower or "czarodziej" in p_lower or "wizard" in p_lower or "czar" in p_lower:
            return {
                "name": "Elora Gwiazda Zmierzchu",
                "race": "Elf",
                "character_class": "Mag",
                "level": 1,
                "current_hp": 8,
                "max_hp": 8,
                "temp_hp": 0,
                "armor_class": 12,
                "speed": 30,
                "proficiency_bonus": 2,
                "stats": {
                    "strength": 8,
                    "dexterity": 14,
                    "constitution": 14,
                    "intelligence": 16,
                    "wisdom": 12,
                    "charisma": 10
                },
                "spell_slots": {
                    "level_1": 2,
                    "level_1_max": 2,
                    "level_2": 0,
                    "level_2_max": 0,
                    "level_3": 0,
                    "level_3_max": 0
                },
                "inventory": [
                    {"name": "Kostur czarodzieja", "quantity": 1, "item_type": "weapon"},
                    {"name": "Księga czarów", "quantity": 1, "item_type": "equipment"},
                    {"name": "Zestaw uczonego", "quantity": 1, "item_type": "equipment"}
                ],
                "spells": ["Magiczny Pocisk", "Tarcza", "Promień Mrozu", "Światło"],
                "gold_gp": 20,
                "conditions": [],
                "backstory": "Urodzona w odległych lasach elfiego królestwa, od dzieciństwa wykazywała niezwykły talent do splatania magii arkanów. Opuściła rodzinną wieżę, by badać starożytne ruiny i odkrywać zapomnianą wiedzę.",
                "bio": "Urodzona w odległych lasach elfiego królestwa, od dzieciństwa wykazywała niezwykły talent do splatania magii arkanów. Opuściła rodzinną wieżę, by badać starożytne ruiny i odkrywać zapomnianą wiedzę."
            }
        elif "łotr" in p_lower or "rogue" in p_lower or "złodziej" in p_lower or "skradan" in p_lower:
            return {
                "name": "Kael Cichy Krok",
                "race": "Niziołek",
                "character_class": "Łotr",
                "level": 1,
                "current_hp": 10,
                "max_hp": 10,
                "temp_hp": 0,
                "armor_class": 14,
                "speed": 25,
                "proficiency_bonus": 2,
                "stats": {
                    "strength": 10,
                    "dexterity": 16,
                    "constitution": 14,
                    "intelligence": 13,
                    "wisdom": 12,
                    "charisma": 10
                },
                "spell_slots": {
                    "level_1": 0,
                    "level_1_max": 0,
                    "level_2": 0,
                    "level_2_max": 0,
                    "level_3": 0,
                    "level_3_max": 0
                },
                "inventory": [
                    {"name": "Rapier", "quantity": 1, "item_type": "weapon"},
                    {"name": "Krótki łuk", "quantity": 1, "item_type": "weapon"},
                    {"name": "Narzędzia złodziejskie", "quantity": 1, "item_type": "equipment"},
                    {"name": "Zbroja skórzana", "quantity": 1, "item_type": "armor"}
                ],
                "spells": [],
                "gold_gp": 25,
                "conditions": [],
                "backstory": "Wychowany w krętych zaułkach portowego miasta, nauczył się, że zręczne palce i cichy krok są cenniejsze niż całe złoto świata. Teraz szuka fortuny w niebezpiecznych wyprawach.",
                "bio": "Wychowany w krętych zaułkach portowego miasta, nauczył się, że zręczne palce i cichy krok są cenniejsze niż całe złoto świata. Teraz szuka fortuny w niebezpiecznych wyprawach."
            }
        elif "krasnolud" in p_lower or "barbar" in p_lower or "topór" in p_lower:
            return {
                "name": "Balgor Żelazny Topór",
                "race": "Krasnolud",
                "character_class": "Wojownik",
                "level": 1,
                "current_hp": 13,
                "max_hp": 13,
                "temp_hp": 0,
                "armor_class": 15,
                "speed": 25,
                "proficiency_bonus": 2,
                "stats": {
                    "strength": 16,
                    "dexterity": 12,
                    "constitution": 16,
                    "intelligence": 10,
                    "wisdom": 12,
                    "charisma": 8
                },
                "spell_slots": {
                    "level_1": 0,
                    "level_1_max": 0,
                    "level_2": 0,
                    "level_2_max": 0,
                    "level_3": 0,
                    "level_3_max": 0
                },
                "inventory": [
                    {"name": "Topór bojowy", "quantity": 1, "item_type": "weapon"},
                    {"name": "Tarcza", "quantity": 1, "item_type": "armor"},
                    {"name": "Kolczuga", "quantity": 1, "item_type": "armor"},
                    {"name": "Plecak podróżny", "quantity": 1, "item_type": "equipment"}
                ],
                "spells": [],
                "gold_gp": 15,
                "conditions": [],
                "backstory": "Dumny wojownik z klanu Żelaznego Szczytu. Po upadku jego rodzinnej twierdzy poprzysiągł odzyskać rodowe dziedzictwo i pomścić poległych towarzyszy broni.",
                "bio": "Dumny wojownik z klanu Żelaznego Szczytu. Po upadku jego rodzinnej twierdzy poprzysiągł odzyskać rodowe dziedzictwo i pomścić poległych towarzyszy broni."
            }
        else:
            return {
                "name": "Valerius Mężny",
                "race": "Człowiek",
                "character_class": "Paladyn",
                "level": 1,
                "current_hp": 12,
                "max_hp": 12,
                "temp_hp": 0,
                "armor_class": 16,
                "speed": 30,
                "proficiency_bonus": 2,
                "stats": {
                    "strength": 16,
                    "dexterity": 10,
                    "constitution": 14,
                    "intelligence": 10,
                    "wisdom": 12,
                    "charisma": 14
                },
                "spell_slots": {
                    "level_1": 0,
                    "level_1_max": 0,
                    "level_2": 0,
                    "level_2_max": 0,
                    "level_3": 0,
                    "level_3_max": 0
                },
                "inventory": [
                    {"name": "Miecz długi", "quantity": 1, "item_type": "weapon"},
                    {"name": "Tarcza", "quantity": 1, "item_type": "armor"},
                    {"name": "Kolczuga", "quantity": 1, "item_type": "armor"},
                    {"name": "Święty symbol", "quantity": 1, "item_type": "equipment"}
                ],
                "spells": [],
                "gold_gp": 15,
                "conditions": [],
                "backstory": "Młody rycerz zakonu Świetlistego Brzasku. Wyruszył w świat z przysięgą obrony niewinnych i niesienia sprawiedliwości w najmroczniejszych zakątkach krainy.",
                "bio": "Młody rycerz zakonu Świetlistego Brzasku. Wyruszył w świat z przysięgą obrony niewinnych i niesienia sprawiedliwości w najmroczniejszych zakątkach krainy."
            }

    async def generate_character(
        self,
        prompt: str,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generuje zbalansowaną postać D&D 5e na podstawie promptu użytkownika.
        Zwraca sparsowany słownik danych zgodny z CharacterModel.
        """
        # 1. Sprawdź zarejestrowany mock testowy
        if self.mock_client is not None:
            if hasattr(self.mock_client, "generate_character"):
                return await self.mock_client.generate_character(prompt)
            elif hasattr(self.mock_client, "generate_narrative"):
                text, _ = await self.mock_client.generate_narrative(prompt, system_prompt)
                try:
                    return json.loads(text)
                except Exception:
                    pass

        # 2. Rzeczywiste wywołanie Gemini API
        if self._genai_client is not None and GENAI_AVAILABLE:
            models_to_try = [self.model]
            for fallback_cand in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
                if fallback_cand not in models_to_try:
                    models_to_try.append(fallback_cand)

            last_error = None
            for current_model in models_to_try:
                for attempt in range(2):
                    try:
                        full_system = system_prompt or CHARACTER_GENERATOR_SYSTEM_PROMPT

                        thinking_config = None
                        if ("3.7" in current_model or "2.5" in current_model) and types and hasattr(types, "ThinkingConfig"):
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

                        response = await self._genai_client.aio.models.generate_content(
                            model=current_model,
                            contents=prompt,
                            config=config
                        )

                        raw_text = (response.text or "").strip()
                        if raw_text.startswith("```"):
                            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                            raw_text = re.sub(r"\s*```$", "", raw_text)

                        parsed = json.loads(raw_text)
                        if isinstance(parsed, dict):
                            return parsed

                    except Exception as e:
                        last_error = e
                        err_str = str(e)
                        logger.warning(f"Próba {attempt+1} generowania postaci z modelem {current_model} napotkała błąd: {e}")
                        if "503" in err_str or "429" in err_str or "unavailable" in err_str.lower():
                            await asyncio.sleep(1.0)
                            continue
                        else:
                            break

            if last_error:
                logger.error(f"Generowanie postaci przez Gemini zakończone błędem: {last_error}. Używam fallbacku.")

        # 3. Deterministic offline fallback
        return self._generate_offline_character(prompt)


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


async def generate_character(
    prompt: str,
    system_prompt: Optional[str] = None,
    client: Optional[GeminiClient] = None
) -> Dict[str, Any]:
    """
    Główny interfejs generowania postaci przez AI.
    """
    active_client = client or default_gemini_client
    return await active_client.generate_character(prompt, system_prompt)
