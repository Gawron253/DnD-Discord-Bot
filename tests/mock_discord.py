"""High-fidelity Mock Discord objects for 100% offline E2E testing.
Emulates discord.py domain model and async contracts without network calls.
"""
from __future__ import annotations
import asyncio
import datetime
from typing import List, Optional, Dict, Any, Union, AsyncIterator
import discord


class MockField:
    """Mock for discord.EmbedField."""
    def __init__(self, name: str, value: str, inline: bool = False):
        self.name = str(name)
        self.value = str(value)
        self.inline = inline

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "value": self.value, "inline": self.inline}


class MockEmbed:
    """Mock for discord.Embed."""
    def __init__(
        self,
        title: Optional[str] = None,
        description: Optional[str] = None,
        color: Optional[Union[int, discord.Color]] = None,
        url: Optional[str] = None,
        timestamp: Optional[datetime.datetime] = None
    ):
        self.title = title
        self.description = description
        self.color = color.value if isinstance(color, discord.Color) else color
        self.url = url
        self.timestamp = timestamp
        self.fields: List[MockField] = []
        self._thumbnail: Optional[Dict[str, Any]] = None
        self._footer: Optional[Dict[str, Any]] = None
        self._author: Optional[Dict[str, Any]] = None

    def add_field(self, name: str, value: str, inline: bool = False) -> MockEmbed:
        self.fields.append(MockField(name=name, value=value, inline=inline))
        return self

    def set_thumbnail(self, url: str) -> MockEmbed:
        self._thumbnail = {"url": url}
        return self

    def set_footer(self, text: str, icon_url: Optional[str] = None) -> MockEmbed:
        self._footer = {"text": text, "icon_url": icon_url}
        return self

    def set_author(self, name: str, url: Optional[str] = None, icon_url: Optional[str] = None) -> MockEmbed:
        self._author = {"name": name, "url": url, "icon_url": icon_url}
        return self

    @property
    def thumbnail(self) -> Optional[Dict[str, Any]]:
        return self._thumbnail

    @property
    def footer(self) -> Optional[Dict[str, Any]]:
        return self._footer

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        if self.title is not None:
            d["title"] = self.title
        if self.description is not None:
            d["description"] = self.description
        if self.color is not None:
            d["color"] = self.color
        if self.fields:
            d["fields"] = [f.to_dict() for f in self.fields]
        if self._thumbnail:
            d["thumbnail"] = self._thumbnail
        if self._footer:
            d["footer"] = self._footer
        return d


class MockUser:
    """Mock for discord.User and discord.Member."""
    def __init__(
        self,
        id: int,
        name: str,
        display_name: Optional[str] = None,
        bot: bool = False,
        discriminator: str = "0001"
    ):
        self.id = id
        self.name = name
        self.display_name = display_name or name
        self.bot = bot
        self.discriminator = discriminator
        self.roles: List[Any] = []
        self.avatar_url: Optional[str] = f"https://cdn.discordapp.com/avatars/{self.id}/avatar.png"

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    def mentioned_in(self, message: MockMessage) -> bool:
        """Checks if user was mentioned in the message."""
        if self in getattr(message, "mentions", []):
            return True
        if f"<@{self.id}>" in (message.content or "") or f"<@!{self.id}>" in (message.content or ""):
            return True
        if "@Mistrz Gry" in (message.content or ""):
            return True
        return False

    def __repr__(self) -> str:
        return f"<MockUser id={self.id} name='{self.name}' bot={self.bot}>"


class MockMessage:
    """Mock for discord.Message."""
    _id_counter = 1000

    def __init__(
        self,
        content: str = "",
        author: Optional[MockUser] = None,
        channel: Optional[Union[MockTextChannel, MockThread]] = None,
        guild: Optional[MockGuild] = None,
        embed: Optional[Union[MockEmbed, discord.Embed]] = None,
        embeds: Optional[List[Union[MockEmbed, discord.Embed]]] = None,
        pinned: bool = False,
        created_at: Optional[datetime.datetime] = None,
        mentions: Optional[List[MockUser]] = None
    ):
        MockMessage._id_counter += 1
        self.id = MockMessage._id_counter
        self.content = content or ""
        self.author = author or MockUser(id=1, name="System")
        self.channel = channel
        self.guild = guild or (channel.guild if channel else None)
        
        # Normalize embeds
        self.embeds: List[Union[MockEmbed, discord.Embed]] = []
        if embeds:
            self.embeds.extend(embeds)
        elif embed:
            self.embeds.append(embed)
            
        self.pinned = pinned
        self.created_at = created_at or datetime.datetime.now(datetime.timezone.utc)
        self.mentions: List[MockUser] = mentions or []
        self.reactions: List[Any] = []

    async def pin(self) -> None:
        self.pinned = True
        if self.channel and hasattr(self.channel, "pinned_messages"):
            if self not in self.channel.pinned_messages:
                self.channel.pinned_messages.append(self)

    async def unpin(self) -> None:
        self.pinned = False
        if self.channel and hasattr(self.channel, "pinned_messages"):
            if self in self.channel.pinned_messages:
                self.channel.pinned_messages.remove(self)

    async def edit(
        self,
        content: Optional[str] = None,
        embed: Optional[Union[MockEmbed, discord.Embed]] = None,
        embeds: Optional[List[Union[MockEmbed, discord.Embed]]] = None
    ) -> MockMessage:
        if content is not None:
            self.content = content
        if embeds is not None:
            self.embeds = list(embeds)
        elif embed is not None:
            self.embeds = [embed]
        return self

    async def delete(self) -> None:
        if self.channel and hasattr(self.channel, "messages"):
            if self in self.channel.messages:
                self.channel.messages.remove(self)
        if self.channel and hasattr(self.channel, "pinned_messages"):
            if self in self.channel.pinned_messages:
                self.channel.pinned_messages.remove(self)

    async def add_reaction(self, emoji: str) -> None:
        self.reactions.append(emoji)

    def __repr__(self) -> str:
        return f"<MockMessage id={self.id} author='{self.author.name}' content='{self.content[:30]}...'>"


class AsyncMessageIterator:
    """Async iterator for channel.history()."""
    def __init__(
        self,
        messages: List[MockMessage],
        limit: Optional[int] = 50,
        after: Optional[MockMessage] = None,
        before: Optional[MockMessage] = None,
        oldest_first: bool = False
    ):
        self.messages = list(messages)
        self.limit = limit
        self.after = after
        self.before = before
        self.oldest_first = oldest_first
        self._index = 0
        self._filtered: List[MockMessage] = self._prepare_list()

    def _prepare_list(self) -> List[MockMessage]:
        msgs = list(self.messages)
        # Default stored order is oldest to newest (chronological)
        if self.after:
            try:
                idx = msgs.index(self.after)
                msgs = msgs[idx + 1:]
            except ValueError:
                # Find by created_at or id
                msgs = [m for m in msgs if m.id > self.after.id]
        if self.before:
            try:
                idx = msgs.index(self.before)
                msgs = msgs[:idx]
            except ValueError:
                msgs = [m for m in msgs if m.id < self.before.id]

        if not self.oldest_first:
            msgs = list(reversed(msgs))

        if self.limit is not None:
            msgs = msgs[:self.limit]
        return msgs

    def __aiter__(self) -> AsyncMessageIterator:
        self._index = 0
        return self

    async def __anext__(self) -> MockMessage:
        if self._index >= len(self._filtered):
            raise StopAsyncIteration
        msg = self._filtered[self._index]
        self._index += 1
        return msg


class AsyncThreadIterator:
    """Async iterator for forum.archived_threads()."""
    def __init__(self, threads: List[MockThread], limit: Optional[int] = 50):
        self.threads = [t for t in threads if t.archived]
        if limit is not None:
            self.threads = self.threads[:limit]
        self._index = 0

    def __aiter__(self) -> AsyncThreadIterator:
        self._index = 0
        return self

    async def __anext__(self) -> MockThread:
        if self._index >= len(self.threads):
            raise StopAsyncIteration
        thread = self.threads[self._index]
        self._index += 1
        return thread


class MockTyping:
    """Mock async context manager for channel.typing()."""
    def __init__(self, channel: Any):
        self.channel = channel
        self.is_typing = False

    async def __aenter__(self) -> MockTyping:
        self.is_typing = True
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.is_typing = False


class MockThread:
    """Mock for discord.Thread."""
    _id_counter = 5000

    def __init__(
        self,
        name: str,
        guild: Optional[MockGuild] = None,
        parent: Optional[Union[MockForumChannel, MockTextChannel]] = None,
        archived: bool = False,
        locked: bool = False,
        id: Optional[int] = None
    ):
        MockThread._id_counter += 1
        self.id = id or MockThread._id_counter
        self.name = name
        self.guild = guild or (parent.guild if parent else None)
        self.parent = parent
        self.archived = archived
        self.locked = locked
        self.messages: List[MockMessage] = []
        self.pinned_messages: List[MockMessage] = []
        self.unarchived_count = 0

    async def send(
        self,
        content: Optional[str] = None,
        embed: Optional[Union[MockEmbed, discord.Embed]] = None,
        embeds: Optional[List[Union[MockEmbed, discord.Embed]]] = None,
        view: Optional[Any] = None
    ) -> MockMessage:
        msg = MockMessage(
            content=content or "",
            author=MockUser(id=999, name="Bot", bot=True),
            channel=self,
            guild=self.guild,
            embed=embed,
            embeds=embeds
        )
        self.messages.append(msg)
        return msg

    def typing(self) -> MockTyping:
        return MockTyping(self)

    async def pins(self) -> List[MockMessage]:
        return list(self.pinned_messages)

    def history(
        self,
        limit: Optional[int] = 50,
        after: Optional[MockMessage] = None,
        before: Optional[MockMessage] = None,
        oldest_first: bool = False
    ) -> AsyncMessageIterator:
        return AsyncMessageIterator(
            messages=self.messages,
            limit=limit,
            after=after,
            before=before,
            oldest_first=oldest_first
        )

    async def edit(
        self,
        name: Optional[str] = None,
        archived: Optional[bool] = None,
        locked: Optional[bool] = None
    ) -> MockThread:
        if name is not None:
            self.name = name
        if archived is not None:
            if self.archived and not archived:
                self.unarchived_count += 1
            self.archived = archived
        if locked is not None:
            self.locked = locked
        return self

    def __repr__(self) -> str:
        return f"<MockThread id={self.id} name='{self.name}' archived={self.archived}>"


class MockTextChannel:
    """Mock for discord.TextChannel."""
    _id_counter = 2000

    def __init__(
        self,
        name: str,
        guild: Optional[MockGuild] = None,
        category: Optional[MockCategoryChannel] = None,
        id: Optional[int] = None
    ):
        MockTextChannel._id_counter += 1
        self.id = id or MockTextChannel._id_counter
        self.name = name
        self.guild = guild
        self.category = category
        self.messages: List[MockMessage] = []
        self.pinned_messages: List[MockMessage] = []
        self.threads: List[MockThread] = []

    async def send(
        self,
        content: Optional[str] = None,
        embed: Optional[Union[MockEmbed, discord.Embed]] = None,
        embeds: Optional[List[Union[MockEmbed, discord.Embed]]] = None,
        view: Optional[Any] = None
    ) -> MockMessage:
        msg = MockMessage(
            content=content or "",
            author=MockUser(id=999, name="Bot", bot=True),
            channel=self,
            guild=self.guild,
            embed=embed,
            embeds=embeds
        )
        self.messages.append(msg)
        return msg

    def typing(self) -> MockTyping:
        return MockTyping(self)

    async def pins(self) -> List[MockMessage]:
        return list(self.pinned_messages)

    def history(
        self,
        limit: Optional[int] = 50,
        after: Optional[MockMessage] = None,
        before: Optional[MockMessage] = None,
        oldest_first: bool = False
    ) -> AsyncMessageIterator:
        return AsyncMessageIterator(
            messages=self.messages,
            limit=limit,
            after=after,
            before=before,
            oldest_first=oldest_first
        )

    async def create_thread(
        self,
        name: str,
        message: Optional[MockMessage] = None,
        auto_archive_duration: int = 1440
    ) -> MockThread:
        thread = MockThread(name=name, guild=self.guild, parent=self)
        if message:
            thread.messages.append(message)
        self.threads.append(thread)
        return thread

    async def delete(self) -> None:
        if self.guild and self in self.guild.text_channels:
            self.guild.text_channels.remove(self)
        if self.category and self in self.category.text_channels:
            self.category.text_channels.remove(self)

    def __repr__(self) -> str:
        return f"<MockTextChannel id={self.id} name='{self.name}'>"


class ThreadWithMessage:
    """Emulates discord.ThreadWithMessage returned by ForumChannel.create_thread."""
    def __init__(self, thread: MockThread, message: MockMessage):
        self.thread = thread
        self.message = message

    def __iter__(self):
        return iter((self.thread, self.message))


class MockForumChannel:
    """Mock for discord.ForumChannel."""
    _id_counter = 3000

    def __init__(
        self,
        name: str,
        guild: Optional[MockGuild] = None,
        category: Optional[MockCategoryChannel] = None,
        id: Optional[int] = None
    ):
        MockForumChannel._id_counter += 1
        self.id = id or MockForumChannel._id_counter
        self.name = name
        self.guild = guild
        self.category = category
        self._threads: List[MockThread] = []

    @property
    def threads(self) -> List[MockThread]:
        """Returns all unarchived threads or all threads depending on query."""
        return [t for t in self._threads if not t.archived]

    @property
    def all_threads(self) -> List[MockThread]:
        return list(self._threads)

    def archived_threads(self, limit: Optional[int] = 50) -> AsyncThreadIterator:
        return AsyncThreadIterator(threads=self._threads, limit=limit)

    async def create_thread(
        self,
        name: str,
        content: Optional[str] = None,
        embed: Optional[Union[MockEmbed, discord.Embed]] = None,
        embeds: Optional[List[Union[MockEmbed, discord.Embed]]] = None,
        auto_archive_duration: int = 1440
    ) -> ThreadWithMessage:
        thread = MockThread(name=name, guild=self.guild, parent=self)
        msg = MockMessage(
            content=content or "",
            author=MockUser(id=999, name="Bot", bot=True),
            channel=thread,
            guild=self.guild,
            embed=embed,
            embeds=embeds
        )
        thread.messages.append(msg)
        thread.pinned_messages.append(msg)
        self._threads.append(thread)
        return ThreadWithMessage(thread, msg)

    async def delete(self) -> None:
        if self.guild and self in self.guild.forums:
            self.guild.forums.remove(self)
        if self.category and self in self.category.forums:
            self.category.forums.remove(self)

    def __repr__(self) -> str:
        return f"<MockForumChannel id={self.id} name='{self.name}'>"


class MockCategoryChannel:
    """Mock for discord.CategoryChannel."""
    _id_counter = 4000

    def __init__(self, name: str, guild: Optional[MockGuild] = None, id: Optional[int] = None):
        MockCategoryChannel._id_counter += 1
        self.id = id or MockCategoryChannel._id_counter
        self.name = name
        self.guild = guild
        self.text_channels: List[MockTextChannel] = []
        self.forums: List[MockForumChannel] = []

    @property
    def channels(self) -> List[Union[MockTextChannel, MockForumChannel]]:
        return list(self.text_channels) + list(self.forums)

    def __repr__(self) -> str:
        return f"<MockCategoryChannel id={self.id} name='{self.name}'>"


class MockGuild:
    """Mock for discord.Guild."""
    _id_counter = 100

    def __init__(self, name: str = "Test RPG Guild", id: Optional[int] = None):
        MockGuild._id_counter += 1
        self.id = id or MockGuild._id_counter
        self.name = name
        self.categories: List[MockCategoryChannel] = []
        self.text_channels: List[MockTextChannel] = []
        self.forums: List[MockForumChannel] = []
        self.members: List[MockUser] = []
        self.roles: List[Any] = []

    @property
    def channels(self) -> List[Any]:
        return list(self.categories) + list(self.text_channels) + list(self.forums)

    def get_channel(self, channel_id: int) -> Optional[Any]:
        for c in self.channels:
            if c.id == channel_id:
                return c
        for f in self.forums:
            for t in f._threads:
                if t.id == channel_id:
                    return t
        for ch in self.text_channels:
            for t in ch.threads:
                if t.id == channel_id:
                    return t
        return None

    def get_member(self, user_id: int) -> Optional[MockUser]:
        for m in self.members:
            if m.id == user_id:
                return m
        return None

    async def create_category(self, name: str) -> MockCategoryChannel:
        cat = MockCategoryChannel(name=name, guild=self)
        self.categories.append(cat)
        return cat

    async def create_text_channel(
        self,
        name: str,
        category: Optional[MockCategoryChannel] = None
    ) -> MockTextChannel:
        ch = MockTextChannel(name=name, guild=self, category=category)
        self.text_channels.append(ch)
        if category:
            category.text_channels.append(ch)
        return ch

    async def create_forum_channel(
        self,
        name: str,
        category: Optional[MockCategoryChannel] = None
    ) -> MockForumChannel:
        forum = MockForumChannel(name=name, guild=self, category=category)
        self.forums.append(forum)
        if category:
            category.forums.append(forum)
        return forum

    # Alias for discord.py create_forum
    async def create_forum(
        self,
        name: str,
        category: Optional[MockCategoryChannel] = None
    ) -> MockForumChannel:
        return await self.create_forum_channel(name=name, category=category)

    def __repr__(self) -> str:
        return f"<MockGuild id={self.id} name='{self.name}'>"


class MockInteractionResponse:
    """Mock for discord.InteractionResponse."""
    def __init__(self, interaction: MockInteraction):
        self.interaction = interaction
        self._responded = False
        self._deferred = False
        self._ephemeral = False
        self.sent_messages: List[MockMessage] = []
        self.sent_modal: Optional[Any] = None

    def is_done(self) -> bool:
        return self._responded or self._deferred

    async def defer(self, ephemeral: bool = False, thinking: bool = True) -> None:
        self._deferred = True
        self._ephemeral = ephemeral

    async def send_modal(self, modal: Any) -> None:
        self._responded = True
        self.sent_modal = modal

    async def send_message(
        self,
        content: Optional[str] = None,
        embed: Optional[Union[MockEmbed, discord.Embed]] = None,
        embeds: Optional[List[Union[MockEmbed, discord.Embed]]] = None,
        view: Optional[Any] = None,
        ephemeral: bool = False
    ) -> MockMessage:
        self._responded = True
        self._ephemeral = ephemeral
        channel = self.interaction.channel
        msg = MockMessage(
            content=content or "",
            author=MockUser(id=888, name="DiceEngine", display_name=self.interaction.user.display_name, bot=True),
            channel=channel,
            guild=self.interaction.guild,
            embed=embed,
            embeds=embeds
        )
        self.sent_messages.append(msg)
        if channel and hasattr(channel, "messages"):
            channel.messages.append(msg)
        return msg

    async def edit_message(
        self,
        content: Optional[str] = None,
        embed: Optional[Union[MockEmbed, discord.Embed]] = None,
        embeds: Optional[List[Union[MockEmbed, discord.Embed]]] = None,
        view: Optional[Any] = None
    ) -> None:
        if self.sent_messages:
            await self.sent_messages[-1].edit(content=content, embed=embed, embeds=embeds)


class MockInteractionFollowup:
    """Mock for discord.Webhook / InteractionFollowup."""
    def __init__(self, interaction: MockInteraction):
        self.interaction = interaction
        self.sent_messages: List[MockMessage] = []

    async def send(
        self,
        content: Optional[str] = None,
        embed: Optional[Union[MockEmbed, discord.Embed]] = None,
        embeds: Optional[List[Union[MockEmbed, discord.Embed]]] = None,
        view: Optional[Any] = None,
        ephemeral: bool = False
    ) -> MockMessage:
        channel = self.interaction.channel
        msg = MockMessage(
            content=content or "",
            author=MockUser(id=999, name="Bot", bot=True),
            channel=channel,
            guild=self.interaction.guild,
            embed=embed,
            embeds=embeds
        )
        self.sent_messages.append(msg)
        if channel and hasattr(channel, "messages"):
            channel.messages.append(msg)
        return msg


class MockInteraction:
    """Mock for discord.Interaction."""
    _id_counter = 8000

    def __init__(
        self,
        user: Optional[MockUser] = None,
        guild: Optional[MockGuild] = ... ,  # sentinel check
        channel: Optional[Union[MockTextChannel, MockThread]] = None,
        data: Optional[Dict[str, Any]] = None
    ):
        MockInteraction._id_counter += 1
        self.id = MockInteraction._id_counter
        self.user = user or MockUser(id=42, name="Player1", display_name="Thorin")
        if guild is ...:
            self.guild = channel.guild if channel else MockGuild()
        else:
            self.guild = guild
        self.channel = channel
        self.data = data or {}
        self.response = MockInteractionResponse(self)
        self.followup = MockInteractionFollowup(self)

    def __repr__(self) -> str:
        return f"<MockInteraction id={self.id} user='{self.user.name}'>"
