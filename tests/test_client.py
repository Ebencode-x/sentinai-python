import logging

import pytest

import sentinai
import sentinai.client as client


@pytest.fixture(autouse=True)
def clean_client(monkeypatch):
    for name in (
        "SENTINAI_INGEST_URL",
        "SENTINAI_INGEST_KEY",
        "SENTINAI_ENVIRONMENT",
        "SENTINAI_RELEASE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(client, "_sender", None)
    monkeypatch.setattr(client, "_config", None)
    monkeypatch.setattr(client, "_before_send", None)
    yield
    sentinai.close(0.5)


def test_calls_before_init_do_nothing():
    assert sentinai.capture("x") is False
    assert sentinai.flush() is True
    assert sentinai.stats() == {"sent": 0, "dropped": 0}


def test_a_bad_configuration_never_raises():
    assert sentinai.init(url="http://example.com", key="snl_abc") is False
    assert sentinai.init(url="https://example.com", key="wrong") is False
    assert sentinai.init() is False
    assert sentinai.capture("x") is False


def test_capture_sends_the_event(ingest):
    server = ingest()
    assert sentinai.init(url=server.url, key="snl_testkey", environment="Test", release="1.0")
    assert sentinai.capture("hello", request_id="req-1") is True
    assert sentinai.flush(5.0)
    (event,) = server.events()
    assert event["message"] == "hello"
    assert event["environment"] == "test"
    assert event["release"] == "1.0"
    assert event["request_id"] == "req-1"
    assert server.requests[0]["auth"] == "Bearer snl_testkey"
    assert sentinai.stats() == {"sent": 1, "dropped": 0}


def test_capture_with_the_current_exception(ingest):
    server = ingest()
    sentinai.init(url=server.url, key="snl_testkey")
    try:
        int("not a number")
    except ValueError:
        assert sentinai.capture("parse failed", exc_info=True)
    assert sentinai.flush(5.0)
    assert server.events()[0]["exception_type"] == "ValueError"


def test_before_send_can_change_or_drop_an_event(ingest):
    server = ingest()

    def hook(event):
        if "secret" in event["message"]:
            return None
        event["message"] = event["message"].upper()
        return event

    sentinai.init(url=server.url, key="snl_testkey", before_send=hook)
    assert sentinai.capture("secret thing") is False
    assert sentinai.capture("fine") is True
    assert sentinai.flush(5.0)
    assert [e["message"] for e in server.events()] == ["FINE"]


def test_a_failing_before_send_never_raises(ingest):
    def hook(event):
        raise RuntimeError("hook bug")

    sentinai.init(url=ingest().url, key="snl_testkey", before_send=hook)
    assert sentinai.capture("x") is False


def test_attach_is_idempotent_and_sends_errors(ingest):
    server = ingest()
    sentinai.init(url=server.url, key="snl_testkey")
    logger = logging.getLogger("tests.attach")
    logger.setLevel(logging.INFO)
    first = sentinai.attach(logger)
    second = sentinai.attach(logger)
    try:
        assert first is second
        assert len(logger.handlers) == 1
        logger.info("not sent")
        logger.error("from logging")
        try:
            int("nope")
        except ValueError:
            logger.exception("with traceback")
        assert sentinai.flush(5.0)
    finally:
        logger.removeHandler(first)
    events = server.events()
    assert [e["message"] for e in events] == ["from logging", "with traceback"]
    assert events[1]["exception_type"] == "ValueError"


def test_records_from_the_sdk_itself_are_ignored(ingest):
    server = ingest()
    sentinai.init(url=server.url, key="snl_testkey")
    root = logging.getLogger()
    handler = sentinai.attach(root)
    try:
        logging.getLogger("sentinai.sender").error("sending failed")
        assert sentinai.flush(5.0)
    finally:
        root.removeHandler(handler)
    assert server.events() == []
