"""Public API: init, capture, attach, flush, close and stats."""

import atexit
import logging
import sys
import threading
from collections.abc import Callable
from types import TracebackType
from typing import Any

from .config import Config, ConfigError, build_config
from .event import LEVELS, Event, build_event
from .handler import SentinAIHandler
from .scrub import ExcInfo
from .sender import Sender

log = logging.getLogger("sentinai")

BeforeSend = Callable[[Event], Event | None]
ExcInfoArg = ExcInfo | BaseException | bool | None

_lock = threading.Lock()
_sender: Sender | None = None
_config: Config | None = None
_before_send: BeforeSend | None = None
_atexit_registered = False
_warned = False


def init(
    url: str | None = None,
    key: str | None = None,
    environment: str | None = None,
    release: str | None = None,
    *,
    before_send: BeforeSend | None = None,
) -> bool:
    """Configure the client. A bad configuration warns once and does nothing."""
    global _sender, _config, _before_send, _atexit_registered, _warned
    try:
        config = build_config(url, key, environment, release)
    except ConfigError as error:
        if not _warned:
            _warned = True
            log.warning("SentinAI is not active: %s", error)
        return False
    except Exception:
        return False
    with _lock:
        previous = _sender
        _config = config
        _before_send = before_send
        _sender = Sender(config)
        if not _atexit_registered:
            atexit.register(close)
            _atexit_registered = True
    if previous is not None:
        previous.close(0.5)
    return True


def _normalize(exc_info: ExcInfoArg) -> ExcInfo | None:
    if exc_info is None or exc_info is False:
        return None
    if exc_info is True:
        exc_info = sys.exc_info()
    if isinstance(exc_info, BaseException):
        return (type(exc_info), exc_info, exc_info.__traceback__)
    if isinstance(exc_info, tuple) and len(exc_info) == 3:
        exc_type, exc, tb = exc_info
        if exc_type is not None and exc is not None:
            return (exc_type, exc, tb if isinstance(tb, TracebackType) else None)
    return None


def capture(
    message: object,
    exc_info: ExcInfoArg = None,
    request_id: object = None,
    *,
    level: str = "error",
) -> bool:
    """Queue one event. Returns False when it was not queued. Never raises."""
    try:
        sender, config, hook = _sender, _config, _before_send
        if sender is None or config is None:
            return False
        event = build_event(
            message,
            level=level if level in LEVELS else "error",
            exc_info=_normalize(exc_info),
            environment=config.environment,
            release=config.release,
            request_id=request_id,
        )
        if event is None:
            return False
        if hook is not None:
            changed: Any = hook(event)
            if not isinstance(changed, dict):
                return False
            event = changed
        return sender.put(event)
    except Exception:
        return False


def attach(
    logger: logging.Logger | str | None = None, level: int = logging.ERROR
) -> logging.Handler | None:
    """Add the logging handler once. A second call returns the same handler."""
    try:
        target = logger if isinstance(logger, logging.Logger) else logging.getLogger(logger)
        for existing in target.handlers:
            if isinstance(existing, SentinAIHandler):
                return existing
        handler = SentinAIHandler(capture, level)
        target.addHandler(handler)
        return handler
    except Exception:
        return None


def flush(timeout: float = 2.0) -> bool:
    """Wait for queued events to be sent. False on timeout."""
    sender = _sender
    if sender is None:
        return True
    try:
        return sender.flush(timeout)
    except Exception:
        return False


def close(timeout: float = 2.0) -> None:
    """Drain the queue for up to timeout seconds and stop the sender."""
    sender = _sender
    if sender is None:
        return
    try:
        sender.close(timeout)
    except Exception:
        return


def stats() -> dict[str, int]:
    """Counters since init: events sent and events dropped."""
    sender = _sender
    if sender is None:
        return {"sent": 0, "dropped": 0}
    try:
        return sender.stats()
    except Exception:
        return {"sent": 0, "dropped": 0}
