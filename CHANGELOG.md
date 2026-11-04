# Changelog

## 0.1.0 - 2026-11-04

First public release.

- Public API: init, capture, attach, flush, close and stats.
- Non-blocking bounded queue with a sender thread and a flush at exit.
- Batches are capped by encoded size so they stay under the server limit.
- Logging handler for ERROR and above.
- Privacy helpers: database error messages are withheld and tracebacks are trimmed.
- Retry-After is honored when the server answers 503.
- Zero dependencies, Python 3.11 to 3.14.
