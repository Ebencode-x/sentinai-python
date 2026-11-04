"""Send one batch to SentinAI and decide what to do with the answer."""

import http.client
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import Config
from .event import Event

USER_AGENT = "sentinai-python/0.1"
MIN_PAUSE = 1.0
MAX_PAUSE = 300.0
RATE_LIMIT_PAUSE = 60.0
KEY_PAUSE = 600.0


@dataclass(frozen=True)
class Outcome:
    """kind is ok, retry, drop or pause. A pause drops the batch, then waits delay seconds."""

    kind: str
    delay: float = 0.0
    status: int | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the key must only go to the configured host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def parse_retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After header, clamped to 1..300. Dates are ignored."""
    text = (value or "").strip()
    if not (text.isascii() and text.isdigit()):
        return None
    return max(MIN_PAUSE, min(MAX_PAUSE, float(text)))


def classify(status: int, retry_after: str | None = None) -> Outcome:
    """Turn an HTTP status into an action, following the table in DESIGN.md."""
    if 200 <= status < 300:
        return Outcome("ok", status=status)
    wait = parse_retry_after(retry_after)
    if status == 429:
        return Outcome("pause", RATE_LIMIT_PAUSE if wait is None else wait, status)
    if status in (401, 403):
        return Outcome("pause", KEY_PAUSE, status)
    if status == 503 and wait is not None:
        return Outcome("retry", wait, status)
    if status == 408 or status >= 500:
        return Outcome("retry", 0.0, status)
    return Outcome("drop", 0.0, status)


def send_batch(config: Config, events: list[Event], timeout: float = 5.0) -> Outcome:
    """POST the events. Never raises."""
    try:
        body = json.dumps({"events": events}, default=str).encode("utf-8")
    except (TypeError, ValueError):
        return Outcome("drop")
    request = urllib.request.Request(
        config.url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return classify(response.status)
    except urllib.error.HTTPError as error:
        retry_after = error.headers.get("Retry-After") if error.headers else None
        error.close()
        return classify(error.code, retry_after)
    except (OSError, http.client.HTTPException, ValueError):
        return Outcome("retry")
