# 🎲 DnD AI Discord Bot – Pure Discord RPG & AI Dungeon Master Engine

[![Python Version](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.4%2B-5865F2.svg)](https://discordpy.readthedocs.io/)
[![Google Gemini](https://img.shields.io/badge/Google%20Gemini-3.7%20Flash%20(Hybrid%20Reasoning)-orange.svg)](https://ai.google.dev/)
[![Tests Passing](https://img.shields.io/badge/Tests-446%2F446%20Passing-brightgreen.svg)]()
[![Database](https://img.shields.io/badge/Database-Pure%20Discord%20(Zero%20External%20DB)-success.svg)]()

Kompletne, bezstanowe środowisko sztucznej inteligencji (**AI Dungeon Master**) do prowadzenia kampanii RPG (D&D 5e, Dark Fantasy, autorskie systemy przygodowe) w ekosystemie Discord.

---

## 🌟 Główne Filary i Filozofia Projektu

Projekt rozwiązuje fundamentalny problem systemów AI RPG (utrata kontekstu, koszty tokenów, halucynacje mechaniki oraz konieczność utrzymywania zewnętrznych baz danych) za pomocą czterech kluczowych filarów:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   ARCHITEKTURA SYSTEMU                                           │
├────────────────────────────────┬────────────────────────────────┬────────────────────────────────┤
│    🏰 PURE DISCORD DATABASE    │  🎲 100% DETERMINISTYCZNY KOD  │  🧠 GOOGLE GEMINI 3.7 FLASH    │
│  Discord jest jedyną bazą      │  Rzuty d20, modyfikatory cech, │  Hybrydowe wnioskowanie        │
│  danych (Fora, Wątki, Embedy,  │  HP, ekwipunek i ocena DC są   │  (ThinkingConfig), 1M tokenów  │
│  ukryte metadane Zero-Width).  │  liczone w czystym Pythonie    │  kontekstu, bezstanowy skan    │
│  Zero zewnętrznych baz SQL/DB! │  (0 tokenów AI, 0 halucynacji).│  historii 'after=last_bot_msg' │
└────────────────────────────────┴────────────────────────────────┴────────────────────────────────┘
```

1. **Pure Discord State Engine (Zero External Databases)**:
   * Discord pełni rolę zarówno interfejsu użytkownika (UI), jak i **jedynego źródła prawdy (Single Source of Truth)**.
   * Karty postaci żyją jako wątki na kanale forum (`#karty-postaci`), gdzie pierwszy post zawiera kolorowy Embed z paskiem życia `[████████░░]`, tłem fabularnym (*Backstory*) oraz niewidocznymi metadanymi (*Base-4 Zero-Width Steganography*). Kolejne posty w wątku tworzą czytelny dziennik audytowy.
   * Reguły gry definiowane są w edytowalnym w locie przypiętym poście w `#zasady-i-mechanika`.
2. **Deterministyczna Mechanika (Zero AI Token Cost & Zero Halucynacji)**:
   * Matematyka RPG, rzuty kośćmi z ułatwieniem/utrudnieniem (*Advantage/Disadvantage*), progi trudności (DC), punkty życia (HP/Temp HP) i zarządzanie ekwipunkiem są wykonywane w 100% lokalnie w kodzie Pythona (`d20`, `random`).
   * AI nie wymyśla liczb ani rzutów – otrzymuje gotowe, prawdziwe wyniki testów z embedów.
3. **Google Gemini 3.7 Flash z Hybrydowym Wnioskowaniem (Hybrid Reasoning)**:
   * Obsługa zaawansowanego parametru `thinking_budget` (0 = błyskawiczna narracja bez myślenia, -1 = dynamiczne myślenie, >0 = stały budżet tokenów myślenia).
   * Gigantyczne okno kontekstu (1M+ tokenów) pozwalające na bezstratne wczytywanie zasad świata i historii sesji.
4. **Bezstanowy Skan Historii (`after=last_bot_message`) & Gated Triggers**:
   * AI **nie spamuje czatu po każdej wiadomości**. Odpowiada **wyłącznie po oznaczeniu `@Mistrz Gry` lub wpisaniu `/next`**.
   * Gracze mogą swobodnie rozmawiać i planować poza postacią `((OOC))`.

---

## 📁 Topologia Serwera Discord

Po wpisaniu komendy `/setup-campaign`, bot automatycznie i bezpiecznie (idempotentnie) tworzy poniższą strukturę:

| Kategoria | Kanał / Forum | Typ | Przeznaczenie |
| :--- | :--- | :---: | :--- |
| **📜 KAMPANIA I FABUŁA** | `#stół-gry` | Text | Główny czat sesji. Deklaracje graczy, wywołanie `@Mistrz Gry`, narracja AI i przyciski akcji. |
| | `#zasady-i-mechanika` | Text (Pinned) | Przypięty regulamin kampanii (D&D 5e / Homebrew) edytowalny w locie przez graczy i DM. |
| | `#dziennik-zadań` | Text (Pinned) | Aktywne i ukończone zadania drużyny (`/quest create`, `/quest complete`). |
| | `#kronika-przygód` | Text | Dziennik kronikarski sesji i podsumowania fabularne. |
| **🛡️ POSTACIE I MECHANIKA** | `#karty-postaci` | **Forum** | **1 Wątek = 1 Postać**. 1. post: Karta postaci + Lore + Pasek HP. Kolejne posty: Log zmian. |
| | `#rzuty-kości` | Text | Dedykowany kanał z estetycznymi embedami rozbicia matematyki rzutów kośćmi. |
| | `#szepty-dm` | Text / Threads | Prywatne wątki dla ukrytych informacji, percepcji i sekretów. |
| **📖 ENCYKLOPEDIA I WIEDZA** | `#kompendium-i-lore` | **Forum** | Baza wiedzy o świecie (wątki z tagami `#Lokacja`, `#NPC`, `#Frakcja`, `#Potwór`). |

---

## 🛠️ Zestawienie Komend Slash

### 🧙‍♂️ Komendy Zarządzania Postaciami (Character Suite):
* `/create-character` – Otwiera interaktywne okno Discord Modal (formularz) do stworzenia nowej postaci z automatycznym wyliczeniem reguł D&D 5e (HP Hit Die, AC, szybkość, komórki czarów).
* `/generate-character <opis>` – Generator postaci AI Gemini 3.7 Flash tworzący pełną kartę D&D 5e na podstawie naturalnego opisu.
* `/character-edit [parametry]` – Selektywna edycja imienia, rasy, klasy, poziomu, statystyk lub historii postaci z logiem zmian.
* `/sheet [character]` – Wyświetlenie czystej, interaktywnej karty postaci z paskiem zdrowia ASCII i przyciskami rzutów.
* `/hp <value> [character] [reason]` – Modyfikacja punktów życia (np. `/hp -8 Ragnar ugryzienie pająka`, `/hp +12 leczenie`).
* `/item <action: add|remove|list> <name> [quantity] [character]` – Zarządzanie ekwipunkiem w karcie postaci.
* `/gold <value> [reason] [character]` – Zarządzanie sakiewką ze złotem (GP).
* `/rest <type: short|long> [heal] [character]` – Wykonanie krótkiego lub długiego odpoczynku.

### 🎲 Komendy Mechaniczne i Kampanii (Czysty Python – 0 Tokenów AI):
* `/setup-campaign` – Automatyczna inicjalizacja całej struktury kategorii, kanałów tekstowych i forów.
* `/roll <expression> [dc] [secret]` – Rzut kośćmi (np. `/roll 1d20+5 dc:14`, `/roll 4d6kh3`, `/roll 2d20kl1+3`).
* `/quest <action: create|complete|list> [title] [description] [reward] [quest_id]` – Zarządzanie zadaniami.
* `/zasady` – Wyświetlenie aktualnych zasad kampanii z kanału `#zasady-i-mechanika`.

### 🎭 Komendy Narracyjne i AI:
* `@Mistrz Gry <treść>` na `#stół-gry` – Wywołanie AI do wygenerowania kolejnej tury narracji na podstawie zdarzeń od poprzedniej odpowiedzi bota.
* `/next` na `#stół-gry` – Wymuszenie wygenerowania tury narracyjnej przez komendę slash.

---

## 🎮 Przebieg Rozgrywki w Praktyce

```
1. Gracze piszą na #stół-gry:
   [Ragnar]: "Podkradam się do strażnika przy bramie."
   [Eldrin]: "Asekuruję go z łukiem w cieniu."
   [Ragnar]: "@Mistrz Gry co się dzieje?"

2. Bot przechwytuje zdarzenie @Mistrz Gry:
   - Skanuje historię wstecz i pobiera nowe wiadomości po ostatniej odpowiedzi bota.
   - Odczytuje statystyki Ragnara z forum #karty-postaci (DEX 16 -> +3 modyfikator).
   - Odczytuje zasady z #zasady-i-mechanika.

3. Gemini 3.7 Flash generuje barwną narrację:
   "Korytarz usłany jest suchymi liśćmi i żwirem. Jeden fałszywy krok zaalarmuje wartownika.
   Wykonaj test Skradania (Zwinność), aby podejść bezszelestnie."
   [Przycisk pod postem: 🎲 Rzuć na Skradanie (DEX +3)]

4. Gracz klika przycisk [🎲 Rzuć na Skradanie]:
   - Czysty kod Pythona wykonuje losowanie: 1d20(14) + 3 = 17 vs DC 13 (SUKCES).
   - Embed rzutu pojawia się natychmiast na #rzuty-kości i na #stół-gry.

5. Drużyna pisze: "@Mistrz Gry udało się!" -> AI kontynuuje opowieść z pełną świadomością sukcesu testu!
```

---

## 🚀 Szybki Start i Instalacja

### Wymagania wstępne:
* **Python 3.11 lub 3.12**
* Konto Discord i aplikacja bota utworzona w [Discord Developer Portal](https://discord.com/developers/applications)
  *(Włącz suwak **MESSAGE CONTENT INTENT** w zakładce Bot!)*
* Klucz API do Google Gemini z [Google AI Studio](https://aistudio.google.com/)

### 1. Klonowanie i instalacja pakietów
```bash
git clone https://github.com/Gawron253/DnD-Discord-Bot.git
cd DnD-Discord-Bot

# Utwórz środowisko wirtualne
python -m venv venv
venv\Scripts\activate      # Windows PowerShell/CMD
# source venv/bin/activate # Linux/macOS

# Zainstaluj zależności
pip install -r requirements.txt
```

### 2. Konfiguracja zmiennych środowiskowych (`.env`)
Skopiuj `.env.example` do `.env` i uzupełnij klucze:
```bash
cp .env.example .env
```

Zawartość `.env`:
```env
DISCORD_BOT_TOKEN="TWOJ_TOKEN_BOTA_DISCORD"
GEMINI_API_KEY="TWOJ_KLUCZ_GOOGLE_GEMINI_API"

# Konfiguracja Gemini 3.7 Flash:
DEFAULT_AI_MODEL="gemini-3.7-flash"
GEMINI_TEMPERATURE=0.70

# Budżet myślenia (ThinkingConfig):
# 0 = wyłączone (błyskawiczna narracja bez myślenia)
# -1 = automatyczne dynamiczne myślenie
# >0 = stały budżet tokenów (np. 1024, 2048 dla złożonych scen)
GEMINI_THINKING_BUDGET=0
GEMINI_INCLUDE_THOUGHTS=false
```

### 3. Uruchomienie bota
```bash
python main.py
```

### 4. Uruchomienie testów automatycznych
Projekt posiada pełny, 100% zautomatyzowany pakiet testów weryfikujących wszystkie moduły:
```bash
pytest
```
*(Wynik: **446 / 446 zdanych testów** w ~30s)*

---

## 📂 Struktura Katalogów Projektu

```text
DnD-Discord-Bot/
├── .env.example              # Szablon zmiennych środowiskowych
├── .gitignore                # Reguły ignorowania plików poufnych i śmieci
├── IMPLEMENTATION_PLAN.md    # Główny dokument architektoniczny i specyfikacja RFC
├── PROJECT.md                # Rejestr funkcji (F1-F9/M1-M5), kamieni milowych i testów
├── README.md                 # Dokumentacja użytkownika i opis projektu
├── requirements.txt          # Lista zależności produkcyjnych
├── main.py                   # Główny punkt wejścia bota Discord
├── ai/                       # Moduł AI Google Gemini 3.7 Flash
│   ├── context_builder.py    # 4-warstwowe składanie kontekstu i skan 'after=last_bot_msg'
│   ├── gemini_client.py      # Klient Gemini 3.7 Flash z ThinkingConfig i generator postaci
│   ├── message_splitter.py   # Inteligentny podział długich wiadomości (<2000 znaków)
│   └── tools.py              # Schematy narzędzi i funkcji
├── commands/                 # Cogi Discord.py (komendy slash i listener czatu)
│   ├── campaign_cog.py       # Obsługa /setup-campaign i /zasady
│   ├── character_cog.py      # Obsługa /create-character, /generate-character, /character-edit, /sheet
│   ├── mechanics_cog.py      # Obsługa /roll, /hp, /item
│   ├── narrative_cog.py      # Listener @Mistrz Gry i komenda /next
│   └── quest_cog.py          # Obsługa /quest
├── config/                   # Konfiguracja środowiska i prompty
│   ├── prompts.py            # Prompty systemowe dla Mistrza Gry, Kronikarza i Generatora Postaci
│   └── settings.py           # Klasa Settings (Pydantic BaseSettings)
├── core/                     # Silnik Pure Discord
│   ├── channel_manager.py    # Idempotentne zarządzanie kanałami i forami
│   ├── discord_db.py         # Serializacja i deserializacja ukrytego JSON w postach
│   └── models.py             # Modele danych (CharacterModel, StatBlock, QuestModel)
├── discord_ui/               # Komponenty interfejsu użytkownika
│   ├── embeds.py             # Graficzne embedy kart postaci z paskami HP w ASCII i Lore
│   └── views.py              # Modale (/create-character), widoki kart i przyciski rzutów kośćmi
├── mechanics/                # Deterministyczny silnik mechaniki gry
│   ├── character_ops.py      # Operacje na HP, ekwipunku i statystykach
│   └── dice.py               # Parser kości d20 z obsługą advantage/disadvantage i DC
└── tests/                    # Kompletny zestaw 446 testów jednostkowych i E2E
```

---

## 📜 Licencja
Projekt stworzony na licencji **MIT**. Możesz go dowolnie modyfikować i rozwijać na potrzeby własnych kampanii RPG!
