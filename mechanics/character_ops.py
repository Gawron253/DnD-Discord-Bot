"""Moduł operacji i mutacji stanu postaci D&D (mechanika deterministyczna).
Wszystkie modyfikacje są w 100% wyliczane w czystym kodzie Python.
"""
from typing import Tuple, Optional, List
from core.models import CharacterModel, ItemModel


def modify_hp(character: CharacterModel, delta: int, is_temp: bool = False) -> Tuple[int, int, str]:
    """Modyfikuje punkty życia postaci (obrażenia lub leczenie).
    
    Zwraca: (aktualne_hp, temp_hp, opis_audytowy)
    - Przy obrażeniach (delta < 0) najpierw redukuje temp_hp, a resztę odejmuje od current_hp (min 0).
    - Przy leczeniu (delta > 0) zwiększa current_hp do maksymalnie max_hp.
    - Jeśli is_temp=True, modyfikuje wyłącznie punkty tymczasowe (temp_hp).
    """
    prev_hp = character.current_hp
    prev_temp = character.temp_hp

    if is_temp:
        if delta >= 0:
            # W 5e punkty tymczasowe się nie sumują, przyjmuje się wyższą wartość lub nową
            character.temp_hp = max(character.temp_hp, delta)
            msg = f"🛡️ Dodano {delta} tymczasowych punktów życia (Aktualne Temp HP: {character.temp_hp})"
        else:
            character.temp_hp = max(0, character.temp_hp + delta)
            msg = f"🛡️ Zmniejszono tymczasowe punkty życia o {abs(delta)} (Aktualne Temp HP: {character.temp_hp})"
        return character.current_hp, character.temp_hp, msg

    if delta < 0:
        damage = abs(delta)
        actual_hp_lost = character.apply_damage(damage)
        msg = f"💔 Otrzymano {damage} obrażeń (Utracono {actual_hp_lost} HP). Stan: {character.current_hp}/{character.max_hp} HP"
        if character.temp_hp != prev_temp:
            msg += f" (Pochłonięto {prev_temp - character.temp_hp} Temp HP)"
        if character.current_hp == 0:
            msg += " ⚠️ **Postać straciła przytomność (0 HP)!**"
    elif delta > 0:
        actual_heal = character.apply_heal(delta)
        msg = f"💚 Uleczono {actual_heal} HP. Stan: {character.current_hp}/{character.max_hp} HP"
    else:
        msg = f"Brak zmiany punktów życia. Stan: {character.current_hp}/{character.max_hp} HP"

    return character.current_hp, character.temp_hp, msg


def add_inventory_item(
    character: CharacterModel,
    item_name: str,
    quantity: int = 1,
    item_type: str = "equipment",
    description: Optional[str] = None,
    weight: float = 1.0,
    is_equipped: bool = False
) -> ItemModel:
    """Dodaje przedmiot do ekwipunku postaci lub zwiększa ilość istniejącego stosu."""
    if quantity <= 0:
        quantity = 1

    clean_name = item_name.strip()
    
    # Sprawdzenie czy przedmiot o tej nazwie już istnieje w ekwipunku
    for item in character.inventory:
        if item.name.lower() == clean_name.lower() and item.item_type == item_type:
            item.quantity += quantity
            return item

    new_item = ItemModel(
        name=clean_name,
        quantity=quantity,
        item_type=item_type,
        is_equipped=is_equipped,
        weight=weight,
        description=description
    )
    character.inventory.append(new_item)
    return new_item


def remove_inventory_item(
    character: CharacterModel,
    item_name: str,
    quantity: int = 1
) -> Tuple[bool, Optional[ItemModel]]:
    """Usuwa określoną liczbę przedmiotów z ekwipunku postaci.
    
    Zwraca: (czy_znaleziono, pozostaly_przedmiot_lub_None)
    """
    clean_name = item_name.strip().lower()
    for i, item in enumerate(character.inventory):
        if item.name.lower() == clean_name:
            if item.quantity > quantity:
                item.quantity -= quantity
                return True, item
            else:
                character.inventory.pop(i)
                return True, None
    return False, None


def modify_gold(character: CharacterModel, delta: int) -> Tuple[bool, int, str]:
    """Modyfikuje ilość złota postaci (w sztukach złota - GP).
    
    Zwraca: (sukces, aktualne_zloto, komunikat)
    """
    if delta < 0 and character.gold_gp + delta < 0:
        return False, character.gold_gp, f"❌ Niewystarczająca ilość złota! Posiadasz {character.gold_gp} GP, potrzeba {abs(delta)} GP."
    
    character.gold_gp = max(0, character.gold_gp + delta)
    action_str = "Dodano" if delta >= 0 else "Wydano"
    return True, character.gold_gp, f"💰 {action_str} {abs(delta)} GP. Aktualny stan sakwy: {character.gold_gp} GP."


def short_rest(character: CharacterModel, hit_dice_heal: int = 0) -> str:
    """Przeprowadza krótki odpoczynek postaci (Short Rest), przywracając opcjonalnie HP z kości wytrzymałości."""
    actual_heal = 0
    if hit_dice_heal > 0:
        actual_heal = character.apply_heal(hit_dice_heal)
    return f"⛺ **Krótki odpoczynek**: Odzyskano {actual_heal} HP. Stan zdrowia: {character.current_hp}/{character.max_hp} HP."


def long_rest(character: CharacterModel) -> str:
    """Przeprowadza długi odpoczynek postaci (Long Rest), w pełni odnawiając HP i komórki czarów."""
    character.current_hp = character.max_hp
    character.temp_hp = 0
    
    # Odnowienie komórek czarów do maksimum
    character.spell_slots.level_1 = character.spell_slots.level_1_max
    character.spell_slots.level_2 = character.spell_slots.level_2_max
    character.spell_slots.level_3 = character.spell_slots.level_3_max
    
    # Usunięcie stanów zmęczenia / standardowych tymczasowych debuffów jeśli obecne
    character.conditions = [c for c in character.conditions if c.lower() not in ["zmęczenie", "exhaustion", "ogłuszenie", "stunned"]]

    return f"🌙 **Długi odpoczynek**: Punkty życia ({character.max_hp}/{character.max_hp} HP) oraz komórki czarów zostały w pełni odnowione!"


def add_condition(character: CharacterModel, condition: str) -> bool:
    """Dodaje stan/efekt (np. Otruty, Przewrócony) do postaci."""
    clean = condition.strip()
    if not clean:
        return False
    if clean not in character.conditions:
        character.conditions.append(clean)
        return True
    return False


def remove_condition(character: CharacterModel, condition: str) -> bool:
    """Usuwa stan/efekt z postaci."""
    clean = condition.strip().lower()
    for i, cond in enumerate(character.conditions):
        if cond.lower() == clean:
            character.conditions.pop(i)
            return True
    return False
