import pytest

from sentinai.config import Config
from sentinai.transport import Outcome, classify, send_batch


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (200, "ok"),
        (202, "ok"),
        (302, "drop"),
        (400, "drop"),
        (404, "drop"),
        (413, "drop"),
        (422, "drop"),
        (408, "retry"),
        (500, "retry"),
        (502, "retry"),
        (503, "retry"),
        (401, "pause"),
        (403, "pause"),
        (429, "pause"),
    ],
)
def test_status_decides_the_action(status, kind):
    assert classify(status).kind == kind


def test_retry_after_is_clamped_and_defaulted():
    assert classify(429, "0").delay == 1.0
    assert classify(429, "7").delay == 7.0
    assert classify(429, "9999").delay == 300.0
    assert classify(429).delay == 60.0
    assert classify(429, "soon").delay == 60.0


def test_503_honors_retry_after():
    assert classify(503, "5") == Outcome("retry", 5.0, 503)


def test_rejected_key_pauses_ten_minutes():
    assert classify(401).delay == 600.0


def test_batch_is_posted_with_the_bearer_key(ingest, make_config):
    server = ingest()
    outcome = send_batch(make_config(server), [{"event_id": "a", "message": "x"}])
    assert outcome.kind == "ok"
    request = server.requests[0]
    assert request["path"] == "/api/v1/events"
    assert request["auth"] == "Bearer snl_testkey"
    assert request["body"] == {"events": [{"event_id": "a", "message": "x"}]}


def test_redirects_are_not_followed(ingest, make_config):
    server = ingest([(302, {"Location": "http://127.0.0.1:1/elsewhere"})])
    assert send_batch(make_config(server), [{"message": "x"}]).kind == "drop"
    assert len(server.requests) == 1


def test_network_error_is_a_retry():
    config = Config(url="http://127.0.0.1:9/api/v1/events", key="snl_testkey")
    assert send_batch(config, [{"message": "x"}], timeout=1.0).kind == "retry"
