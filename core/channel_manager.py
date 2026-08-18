"""Modul zarzadzania hierarchia kanalow i forow kampanii RPG na serwerze Discord.
Zapewnia pelna idempotetnosc (bezpieczne wielokrotne uruchomienie /setup-campaign).
"""
import unicodedata
from typing import Dict, List, Any, Optional
import discord

from core.models import QuestList
from core.discord_db import update_quest_board

DEFAULT_RULES_CONTENT = (
    "📌 **AKTUALNE ZASADY KAMPANII I ŚWIATA (Edytowalne w locie)**\n"
    "- **System**: D&D 5e (Dungeons & Dragons 5. edycja)\n"
    "- **Klimat**: Dark Fantasy / Epicka Przygoda\n"
    "- **Reguły domowe (Homebrew)**: Edytuj ten post, a AI Dungeon Master automatycznie zastosuje nowe reguły!"
)

CAMPAIGN_STRUCTURE = {
    "📜 KAMPANIA I FABUŁA": {
        "text": ["stół-gry", "dziennik-zadań", "kronika-przygod", "zasady-i-mechanika"],
        "forum": []
    },
    "🛡️ POSTACIE I MECHANIKA": {
        "text": ["rzuty-kości", "szepty-dm"],
        "forum": ["karty-postaci"]
    },
    "📖 ENCYKLOPEDIA I WIEDZA": {
        "text": [],
        "forum": ["kompendium-i-lore"]
    }
}


def normalize_name(name: str) -> str:
    """Normalizuje nazwe kanalu/kategorii do porownan (usuwa diakrytyki, spacje, male litery)."""
    if not name:
        return ""
    nfkd_form = unicodedata.normalize('NFKD', name)
    only_ascii = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    clean = "".join(c.lower() for c in only_ascii if c.isalnum() or c in ("-", "_"))
    return clean




def find_category(guild: discord.Guild, name: str) -> Optional[discord.CategoryChannel]:
    """Wyszukuje kategorie wedlug dokladnej lub znormalizowanej nazwy."""
    norm_target = normalize_name(name)
    for cat in getattr(guild, "categories", []):
        if cat.name == name or normalize_name(cat.name) == norm_target:
            return cat
    return None


def find_text_channel(
    guild: discord.Guild,
    name: str,
    category: Optional[discord.CategoryChannel] = None
) -> Optional[discord.TextChannel]:
    """Wyszukuje kanal tekstowy wedlug dokladnej lub znormalizowanej nazwy."""
    norm_target = normalize_name(name)
    # Sprawdz najpierw w kategorii
    if category and hasattr(category, "text_channels"):
        for ch in category.text_channels:
            if ch.name == name or normalize_name(ch.name) == norm_target:
                return ch
    # Sprawdz w calym guild
    for ch in getattr(guild, "text_channels", []):
        if ch.name == name or normalize_name(ch.name) == norm_target:
            return ch
    return None


def find_forum_channel(
    guild: discord.Guild,
    name: str,
    category: Optional[discord.CategoryChannel] = None
) -> Optional[discord.ForumChannel]:
    """Wyszukuje kanal forum wedlug dokladnej lub znormalizowanej nazwy."""
    norm_target = normalize_name(name)
    forums = getattr(guild, "forums", [])
    if not forums and hasattr(guild, "channels"):
        forums = [c for c in guild.channels if isinstance(c, getattr(discord, "ForumChannel", type(None)))]
    for forum in forums:
        if forum.name == name or normalize_name(forum.name) == norm_target:
            return forum
    return None


async def setup_campaign_infrastructure(guild: discord.Guild) -> Dict[str, Any]:
    """
    Idempotentny kreator struktury kampanii na Discordzie.
    Tworzy kategorie, kanaly tekstowe, fora oraz inicjalizuje przypiete posty w #zasady-i-mechanika oraz #dziennik-zadan.
    """
    report = {
        "categories_created": [],
        "channels_created": [],
        "forums_created": [],
        "reused": [],
        "initialized_pins": []
    }

    for cat_name, items in CAMPAIGN_STRUCTURE.items():
        cat = find_category(guild, cat_name)
        if not cat:
            cat = await guild.create_category(name=cat_name)
            report["categories_created"].append(cat_name)
        else:
            report["reused"].append(f"Kategoria: {cat.name}")

        # 1. Kanaly tekstowe
        for ch_name in items.get("text", []):
            ch = find_text_channel(guild, ch_name, category=cat)
            if not ch:
                ch = await guild.create_text_channel(name=ch_name, category=cat)
                report["channels_created"].append(f"#{ch_name}")
            else:
                report["reused"].append(f"#{ch.name}")

            # Inicjalizacja przypietego posta zasad
            if "zasady" in normalize_name(ch_name):
                pins = await ch.pins()
                if not pins:
                    msg = await ch.send(DEFAULT_RULES_CONTENT)
                    try:
                        await msg.pin()
                        report["initialized_pins"].append(f"#{ch_name} (Zasady)")
                    except Exception:
                        pass

            # Inicjalizacja przypietego dziennika zadan
            if "dziennik" in normalize_name(ch_name) or "zadan" in normalize_name(ch_name):
                pins = await ch.pins()
                if not pins:
                    await update_quest_board(ch, QuestList(quests=[]))
                    report["initialized_pins"].append(f"#{ch_name} (Dziennik zadań)")

        # 2. Kanaly Forum
        for forum_name in items.get("forum", []):
            forum = find_forum_channel(guild, forum_name, category=cat)
            if not forum:
                forum = await guild.create_forum(name=forum_name, category=cat)
                report["forums_created"].append(f"💬 [Forum] #{forum_name}")
            else:
                report["reused"].append(f"💬 [Forum] #{forum.name}")

    return report
