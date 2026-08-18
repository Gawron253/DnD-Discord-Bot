"""Definicje narzedzi (Function Calling) dla modeli AI Dungeon Master."""
from typing import List, Dict, Any

AI_TOOLS_SPEC: List[Dict[str, Any]] = [
    {
        "name": "roll_dice",
        "description": "Wykonuje rzut koscmi RPG (np. 1d20+5, 2d6+3) z uwzglednieniem modyfikatorow, ulatwien i stopnia trudnosci DC.",
        "parameters": {
            "type": "object",
            "properties": {
                "formula": {"type": "string", "description": "Formula rzutu koscmi np. 1d20+5 lub 2d8+3"},
                "reason": {"type": "string", "description": "Powod rzutu np. Test Akrobatyki, Atak mieczem"},
                "target_dc": {"type": "integer", "description": "Stopien trudnosci DC (opcjonalny)"},
                "advantage_disadvantage": {
                    "type": "string",
                    "enum": ["normal", "advantage", "disadvantage"],
                    "description": "Czy rzut ma ulatwienie (advantage) lub utrudnienie (disadvantage)"
                },
                "is_secret": {"type": "boolean", "description": "Czy rzut ma byc tajny (tylko dla DM)"}
            },
            "required": ["formula", "reason"]
        }
    },
    {
        "name": "modify_character_sheet",
        "description": "Modyfikuje punkty zycia HP, sloty czarow, naklada lub zdejmuje stany (conditions) postaci gracza.",
        "parameters": {
            "type": "object",
            "properties": {
                "character_name": {"type": "string", "description": "Imie postaci gracza"},
                "hp_change": {"type": "integer", "description": "Zmiana punktow zycia (ujemna dla obrazen np. -8, dodatnia dla leczenia np. +10)"},
                "spell_slot_used": {"type": "integer", "description": "Poziom zuzytego slotu czaru (1-9)"},
                "add_condition": {"type": "string", "description": "Stan nalozony na postac np. Zatruty, Powalony, Blogoslawiony"},
                "remove_condition": {"type": "string", "description": "Stan usuniety z postaci"}
            },
            "required": ["character_name"]
        }
    },
    {
        "name": "manage_inventory",
        "description": "Zarzadza ekwipunkiem gracza: dodawanie, usuwanie przedmiotow, wydawanie lub zdobywanie zlota.",
        "parameters": {
            "type": "object",
            "properties": {
                "character_name": {"type": "string"},
                "action": {"type": "string", "enum": ["add", "remove", "equip", "unequip", "give_gold", "spend_gold"]},
                "item_name": {"type": "string"},
                "quantity": {"type": "integer", "default": 1},
                "item_details": {"type": "string", "description": "Wlasciwosci, typ lub opis przedmiotu"}
            },
            "required": ["character_name", "action"]
        }
    },
    {
        "name": "query_lore_rag",
        "description": "Przeszukuje baze wiedzy o swiecie, zasady D&D 5e SRD, zaklecia, bestiariusz lub historie kampanii.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Zapytanie do bazy wiedzy"},
                "category": {"type": "string", "enum": ["rules_srd", "world_lore", "campaign_history", "npcs_bestiary"]}
            },
            "required": ["query"]
        }
    },
    {
        "name": "update_combat_tracker",
        "description": "Zarzadza przebiegiem walki na kanale #arena-walki (start starcia, kolejna tura, zadanie obrazen potworom).",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["start_combat", "next_turn", "damage_combatant", "end_combat"]},
                "target_name": {"type": "string"},
                "damage_amount": {"type": "integer"}
            },
            "required": ["action"]
        }
    }
]
