"""Moduł dynamicznego budowania kontekstu dla Google Gemini bezpośrednio ze stanu Discorda.
Bezstanowy skan historii kanału, filtrowanie OOC ((...)) i //..., parsowanie embedów rzutów,
odczyt aktualnych zasad z #zasady-i-mechanika oraz kart postaci z forum #karty-postaci (z 24h auto-unarchive).
"""
from __future__ import annotations
import unicodedata
import discord
from typing import List, Dict, Any, Optional, Union, Tuple

from core.discord_db import get_character_from_thread, _get_all_forum_threads
from core.models import CharacterModel
from config.prompts import DUNGEON_MASTER_SYSTEM_PROMPT


def normalize_channel_name(name: str) -> str:
    """Normalizuje nazwę kanału (usuwa polskie znaki, myślniki, spacje) do elastycznych porównań."""
    if not name:
        return ""
    name_mapped = name.replace("ł", "l").replace("Ł", "L")
    nfkd_form = unicodedata.normalize('NFKD', name_mapped)
    only_ascii = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return "".join(c.lower() for c in only_ascii if c.isalnum())



def is_ooc_message(content: str) -> bool:
    """
    Sprawdza, czy wiadomość jest pozagrową rozmową graczy (Out of Character - OOC).
    Wykrywa formaty: ((...)), //..., /*...*/ oraz linie zaczynające się od OOC:.
    """
    if not content:
        return False
    stripped = content.strip()
    if stripped.startswith("((") and stripped.endswith("))"):
        return True
    if stripped.startswith("((") or stripped.endswith("))"):
        return True
    if stripped.startswith("//"):
        return True
    if stripped.startswith("/*") and stripped.endswith("*/"):
        return True
    if stripped.lower().startswith("ooc:"):
        return True
    return False


async def parse_dice_roll_embed(embed: Union[discord.Embed, Any]) -> Optional[str]:
    """Wyciąga sformatowane informacje o rzucie kością z embedu."""
    title = getattr(embed, "title", "") or ""
    if not ("rzuca:" in title.lower() or "rzut" in title.lower()):
        return None

    wynik = ""
    dc_str = ""
    fields = getattr(embed, "fields", []) or []
    for field in fields:
        fname = getattr(field, "name", "").lower()
        fval = getattr(field, "value", "")
        if "wynik" in fname:
            wynik = fval.replace("#", "").replace("*", "").strip()
        elif "dc" in fname or "stopien" in fname or "stopień" in fname:
            dc_str = f" ({fval.strip()})"

    if wynik or title:
        return f"[SYSTEM RZUTOW]: {title} -> Wynik: {wynik}{dc_str}".strip()
    return None


async def fetch_messages_since_last_dm_response(
    channel: discord.TextChannel,
    bot_user: discord.ClientUser,
    guild: Optional[discord.Guild] = None
) -> str:
    """
    Pobiera poprzednią narrację bota oraz wszystkie nowe wypowiedzi graczy i rzuty kośćmi (embedy) od tamtej pory.
    Filtruje czat OOC ((...)), rozpoznaje rzuty kośćmi wysyłane przez bota i zachowuje porządek chronologiczny.
    """
    # 1. Pobranie ostatnich wiadomości ze stołu gry
    messages: List[discord.Message] = []
    try:
        if hasattr(channel, "history"):
            async for msg in channel.history(limit=30, oldest_first=False):
                messages.append(msg)
    except Exception:
        pass

    # Ułożenie w porządku chronologicznym (od najstarszej do najnowszej)
    messages.reverse()

    # 2. Wyszukanie ostatniej wiadomości NARRACYJNEJ bota (z wykluczeniem rzutów kośćmi)
    last_story_msg_index = -1
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if bot_user and msg.author.id == bot_user.id:
            # Sprawdź czy to rzut kością
            is_roll = False
            if getattr(msg, "embeds", None):
                for emb in msg.embeds:
                    if await parse_dice_roll_embed(emb) is not None:
                        is_roll = True
                        break
            if not is_roll and msg.content and len(msg.content.strip()) > 0:
                last_story_msg_index = i
                break

    events_list: List[str] = []

    # Jeśli odnaleziono poprzednią narrację Mistrza Gry, dołączamy ją do kontekstu
    if last_story_msg_index != -1:
        prev_story = messages[last_story_msg_index].content.strip()
        if len(prev_story) > 600:
            prev_story = prev_story[:600] + "..."
        events_list.append(f"[POPRZEDNIA NARRACJA MISTRZA GRY]:\n\"{prev_story}\"\n")
        relevant_messages = messages[last_story_msg_index + 1:]
    else:
        relevant_messages = messages

    # 3. Parsowanie nowych zdarzeń (rzutów kośćmi i deklaracji graczy)
    for msg in relevant_messages:
        # A. Embed z rzutem kością (może pochodzić z interakcji bota lub gracza)
        if getattr(msg, "embeds", None):
            for embed in msg.embeds:
                parsed_roll = await parse_dice_roll_embed(embed)
                if parsed_roll and parsed_roll not in events_list:
                    events_list.append(parsed_roll)

        # B. Deklaracja tekstowa gracza
        if not getattr(msg.author, "bot", False) and msg.content and msg.content.strip():
            if is_ooc_message(msg.content):
                continue
            clean_content = msg.content
            if bot_user:
                clean_content = clean_content.replace(f"<@{bot_user.id}>", "").replace(f"<@!{bot_user.id}>", "").replace("@Mistrz Gry", "").replace("@MistrzGry", "").replace("@DM", "").strip()
            if clean_content:
                events_list.append(f"[{msg.author.display_name}]: {clean_content}")

    # 4. Sprawdzenie dedykowanego kanału rzutów kośćmi (#rzuty-kości / #rzuty-kostkami), jeśli istnieje
    target_guild = guild or getattr(channel, "guild", None)
    if target_guild:
        dice_ch = None
        for ch in getattr(target_guild, "text_channels", []):
            norm_name = normalize_channel_name(ch.name)
            if norm_name in ("rzutykosci", "rzutykostkami", "rzuty") and ch.id != channel.id:
                dice_ch = ch
                break

        if dice_ch and hasattr(dice_ch, "history"):
            try:
                dice_messages: List[discord.Message] = []
                async for dmsg in dice_ch.history(limit=10, oldest_first=False):
                    dice_messages.append(dmsg)
                dice_messages.reverse()
                for dmsg in dice_messages:
                    if getattr(dmsg, "embeds", None):
                        for embed in dmsg.embeds:
                            parsed_roll = await parse_dice_roll_embed(embed)
                            if parsed_roll and parsed_roll not in events_list:
                                events_list.append(parsed_roll)
            except Exception:
                pass

    return "\n".join(events_list)


async def fetch_campaign_rules(guild_or_channel: Union[discord.Guild, discord.TextChannel]) -> str:
    """
    Odczytuje aktualne zasady z przypiętego posta lub wiadomości w kanale #zasady-i-mechanika.
    Zapewnia pełną zgodność z modyfikacjami reguł na żywo przez graczy i DM.
    """
    rules_channel = None

    if hasattr(guild_or_channel, "text_channels"):
        for ch in guild_or_channel.text_channels:
            if "zasady" in normalize_channel_name(ch.name):
                rules_channel = ch
                break
    elif hasattr(guild_or_channel, "pins") and (hasattr(guild_or_channel, "history") or hasattr(guild_or_channel, "send")):
        rules_channel = guild_or_channel

    if not rules_channel:
        return "System bazowy: Standardowe D&D 5e."

    try:
        pinned = await rules_channel.pins()
        if pinned:
            first_pin = pinned[0]
            if getattr(first_pin, "content", None):
                return first_pin.content
            if getattr(first_pin, "embeds", None) and first_pin.embeds:
                return first_pin.embeds[0].description or first_pin.embeds[0].title or "Standardowe D&D 5e."

        async for msg in rules_channel.history(limit=3, oldest_first=False):
            if getattr(msg, "content", None):
                return msg.content
            if getattr(msg, "embeds", None) and msg.embeds:
                return msg.embeds[0].description or "Standardowe D&D 5e."
    except Exception:
        pass

    return "System bazowy: Standardowe D&D 5e."


async def fetch_active_characters(guild: discord.Guild) -> List[Dict[str, Any]]:
    """
    Odczytuje karty postaci wszystkich graczy z forum #karty-postaci.
    Wykrywa uśpione wątki (starsze niż 24h) i automatycznie je przywraca (unarchive).
    """
    forum = None
    for f in getattr(guild, "forums", []):
        if "karty" in normalize_channel_name(f.name):
            forum = f
            break

    if not forum and hasattr(guild, "channels"):
        for c in guild.channels:
            if isinstance(c, getattr(discord, "ForumChannel", type(None))) and "karty" in normalize_channel_name(c.name):
                forum = c
                break

    if not forum:
        return []

    characters: List[Dict[str, Any]] = []
    all_threads = await _get_all_forum_threads(forum)

    for thread in all_threads:
        # Automatyczne budzenie uśpionych wątków
        if getattr(thread, "archived", False):
            try:
                await thread.edit(archived=False)
            except Exception:
                pass

        char = await get_character_from_thread(thread)
        if char:
            characters.append(char.model_dump())

    return characters


async def fetch_campaign_lore_and_chronicle(guild: Optional[discord.Guild]) -> str:
    """
    Odczytuje wpisy encyklopedyczne z forum #kompendium-i-lore oraz ostatnie wpisy z #kronika-przygod.
    """
    if not guild:
        return ""

    lore_snippets: List[str] = []

    # 1. Odczyt z kanału #kronika-przygod
    for ch in getattr(guild, "text_channels", []):
        if "kronika" in normalize_channel_name(ch.name):
            try:
                if hasattr(ch, "pins"):
                    pins = await ch.pins()
                    if pins and getattr(pins[0], "content", None):
                        lore_snippets.append(f"📖 **Ostatnie wydarzenia z Kroniki:**\n{pins[0].content}")
                if not lore_snippets and hasattr(ch, "history"):
                    async for msg in ch.history(limit=2, oldest_first=False):
                        if getattr(msg, "content", None):
                            lore_snippets.append(f"📖 **Kronika:**\n{msg.content[:400]}")
                            break
            except Exception:
                pass
            break

    # 2. Odczyt wątków z forum #kompendium-i-lore
    forums = getattr(guild, "forums", [])
    if not forums and hasattr(guild, "channels"):
        forums = [c for c in guild.channels if isinstance(c, getattr(discord, "ForumChannel", type(None)))]
    for forum in forums:
        if "kompendium" in normalize_channel_name(forum.name) or "lore" in normalize_channel_name(forum.name):
            try:
                threads = await _get_all_forum_threads(forum)
                topics = []
                for th in threads[:5]:
                    starter = getattr(th, "starter_message", None)
                    content = starter.content[:200] if starter and getattr(starter, "content", None) else ""
                    topics.append(f"• **{th.name}**: {content}" if content else f"• **{th.name}**")
                if topics:
                    lore_snippets.append("🏛️ **Znane Lokacje i Lore z Kompendium:**\n" + "\n".join(topics))
            except Exception:
                pass
            break

    return "\n\n".join(lore_snippets)


async def build_full_dm_context(
    guild: discord.Guild,
    table_channel: discord.TextChannel,
    bot_user: discord.ClientUser,
    custom_system_prompt: Optional[str] = None
) -> Tuple[str, str]:
    """
    Zbiera pełen 4-warstwowy stan kampanii z Discorda i przygotowuje prompty dla Gemini:
    - Warstwa 1: System Persona (DM Prompt + instrukcje przycisków akcji)
    - Warstwa 2: Live Rules z #zasady-i-mechanika + Lore z #kompendium-i-lore + #kronika-przygod
    - Warstwa 3: Karty postaci z forum #karty-postaci
    - Warstwa 4: Historia wypowiedzi i rzutów z #stół-gry

    Returns:
        Tuple[system_prompt, context_prompt]
    """
    from ai.gemini_client import build_4layer_prompt

    rules = await fetch_campaign_rules(guild)
    lore = await fetch_campaign_lore_and_chronicle(guild)
    if lore:
        rules = f"{rules}\n\n=== [ENCYKLOPEDIA I KRONIKA ŚWIATA] ===\n{lore}"

    characters = await fetch_active_characters(guild)
    events = await fetch_messages_since_last_dm_response(table_channel, bot_user, guild=guild)

    return build_4layer_prompt(
        rules=rules,
        characters=characters,
        events=events,
        custom_system_prompt=custom_system_prompt
    )
