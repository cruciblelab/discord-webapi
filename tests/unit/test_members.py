from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from discord_webapi.members import install_member_listing
from discord_webapi.transport import InProcessTransport


class _FakeRole:
    def __init__(self, id_: int, name: str, default: bool = False) -> None:
        self.id = id_
        self.name = name
        self._default = default

    def is_default(self) -> bool:
        return self._default


class _FakeMember:
    def __init__(
        self,
        id_: int,
        username: str,
        display_name: str,
        roles: list[_FakeRole],
        joined_at: datetime | None = None,
        avatar_url: str | None = None,
    ) -> None:
        self.id = id_
        self._username = username
        self.display_name = display_name
        self.roles = roles
        self.joined_at = joined_at
        self.display_avatar = SimpleNamespace(url=avatar_url) if avatar_url else None

    def __str__(self) -> str:
        return self._username


def _bot_with_guild(guild_id: int, members: list[_FakeMember]) -> MagicMock:
    bot = MagicMock()
    guild = SimpleNamespace(members=members)
    bot.get_guild.side_effect = lambda gid: guild if gid == guild_id else None
    return bot


async def test_list_members_returns_roles_and_excludes_everyone() -> None:
    everyone = _FakeRole(1, "@everyone", default=True)
    admin_role = _FakeRole(2, "Admin")
    member = _FakeMember(
        id_=42,
        username="tester#0",
        display_name="Tester",
        roles=[everyone, admin_role],
        joined_at=datetime(2024, 1, 1, tzinfo=UTC),
        avatar_url="https://cdn.example/42.png",
    )
    bot = _bot_with_guild(999, [member])
    transport = InProcessTransport()
    await transport.start()
    install_member_listing(bot, transport)

    response = await transport.request("list_members", {"guild_id": 999})

    assert response["found"] is True
    assert len(response["members"]) == 1
    m = response["members"][0]
    assert m["id"] == 42
    assert m["display_name"] == "Tester"
    assert m["role_names"] == ["Admin"]
    assert m["role_ids"] == [2]
    assert m["avatar_url"] == "https://cdn.example/42.png"
    assert m["joined_at"] == "2024-01-01T00:00:00+00:00"


async def test_list_members_unknown_guild_returns_not_found() -> None:
    bot = _bot_with_guild(999, [])
    transport = InProcessTransport()
    await transport.start()
    install_member_listing(bot, transport)

    response = await transport.request("list_members", {"guild_id": 111})

    assert response == {"found": False, "members": []}


async def test_list_members_returns_all_members() -> None:
    members = [
        _FakeMember(id_=1, username="a#0", display_name="A", roles=[]),
        _FakeMember(id_=2, username="b#0", display_name="B", roles=[]),
    ]
    bot = _bot_with_guild(5, members)
    transport = InProcessTransport()
    await transport.start()
    install_member_listing(bot, transport)

    response = await transport.request("list_members", {"guild_id": 5})

    assert {m["id"] for m in response["members"]} == {1, 2}
