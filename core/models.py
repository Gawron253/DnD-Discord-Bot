"""Modele danych Pydantic dla postaci, ekwipunku, zadan, rzutow i walki.
Discord (kanaly, watki, embedy, komentarze HTML) stanowi jedyne zrodlo prawdy.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


class StatBlock(BaseModel):
    """Blok 6 podstawowych cech D&D 5e z obliczaniem modyfikatorow."""
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10

    def get_modifier(self, stat_name: str) -> int:
        """Oblicza modyfikator cechy: (wartosc - 10) // 2."""
        stat_map = {
            "str": "strength", "strength": "strength", "sila": "strength", "siła": "strength",
            "dex": "dexterity", "dexterity": "dexterity", "zrecznosc": "dexterity", "zręczność": "dexterity",
            "con": "constitution", "constitution": "constitution", "kondycja": "constitution", "budowa": "constitution",
            "int": "intelligence", "intelligence": "intelligence", "inteligencja": "intelligence",
            "wis": "wisdom", "wisdom": "wisdom", "madrosc": "wisdom", "mądrość": "wisdom",
            "cha": "charisma", "charisma": "charisma", "charyzma": "charisma"
        }
        normalized = stat_map.get(stat_name.lower().strip(), stat_name.lower().strip())
        val = getattr(self, normalized, 10)
        return (val - 10) // 2

    def modifier(self, stat_name: str) -> int:
        """Alias dla get_modifier dla zachowania kompatybilnosci."""
        return self.get_modifier(stat_name)


class ItemModel(BaseModel):
    """Model przedmiotu w ekwipunku postaci."""
    name: str
    quantity: int = 1
    item_type: str = "equipment"  # weapon, armor, consumable, quest, misc, equipment
    is_equipped: bool = False
    weight: float = 1.0
    description: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None


class SpellSlots(BaseModel):
    """Dostepne i maksymalne komorki czarow postaci."""
    level_1: int = 0
    level_1_max: int = 0
    level_2: int = 0
    level_2_max: int = 0
    level_3: int = 0
    level_3_max: int = 0


class CharacterModel(BaseModel):
    """Glowny model postaci gracza przechowywany w watku forum."""
    id: Optional[int] = None
    discord_user_id: str
    name: str
    character_class: str
    race: str
    level: int = 1
    xp: int = 0
    
    current_hp: int = 10
    max_hp: int = 10
    temp_hp: int = 0
    armor_class: int = 10
    speed: int = 30
    proficiency_bonus: int = 2
    
    stats: StatBlock = Field(default_factory=StatBlock)
    spell_slots: SpellSlots = Field(default_factory=SpellSlots)
    inventory: List[ItemModel] = Field(default_factory=list)
    gold_gp: int = 10
    conditions: List[str] = Field(default_factory=list)
    
    avatar_url: Optional[str] = None
    pinned_sheet_message_id: Optional[str] = None

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: int) -> int:
        return max(1, v)

    def apply_damage(self, amount: int) -> int:
        """Odejmuje obrazenia najpierw z temp_hp, nastepnie z current_hp (min 0). Zwraca faktycznie utracone HP."""
        if amount <= 0:
            return 0
        rem = amount
        if self.temp_hp > 0:
            if self.temp_hp >= rem:
                self.temp_hp -= rem
                return 0
            else:
                rem -= self.temp_hp
                self.temp_hp = 0
        
        actual_hp_lost = min(self.current_hp, rem)
        self.current_hp = max(0, self.current_hp - rem)
        return actual_hp_lost

    def apply_heal(self, amount: int) -> int:
        """Leczy postac do wartosci max_hp. Zwraca faktycznie uleczone HP."""
        if amount <= 0:
            return 0
        prev_hp = self.current_hp
        self.current_hp = min(self.max_hp, self.current_hp + amount)
        return self.current_hp - prev_hp

    def add_item(self, item: ItemModel) -> None:
        """Dodaje przedmiot do ekwipunku (laczy ilosci jesli ten sam typ i nazwa)."""
        for existing in self.inventory:
            if existing.name.lower() == item.name.lower() and existing.item_type == item.item_type:
                existing.quantity += item.quantity
                return
        self.inventory.append(item)

    def remove_item(self, item_name: str, quantity: int = 1) -> bool:
        """Usuwa podana liczbe przedmiotow z ekwipunku. Zwraca True jesli sukces."""
        for i, item in enumerate(self.inventory):
            if item.name.lower() == item_name.lower():
                if item.quantity > quantity:
                    item.quantity -= quantity
                    return True
                else:
                    self.inventory.pop(i)
                    return True
        return False

    def has_item(self, item_name: str) -> bool:
        """Sprawdza czy postac posiada dany przedmiot."""
        return any(item.name.lower() == item_name.lower() for item in self.inventory)


class QuestObjective(BaseModel):
    """Pojedynczy cel zadania."""
    text: str
    is_completed: bool = False

ObjectiveItem = QuestObjective


class QuestItem(BaseModel):
    """Pojedyncze zadanie na tablicy zadan."""
    id: str
    title: str
    giver: str = "Mistrz Gry"
    description: str = ""
    objectives: List[QuestObjective] = Field(default_factory=list)
    reward: Optional[str] = None
    status: str = "active"  # active, completed, failed

QuestModel = QuestItem


class QuestList(BaseModel):
    """Zbior zadan przechowywany w przypietym embedzie #dziennik-zadan."""
    quests: List[QuestItem] = Field(default_factory=list)

    def get_quest(self, quest_id_or_title: str) -> Optional[QuestItem]:
        """Wyszukuje zadanie po ID lub tytule."""
        q_id = quest_id_or_title.strip().lower()
        for q in self.quests:
            if q.id.lower() == q_id or q.title.lower() == q_id:
                return q
        return None

    def add_quest(self, quest: QuestItem) -> None:
        """Dodaje zadanie do listy."""
        self.quests.append(quest)

    def complete_quest(self, quest_id_or_title: str) -> Optional[QuestItem]:
        """Oznacza zadanie i wszystkie jego cele jako ukonczone."""
        quest = self.get_quest(quest_id_or_title)
        if quest:
            quest.status = "completed"
            for obj in quest.objectives:
                obj.is_completed = True
        return quest

    def active_quests(self) -> List[QuestItem]:
        """Zwraca liste aktywnych zadan."""
        return [q for q in self.quests if q.status == "active"]

    def completed_quests(self) -> List[QuestItem]:
        """Zwraca liste ukonczonych zadan."""
        return [q for q in self.quests if q.status == "completed"]


class DiceRollResult(BaseModel):
    """Struktura wyniku rzutu koscia (deterministyczny silnik kości)."""
    formula: str
    total: int
    dice_rolls: List[int] = Field(default_factory=list)
    modifier: int = 0
    is_crit_success: bool = False
    is_crit_failure: bool = False
    dc: Optional[int] = None
    is_success: Optional[bool] = None
    reason: Optional[str] = None
    breakdown: str = ""

    @property
    def is_critical_success(self) -> bool:
        return self.is_crit_success

    @is_critical_success.setter
    def is_critical_success(self, val: bool) -> None:
        self.is_crit_success = val

    @property
    def is_critical_failure(self) -> bool:
        return self.is_crit_failure

    @is_critical_failure.setter
    def is_critical_failure(self, val: bool) -> None:
        self.is_crit_failure = val

    @property
    def target_dc(self) -> Optional[int]:
        return self.dc

    @target_dc.setter
    def target_dc(self, val: Optional[int]) -> None:
        self.dc = val


class ActionDirective(BaseModel):
    """Dyrektywa akcji narracyjnej lub mechanicznej wygenerowana przez AI lub komende."""
    action_type: str  # roll_check, damage_player, heal_player, award_item, quest_update, reply
    payload: Dict[str, Any] = Field(default_factory=dict)
    target_user_id: Optional[str] = None


class Combatant(BaseModel):
    """Uczestnik starcia (gracz lub potwor)."""
    name: str
    initiative: int
    current_hp: int
    max_hp: int
    armor_class: int
    is_player: bool
    status_effects: List[str] = Field(default_factory=list)


class CombatState(BaseModel):
    """Stan aktywnej walki."""
    is_active: bool = False
    round_number: int = 1
    current_turn_index: int = 0
    combatants: List[Combatant] = Field(default_factory=list)
