from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord
from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from discord_webapi.auth.dependencies import get_current_user
from discord_webapi.auth.models import DiscordUser
from discord_webapi.authz.app_roles import AppRoleCache
from discord_webapi.authz.cache import ChannelPermissionCache, GuildMemberCache
from discord_webapi.authz.permissions import has_permission


class GuildContext(BaseModel):
    """Resolved for an authorized request: the logged-in user, scoped to a
    specific guild, along with their roles/permissions in that guild."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    guild_id: int
    user: DiscordUser
    role_ids: list[int]
    permissions: discord.Permissions


class ChannelContext(BaseModel):
    """Resolved for an authorized request: the logged-in user, scoped to a
    specific channel, with their *effective* permissions there -- guild
    role permissions folded together with that channel's own overwrites
    (see `commands.bridge.get_channel_permissions`)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    guild_id: int
    channel_id: int
    user: DiscordUser
    permissions: discord.Permissions


def _get_member_cache(request: Request) -> GuildMemberCache:
    cache: GuildMemberCache = request.app.state.discord_webapi_member_cache
    return cache


def _get_channel_permission_cache(request: Request) -> ChannelPermissionCache:
    cache: ChannelPermissionCache = request.app.state.discord_webapi_channel_permission_cache
    return cache


def _get_app_role_cache(request: Request) -> AppRoleCache:
    cache: AppRoleCache = request.app.state.discord_webapi_app_role_cache
    return cache


async def _resolve_guild_context(
    guild_id: int, request: Request, user: DiscordUser
) -> GuildContext:
    cache = _get_member_cache(request)
    info = await cache.get(guild_id, user.id)
    if info is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this guild")
    return GuildContext(
        guild_id=guild_id, user=user, role_ids=info.role_ids, permissions=info.permissions
    )


def require_guild_permission(
    *permission_names: str,
) -> Callable[..., Awaitable[GuildContext]]:
    """FastAPI dependency factory: `Depends(require_guild_permission("manage_guild"))`.

    `guild_id` is resolved from the endpoint's own path parameter (FastAPI
    matches dependency parameter names against path params automatically).
    """

    async def _dependency(
        guild_id: int,
        request: Request,
        user: DiscordUser = Depends(get_current_user),
    ) -> GuildContext:
        ctx = await _resolve_guild_context(guild_id, request, user)
        if not all(has_permission(ctx.permissions, name) for name in permission_names):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing required permission")
        return ctx

    return _dependency


def require_role(*, role_id: int) -> Callable[..., Awaitable[GuildContext]]:
    """FastAPI dependency factory: `Depends(require_role(role_id=123456789))`.

    An administrator always passes, matching Discord's own permission
    semantics (see `authz.permissions.has_permission`).
    """

    async def _dependency(
        guild_id: int,
        request: Request,
        user: DiscordUser = Depends(get_current_user),
    ) -> GuildContext:
        ctx = await _resolve_guild_context(guild_id, request, user)
        if role_id not in ctx.role_ids and not ctx.permissions.administrator:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing required role")
        return ctx

    return _dependency


def require_app_role(name: str) -> Callable[..., Awaitable[GuildContext]]:
    """FastAPI dependency factory: `Depends(require_app_role("moderator"))`.

    Checks a bot-owner-defined `AppRole` (see `authz.models.AppRole`) —
    independent of Discord's own role/permission system, managed via the
    `/api/guilds/{guild_id}/app-roles` dashboard endpoints. An administrator
    always passes, matching the other `require_*` dependencies.
    """

    async def _dependency(
        guild_id: int,
        request: Request,
        user: DiscordUser = Depends(get_current_user),
    ) -> GuildContext:
        ctx = await _resolve_guild_context(guild_id, request, user)
        if ctx.permissions.administrator:
            return ctx
        cache = _get_app_role_cache(request)
        allowed = await cache.user_has_role(
            guild_id, name, user_id=user.id, discord_role_ids=ctx.role_ids
        )
        if not allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing required app role {name!r}")
        return ctx

    return _dependency


def require_channel_permission(
    *permission_names: str,
) -> Callable[..., Awaitable[ChannelContext]]:
    """FastAPI dependency factory: `Depends(require_channel_permission("manage_messages"))`.

    `guild_id` and `channel_id` are both resolved from the endpoint's own
    path parameters. Unlike `require_guild_permission`, this checks
    *effective* permissions in that specific channel -- a member with
    `manage_messages` at the guild level but denied it via a channel-specific
    overwrite fails this check even though `require_guild_permission` would
    have passed them.
    """

    async def _dependency(
        guild_id: int,
        channel_id: int,
        request: Request,
        user: DiscordUser = Depends(get_current_user),
    ) -> ChannelContext:
        cache = _get_channel_permission_cache(request)
        permissions = await cache.get(guild_id, channel_id, user.id)
        if permissions is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Not a member of this guild, or channel not found"
            )
        if not all(has_permission(permissions, name) for name in permission_names):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing required channel permission")
        return ChannelContext(
            guild_id=guild_id, channel_id=channel_id, user=user, permissions=permissions
        )

    return _dependency
