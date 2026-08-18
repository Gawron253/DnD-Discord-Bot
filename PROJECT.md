# Project: D&D AI Discord Bot (Pure Discord Architecture + Gemini 3.7 Flash)

## Architecture
- **Pure Discord State Architecture**: Discord channels, forum threads, pinned posts, rich embeds, and hidden HTML comments `<!-- DATA_JSON: {...} -->` are the **sole persistent database**. No external SQL/NoSQL or ChromaDB database is required or utilized.
- **Deterministic Mechanics (0 AI Tokens)**: All dice rolls, DC checks, ability modifiers, HP updates, inventory mutations, and combat state are computed 100% deterministically in pure Python (`d20`, `random`).
- **AI Dungeon Master (Google Gemini 3.7 Flash)**: Invoked **strictly on demand** via `@Mistrz Gry` mention or `/next` slash command on `#stół-gry`. Supports **Hybrid Reasoning (`thinking_budget`)**, performs stateless history scanning (`after=last_bot_message`), synthesizes player declarations with dice results and live rules from `#zasady-i-mechanika`, and yields narrative responses with dynamic action buttons.
- **Offline Mock Test Harness**: Mock Discord domain objects (`MockGuild`, `MockTextChannel`, `MockForumChannel`, `MockThread`, `MockMessage`, `MockInteraction`) and `MockGeminiClient` enabling 100% offline unit/E2E test suite.

## Feature Inventory
| # | Feature | Description | Milestone | Source | Status |
|---|---------|-------------|-----------|--------|--------|
| F1 | Setup Campaign Command | `/setup-campaign` creating categories, text channels, forum channels `#karty-postaci`, `#kompendium-i-lore` idempotently | M1 | ORIGINAL_REQUEST §R1 | DONE |
| F2 | Live Pinned Rules Parsing | `#zasady-i-mechanika` pinned post live parsing without local cache or file lock | M1 | ORIGINAL_REQUEST §R1 | DONE |
| F3 | Forum Character State Persistence | `#karty-postaci` forum thread state storage using `<!-- DATA_JSON: ... -->` and ASCII HP bars | M1 | ORIGINAL_REQUEST §R1 | DONE |
| F4 | 24h Thread Auto-Unarchiving | Automatic waking up (`thread.edit(archived=False)`) of sleeping forum threads when reading/updating character sheets | M1 | ORIGINAL_REQUEST §R1 | DONE |
| F5 | Quest Journal System | `/quest create` and `/quest complete` updating pinned embed in `#dziennik-zadań` with `<!-- DATA_JSON: ... -->` | M1 | ORIGINAL_REQUEST §R1 | DONE |
| F6 | Deterministic Dice Engine | Pure Python dice parser (`1d20+5`, `2d6+3`, advantage/disadvantage `2d20kh1`/`2d20kl1`, DC checks, 0 AI tokens) | M2 | ORIGINAL_REQUEST §R2 | DONE |
| F7 | Core Slash Commands Suite | `/roll`, `/hp <wartość> [postać] [powód]`, `/item <add/remove> <nazwa>`, `/sheet`, `/quest` | M2 | ORIGINAL_REQUEST §R2 | DONE |
| F8 | Dynamic Discord UI Buttons | Interactive buttons under DM responses (`[🎲 Rzuć na Percepcję (WIS +2)]`) with instant Python dice execution | M2 | ORIGINAL_REQUEST §R2 | DONE |
| F9 | Aesthetic Rich Embeds | Visual embed formatting for character sheets, dice roll breakdowns, and quest lists | M2 | ORIGINAL_REQUEST §R2 | DONE |
| F10 | Google Gemini 3.7 Flash Integration | `google-genai` / REST client with Hybrid Reasoning (`thinking_budget`), 4-layer hierarchical prompt assembly, custom RPG safety thresholds, and mock fallback | M3 | ORIGINAL_REQUEST §R3 | DONE |
| F11 | Strict Narrative Triggering Filter | Gated exclusively on `@Mistrz Gry` mention or `/next` slash command on `#stół-gry`, ignoring passive chatter | M3 | ORIGINAL_REQUEST §R3 | DONE |
| F12 | Stateless Channel History Scanner | Scanning `after=last_bot_message` on `#stół-gry`, filtering `((OOC))`, parsing roll embeds from `#stół-gry` / `#rzuty-kości` | M3 | ORIGINAL_REQUEST §R3 | DONE |
| F13 | Smart Paragraph Message Splitter | Chunking long responses (>2000 chars) on paragraph/sentence boundaries without HTTP 400 Bad Request | M3 | ORIGINAL_REQUEST §R3 | DONE |
| F14 | Dynamic Action Button Extraction | Extracting `[ACTION_BUTTONS: [...]]` from Gemini narrative and attaching `NarrativeActionView` to the final message | M3 | ORIGINAL_REQUEST §R3 | DONE |
| F15 | Complete Integration & E2E Testing | Full lifecycle wiring in `main.py`, 100% pass on E2E Test Suite (Tiers 1-4), Tier 5 Adversarial Coverage Hardening | M4 | ORIGINAL_REQUEST Acceptance Criteria | DONE |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Suite Track | Mock harness (`MockGuild`, `MockThread`, etc.), Mock Gemini, Tiers 1-4 Test Suites -> `TEST_READY.md` | none | DONE |
| M1 | Pure Discord State & Channel Manager | `core/models.py`, `core/discord_db.py`, `core/channel_manager.py`, `/setup-campaign`, forum threads, unarchive, `/quest` | none | DONE |
| M2 | Deterministic RPG Mechanics & Discord UI | `mechanics/dice.py`, `mechanics/character_ops.py`, `discord_ui/embeds.py`, `discord_ui/views.py`, `/roll`, `/hp`, `/item`, `/sheet` | M1 | DONE |
| M3 | AI Dungeon Master & Context Engine | `ai/gemini_client.py`, `ai/context_builder.py`, `ai/message_splitter.py`, `commands/narrative_cog.py`, `@Mistrz Gry` listener, `/next` | M1, M2 | DONE |
| M4 | Final Integration, E2E Acceptance & Tier 5 Hardening | `main.py`, bot lifecycle, cog registration, 100% E2E test pass (Tiers 1-4), Phase 2 Adversarial coverage hardening (Tier 5), Final Forensic Audit | E2E, M1, M2, M3 | DONE |

## Verification Summary
- **Total Test Suite:** 317 Tests (100% Passing in ~1.1s)
- **Tier 1 (Feature Coverage):** 70 Tests
- **Tier 2 (Boundary & Corner Cases):** 70 Tests
- **Tier 3 (Cross-Feature Pairwise):** 15 Tests
- **Tier 4 (Real-World Campaign Scenarios):** 5 Tests
- **Tier 5 (Adversarial & Stress Hardening):** 28 Tests
- **Unit & Integration Tests (including Gemini 3.7 Flash ThinkingConfig):** 129 Tests
- **Forensic Integrity Verdict:** CLEAN (0 cheat tables, 0 facade implementations, 0 external database dependencies)
