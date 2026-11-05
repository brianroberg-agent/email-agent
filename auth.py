"""Bearer-token authentication for the email agent server."""

import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, Mapping, Optional, Sequence


logger = logging.getLogger("email_agent.auth")

KEYS_ENV = "EMAIL_AGENT_API_KEYS"
MODE_ENV = "EMAIL_AGENT_AUTH"

MIN_TOKEN_LENGTH = 32
# A name must be shorter than the shortest token, so a token pasted in the
# name position is rejected rather than accepted as a name and logged.
MAX_NAME_LENGTH = MIN_TOKEN_LENGTH - 1

_NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,%d}" % MAX_NAME_LENGTH)
_TOKEN_PATTERN = re.compile(r"[\x21-\x7e]+")


class AuthConfigError(ValueError):
    """The authentication settings are missing or malformed."""


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


@dataclass(frozen=True)
class ApiKey:
    """One caller's name and the SHA-256 digest of its token."""

    name: str
    digest: bytes = field(repr=False)

    def matches(self, presented: str) -> bool:
        return hmac.compare_digest(self.digest, _digest(presented))


class AuthMode(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    OFF = "off"


@dataclass(frozen=True)
class AuthSettings:
    mode: AuthMode
    keys: tuple[ApiKey, ...]


def load_auth_settings(environ: Mapping[str, str]) -> AuthSettings:
    """Read the mode and the keys from `environ`.

    Raises AuthConfigError for an unknown mode, a malformed key list (in any
    mode), or `required` mode with no keys.
    """
    raw_mode = (environ.get(MODE_ENV) or "").strip().lower()
    allowed = ", ".join(mode.value for mode in AuthMode)
    try:
        mode = AuthMode(raw_mode) if raw_mode else AuthMode.REQUIRED
    except ValueError:
        raise AuthConfigError(f"{MODE_ENV} must be one of: {allowed}") from None
    keys = parse_api_keys(environ.get(KEYS_ENV))
    if mode is AuthMode.REQUIRED and not keys:
        raise AuthConfigError(
            f"{MODE_ENV} is 'required' (the default) and {KEYS_ENV} holds no "
            f"tokens. Set {KEYS_ENV} to comma-separated name:token pairs, or "
            f"set {MODE_ENV} to 'optional' or 'off'."
        )
    return AuthSettings(mode=mode, keys=keys)


def startup_messages(settings: AuthSettings) -> list[tuple[int, str]]:
    """The (level, message) lines to log when the service starts. They name
    the mode and the callers; they hold no token."""
    callers = ", ".join(key.name for key in settings.keys)
    if settings.mode is AuthMode.OFF:
        return [
            (
                logging.WARNING,
                f"auth: {MODE_ENV}=off: every request is served without "
                "authentication",
            )
        ]
    if settings.mode is AuthMode.OPTIONAL:
        configured = (
            f"tokens are configured for: {callers}"
            if callers
            else "no tokens are configured, so every request that carries a "
            "token is refused"
        )
        return [
            (
                logging.WARNING,
                f"auth: {MODE_ENV}=optional: requests without a token are served "
                f"and logged; {configured}",
            )
        ]
    return [
        (
            logging.INFO,
            f"auth: {MODE_ENV}=required: every route except the health check "
            f"needs a bearer token; tokens are configured for: {callers}",
        )
    ]


class StderrLogging:
    """Writes the auth logger's lines to stderr while the service runs.

    install() adds a stderr handler (and INFO level) to the auth logger
    unless the logger already has a handler of its own, in which case the
    operator's logging setup is left as it is. remove() undoes install().
    """

    FORMAT = "email-agent: %(levelname)s %(message)s"

    def __init__(self) -> None:
        self._handler: Optional[logging.Handler] = None
        self._previous_level = logging.NOTSET

    def install(self) -> None:
        if logger.handlers:
            return
        self._handler = logging.StreamHandler()
        self._handler.setFormatter(logging.Formatter(self.FORMAT))
        self._previous_level = logger.level
        logger.addHandler(self._handler)
        if logger.level == logging.NOTSET:
            logger.setLevel(logging.INFO)

    def remove(self) -> None:
        if self._handler is None:
            return
        logger.removeHandler(self._handler)
        logger.setLevel(self._previous_level)
        self._handler = None


@dataclass(frozen=True)
class Decision:
    """What to do with one request.

    credential is "valid", "invalid", "none" (no Authorization header) or
    "unchecked" (mode off). caller is the matching key's name, if any.
    """

    allowed: bool
    caller: Optional[str]
    credential: str


def decide(settings: AuthSettings, authorization: Sequence[str]) -> Decision:
    """Decide a request from its Authorization header values.

    Only the absence of the header counts as "no token". A header that is
    present but is not exactly one `Bearer <configured token>` is invalid.
    """
    if settings.mode is AuthMode.OFF:
        return Decision(allowed=True, caller=None, credential="unchecked")
    if not authorization:
        return Decision(
            allowed=settings.mode is AuthMode.OPTIONAL, caller=None, credential="none"
        )
    caller = None
    if len(authorization) == 1:
        parts = authorization[0].split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            caller = match_token(parts[1], settings.keys)
    if caller is None:
        return Decision(allowed=False, caller=None, credential="invalid")
    return Decision(allowed=True, caller=caller, credential="valid")


def match_token(presented: str, keys: Sequence[ApiKey]) -> Optional[str]:
    """Return the name of the key `presented` matches, or None.

    Compares SHA-256 digests with hmac.compare_digest and visits every key,
    so the time taken does not depend on which key matched or on how much of
    a token was right.
    """
    presented_digest = _digest(presented)
    caller = None
    for key in keys:
        if hmac.compare_digest(key.digest, presented_digest):
            caller = key.name
    return caller


def parse_api_keys(raw: Optional[str]) -> tuple[ApiKey, ...]:
    """Parse the EMAIL_AGENT_API_KEYS value: comma-separated name:token pairs.

    Raises AuthConfigError for a malformed value. The error names the entry
    by its position and repeats nothing from the value, so a token pasted in
    the wrong place is not printed.
    """
    keys: list[ApiKey] = []
    entries = [entry.strip() for entry in (raw or "").split(",")]
    for position, entry in enumerate((e for e in entries if e), start=1):
        name, colon, token = entry.partition(":")
        name, token = name.strip(), token.strip()
        if not colon or not name:
            raise _entry_error(position, "has no name; each entry is name:token")
        if not _NAME_PATTERN.fullmatch(name):
            raise _entry_error(
                position,
                f"has an unusable name; a name is 1 to {MAX_NAME_LENGTH} "
                "characters from letters, digits, '.', '_' and '-'",
            )
        if not token:
            raise _entry_error(position, "has an empty token")
        if not _TOKEN_PATTERN.fullmatch(token):
            raise _entry_error(
                position,
                "has an unusable token; a token is printable ASCII with no spaces",
            )
        if len(token) < MIN_TOKEN_LENGTH:
            raise _entry_error(
                position, f"has a token shorter than {MIN_TOKEN_LENGTH} characters"
            )
        key = ApiKey(name=name, digest=_digest(token))
        for earlier_position, earlier in enumerate(keys, start=1):
            if earlier.name == key.name:
                raise _entry_error(
                    position, f"repeats the name of entry {earlier_position}"
                )
            if hmac.compare_digest(earlier.digest, key.digest):
                raise _entry_error(
                    position, f"repeats the token of entry {earlier_position}"
                )
        keys.append(key)
    return tuple(keys)


def _entry_error(position: int, problem: str) -> AuthConfigError:
    return AuthConfigError(f"{KEYS_ENV}: entry {position} {problem}")


UNAUTHORIZED_DETAIL = "Missing or invalid bearer token"


def _printable(text: str) -> str:
    """Escape control and non-ASCII characters, so request text placed in a
    log line cannot start a new line or drive a terminal."""
    return text.encode("unicode_escape").decode("ascii")


def _describe_request(scope) -> str:
    """'<METHOD> <path> from <client address>'. The query string and the
    headers are left out."""
    method = _printable(str(scope.get("method") or scope["type"]))
    path = _printable(str(scope.get("path") or ""))
    client = scope.get("client")
    origin = _printable(str(client[0])) if client else "an unknown address"
    return f"{method} {path} from {origin}"


def _log_decision(decision: Decision, scope) -> None:
    """One log line per checked request. It carries the method, the path,
    the client address and, for a valid token, the caller's name."""
    request = _describe_request(scope)
    if not decision.allowed:
        reason = "no token" if decision.credential == "none" else "invalid token"
        logger.warning("auth: refused %s (%s)", request, reason)
    elif decision.credential == "none":
        logger.warning("auth: unauthenticated request served (optional mode): %s", request)
    elif decision.credential == "valid":
        logger.info("auth: %s authenticated as '%s'", request, decision.caller)


class BearerAuthMiddleware:
    """ASGI middleware that applies decide() to every request.

    It wraps the whole application, so it runs before routing: a request is
    checked whether or not its path is registered. Only a path listed in
    `exempt_paths` (exact match) skips the check.
    """

    def __init__(
        self,
        app,
        *,
        get_settings: Callable[[], AuthSettings],
        exempt_paths: Iterable[str],
    ) -> None:
        self.app = app
        self.get_settings = get_settings
        self.exempt_paths = frozenset(exempt_paths)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan" or scope.get("path") in self.exempt_paths:
            await self.app(scope, receive, send)
            return
        authorization = [
            value.decode("latin-1")
            for name, value in scope.get("headers") or []
            if name == b"authorization"
        ]
        decision = decide(self.get_settings(), authorization)
        _log_decision(decision, scope)
        if decision.allowed:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            # Closing before accepting refuses the handshake (policy violation).
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            return
        body = json.dumps({"detail": UNAUTHORIZED_DETAIL}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def declare_bearer_scheme(schema: dict, exempt_paths: Iterable[str]) -> dict:
    """Add the bearer scheme to an OpenAPI document, in place: required for
    the whole API, with an empty requirement on the exempt paths' operations.
    Applying it twice gives the same document."""
    components = schema.setdefault("components", {})
    components.setdefault("securitySchemes", {})["bearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
    }
    schema["security"] = [{"bearerAuth": []}]
    for path in exempt_paths:
        for operation in schema.get("paths", {}).get(path, {}).values():
            operation["security"] = []
    return schema
