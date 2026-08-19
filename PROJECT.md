# Project: DnD AI Discord Bot — Character Creation & Editing Suite

## Architecture
- **Core Engine**: Pure Discord DB (`core/discord_db.py`) utilizing `#karty-postaci` forum channels, threads, pinned embeds, and message metadata as the single source of truth with 24h auto-unarchiving.
- **Data Models**: Pydantic models in `core/models.py` (`CharacterModel`, `StatBlock`, `ItemModel`, `SpellSlots`) extended with `backstory`, `bio`, `spells`, `background`, and `alignment`.
- **UI Components**: `discord_ui/embeds.py` and `discord_ui/views.py` with clean embed rendering (no visible `DATA_JSON` metadata in user-facing descriptions), `CharacterCreateModal`, `CharacterEditModal`, `CharacterSheetView`.
- **AI Integration**: `ai/gemini_client.py` using Gemini 3.7 Flash (`config/settings.py`, `config/prompts.py`) with structured JSON schema extraction, RPG safety filters, and deterministic offline fallback.
- **Commands**: `commands/character_cog.py` hosting `/sheet`, `/hp`, `/item`, `/gold`, `/rest`, and the new `/create-character`, `/generate-character`, `/character-edit`.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Clean Embeds & DATA_JSON Hiding (R1) | Eliminate raw `<!-- DATA_JSON: ... -->` from visible embed description, display clean backstory/bio, persist state in message content / steganographic metadata, maintain 100% backward compatible extraction | M1 | ORIGINAL_REQUEST §R1 |
| F2 | Model Extensions (R1/R2/R3/R4) | Add `backstory`, `bio`, `spells`, `background`, `alignment` to `CharacterModel` with safe default values | M1 | ORIGINAL_REQUEST §R1-R4 |
| F3 | Mock Discord send_modal Support | Add `send_modal` to `MockInteractionResponse` in `tests/mock_discord.py` for automated modal testing | M2 | Survey Explorer 2 |
| F4 | Interactive Character Creator Modal (R2) | Implement `CharacterCreateModal` (Name, Race & Class, Stats, Gear/Gold, Backstory) with automated D&D 5e rule computation (Hit Die + CON, AC, proficiency, speed, spell slots) | M2 | ORIGINAL_REQUEST §R2 |
| F5 | `/create-character` Slash Command (R2) | Slash command in `commands/character_cog.py` triggering modal, creating `#karty-postaci` forum thread, pinning sheet embed, and returning `CharacterSheetView` | M2 | ORIGINAL_REQUEST §R2 |
| F6 | Gemini 3.7 Flash Character Generator (R3) | Add `CHARACTER_GENERATOR_SYSTEM_PROMPT` in `config/prompts.py` and `generate_character()` in `ai/gemini_client.py` & `tests/mock_ai.py` with structured JSON parsing & offline fallback | M3 | ORIGINAL_REQUEST §R3 |
| F7 | `/generate-character <prompt>` Slash Command (R3) | Slash command in `commands/character_cog.py` generating full D&D 5e character from prompt, provisioning `#karty-postaci` forum thread, and displaying clean embed | M3 | ORIGINAL_REQUEST §R3 |
| F8 | `/character-edit` Slash Command & Audit Logging (R4) | Slash command in `commands/character_cog.py` allowing selective updates to name, stats, max_hp, ac, speed, backstory without corrupting inventory/gold, logging changes to forum thread history | M4 | ORIGINAL_REQUEST §R4 |
| F9 | Comprehensive Test Suite & Regression Verification | Comprehensive test suite covering R1, R2, R3, R4 across all tiers, ensuring 100% pass rate on all 317+ existing tests and new feature tests | M5 | ORIGINAL_REQUEST §Verification |
| F10 | Multi-Turn Rolling Scene Memory & Dice Embed Ingestion | Multi-turn rolling scene history, automatic ingestion of interactive button dice rolls, and previous narrative scene continuity | M6 | Gameplay Experience Enhancement |
| F11 | Chronicler Session Recap & Lore Integration (`/kronika`) | Add `/kronika` command with `LAST_MSG_ID` anchor deduplication and dynamic feeding of `#kompendium-i-lore` & `#kronika-przygód` into Layer 2 Prompt | M6 | Gameplay Experience Enhancement |
| F12 | Multi-Model Fallback Chain & Concurrency Locking | Implement cascade fallback (`gemini-3.7-flash` -> `gemini-3.5-flash` -> `gemini-3.5-flash-lite` -> `gemini-2.5-flash`) on 503/429 errors and per-channel `asyncio.Lock` | M6 | Robustness & Reliability |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Embed Cleanup & Model Extension | Update `core/models.py`, `core/discord_db.py`, `discord_ui/embeds.py` to eliminate visible `DATA_JSON` and support backstory/bio with 100% extraction backward compatibility | none | DONE |
| M2 | Interactive Character Creator (`/create-character`) | Implement `send_modal` mock, `CharacterCreateModal` in `discord_ui/views.py`, and `/create-character` command in `commands/character_cog.py` | M1 | DONE |
| M3 | AI Character Generator (`/generate-character`) | Implement `CHARACTER_GENERATOR_SYSTEM_PROMPT`, `GeminiClient.generate_character()`, `MockGeminiClient` update, and `/generate-character` command | M1 | DONE |
| M4 | Character Editor & Audit Logging (`/character-edit`) | Implement `/character-edit` command with selective field mutations, non-destructive updates, and forum thread audit logging | M1, M2 | DONE |
| M5 | Full Verification & Integration Hardening | Multi-tier test suite (Tiers 1-4) for all new commands + Adversarial review & Challenger testing + Forensic Integrity Audit | M1, M2, M3, M4 | DONE |
| M6 | Scene Memory, Chronicler & Fallback Resilience | Multi-turn rolling scene context, button roll capture, `/kronika` deduplication, compendium lore injection, multi-model fallback chain | M1, M5 | DONE |

## Interface Contracts
### `core/models.py` ↔ `discord_ui/embeds.py` / `core/discord_db.py`
- `CharacterModel` fields:
  - `backstory: Optional[str] = None`
  - `bio: Optional[str] = None`
  - `spells: List[str] = Field(default_factory=list)`
  - `background: Optional[str] = None`
  - `alignment: Optional[str] = None`
- `build_character_sheet_embed(char: CharacterModel) -> discord.Embed`:
  - `embed.description` contains `char.backstory` (or clean bio text, or None) — strictly NO raw `<!-- DATA_JSON: ... -->` string.
- `extract_data_from_message_or_embed(msg: discord.Message) -> Optional[Dict[str, Any]]`:
  - Checks `msg.content`, `embed.description`, `embed.footer.text` for JSON data.

### `ai/gemini_client.py` ↔ `commands/character_cog.py`
- `GeminiClient.generate_character(prompt: str) -> Dict[str, Any]`:
  - Accepts user prompt (e.g. "Krasnoludzki kowal który został kapłanem Moradina").
  - Returns dict validated against `CharacterModel` schema.
  - Deterministic offline fallback returns fully populated valid Level 1 character dict.

### `discord_ui/views.py` ↔ `commands/character_cog.py`
- `CharacterCreateModal(discord.ui.Modal)`:
  - Collects inputs: `name_input`, `class_race_input`, `stats_input`, `equipment_input`, `backstory_input`.
  - Computes HP (`Hit Die + CON mod`), AC, speed, proficiency bonus (+2), spell slots.
  - `on_submit(interaction: discord.Interaction)`: creates `#karty-postaci` forum thread, sets pinned sheet, responds with embed and `CharacterSheetView`.
- `/character-edit`:
  - Modifies specified fields on target character.
  - Calls `update_character_sheet(thread, char, reason=f"Edycja postaci: {summary}")`.

## Code Layout
- `core/models.py`: Pydantic models (`CharacterModel`, `StatBlock`, `ItemModel`, `SpellSlots`)
- `core/discord_db.py`: Pure Discord DB persistence, embed builders, thread managers
- `discord_ui/embeds.py`: Discord Rich Embed presentation logic
- `discord_ui/views.py`: Discord UI Modals, Buttons, Action Views
- `config/prompts.py`: AI System Prompts & JSON generation schemas
- `config/settings.py`: Bot configurations & AI model parameters
- `ai/gemini_client.py`: Gemini AI API client & structured parsing
- `commands/character_cog.py`: Character management slash commands
- `tests/mock_discord.py`: Test mock objects for Discord API
- `tests/mock_ai.py`: Test mock objects for Gemini client
- `tests/test_character_creation_suite.py`: E2E and unit test suite for new features
