"""Mock Gemini AI client for 100% offline testing of D&D DM AI integration.
Supports programmable responses, error injection, action button synthesis, and call auditing.
"""
from __future__ import annotations
import json
import re
from typing import List, Dict, Any, Optional, Tuple, Callable


class MockGeminiError(Exception):
    """Base mock Gemini exception."""
    pass


class MockRateLimitError(MockGeminiError):
    """Simulates HTTP 429 Rate Limit."""
    pass


class MockAPIError(MockGeminiError):
    """Simulates HTTP 500/503 Internal AI Server Error."""
    pass


class MockSafetyFilterError(MockGeminiError):
    """Simulates Gemini Safety/Harm filter blocking output."""
    pass


class MockGeminiClient:
    """Deterministic Mock AI client mimicking Google Gemini 3.7 Flash DM."""

    ACTION_BUTTON_PATTERN = re.compile(r"\[ACTION_BUTTONS:\s*(\[.*?\]|\{.*?\}|.*?\])\s*\]", re.DOTALL)

    def __init__(
        self,
        default_response: Optional[str] = None,
        default_action_buttons: Optional[List[Dict[str, Any]]] = None
    ):
        self.default_response = default_response or (
            "Mistrz Gry: Rozglądasz się po kamiennej sali. Cienie tańczą na ścianach, "
            "a z głębi korytarza słychać cichy szmer.\n\n*Co robicie?*\n\n"
            "[ACTION_BUTTONS: [{\"label\": \"Rzut na Percepcję (WIS +2)\", \"formula\": \"1d20+2\", \"reason\": \"Percepcja\", \"dc\": 13}]]"
        )
        self.default_action_buttons = default_action_buttons or [
            {"label": "Rzut na Percepcję (WIS +2)", "formula": "1d20+2", "reason": "Percepcja", "dc": 13}
        ]
        self._queued_responses: List[Tuple[str, Optional[List[Dict[str, Any]]]]] = []
        self._queued_character_responses: List[Dict[str, Any]] = []
        self._injected_errors: List[Exception] = []
        self._custom_handler: Optional[Callable[[str, Optional[str]], Tuple[str, List[Dict[str, Any]]]]] = None
        
        # Call history for assertions
        self.call_history: List[Dict[str, Any]] = []

    def set_default_response(self, text: str, action_buttons: Optional[List[Dict[str, Any]]] = None) -> None:
        """Sets the fallback response when queue is empty."""
        self.default_response = text
        if action_buttons is not None:
            self.default_action_buttons = action_buttons

    def queue_response(self, text: str, action_buttons: Optional[List[Dict[str, Any]]] = None) -> None:
        """Queues a sequential response for upcoming calls."""
        self._queued_responses.append((text, action_buttons))

    def queue_character_response(self, char_data: Union[Dict[str, Any], str]) -> None:
        """Queues a character response for generate_character calls."""
        if isinstance(char_data, str):
            parsed = json.loads(char_data)
            self._queued_character_responses.append(parsed)
        else:
            self._queued_character_responses.append(char_data)

    def inject_error(self, exc: Exception) -> None:
        """Queues an exception to be raised on the next call."""
        self._injected_errors.append(exc)

    def set_handler(self, handler: Callable[[str, Optional[str]], Tuple[str, List[Dict[str, Any]]]]) -> None:
        """Sets a dynamic handler function based on prompt and system prompt."""
        self._custom_handler = handler

    def reset(self) -> None:
        """Clears all queued responses, errors, and call history."""
        self._queued_responses.clear()
        self._queued_character_responses.clear()
        self._injected_errors.clear()
        self._custom_handler = None
        self.call_history.clear()

    @property
    def call_count(self) -> int:
        return len(self.call_history)

    @property
    def last_call(self) -> Optional[Dict[str, Any]]:
        return self.call_history[-1] if self.call_history else None

    @classmethod
    def extract_action_buttons(cls, raw_text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Extracts [ACTION_BUTTONS: [...]] json block from text and returns clean text + buttons list."""
        match = cls.ACTION_BUTTON_PATTERN.search(raw_text)
        if not match:
            return raw_text.strip(), []
        
        btn_json_str = match.group(1)
        clean_text = cls.ACTION_BUTTON_PATTERN.sub("", raw_text).strip()
        try:
            buttons = json.loads(btn_json_str)
            if isinstance(buttons, list):
                return clean_text, buttons
        except Exception:
            pass
        return clean_text, []

    @classmethod
    def format_narrative_with_buttons(cls, narrative: str, buttons: List[Dict[str, Any]]) -> str:
        """Helper to embed action buttons block in narrative text."""
        btn_json = json.dumps(buttons, ensure_ascii=False)
        return f"{narrative}\n\n[ACTION_BUTTONS: {btn_json}]"

    async def generate_narrative(
        self,
        context_prompt: str,
        system_prompt: Optional[str] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Simulates async generation of DM narrative response and action buttons."""
        # 1. Audit call
        self.call_history.append({
            "type": "narrative",
            "context_prompt": context_prompt,
            "system_prompt": system_prompt
        })

        # 2. Check injected error
        if self._injected_errors:
            err = self._injected_errors.pop(0)
            raise err

        # 3. Custom handler if registered
        if self._custom_handler:
            return self._custom_handler(context_prompt, system_prompt)

        # 4. Check queued response
        if self._queued_responses:
            text, btns = self._queued_responses.pop(0)
            if btns is not None:
                clean_text, parsed_btns = self.extract_action_buttons(text)
                return clean_text, btns or parsed_btns
            clean_text, parsed_btns = self.extract_action_buttons(text)
            return clean_text, parsed_btns

        # 5. Fallback to default
        clean_text, parsed_btns = self.extract_action_buttons(self.default_response)
        buttons = parsed_btns if parsed_btns else self.default_action_buttons
        return clean_text, buttons

    async def generate_character(
        self,
        prompt: str,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """Simulates async generation of structured D&D 5e character JSON."""
        # 1. Audit call
        self.call_history.append({
            "type": "character",
            "prompt": prompt,
            "system_prompt": system_prompt
        })

        # 2. Check injected error
        if self._injected_errors:
            err = self._injected_errors.pop(0)
            raise err

        # 3. Check queued character response
        if self._queued_character_responses:
            return self._queued_character_responses.pop(0)

        # 4. Check general queued responses if contains JSON
        if self._queued_responses:
            text, _ = self._queued_responses.pop(0)
            try:
                clean = text.strip()
                if clean.startswith("```"):
                    clean = re.sub(r"^```(?:json)?\s*", "", clean)
                    clean = re.sub(r"\s*```$", "", clean)
                return json.loads(clean)
            except Exception:
                pass

        # 5. Fallback deterministic character
        from ai.gemini_client import GeminiClient
        return GeminiClient()._generate_offline_character(prompt)


def split_long_message(text: str, limit: int = 1900) -> List[str]:
    """Smart paragraph message splitter that chunks long text (>2000 chars)
    along paragraph and sentence boundaries without breaking words or markdown.
    """
    if not text or not text.strip():
        return []
    if len(text) <= limit:
        return [text.strip()]

    chunks: List[str] = []
    # Split by double newline first (paragraphs)
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for p in paragraphs:
        p_clean = p.strip()
        if not p_clean:
            continue
        
        # If single paragraph exceeds limit, split by single newline or sentence
        if len(p_clean) > limit:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            
            sentences = re.split(r"(?<=[.!?])\s+", p_clean)
            sub_chunk = ""
            for s in sentences:
                if len(s) > limit:
                    # Hard break if a single giant token
                    if sub_chunk:
                        chunks.append(sub_chunk.strip())
                        sub_chunk = ""
                    for i in range(0, len(s), limit):
                        chunks.append(s[i:i + limit].strip())
                elif len(sub_chunk) + len(s) + 1 <= limit:
                    sub_chunk = f"{sub_chunk} {s}".strip()
                else:
                    chunks.append(sub_chunk.strip())
                    sub_chunk = s
            if sub_chunk:
                chunks.append(sub_chunk.strip())
        elif len(current_chunk) + len(p_clean) + 2 <= limit:
            current_chunk = f"{current_chunk}\n\n{p_clean}".strip()
        else:
            chunks.append(current_chunk.strip())
            current_chunk = p_clean

    if current_chunk:
        chunks.append(current_chunk.strip())

    return [c for c in chunks if c]
