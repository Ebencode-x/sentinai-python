"""Build one event in the shape ingest API v1 expects."""

import uuid
from datetime import UTC, datetime
from typing import Any

from .scrub import WITHHELD, ExcInfo, safe_traceback, trim, withhold_db_messages

Event = dict[str, Any]

LEVELS = frozenset({"warning", "error", "critical"})
MAX_MESSAGE_CHARS = 1000
MAX_STACKTRACE_CHARS = 6000
MAX_EXCEPTION_TYPE_CHARS = 255
MAX_REQUEST_ID_CHARS = 128


def is_db_exception(exc_type: type[BaseException]) -> bool:
    """True for database exceptions, using the same list as the scrubber."""
    probe = f"{exc_type.__module__}.{exc_type.__qualname__}: x"
    return WITHHELD in withhold_db_messages(probe)


def build_event(
    message: object,
    *,
    level: str = "error",
    exc_info: ExcInfo | None = None,
    environment: str | None = None,
    release: str | None = None,
    request_id: object = None,
) -> Event | None:
    """Return a ready event, or None when there is no message to send."""
    text = "" if message is None else str(message).strip()
    if exc_info is not None and is_db_exception(exc_info[0]):
        detail = str(exc_info[1])
        if detail:
            text = text.replace(detail, WITHHELD)
    text = withhold_db_messages(text)
    if not text:
        return None
    event: Event = {
        "event_id": str(uuid.uuid4()),
        "message": trim(text, MAX_MESSAGE_CHARS),
        "level": level if level in LEVELS else "error",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if exc_info is not None:
        event["exception_type"] = exc_info[0].__name__[:MAX_EXCEPTION_TYPE_CHARS]
        event["stacktrace"] = trim(safe_traceback(exc_info), MAX_STACKTRACE_CHARS)
    if environment:
        event["environment"] = environment
    if release:
        event["release"] = release
    if request_id:
        event["request_id"] = str(request_id)[:MAX_REQUEST_ID_CHARS]
    return event
