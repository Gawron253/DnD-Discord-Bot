# 🎲 AI Dungeon Master – Discord RPG & DnD Campaign Engine

Kompletne środowisko oparte na sztucznej inteligencji (**AI Dungeon Master z modelem Google Gemini 3.7 Flash**) do prowadzenia interaktywnych kampanii RPG (D&D 5e / Fantasy / Przygoda) na serwerze Discord.

## 🏗️ Architektura Systemu
- **Discord jako Baza Danych i Interfejs (Pure Discord)** – dynamicznie aktualizowane karty postaci w wątkach forum (`#karty-postaci`), ekwipunek, dziennik zadań (`#dziennik-zadań`), kronika (`#kronika-przygód`) i arena walki.
- **Model Językowy Google Gemini 3.7 Flash (Hybrid Reasoning)** – obsługa hybrydowego wnioskowania (`thinking_budget`), pozwalająca na błyskawiczne generowanie narracji (0 tokenów myślenia) lub głębokie taktyczne rozstrzyganie skomplikowanych starć i reguł.
- **100% Deterministyczna Mechanika (Czysty Python)** – rzuty kośćmi d20, modyfikatory, ułatwienia/utrudnienia (Advantage/Disadvantage) i ocena DC działają w kodzie bez zużycia tokenów AI.
- **Dynamiczne Komponenty Discord UI** – przyciski akcji generowane pod narracją, formularze modali i podgląd kart.

## 🚀 Szybki Start

```bash
# 1. Klonowanie i instalacja pakietów
pip install -r requirements.txt

# 2. Konfiguracja zmiennych środowiskowych
cp .env.example .env
# uzupełnij DISCORD_BOT_TOKEN oraz GEMINI_API_KEY w .env

# 3. Uruchomienie bota
python main.py
```

### Konfiguracja Gemini 3.7 Flash (.env):
```env
DEFAULT_AI_MODEL="gemini-3.7-flash"
# 0 = natychmiastowa narracja bez myślenia (low-latency)
# -1 = automatyczne dynamiczne myślenie dla złożonych scen
# 1024/2048 = stały budżet tokenów myślenia
GEMINI_THINKING_BUDGET=0
GEMINI_INCLUDE_THOUGHTS=false
GEMINI_TEMPERATURE=0.70
```

W Discordzie użyj komendy slash:
- `/setup-campaign` – automatycznie tworzy kompletną strukturę kategorii, kanałów i forów RPG.
- `/roll <expression> [dc] [secret]` – deterministyczny rzut kośćmi z kalkulatorem i embedem.
- `/sheet [character]` – podgląd karty postaci z przyciskami rzutów.
- `/quest create/complete` – zarządzanie tablicą zadań.
- Wywołanie `@Mistrz Gry` lub `/next` na `#stół-gry` – generowanie narracji przez Gemini 3.7 Flash.
