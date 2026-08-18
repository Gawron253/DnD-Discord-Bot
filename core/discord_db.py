"""Modul zarzadzania stanem postaci, zadan i zasad bezposrednio w Discordzie.
Brak zewnetrznych baz danych - Discord (kanaly, watki, embedy, komentarze HTML) jest jedynym zrodlem prawdy.
"""
import re
import json
import inspect
from typing import Optional, Dict, Any, Union, List, Tuple
import discord

from core.models import CharacterModel, QuestList, QuestItem, QuestObjective


JSON_PATTERN = re.compile(r"<!--\s*DATA_JSON:\s*(.*?)\s*-->", re.DOTALL)


def extract_data_from_text(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Wyciaga strukturalne dane JSON ukryte w komentarzu HTML posta lub opisu embedu."""
    if not text:
        return None
    match = JSON_PATTERN.search(text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except Exception:
            return None
    return None


extract_json_from_message = extract_data_from_text


def inject_data_into_text(base_text: str, data: Dict[str, Any]) -> str:
    """Wstrzykuje lub aktualizuje ukryty blok danych JSON na koncu tekstu."""
    clean_text = JSON_PATTERN.sub("", base_text or "").strip()
    json_str = json.dumps(data, ensure_ascii=False)
    if clean_text:
        return f"{clean_text}\n\n<!-- DATA_JSON: {json_str} -->"
    return f"<!-- DATA_JSON: {json_str} -->"


inject_json_to_text = inject_data_into_text


def extract_data_from_message_or_embed(msg: discord.Message) -> Optional[Dict[str, Any]]:
    """Pomocnik wyciagajacy dane JSON z opisu embedu, stopki lub samej tresci wiadomosci."""
    if not msg:
        return None
    if getattr(msg, "embeds", None):
        for emb in msg.embeds:
            if getattr(emb, "description", None):
                data = extract_data_from_text(emb.description)
                if data is not None:
                    return data
            if getattr(emb, "footer", None) and getattr(emb.footer, "text", None):
                data = extract_data_from_text(emb.footer.text)
                if data is not None:
                    return data
    if getattr(msg, "content", None):
        data = extract_data_from_text(msg.content)
        if data is not None:
            return data
    return None


def create_health_bar(current: int, max_val: int, length: int = 10) -> str:
    """Generuje graficzny pasek zdrowia w formacie [████████░░] {current}/{max_val} HP."""
    if max_val <= 0:
        ratio = 0.0
        safe_max = max(0, max_val)
    else:
        ratio = max(0.0, min(1.0, current / max_val))
        safe_max = max_val
    filled = int(round(ratio * length))
    empty = max(0, length - filled)
    return f"[{'█' * filled}{'░' * empty}] {current}/{safe_max} HP"


def build_character_sheet_embed(char: CharacterModel) -> discord.Embed:
    """Generuje estetyczny embed karty postaci z paskiem zycia i ukrytym DATA_JSON."""
    embed = discord.Embed(
        title=f"🛡️ {char.name} – Poziom {char.level} {char.race} {char.character_class}",
        description=inject_data_into_text("", char.model_dump()),
        color=discord.Color.dark_teal()
    )
    if char.avatar_url:
        embed.set_thumbnail(url=char.avatar_url)

    embed.add_field(
        name="❤️ Żywotność",
        value=f"`{create_health_bar(char.current_hp, char.max_hp)}`",
        inline=False
    )
    embed.add_field(name="🛡️ Klasa Pancerza (AC)", value=f"**{char.armor_class}**", inline=True)
    embed.add_field(name="⚡ Szybkość", value=f"{char.speed} ft", inline=True)
    embed.add_field(name="💰 Złoto", value=f"**{char.gold_gp}** GP", inline=True)

    s = char.stats
    stats_text = (
        f"**STR:** {s.strength} ({s.get_modifier('strength'):+d}) | "
        f"**DEX:** {s.dexterity} ({s.get_modifier('dexterity'):+d}) | "
        f"**CON:** {s.constitution} ({s.get_modifier('constitution'):+d})\n"
        f"**INT:** {s.intelligence} ({s.get_modifier('intelligence'):+d}) | "
        f"**WIS:** {s.wisdom} ({s.get_modifier('wisdom'):+d}) | "
        f"**CHA:** {s.charisma} ({s.get_modifier('charisma'):+d})"
    )
    embed.add_field(name="📊 Cechy i Modyfikatory", value=stats_text, inline=False)

    if char.inventory:
        inv_items = [f"• {item.name} (x{item.quantity})" for item in char.inventory]
        embed.add_field(name="🎒 Ekwipunek", value="\n".join(inv_items[:10]), inline=False)

    if char.conditions:
        embed.add_field(name="⚠️ Aktywne Stany", value=", ".join(f"`{c}`" for c in char.conditions), inline=False)

    embed.set_footer(text=f"ID Gracza: {char.discord_user_id} | Synchronizacja Pure Discord DB")
    return embed


create_character_sheet_embed = build_character_sheet_embed




def build_quest_board_embed(quest_list: QuestList) -> discord.Embed:
    """Generuje estetyczny embed tablicy zadan z ukrytym DATA_JSON."""
    embed = discord.Embed(
        title="📜 Tablica Zadań i Dziennik Przygód",
        description=inject_data_into_text(
            "Aktualna lista aktywnych i zrealizowanych zadań w kampanii.\n"
            "Użyj `/quest create` lub `/quest complete`, aby zarządzać zadaniami.",
            quest_list.model_dump()
        ),
        color=discord.Color.gold()
    )
    active = quest_list.active_quests()
    if active:
        for q in active:
            objs = "\n".join(f"{'✅' if o.is_completed else '⬜'} {o.text}" for o in q.objectives)
            rew = f"\n💰 **Nagroda:** {q.reward}" if q.reward else ""
            giver = f" (Zleceniodawca: *{q.giver}*)" if q.giver else ""
            val = f"**Opis:** {q.description or 'Brak opisu'}{giver}\n**Cele:**\n{objs or '• Brak określonych celów'}{rew}"
            embed.add_field(name=f"⚔️ [{q.id}] {q.title}", value=val, inline=False)
    else:
        embed.add_field(name="⚔️ Aktywne Zadania", value="*Brak aktywnych zadań w dzienniku.*", inline=False)

    completed = quest_list.completed_quests()
    if completed:
        comp_titles = [f"• ~~[{q.id}] {q.title}~~" for q in completed]
        embed.add_field(name="🏆 Ukończone Zadania", value="\n".join(comp_titles[:10]), inline=False)

    embed.set_footer(text="Dziennik synchronizowany automatycznie przez Pure Discord State")
    return embed


async def _get_all_forum_threads(forum: discord.ForumChannel) -> List[discord.Thread]:
    """Pobiera wszystkie watki forum (aktywne oraz zarchiwizowane)."""
    threads = list(getattr(forum, "threads", []))
    
    # Obsluga archiwum forum
    if hasattr(forum, "archived_threads"):
        arch_res = forum.archived_threads()
        if hasattr(arch_res, "__aiter__"):
            async for t in arch_res:
                if t not in threads:
                    threads.append(t)
        elif inspect.isawaitable(arch_res):
            arch_list = await arch_res
            for t in arch_list:
                if t not in threads:
                    threads.append(t)
        elif isinstance(arch_res, (list, tuple)):
            for t in arch_res:
                if t not in threads:
                    threads.append(t)
    return threads


async def get_or_create_character_sheet(
    forum: discord.ForumChannel,
    user_id: Union[str, int],
    character: Optional[CharacterModel] = None
) -> Tuple[discord.Thread, discord.Message, CharacterModel]:
    """
    Wyszukuje lub tworzy watek z karta postaci na forum #karty-postaci.
    Jesli watek byl zarchiwizowany (>24h bezczynnosci), automatycznie go odarchiwizowuje.
    """
    str_user_id = str(user_id)
    all_threads = await _get_all_forum_threads(forum)
    
    target_thread: Optional[discord.Thread] = None
    target_msg: Optional[discord.Message] = None
    parsed_char: Optional[CharacterModel] = None

    # 1. Poszukiwanie watku przypisanego do user_id
    for t in all_threads:
        # Sprawdzanie po nazwie watku (np. "🛡️ Conan (12345)")
        if str_user_id in getattr(t, "name", ""):
            target_thread = t
            break

    # Jesli nie znaleziono po nazwie, sprawdz zawartosc przypietych wiadomosci
    if not target_thread:
        for t in all_threads:
            try:
                pins = await t.pins()
                for p in pins:
                    data = extract_data_from_message_or_embed(p)
                    if data and str(data.get("discord_user_id")) == str_user_id:
                        target_thread = t
                        target_msg = p
                        parsed_char = CharacterModel(**data)
                        break
            except Exception:
                continue
            if target_thread:
                break

    # 2. Jesli znaleziono istniejacy watek
    if target_thread:
        # Auto-odarchiwizowanie jesli spiacy
        if getattr(target_thread, "archived", False):
            await target_thread.edit(archived=False)

        # Odczytanie przypietej karty
        if not target_msg:
            try:
                pins = await target_thread.pins()
                if pins:
                    target_msg = pins[0]
                else:
                    async for msg in target_thread.history(limit=5, oldest_first=True):
                        if extract_data_from_message_or_embed(msg):
                            target_msg = msg
                            break
            except Exception:
                pass

        if target_msg and not parsed_char:
            data = extract_data_from_message_or_embed(target_msg)
            if data:
                try:
                    parsed_char = CharacterModel(**data)
                except Exception:
                    pass

        # Jesli nie ma karty lub jest uszkodzona, uzyj dostarczonej
        if not parsed_char:
            parsed_char = character or CharacterModel(
                discord_user_id=str_user_id,
                name=f"Bohater-{str_user_id[-4:]}",
                character_class="Wojownik",
                race="Człowiek"
            )
            embed = build_character_sheet_embed(parsed_char)
            if target_msg:
                await target_msg.edit(embed=embed)
            else:
                target_msg = await target_thread.send(embed=embed)
                try:
                    await target_msg.pin()
                except Exception:
                    pass
        return target_thread, target_msg, parsed_char

    # 3. Brak watku - tworzymy nowy watek karty postaci
    char_to_use = character or CharacterModel(
        discord_user_id=str_user_id,
        name=f"Bohater-{str_user_id[-4:]}",
        character_class="Wojownik",
        race="Człowiek"
    )
    embed = build_character_sheet_embed(char_to_use)
    thread_name = f"🛡️ {char_to_use.name} ({str_user_id})"

    res = await forum.create_thread(name=thread_name, embed=embed)
    if hasattr(res, "thread") and hasattr(res, "message"):
        created_thread = res.thread
        created_msg = res.message
    elif isinstance(res, (list, tuple)) and len(res) == 2:
        created_thread = res[0]
        created_msg = res[1]
    else:
        created_thread = res
        created_msg = getattr(created_thread, "starter_message", None)
        if not created_msg:
            created_msg = await created_thread.send(embed=embed)

    try:
        await created_msg.pin()
    except Exception:
        pass

    return created_thread, created_msg, char_to_use


async def update_character_sheet(
    thread: discord.Thread,
    character: CharacterModel,
    reason: str = ""
) -> discord.Message:
    """Aktualizuje przypiety embed karty postaci w watku oraz publikuje wpis audytowy."""
    if getattr(thread, "archived", False):
        await thread.edit(archived=False)

    pins = await thread.pins()
    target_msg = pins[0] if pins else None
    if not target_msg:
        async for msg in thread.history(limit=5, oldest_first=True):
            if msg.embeds or extract_data_from_message_or_embed(msg):
                target_msg = msg
                break

    embed = build_character_sheet_embed(character)
    if target_msg:
        await target_msg.edit(embed=embed)
    else:
        target_msg = await thread.send(embed=embed)
        try:
            await target_msg.pin()
        except Exception:
            pass

    # Rejestracja wpisu w historii watku
    audit_header = f"📝 **Aktualizacja karty postaci**"
    if reason:
        audit_header += f" | Powód: *{reason}*"
    audit_body = (
        f"{audit_header}\n"
        f"❤️ HP: **{character.current_hp}/{character.max_hp}** (Temp: {character.temp_hp}) | "
        f"💰 Złoto: **{character.gold_gp}** GP | 🛡️ AC: **{character.armor_class}**"
    )
    await thread.send(audit_body)
    return target_msg


async def get_character_from_thread(thread: discord.Thread) -> Optional[CharacterModel]:
    """Odczytuje karte postaci z watku forum (z uwzglednieniem odarchiwizowania)."""
    try:
        if getattr(thread, "archived", False):
            await thread.edit(archived=False)
        pinned = await thread.pins()
        target_msg = pinned[0] if pinned else None
        if not target_msg:
            async for msg in thread.history(limit=5, oldest_first=True):
                if msg.embeds:
                    target_msg = msg
                    break
        if target_msg:
            data = extract_data_from_message_or_embed(target_msg)
            if data:
                return CharacterModel(**data)
    except Exception as e:
        print(f"Blad odczytu postaci z watku {getattr(thread, 'name', 'unknown')}: {e}")
    return None


async def get_quest_board(journal_channel: discord.TextChannel) -> QuestList:
    """Odczytuje aktualna tablice zadan z przypietego posta w #dziennik-zadan."""
    try:
        pins = await journal_channel.pins()
        for msg in pins:
            data = extract_data_from_message_or_embed(msg)
            if data and ("quests" in data or isinstance(data, list)):
                if isinstance(data, list):
                    return QuestList(quests=[QuestItem(**q) for q in data])
                return QuestList(**data)

        async for msg in journal_channel.history(limit=10, oldest_first=False):
            data = extract_data_from_message_or_embed(msg)
            if data and ("quests" in data or isinstance(data, list)):
                if isinstance(data, list):
                    return QuestList(quests=[QuestItem(**q) for q in data])
                return QuestList(**data)
    except Exception as e:
        print(f"Blad odczytu tablicy zadan: {e}")
    return QuestList(quests=[])


async def update_quest_board(
    journal_channel: discord.TextChannel,
    quest_list: QuestList
) -> discord.Message:
    """Aktualizuje lub tworzy przypiety embed z tablica zadan w #dziennik-zadan."""
    pins = await journal_channel.pins()
    target_msg: Optional[discord.Message] = None
    for msg in pins:
        if getattr(msg, "embeds", None):
            title = msg.embeds[0].title or ""
            if "Tablica Zadań" in title or "Dziennik" in title or extract_data_from_message_or_embed(msg) is not None:
                target_msg = msg
                break

    embed = build_quest_board_embed(quest_list)
    if target_msg:
        await target_msg.edit(embed=embed)
        return target_msg
    else:
        target_msg = await journal_channel.send(embed=embed)
        try:
            await target_msg.pin()
        except Exception:
            pass
        return target_msg


async def fetch_campaign_rules(target: Any) -> str:
    """Odczytuje biezace reguly kampanii z kanalu #zasady-i-mechanika."""
    rules_channel: Optional[Any] = None
    if hasattr(target, "text_channels") and hasattr(target, "categories"):
        for ch in getattr(target, "text_channels", []):
            if "zasady" in getattr(ch, "name", "").lower():
                rules_channel = ch
                break
    elif hasattr(target, "pins") and (hasattr(target, "history") or hasattr(target, "send")):
        rules_channel = target

    if not rules_channel:
        return "System bazowy: Standardowe D&D 5e."

    try:
        pins = await rules_channel.pins()
        if pins:
            if pins[0].content:
                return pins[0].content
            if pins[0].embeds and pins[0].embeds[0].description:
                return pins[0].embeds[0].description
        async for msg in rules_channel.history(limit=5, oldest_first=False):
            if msg.content:
                return msg.content
            if msg.embeds and msg.embeds[0].description:
                return msg.embeds[0].description
    except Exception as e:
        print(f"Blad odczytu zasad: {e}")
    return "System bazowy: Standardowe D&D 5e."
