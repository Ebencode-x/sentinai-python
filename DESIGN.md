# SentinAI Python SDK: design

Status: design only. Nothing here is implemented yet, and nothing is installable.

The SDK sends errors and log records from a Python application to SentinAI
(`POST /api/v1/events`). It is built around one rule: it must never slow down,
break or leak data from the application it runs in.

## Goals

- Zero runtime dependencies (standard library only).
- Never raise into the host application, never block a request.
- Safe retries: a retried event is never counted twice.
- Private by default: no request bodies, no local variables, database error
  messages withheld.

## Public API

- `sentinai.init(url, key, environment, release)` configures the client.
- `sentinai.capture(message, exc_info, request_id)` sends one event.
- `sentinai.attach(logger)` adds the logging handler once (idempotent).
- `sentinai.flush(timeout)` waits for queued events to be sent.
- `sentinai.close()` stops the sender.
- `sentinai.stats()` returns the `sent` and `dropped` counters.
- `before_send(event)` is an optional hook to change or drop an event.

## Configuration

Arguments first, then environment variables `SENTINAI_INGEST_URL`,
`SENTINAI_INGEST_KEY`, `SENTINAI_ENVIRONMENT`, `SENTINAI_RELEASE`.

- The URL may be a base URL (`https://host`); the SDK appends `/api/v1/events`.
  If the URL already ends with that path, it is used as is.
- https is required. Plain http is accepted for localhost only.
- The key must start with `snl_`.
- The environment name must match `^[a-z0-9][a-z0-9_.-]{0,31}$`; an invalid name
  is dropped, not sent.
- A bad configuration never raises: the SDK warns once and does nothing.

## Event shape

The event mirrors the server model for API v1. The source is taken from the key,
never from the body.

| Field | Notes |
| --- | --- |
| `event_id` | uuid4 created by the client; makes retries safe |
| `message` | required, cut to 1000 characters (server allows 2000) |
| `level` | `warning`, `error` or `critical` |
| `timestamp` | UTC, ISO 8601 |
| `exception_type` | up to 255 characters |
| `stacktrace` | cut to 6000 characters, start and end kept |
| `environment` | optional |
| `release` | optional, up to 64 characters |
| `request_id` | optional, up to 128 characters |

Batches hold up to 20 events (server allows 100).

## Delivery behavior

- A bounded queue of 200 events. When it is full the new event is dropped and
  counted, so memory never grows.
- One daemon sender thread. It is restarted in a forked child by comparing the
  process id, which matters for pre-fork servers such as gunicorn.
- A batch is sent when it holds 20 events or after 3 seconds.
- Records from the SDK's own transport are ignored, so sending errors can never
  create new errors.
- On exit the queue is drained for about 2 seconds.

| Response | Action |
| --- | --- |
| 2xx | success |
| network error, 408, 5xx | up to 3 attempts, same `event_id`, growing delay |
| 429 | pause for `Retry-After` (1 to 300 seconds), drop the batch |
| 503 | honor `Retry-After` when present |
| 401, 403 | warn once, pause 10 minutes (the key is probably revoked) |
| 413, 422 | drop the batch, do not retry |

After 3 failed batches in a row the sender pauses for 60 seconds.

## Privacy

- Messages of database exceptions (sqlalchemy, psycopg, sqlite3 and similar)
  are replaced with `<message withheld>`, because they can carry names, phone
  numbers and emails.
- No request bodies and no local variables are ever collected.
- `before_send` lets the user change or drop any event.
- The server masks personal data as well; the SDK does not rely on that.

## Compatibility

- Python 3.11 and newer (CI covers 3.11 to 3.14).
- Talks to ingest API v1. A new API version means a new major SDK version.

## Testing

- pytest against a real local HTTP server running in a thread, not mocks.
- Cases: retries with the same `event_id`, pause and `Retry-After`, full queue,
  fork, `flush`, `close`, invalid configuration, database message withholding.

## Release

- `0.1.0` with tag `v0.1.0`. Until PyPI, install from a git tag.
- CI: ruff format, ruff check, pytest matrix, `python -m build`, `twine check`.
- The `protect-main` ruleset is added after the first CI run exists.

## Not in 0.1

Tracing, breadcrumbs, sampling, performance data, async framework plugins.
