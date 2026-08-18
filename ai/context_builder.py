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
    Pobiera wszystkie wypowiedzi graczy oraz rzuty kośćmi (embedy) od ostatniej odpowiedzi bota.
    Filtruje czat OOC ((...)) i zachowuje porządek chronologiczny.
    """
    last_bot_message = None

    # 1. Skanowanie wstecz w poszukiwaniu ostatniej wiadomości bota na stole gry
    try:
        async for msg in channel.history(limit=50):
            if msg.author.id == bot_user.id:
                last_bot_message = msg
                break
    except Exception:
        pass

    # 2. Pobranie wiadomości PO ostatniej odpowiedzi bota (chronologicznie od najstarszej)
    new_events: List[str] = []
    history_iterator = (
        channel.history(limit=30, after=last_bot_message, oldest_first=True)
        if last_bot_message
        else channel.history(limit=15, oldest_first=True)
    )

    async for msg in history_iterator:
        # Pomiń wiadomości wysłane przez bota
        if msg.author.id == bot_user.id:
            continue

        # A. Deklaracja tekstowa gracza
        if not getattr(msg.author, "bot", False) and msg.content and msg.content.strip():
            if is_ooc_message(msg.content):
                continue
            new_events.append(f"[{msg.author.display_name}]: {msg.content.strip()}")

        # B. Embed z rzutem kością na stole gry
        if getattr(msg, "embeds", None):
            for embed in msg.embeds:
                parsed_roll = await parse_dice_roll_embed(embed)
                if parsed_roll:
                    new_events.append(parsed_roll)

    # 3. Sprawdzenie dedykowanego kanału rzutów kośćmi (#rzuty-kości / #rzuty-kostkami), jeśli istnieje
    target_guild = guild or getattr(channel, "guild", None)
    if target_guild:
        dice_ch = None
        for ch in getattr(target_guild, "text_channels", []):
            norm_name = normalize_channel_name(ch.name)
            if norm_name in ("rzutykosci", "rzutykostkami", "rzuty") and ch.id != channel.id:
                dice_ch = ch
                break

        if dice_ch:
            try:
                dice_iter = (
                    dice_ch.history(limit=15, after=last_bot_message, oldest_first=True)
                    if last_bot_message
                    else dice_ch.history(limit=10, oldest_first=True)
                )
                async for dmsg in dice_iter:
                    if getattr(dmsg, "embeds", None):
                        for embed in dmsg.embeds:
                            parsed_roll = await parse_dice_roll_embed(embed)
                            if parsed_roll and parsed_roll not in new_events:
                                new_events.append(parsed_roll)
            except Exception:
                pass

    return "\n".join(new_events)


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


async def build_full_dm_context(
    guild: discord.Guild,
    table_channel: discord.TextChannel,
    bot_user: discord.ClientUser,
    custom_system_prompt: Optional[str] = None
) -> Tuple[str, str]:
    """
    Zbiera pełen 4-warstwowy stan kampanii z Discorda i przygotowuje prompty dla Gemini:
    - Warstwa 1: System Persona (DM Prompt + instrukcje przycisków akcji)
    - Warstwa 2: Live Rules z #zasady-i-mechanika
    - Warstwa 3: Karty postaci z forum #karty-postaci
    - Warstwa 4: Historia wypowiedzi i rzutów z #stół-gry

    Returns:
        Tuple[system_prompt, context_prompt]
    """
    from ai.gemini_client import build_4layer_prompt

    rules = await fetch_campaign_rules(guild)
    characters = await fetch_active_characters(guild)
    events = await fetch_messages_since_last_dm_response(table_channel, bot_user, guild=guild)

    return build_4layer_prompt(
        rules=rules,
        characters=characters,
        events=events,
        custom_system_prompt=custom_system_prompt
    )
