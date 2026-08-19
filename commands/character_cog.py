"""Moduł komend slash do zarządzania kartami postaci, punktami życia i ekwipunkiem."""
from typing import Optional, Literal
import discord
from discord import app_commands
from discord.ext import commands

from core.models import CharacterModel, ItemModel
from core.discord_db import (
    get_or_create_character_sheet,
    update_character_sheet,
    get_character_from_thread
)
from core.channel_manager import find_forum_channel
from mechanics.character_ops import (
    modify_hp,
    add_inventory_item,
    remove_inventory_item,
    modify_gold,
    short_rest,
    long_rest
)
from discord_ui.embeds import create_character_sheet_embed
from discord_ui.views import CharacterSheetView


class CharacterCog(commands.Cog):
    """Cog rejestrujący komendy slash dla postaci graczy (/sheet, /hp, /item, /rest, /gold)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _resolve_character(
        self,
        interaction: discord.Interaction,
        target_user: Optional[discord.User] = None
    ) -> Optional[tuple]:
        """Pomocnik pobierający forum #karty-postaci oraz wątek i postać gracza."""
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ Komenda dostępna wyłącznie na serwerze.")
            return None

        forum = find_forum_channel(guild, "karty-postaci")
        if not forum:
            await interaction.followup.send("❌ Nie znaleziono forum `#karty-postaci`. Użyj `/setup-campaign`.")
            return None

        user = target_user or interaction.user
        thread, msg, char = await get_or_create_character_sheet(forum, str(user.id))
        return forum, thread, msg, char, user

    @app_commands.command(name="sheet", description="Wyświetla kartę postaci gracza")
    @app_commands.describe(postac="Opcjonalny gracz, którego kartę chcesz wyświetlić (domyślnie Twoja)")
    async def show_sheet(self, interaction: discord.Interaction, postac: Optional[discord.User] = None):
        """Wyświetla bogaty embed karty postaci z paskiem zdrowia ASCII i statystykami."""
        await interaction.response.defer(ephemeral=False)
        resolved = await self._resolve_character(interaction, postac)
        if not resolved:
            return

        _, _, _, char, user = resolved
        embed = create_character_sheet_embed(char)
        view = CharacterSheetView(character=char)
        await interaction.followup.send(
            content=f"📜 **Karta postaci gracza {user.display_name}**:",
            embed=embed,
            view=view
        )

    @app_commands.command(name="hp", description="Modyfikuje punkty życia postaci (np. -5 obrażenia, +10 leczenie)")
    @app_commands.describe(
        wartosc="Wartość zmiany HP (np. -5 dla obrażeń, +10 dla leczenia)",
        postac="Gracz, którego HP ma zostać zmodyfikowane (domyślnie Ty)",
        powod="Powód zmiany punktów życia (np. Trafienie mieczem, Mikstura leczenia)"
    )
    async def change_hp(
        self,
        interaction: discord.Interaction,
        wartosc: int,
        postac: Optional[discord.User] = None,
        powod: Optional[str] = None
    ):
        """Zmienia punkty życia postaci, aktualizuje przypiętą kartę na forum i dodaje wpis w historii wątku."""
        await interaction.response.defer(ephemeral=False)
        resolved = await self._resolve_character(interaction, postac)
        if not resolved:
            return

        _, thread, _, char, user = resolved
        
        # Obliczenie zmiany HP
        curr_hp, temp_hp, audit_msg = modify_hp(char, wartosc)
        reason_str = powod or f"Komenda /hp {wartosc:+d}"
        
        # Zapis stanu w wątku forum
        await update_character_sheet(thread, char, reason=reason_str)

        # Zwrot informacji do gracza
        embed = discord.Embed(
            title=f"❤️ Aktualizacja Zdrowia: {char.name}",
            description=audit_msg,
            color=discord.Color.red() if wartosc < 0 else discord.Color.green()
        )
        embed.add_field(name="Powód", value=reason_str, inline=True)
        embed.add_field(name="Aktualny Stan", value=f"**{char.current_hp}/{char.max_hp} HP**", inline=True)
        embed.set_footer(text=f"Zsynchronizowano w wątku: #{thread.name}")

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="item", description="Zarządzanie ekwipunkiem postaci (dodawanie/usuwanie przedmiotów)")
    @app_commands.describe(
        akcja="Operacja do wykonania (add / remove / list)",
        nazwa="Nazwa przedmiotu",
        ilosc="Ilość przedmiotów (domyślnie 1)",
        postac="Gracz, którego ekwipunek modyfikujesz (domyślnie Ty)"
    )
    async def manage_item(
        self,
        interaction: discord.Interaction,
        akcja: Literal["add", "remove", "list"],
        nazwa: Optional[str] = None,
        ilosc: Optional[int] = 1,
        postac: Optional[discord.User] = None
    ):
        """Dodaje lub usuwa przedmioty z ekwipunku postaci."""
        await interaction.response.defer(ephemeral=False)
        resolved = await self._resolve_character(interaction, postac)
        if not resolved:
            return

        _, thread, _, char, user = resolved
        qty = max(1, ilosc or 1)

        if akcja == "list":
            embed = discord.Embed(
                title=f"🎒 Ekwipunek: {char.name}",
                color=discord.Color.blue()
            )
            if char.inventory:
                lines = [f"• **{item.name}** x{item.quantity} ({item.item_type})" for item in char.inventory]
                embed.description = "\n".join(lines)
            else:
                embed.description = "*Ekwipunek jest pusty.*"
            await interaction.followup.send(embed=embed)
            return

        if not nazwa:
            await interaction.followup.send("❌ Podaj nazwę przedmiotu dla operacji `add` lub `remove`.")
            return

        clean_item_name = nazwa.strip()

        if akcja == "add":
            item = add_inventory_item(char, clean_item_name, quantity=qty)
            await update_character_sheet(thread, char, reason=f"Dodano przedmiot: {clean_item_name} x{qty}")
            embed = discord.Embed(
                title=f"🎒 Dodano do Ekwipunku: {clean_item_name}",
                description=f"Postać **{char.name}** otrzymała **{clean_item_name}** x{qty}.\nŁącznie w plecaku: **{item.quantity}** szt.",
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed)

        elif akcja == "remove":
            success, remaining = remove_inventory_item(char, clean_item_name, quantity=qty)
            if not success:
                await interaction.followup.send(f"❌ Postać **{char.name}** nie posiada przedmiotu `{clean_item_name}`.")
                return

            await update_character_sheet(thread, char, reason=f"Usunięto przedmiot: {clean_item_name} x{qty}")
            rem_str = f"Pozostało w plecaku: **{remaining.quantity}** szt." if remaining else "Przedmiot został całkowicie usunięty z plecaka."
            embed = discord.Embed(
                title=f"🎒 Usunięto z Ekwipunku: {clean_item_name}",
                description=f"Usunięto **{clean_item_name}** x{qty} z ekwipunku postaci **{char.name}**.\n{rem_str}",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="gold", description="Dodaje lub odejmuje złoto (GP) ze skarbca postaci")
    @app_commands.describe(
        wartosc="Zmiana ilości sztuk złota (np. +50, -10)",
        powod="Powód zmiany stanu majątku",
        postac="Gracz, którego sakiewkę modyfikujesz"
    )
    async def manage_gold(
        self,
        interaction: discord.Interaction,
        wartosc: int,
        powod: Optional[str] = None,
        postac: Optional[discord.User] = None
    ):
        """Modyfikuje ilość sztuk złota postaci z zapisem audytu w wątku."""
        await interaction.response.defer(ephemeral=False)
        resolved = await self._resolve_character(interaction, postac)
        if not resolved:
            return

        _, thread, _, char, user = resolved
        success, new_gold, msg = modify_gold(char, wartosc)
        if not success:
            await interaction.followup.send(msg)
            return

        reason_str = powod or f"Zmiana złota: {wartosc:+d} GP"
        await update_character_sheet(thread, char, reason=reason_str)

        embed = discord.Embed(
            title=f"💰 Sakiewka: {char.name}",
            description=msg,
            color=discord.Color.gold()
        )
        embed.add_field(name="Aktualny Stan Złota", value=f"**{new_gold}** GP", inline=True)
        if powod:
            embed.add_field(name="Powód", value=powod, inline=True)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="rest", description="Wykonuje krótki lub długi odpoczynek postaci")
    @app_commands.describe(
        typ="Typ odpoczynku: short (krótki) lub long (długi)",
        leczenie="Opcjonalne wyleczone HP przy krótkim odpoczynku (rzut kością wytrzymałości)",
        postac="Gracz, który odpoczywa"
    )
    async def rest(
        self,
        interaction: discord.Interaction,
        typ: Literal["short", "long"],
        leczenie: Optional[int] = 0,
        postac: Optional[discord.User] = None
    ):
        """Regeneruje postać poprzez odpoczynek."""
        await interaction.response.defer(ephemeral=False)
        resolved = await self._resolve_character(interaction, postac)
        if not resolved:
            return

        _, thread, _, char, user = resolved
        if typ == "long":
            msg = long_rest(char)
            reason = "Długi odpoczynek (Long Rest)"
        else:
            msg = short_rest(char, hit_dice_heal=leczenie or 0)
            reason = f"Krótki odpoczynek (Short Rest) +{leczenie or 0} HP"

        await update_character_sheet(thread, char, reason=reason)

        embed = discord.Embed(
            title=f"⛺ Odpoczynek: {char.name}",
            description=msg,
            color=discord.Color.teal()
        )
        embed.add_field(name="Punkty Życia", value=f"**{char.current_hp}/{char.max_hp} HP**", inline=True)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="create-character", description="Otwiera interaktywny formularz tworzenia nowej postaci D&D 5e")
    async def create_character(self, interaction: discord.Interaction):
        """Otwiera 5-polowy modal tworzenia postaci z automatycznym przeliczaniem reguł D&D 5e."""
        from discord_ui.views import CharacterCreateModal
        modal = CharacterCreateModal()
        await interaction.response.send_modal(modal)

    @app_commands.command(name="generate-character", description="Generuje kompletną postać D&D 5e za pomocą sztucznej inteligencji")
    @app_commands.describe(
        opis="Opis lub koncept postaci (np. Młody elficki mag szukający starożytnych tajemnic)"
    )
    async def generate_character_cmd(
        self,
        interaction: discord.Interaction,
        opis: str
    ):
        """Generuje zbalansowaną postać D&D 5e na 1 poziomie za pomocą Gemini AI i tworzy wątek na forum."""
        await interaction.response.defer(ephemeral=False)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ Komenda dostępna wyłącznie na serwerze.")
            return

        forum = find_forum_channel(guild, "karty-postaci")
        if not forum:
            await interaction.followup.send("❌ Nie znaleziono forum `#karty-postaci`. Użyj `/setup-campaign`.")
            return

        from ai.gemini_client import generate_character as ai_generate_character
        try:
            char_data = await ai_generate_character(opis)
        except Exception as e:
            await interaction.followup.send(f"❌ Wystąpił błąd podczas generowania postaci przez AI: {e}")
            return

        char_data["discord_user_id"] = str(interaction.user.id)
        
        try:
            char = CharacterModel(**char_data)
        except Exception:
            from discord_ui.views import compute_5e_character
            char = compute_5e_character(
                name=char_data.get("name", "Wygenerowany Bohater"),
                race_and_class=f"{char_data.get('race', 'Człowiek')} {char_data.get('character_class', 'Wojownik')}",
                stats_raw=str(char_data.get("stats", "")),
                backstory=char_data.get("backstory") or char_data.get("bio"),
                user_id=str(interaction.user.id)
            )

        thread, msg, created_char = await get_or_create_character_sheet(forum, str(interaction.user.id), character=char)
        if created_char.name != char.name or created_char.character_class != char.character_class:
            await update_character_sheet(thread, char, reason=f"Wygenerowano nową postać przez AI ({opis[:50]}...)")
            try:
                await thread.edit(name=f"🛡️ {char.name} ({interaction.user.id})")
            except Exception:
                pass

        embed = create_character_sheet_embed(char)
        view = CharacterSheetView(character=char)
        await interaction.followup.send(
            content=f"✨ **AI pomyślnie wygenerowało postać dla {interaction.user.display_name}!** Karta zapisana w wątku: #{thread.name}",
            embed=embed,
            view=view
        )

    @app_commands.command(name="character-edit", description="Edytuje parametry karty postaci z rejestracją audytu na forum")
    @app_commands.describe(
        imie="Nowe imię postaci",
        klasa="Nowa klasa postaci",
        rasa="Nowa rasa postaci",
        poziom="Nowy poziom postaci",
        max_hp="Nowa maksymalna liczba punktów życia",
        ac="Nowa klasa pancerza (AC)",
        speed="Nowa szybkość postaci (ft)",
        str_stat="Wartość Siły (STR)",
        dex_stat="Wartość Zręczności (DEX)",
        con_stat="Wartość Kondycji (CON)",
        int_stat="Wartość Inteligencji (INT)",
        wis_stat="Wartość Mądrości (WIS)",
        cha_stat="Wartość Charyzmy (CHA)",
        historia="Nowa historia / opis postaci (Backstory)",
        postac="Gracz, którego postać edytujesz (domyślnie Ty)"
    )
    async def character_edit_cmd(
        self,
        interaction: discord.Interaction,
        imie: Optional[str] = None,
        klasa: Optional[str] = None,
        rasa: Optional[str] = None,
        poziom: Optional[int] = None,
        max_hp: Optional[int] = None,
        ac: Optional[int] = None,
        speed: Optional[int] = None,
        str_stat: Optional[int] = None,
        dex_stat: Optional[int] = None,
        con_stat: Optional[int] = None,
        int_stat: Optional[int] = None,
        wis_stat: Optional[int] = None,
        cha_stat: Optional[int] = None,
        historia: Optional[str] = None,
        postac: Optional[discord.User] = None
    ):
        """Umożliwia selektywną edycję parametrów postaci bez naruszania ekwipunku, złota czy historii."""
        await interaction.response.defer(ephemeral=False)
        resolved = await self._resolve_character(interaction, postac)
        if not resolved:
            return

        _, thread, _, char, user = resolved
        changed = []

        if imie and imie.strip():
            char.name = imie.strip()
            changed.append(f"Imię -> {char.name}")
            try:
                await thread.edit(name=f"🛡️ {char.name} ({char.discord_user_id})")
            except Exception:
                pass

        if klasa and klasa.strip():
            char.character_class = klasa.strip()
            changed.append(f"Klasa -> {char.character_class}")

        if rasa and rasa.strip():
            char.race = rasa.strip()
            changed.append(f"Rasa -> {char.race}")

        if poziom is not None:
            char.level = max(1, poziom)
            char.proficiency_bonus = 2 + (char.level - 1) // 4
            changed.append(f"Poziom -> {char.level}")

        if max_hp is not None:
            char.max_hp = max(1, max_hp)
            char.current_hp = min(char.current_hp, char.max_hp)
            changed.append(f"Max HP -> {char.max_hp}")

        if ac is not None:
            char.armor_class = max(1, ac)
            changed.append(f"AC -> {char.armor_class}")

        if speed is not None:
            char.speed = max(0, speed)
            changed.append(f"Speed -> {char.speed} ft")

        if str_stat is not None:
            char.stats.strength = str_stat
            changed.append(f"STR -> {str_stat}")

        if dex_stat is not None:
            char.stats.dexterity = dex_stat
            changed.append(f"DEX -> {dex_stat}")

        if con_stat is not None:
            char.stats.constitution = con_stat
            changed.append(f"CON -> {con_stat}")

        if int_stat is not None:
            char.stats.intelligence = int_stat
            changed.append(f"INT -> {int_stat}")

        if wis_stat is not None:
            char.stats.wisdom = wis_stat
            changed.append(f"WIS -> {wis_stat}")

        if cha_stat is not None:
            char.stats.charisma = cha_stat
            changed.append(f"CHA -> {cha_stat}")

        if historia and historia.strip():
            char.backstory = historia.strip()
            char.bio = char.backstory
            changed.append("Historia/Bio")

        if not changed:
            await interaction.followup.send("⚠️ Nie podano żadnych pól do modyfikacji.")
            return

        reason_str = f"Edycja postaci: {', '.join(changed)}"
        await update_character_sheet(thread, char, reason=reason_str)

        embed = create_character_sheet_embed(char)
        view = CharacterSheetView(character=char)
        await interaction.followup.send(
            content=f"📝 **Zaktualizowano kartę postaci gracza {user.display_name}!** Zmiany: *{', '.join(changed)}*",
            embed=embed,
            view=view
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(CharacterCog(bot))
