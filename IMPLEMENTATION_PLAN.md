# 🎲 AI Dungeon Master (Pure Discord Architecture) – Master Project Plan

Kompleksowy plan i specyfikacja techniczna środowiska AI do prowadzenia kampanii RPG / D&D / przygód narracyjnych, **w 100% opartego na ekosystemie Discord jako jedynej bazie danych i nośniku pamięci**.

---

## 1. Kluczowe Założenia Projektowe (Ustalenia Grill-Me)

1. **Pure Discord jako Baza Danych (Zero Zewnętrznych Baz Danych)**:
   * Brak zewnętrznych baz SQL, NoSQL czy serwerów wektorowych.
   * Kanały i fora Discord pełnią rolę tabel i rekordów.
   * Stan kart postaci, ekwipunku i zadań przechowywany jest w przypiętych wiadomościach (Rich Embeds z ukrytym blokiem JSON w metadanych), a historia zmian to kolejne posty w dedykowanych wątkach.
2. **Podział na Czysty Kod (Determinizm) vs AI (Klimat i Narracja)**:
   * **Moduł Mechaniki**: 100% deterministyczny kod Python (`random.randint`, biblioteka `d20`, parsowanie modyfikatorów, komendy `/roll`, `/hp`, `/item`). Zero halucynacji liczb, natychmiastowa odpowiedź, 0 kosztu tokenów.
   * **Moduł Narratora (AI DM)**: Model **Google Gemini 3.7 Flash** (hybrydowe wnioskowanie ThinkingConfig, darmowy/bardzo tani tier, gigantyczne okno 1M-2M tokenów pozwalające na bezstratne wczytywanie całych wątków z Discorda).
3. **Selektywne Wyzwalanie AI (Brak spamu i kontrola kosztów)**:
   * AI odpowiada na kanale `#stół-gry` **wyłącznie po oznaczeniu `@Mistrz Gry` lub użyciu komendy `/next`**. Gracze mogą swobodnie dyskutować i planować na czacie bez przedwczesnego wtrącania się bota.
4. **Bezstanowy Mechanizm Śledzenia Kontekstu (`after=last_bot_message`)**:
   * Gdy gracz oznacza `@Mistrz Gry`, bot skanuje wstecz historię kanału, odnajduje ID swojej ostatniej wypowiedzi (`last_bot_message`) i pobiera **wszystkie wiadomości, deklaracje graczy oraz rzuty kośćmi, które wydarzyły się od tego momentu**.
   * Filtrowane są rozmowy pozagrowe `((OOC: ...))`.
5. **Interaktywne Rzuty Kośćmi**:
   * AI prosi o rzut lub dołącza przycisk `[🎲 Rzuć na Akrobatykę]`.
   * Gracz klika przycisk lub wpisuje `/roll`. Wynik losowany jest w czystym kodzie i publikowany na czacie oraz w kanale `#rzuty-kostkami`.
   * Gracze oznaczają `@Mistrz Gry`, a AI opisuje skutek rzutu na podstawie wyniku odczytanego z embedu.
6. **Ewoluujący System Zasad (`#zasady-i-mechanika`)**:
   * Dedykowany kanał konfiguracyjny z przypiętą wiadomością definiującą aktywny system (D&D 5e, autorski system, Call of Cthulhu itp.).
   * Gracze i DM mogą w trakcie trwania kampanii edytować reguły gry, a AI natychmiast dostosowuje swoje działanie do zaktualizowanego posta.

---

## 2. Architektura Kanałów i Struktur Danych Discorda

```mermaid
flowchart TB
    subgraph Discord_Server["🏰 Serwer Discord (Interfejs + Baza Danych)"]
        subgraph Cat_Camp["📜 KAMPANIA I FABUŁA"]
            Ch_Play["#stół-gry (Czat sesji + wywołanie @Mistrz Gry)"]
            Ch_Rules["#zasady-i-mechanika (Przypięty post z regułami - edytowalny w locie!)"]
            Ch_Quests["#dziennik-zadań (Wątki z misjami)"]
            Ch_Chro["#kronika-przygód (Podsumowania sesji)"]
        end

        subgraph Cat_Mech["🛡️ KARTY I MECHANIKA"]
            Forum_Chars["#karty-postaci (FORUM - 1 Wątek = 1 Postać)\n- 1. post: Pasek HP + Embed + JSON\n- Kolejne posty: Historia zmian"]
            Ch_Dice["#rzuty-kostkami (Logi rzutów z formułami)"]
            Ch_Whispers["#szepty-dm (Prywatne wątki graczy)"]
        end

        subgraph Cat_Lore["📖 ENCYKLOPEDIA I WIEDZA"]
            Forum_Lore["#kompendium-i-lore (FORUM - Lokacje, NPC, Frakcje)"]
        end
    end

    subgraph Bot_Architecture["⚙️ Bot Discord (Python discord.py)"]
        subgraph Deterministic_Engine["🎲 Moduł Mechaniki (Czysty Python - 0 Tokenów)"]
            DiceEngine["d20 / Random Roller (/roll)"]
            SheetParser["JSON Embed Parser & Editor (/hp, /item)"]
            UIController["Button & Modal Handlers"]
        end

        subgraph AI_Engine["🧠 Moduł Narratora AI (Google Gemini)"]
            GeminiClient["Gemini 3.7 Flash (ThinkingConfig / 1M+ Token Context)"]
            HistoryScanner["Skaner historii (after=last_bot_message)"]
            ContextBuilder["Discord Context Fetcher (Czyta #zasady i #karty)"]
        end
    end

    Ch_Play -->|Wzmianka @Mistrz Gry / /next| HistoryScanner
    HistoryScanner --> ContextBuilder
    ContextBuilder -->|Odczyt kart postaci| Forum_Chars
    ContextBuilder -->|Odczyt reguł| Ch_Rules
    ContextBuilder -->|Wyszukanie lore| Forum_Lore
    ContextBuilder --> GeminiClient
    GeminiClient -->|Odpowiedź narracyjna + Przyciski| Ch_Play
    Ch_Play -->|Kliknięcie [🎲 Rzuć test]| UIController
    UIController --> DiceEngine
    DiceEngine -->|Embed rzutu| Ch_Dice
    DiceEngine -->|Embed rzutu| Ch_Play
    Deterministic_Engine <-->|Zapis/Edycja postów| Forum_Chars
```

---

## 3. Szczegółowy Model Danych w Postach Discorda

### 3.1. Karty Postaci (Kanał Forum `#karty-postaci`)
* **Format**: Kanał typu Forum. Każdy wątek ma tytuł np. `🧝 Legolas – Elf Łowca (Lvl 3)`.
* **Pierwszy (przypięty) post**:
  * Wizualny Embed z portretem, paskiem życia `[████████░░] 28/35 HP`, AC, cechami (STR, DEX, CON, INT, WIS, CHA) oraz ekwipunkiem.
  * Ukryty znacznik danych na samym końcu posta:
    ```markdown
    <!-- DATA_JSON: {"id": "123456", "name": "Legolas", "hp": 28, "max_hp": 35, "ac": 15, "stats": {"str": 10, "dex": 18, "con": 14, "int": 12, "wis": 14, "cha": 8}, "gold": 45, "inventory": [{"name": "Łuk kompozytowy", "qty": 1}, {"name": "Lecznicza mikstura", "qty": 2}]} -->
    ```
* **Kolejne posty w wątku**: Log transakcji i zmian, np.
  * *„[18.08 21:30] Otrzymano 5 pkt. obrażeń od goblina (HP: 33 -> 28)”*
  * *„[18.08 21:35] Zużyto: Lecznicza mikstura (+8 HP)”*

### 3.2. Konfiguracja Systemu i Zasad (`#zasady-i-mechanika`)
* Przypięty post zawiera definicję mechaniki, którą AI wczytuje przed każdą odpowiedzią:
  ```markdown
  # 📜 Aktualne Zasady Gry i Świata
  - **System bazowy**: D&D 5e (Dungeons & Dragons 5. edycja)
  - **Cechy**: Siła (STR), Zręczność (DEX), Kondycja (CON), Inteligencja (INT), Mądrość (WIS), Charyzma (CHA)
  - **Klimat**: Dark Fantasy z elementami tajemnicy i realizmu.
  - **Zasady specjalne (Homebrew)**: 
    * Porażka krytyczna na kości k20 wywołuje komplikację fabularną.
    * Krótki odpoczynek trwa 1 godzinę i wymaga zużycia 1 racji żywnościowej.
  ```
  *(Gracze mogą edytować ten post w dowolnym momencie, a AI automatycznie zaadaptuje nowe zasady!)*

### 3.3. Algorytm Pobierania Nowych Wydarzeń z `#stół-gry`
1. Bot przeszukuje historię kanału wstecz (`history(limit=50)`), aż trafi na wiadomość wysłaną przez `bot.user.id`.
2. Pobiera wszystkie wiadomości PO tej wiadomości (`after=last_bot_msg`).
3. Parsuje wiadomości tekstowe graczy oraz Embedy rzutów kośćmi wygenerowane przez bota.
4. Formatuje je do czytelnego bloku zdarzeń dla Google Gemini.

---

## 4. Zestawienie Komend Bota

### 🎲 Komendy Mechaniczne (Deterministyczny kod Python – 0 tokenów):
* `/roll <formuła> [powód] [dc]` – Rzut kośćmi (np. `/roll 1d20+5 powód:Atak dc:14`, `/roll 2d6+3`).
* `/hp <wartość> [postać] [powód]` – Modyfikacja punktów życia (np. `/hp -6 Ragnar ugryzienie pająka`).
* `/item add/remove <nazwa> [ilość] [postać]` – Zarządzanie ekwipunkiem w karcie postaci.
* `/sheet [postać]` – Wyświetlenie lub ponowne wygenerowanie karty postaci.
* `/setup-campaign` – Automatyczne utworzenie wszystkich kategorii, kanałów tekstowych i forów na serwerze Discord.

### 🎭 Komendy Narracyjne i AI:
* `@Mistrz Gry <treść>` lub `/next` – Wezwanie AI do wygenerowania kolejnego fragmentu opowieści na podstawie zdarzeń od ostatniej wypowiedzi.
* `/recap` – Pisarz AI generuje podsumowanie bieżącej sesji i publikuje je w `#kronika-przygód`.
* `/create-npc <nazwa> <opis>` – AI tworzy nowy wpis NPC w `#kompendium-i-lore`.

---

## 5. Struktura Kodu Projektu

```text
dnd_ai_discord_bot/
├── config/
│   ├── settings.py           # Token Discorda, Klucz Gemini API
│   └── prompts.py            # Prompty systemowe dla AI DM i Kronikarza
├── core/
│   ├── bot.py                # Inicjalizacja bota Discord (discord.py)
│   ├── discord_db.py         # Zarządzanie 'Bazą Discord': odczyt/zapis kart w embedach JSON
│   └── models.py             # Modele danych Pydantic dla postaci i rzutów
├── mechanics/
│   ├── dice.py               # 100% deterministyczny silnik kości (d20 / random)
│   └── sheet_manager.py      # Modyfikacja HP, ekwipunku i statystyk w postach forum
├── ai/
│   ├── gemini_client.py      # Klient Google Gemini 3.7 Flash (Hybrid Reasoning)
│   ├── context_builder.py    # Skaner historii (after=last_bot_msg), czytanie #zasady i #karty
│   └── tools.py              # Narzędzia wywoływane przez Gemini (edycja postów)
├── discord_ui/
│   ├── embeds.py             # Szablony Embedów kart postaci z paskami HP ASCII
│   └── views.py              # Przyciski rzutów kośćmi i modale
├── .env.example              # Konfiguracja zmiennych
├── requirements.txt          # Zależności (discord.py, google-genai, d20, pydantic)
├── main.py                   # Punkt wejścia bota z obsługą @Mistrz Gry i komend
└── README.md                 # Dokumentacja użytkownika
```
