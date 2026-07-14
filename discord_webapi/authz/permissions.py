import discord


def has_permission(permissions: discord.Permissions, name: str) -> bool:
    """Discord-native permission check, reusing `discord.Permissions`'
    bitfield math rather than reinventing it. `administrator` always
    short-circuits, matching Discord's own semantics."""
    if permissions.administrator:
        return True
    return bool(getattr(permissions, name, False))
