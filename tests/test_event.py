import sys
import uuid
from datetime import datetime

from sentinai.event import MAX_MESSAGE_CHARS, build_event
from sentinai.scrub import WITHHELD

OperationalError = type("OperationalError", (Exception,), {"__module__": "sqlalchemy.exc"})


def test_event_has_the_expected_fields():
    event = build_event("boom", environment="prod", release="1.2", request_id="req-1")
    assert set(event) == {
        "event_id",
        "message",
        "level",
        "timestamp",
        "environment",
        "release",
        "request_id",
    }
    uuid.UUID(event["event_id"])
    datetime.fromisoformat(event["timestamp"])
    assert event["level"] == "error"


def test_event_ids_are_unique():
    assert build_event("a")["event_id"] != build_event("a")["event_id"]


def test_empty_message_gives_no_event():
    assert build_event("   ") is None
    assert build_event(None) is None


def test_unknown_level_becomes_error():
    assert build_event("a", level="loud")["level"] == "error"


def test_long_message_is_cut():
    assert len(build_event("x" * 5000)["message"]) <= MAX_MESSAGE_CHARS


def test_request_id_is_cut():
    assert len(build_event("a", request_id="r" * 500)["request_id"]) == 128


def test_exception_fills_type_and_stacktrace():
    try:
        raise ValueError("bad value")
    except ValueError:
        info = sys.exc_info()
    event = build_event("failed", exc_info=info)
    assert event["exception_type"] == "ValueError"
    assert "ValueError: bad value" in event["stacktrace"]


def test_database_messages_are_withheld():
    detail = "could not connect as amani, phone 0712345678"
    try:
        raise OperationalError(detail)
    except OperationalError:
        info = sys.exc_info()
    event = build_event(f"query failed: {detail}", exc_info=info)
    assert "0712345678" not in event["message"]
    assert "0712345678" not in event["stacktrace"]
    assert WITHHELD in event["message"]
    assert WITHHELD in event["stacktrace"]
