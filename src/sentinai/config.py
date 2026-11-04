"""Settings: where to send events and who is sending them."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

EVENTS_PATH = "/api/v1/events"
KEY_PREFIX = "snl_"
MAX_RELEASE_CHARS = 64
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_ENVIRONMENT_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")


class ConfigError(ValueError):
    """The settings cannot be used. The message never contains the key."""


@dataclass(frozen=True)
class Config:
    url: str
    key: str = field(repr=False)
    environment: str | None = None
    release: str | None = None


def clean_url(raw: str | None) -> str:
    """Return the full events URL, or raise ConfigError."""
    value = (raw or "").strip()
    if not value:
        raise ConfigError("The SentinAI URL is missing.")
    try:
        parts = urlsplit(value)
        host = parts.hostname
    except ValueError:
        raise ConfigError("The SentinAI URL is not valid.") from None
    if parts.username or parts.password:
        raise ConfigError("The SentinAI URL must not contain credentials.")
    if parts.query or parts.fragment:
        raise ConfigError("The SentinAI URL must not contain a query or a fragment.")
    if not host:
        raise ConfigError("The SentinAI URL has no host.")
    if parts.scheme != "https" and not (parts.scheme == "http" and host in LOCAL_HOSTS):
        raise ConfigError("The SentinAI URL must use https (http only for localhost).")
    path = parts.path.rstrip("/")
    if not path.endswith(EVENTS_PATH):
        path += EVENTS_PATH
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def clean_key(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value.startswith(KEY_PREFIX) or len(value) <= len(KEY_PREFIX):
        # The message must never repeat the value: it may be a real secret.
        raise ConfigError("The SentinAI key must be a source key that starts with snl_.")
    return value


def clean_environment(raw: str | None) -> str | None:
    """An invalid name is dropped, not sent."""
    name = (raw or "").strip().lower()
    return name if _ENVIRONMENT_NAME.match(name) else None


def clean_release(raw: str | None) -> str | None:
    return (raw or "").strip()[:MAX_RELEASE_CHARS] or None


def build_config(
    url: str | None = None,
    key: str | None = None,
    environment: str | None = None,
    release: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Config:
    """Arguments win over environment variables. Raises ConfigError if unusable."""
    source = os.environ if env is None else env
    return Config(
        url=clean_url(url or source.get("SENTINAI_INGEST_URL")),
        key=clean_key(key or source.get("SENTINAI_INGEST_KEY")),
        environment=clean_environment(environment or source.get("SENTINAI_ENVIRONMENT")),
        release=clean_release(release or source.get("SENTINAI_RELEASE")),
    )
