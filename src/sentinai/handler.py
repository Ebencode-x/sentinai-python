"""A logging handler that hands error records to the SDK."""

import contextlib
import logging
from collections.abc import Callable


def _level(levelno: int) -> str:
    if levelno >= logging.CRITICAL:
        return "critical"
    if levelno >= logging.ERROR:
        return "error"
    return "warning"


class SentinAIHandler(logging.Handler):
    """Never raises and ignores records written by the SDK itself."""

    def __init__(self, capture: Callable[..., bool], level: int = logging.ERROR) -> None:
        super().__init__(level)
        self._capture = capture

    def emit(self, record: logging.LogRecord) -> None:
        with contextlib.suppress(Exception):
            if record.name == "sentinai" or record.name.startswith("sentinai."):
                return
            exc_info = record.exc_info
            if not (isinstance(exc_info, tuple) and exc_info[0] is not None):
                exc_info = None
            self._capture(
                record.getMessage(),
                exc_info,
                getattr(record, "request_id", None),
                level=_level(record.levelno),
            )
