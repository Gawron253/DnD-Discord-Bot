"""Silnik rzutów kośćmi RPG oparty na d20 z obsługą D&D 5e, Advantage/Disadvantage i DC.
100% deterministyczny kod w Pythonie (0 tokenów AI).
"""
import re
from typing import Optional, List
import d20
from core.models import DiceRollResult


def create_health_bar(current: int, max_val: int, length: int = 10) -> str:
    """Generuje graficzny pasek zdrowia w formacie [████████░░] {current}/{max_val} HP.
    
    Bezpiecznie obsługuje wartości graniczne: ujemne HP, przekroczenie max_hp, max_hp <= 0.
    """
    if max_val <= 0:
        ratio = 0.0
        safe_max = max(0, max_val)
    elif current < 0:
        ratio = 0.0
        safe_max = max_val
    else:
        ratio = max(0.0, min(1.0, current / max_val))
        safe_max = max_val

    filled = int(round(ratio * length))
    empty = max(0, length - filled)
    return f"[{'█' * filled}{'░' * empty}] {current}/{safe_max} HP"


def _extract_individual_dice_rolls(node) -> List[int]:
    """Wyciąga wartości poszczególnych wyrzuconych kości z drzewa AST biblioteki d20."""
    rolls: List[int] = []
    if isinstance(node, d20.Dice):
        for die in getattr(node, "values", []):
            if hasattr(die, "values"):
                for val in die.values:
                    if hasattr(val, "number"):
                        rolls.append(val.number)
                    elif hasattr(val, "total"):
                        rolls.append(val.total)
            elif hasattr(die, "total"):
                rolls.append(die.total)
    if hasattr(node, "children"):
        for ch in node.children:
            rolls.extend(_extract_individual_dice_rolls(ch))
    return rolls


def roll_dice(
    formula: str,
    reason: Optional[str] = "Rzut testowy",
    target_dc: Optional[int] = None,
    dc: Optional[int] = None,
    advantage_disadvantage: str = "normal",
    advantage: bool = False,
    disadvantage: bool = False
) -> DiceRollResult:
    """Wykonuje deterministyczny rzut kością i zwraca ustrukturyzowany wynik DiceRollResult.
    
    Obsługuje:
    - Podstawowe formuły (1d20+5, 2d6+3, 20d6)
    - Modyfikatory ujemne (1d20-5)
    - Rzuty z ułatwieniem (advantage -> 2d20kh1) i utrudnieniem (disadvantage -> 2d20kl1)
    - Wykrywanie krytycznych sukcesów (Natural 20) i porażek (Natural 1)
    - Porównanie ze stopniem trudności DC (total >= dc)
    """
    clean_formula = formula.strip()
    
    # Obsługa parametru target_dc / dc
    effective_dc = target_dc if target_dc is not None else dc

    # Obsługa ułatwień / utrudnień
    is_advantage = advantage or (advantage_disadvantage.lower() == "advantage")
    is_disadvantage = disadvantage or (advantage_disadvantage.lower() == "disadvantage")

    if is_advantage and not is_disadvantage:
        if "1d20" in clean_formula:
            clean_formula = re.sub(r"\b1d20\b", "2d20kh1", clean_formula)
        elif "d20" in clean_formula and "2d20" not in clean_formula:
            clean_formula = re.sub(r"\bd20\b", "2d20kh1", clean_formula)
    elif is_disadvantage and not is_advantage:
        if "1d20" in clean_formula:
            clean_formula = re.sub(r"\b1d20\b", "2d20kl1", clean_formula)
        elif "d20" in clean_formula and "2d20" not in clean_formula:
            clean_formula = re.sub(r"\bd20\b", "2d20kl1", clean_formula)

    # Wykonanie rzutu biblioteką d20 (rzuci błąd w przypadku niepoprawnej formuły)
    result = d20.roll(clean_formula)
    total = result.total
    breakdown = str(result)

    # Wyciągnięcie pojedynczych wartości kości
    dice_rolls = _extract_individual_dice_rolls(result.expr)
    
    # Wyliczenie modyfikatora
    if dice_rolls:
        modifier = total - sum(dice_rolls)
    else:
        modifier = 0

    # Wykrywanie krytycznych sukcesów / porażek
    is_crit_succ = result.crit == d20.CritType.CRIT
    is_crit_fail = result.crit == d20.CritType.FAIL

    # Fallback dla bezpośrednich rzutów 1d20 jeśli biblioteka d20 nie oznaczyła
    if not is_crit_succ and not is_crit_fail and "d20" in clean_formula:
        if total == 20 and len(dice_rolls) == 1 and dice_rolls[0] == 20:
            is_crit_succ = True
        elif total == 1 and len(dice_rolls) == 1 and dice_rolls[0] == 1:
            is_crit_fail = True

    # Ocena względem DC
    is_success: Optional[bool] = None
    if effective_dc is not None:
        is_success = total >= effective_dc

    return DiceRollResult(
        formula=clean_formula,
        total=total,
        dice_rolls=dice_rolls,
        modifier=modifier,
        is_crit_success=is_crit_succ,
        is_crit_failure=is_crit_fail,
        dc=effective_dc,
        is_success=is_success,
        reason=reason or "Rzut kością",
        breakdown=breakdown
    )
