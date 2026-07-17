class DiscordWebAPIError(Exception):
    """Base class for all discord-webapi errors."""


class TransportError(DiscordWebAPIError):
    """Raised for transport-level failures (publish/subscribe/request)."""


class TransportTimeoutError(TransportError):
    """Raised when a request() call receives no reply within its timeout."""


class AuthError(DiscordWebAPIError):
    """Base class for authentication failures."""


class InvalidStateError(AuthError):
    """Raised when the OAuth2 state cookie does not match the callback query param."""


class SessionExpiredError(AuthError):
    """Raised when a session id no longer resolves to a valid session."""


class DiscordAPIError(AuthError):
    """Raised when Discord's own OAuth2 `/oauth2/token` endpoint rejects a
    request -- a revoked/reused authorization code (the callback route
    hit twice, e.g. a double-click or a back-button reload), or a
    revoked/expired refresh token (the user removed the app's Discord
    authorization). Discord returns a normal HTTP error status for both,
    which `DiscordAuth._exchange()` turns into this instead of letting an
    `httpx.HTTPStatusError` propagate raw."""


class AuthorizationError(DiscordWebAPIError):
    """Raised when a user lacks the required guild permission or role."""
