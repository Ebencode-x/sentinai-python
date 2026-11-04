import time


def event(name):
    return {"event_id": name, "message": name}


def test_events_are_sent_in_batches(ingest, make_config, make_sender):
    server = ingest()
    sender = make_sender(make_config(server))
    for number in range(25):
        sender.put(event(f"id{number}"))
    assert sender.flush(5.0)
    assert sorted(e["event_id"] for e in server.events()) == sorted(f"id{n}" for n in range(25))
    assert all(len(r["body"]["events"]) <= 20 for r in server.requests)
    assert sender.stats() == {"sent": 25, "dropped": 0}


def test_flush_on_an_idle_sender_returns_at_once(ingest, make_config, make_sender):
    sender = make_sender(make_config(ingest()))
    assert sender.flush(0.1) is True


def test_a_retry_keeps_the_same_event_id(ingest, make_config, make_sender):
    server = ingest([(500, {}), (502, {})])
    sender = make_sender(make_config(server))
    sender.put(event("same"))
    assert sender.flush(5.0)
    assert [e["event_id"] for e in server.events()] == ["same", "same", "same"]
    assert sender.stats() == {"sent": 1, "dropped": 0}


def test_a_batch_is_dropped_after_three_failed_attempts(ingest, make_config, make_sender):
    server = ingest([(500, {})] * 3)
    sender = make_sender(make_config(server))
    sender.put(event("a"))
    assert sender.flush(5.0)
    assert len(server.requests) == 3
    assert sender.stats() == {"sent": 0, "dropped": 1}


def test_a_rejected_batch_is_not_retried(ingest, make_config, make_sender):
    server = ingest([(422, {})])
    sender = make_sender(make_config(server))
    sender.put(event("a"))
    assert sender.flush(5.0)
    assert len(server.requests) == 1
    assert sender.stats() == {"sent": 0, "dropped": 1}


def test_rate_limit_drops_the_batch_then_resumes(ingest, make_config, make_sender):
    server = ingest([(429, {"Retry-After": "1"})])
    sender = make_sender(make_config(server))
    sender.put(event("a"))
    assert sender.flush(5.0)
    assert sender.stats() == {"sent": 0, "dropped": 1}
    sender.put(event("b"))
    assert sender.flush(5.0)
    assert [e["event_id"] for e in server.events()] == ["a", "b"]
    assert sender.stats() == {"sent": 1, "dropped": 1}


def test_rejected_key_pauses_sending_and_close_does_not_wait(ingest, make_config, make_sender):
    server = ingest([(401, {})])
    sender = make_sender(make_config(server))
    sender.put(event("a"))
    assert sender.flush(5.0)
    assert sender.stats() == {"sent": 0, "dropped": 1}
    sender.put(event("b"))
    started = time.monotonic()
    sender.close(1.0)
    assert time.monotonic() - started < 3.0
    assert len(server.requests) == 1
    assert sender.stats()["dropped"] == 2


def test_a_full_queue_drops_and_counts(ingest, make_config, make_sender):
    server = ingest(delay=1.0)
    sender = make_sender(make_config(server), queue_size=2, batch_size=1)
    sender.put(event("first"))
    assert server.seen.wait(2.0)
    results = [sender.put(event(f"e{number}")) for number in range(5)]
    assert results == [True, True, False, False, False]
    assert sender.stats()["dropped"] == 3


def test_the_thread_restarts_in_a_forked_child(ingest, make_config, make_sender):
    server = ingest()
    sender = make_sender(make_config(server))
    sender.put(event("a"))
    assert sender.flush(5.0)
    sender._pid = -1  # pretend this process was forked
    sender.put(event("b"))
    assert sender.flush(5.0)
    assert {e["event_id"] for e in server.events()} == {"a", "b"}


def test_close_stops_the_sender(ingest, make_config, make_sender):
    server = ingest()
    sender = make_sender(make_config(server))
    sender.put(event("a"))
    sender.close(2.0)
    assert sender.put(event("b")) is False
    assert sender.stats() == {"sent": 1, "dropped": 1}


def test_big_batches_are_split_below_the_server_limit(ingest, make_config, make_sender):
    server = ingest()
    sender = make_sender(make_config(server))
    for number in range(20):
        sender.put({"event_id": f"big{number}", "message": "m", "stacktrace": "é" * 6000})
    assert sender.flush(10.0)
    assert len(server.events()) == 20
    assert len(server.requests) > 1
    assert all(request["size"] <= 256 * 1024 for request in server.requests)
