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


async def setup(bot: commands.Bot):
    await bot.add_cog(CharacterCog(bot))
