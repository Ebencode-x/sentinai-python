"""Queue events and send them from one background thread."""

import logging
import os
import queue
import threading
import time

from .config import Config
from .event import Event
from .transport import send_batch

log = logging.getLogger("sentinai.sender")

QUEUE_SIZE = 200
BATCH_SIZE = 20
BATCH_WAIT = 3.0
MAX_ATTEMPTS = 3
RETRY_DELAYS = (1.0, 2.0)
FAILURE_LIMIT = 3
FAILURE_PAUSE = 60.0
REQUEST_TIMEOUT = 5.0
POLL = 0.2


class Sender:
    """A bounded queue and one daemon thread. Nothing here may raise into the caller."""

    def __init__(
        self,
        config: Config,
        *,
        queue_size: int = QUEUE_SIZE,
        batch_size: int = BATCH_SIZE,
        batch_wait: float = BATCH_WAIT,
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
        failure_pause: float = FAILURE_PAUSE,
        request_timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        self._config = config
        self._queue_size = queue_size
        self._batch_size = batch_size
        self._batch_wait = batch_wait
        self._retry_delays = retry_delays
        self._failure_pause = failure_pause
        self._request_timeout = request_timeout
        self._sent = 0
        self._dropped = 0
        self._failures = 0
        self._warned_key = False
        self._closed = False
        self._pid = os.getpid()
        self._make_primitives()

    def _make_primitives(self) -> None:
        """Fresh queue, locks and flags. Also used in a forked child, where old locks are unsafe."""
        self._queue: queue.Queue[Event] = queue.Queue(maxsize=self._queue_size)
        self._cond = threading.Condition()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._flushing = threading.Event()
        if self._closed:
            self._stop.set()
        self._pending = 0
        self._thread: threading.Thread | None = None

    def _check_pid(self) -> None:
        pid = os.getpid()
        if pid != self._pid:
            self._pid = pid
            self._make_primitives()

    def _ensure_thread(self) -> None:
        self._check_pid()
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            thread = threading.Thread(target=self._run, name="sentinai-sender", daemon=True)
            self._thread = thread
            thread.start()

    def _count(self, sent: int = 0, dropped: int = 0) -> None:
        with self._cond:
            self._sent += sent
            self._dropped += dropped

    def put(self, event: Event) -> bool:
        """Queue one event. A full queue drops it and counts it, so memory never grows."""
        try:
            self._check_pid()
            if self._closed:
                self._count(dropped=1)
                return False
            self._ensure_thread()
            with self._cond:
                self._pending += 1
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                with self._cond:
                    self._pending -= 1
                    self._dropped += 1
                    self._cond.notify_all()
                return False
            return True
        except Exception:
            return False

    def stats(self) -> dict[str, int]:
        self._check_pid()
        with self._cond:
            return {"sent": self._sent, "dropped": self._dropped}

    def flush(self, timeout: float = 2.0) -> bool:
        """Wait until every queued event was sent or dropped. False on timeout."""
        self._check_pid()
        deadline = time.monotonic() + timeout
        self._flushing.set()
        try:
            with self._cond:
                while self._pending > 0:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        break
                    self._cond.wait(left)
                return self._pending == 0
        finally:
            self._flushing.clear()

    def close(self, timeout: float = 2.0) -> bool:
        """Drain for up to timeout seconds, then stop the thread. Safe to call twice."""
        self._check_pid()
        done = self.flush(timeout)
        self._closed = True
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout)
        leftover = 0
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            leftover += 1
        if leftover:
            with self._cond:
                self._dropped += leftover
                self._pending -= leftover
                self._cond.notify_all()
        return done

    def _run(self) -> None:
        events = self._queue
        batch: list[Event] = []
        deadline = 0.0
        while True:
            wait = POLL
            if batch:
                wait = max(0.0, min(POLL, deadline - time.monotonic()))
            try:
                item = events.get(timeout=wait)
            except queue.Empty:
                item = None
            if item is not None:
                if not batch:
                    deadline = time.monotonic() + self._batch_wait
                batch.append(item)
            due = (
                len(batch) >= self._batch_size
                or time.monotonic() >= deadline
                or self._flushing.is_set()
                or self._stop.is_set()
            )
            if batch and due:
                pause = self._deliver(batch)
                batch = []
                if pause:
                    self._stop.wait(pause)
            if not batch and self._stop.is_set():
                return

    def _deliver(self, batch: list[Event]) -> float:
        count = len(batch)
        pause = 0.0
        try:
            pause = self._attempt(batch)
        except Exception:
            self._count(dropped=count)
        finally:
            with self._cond:
                self._pending -= count
                self._cond.notify_all()
        return pause

    def _attempt(self, batch: list[Event]) -> float:
        """Send one batch. Returns how long the thread should pause afterwards."""
        count = len(batch)
        for attempt in range(MAX_ATTEMPTS):
            outcome = send_batch(self._config, batch, self._request_timeout)
            if outcome.kind == "ok":
                self._failures = 0
                self._count(sent=count)
                return 0.0
            if outcome.kind == "drop":
                self._count(dropped=count)
                return 0.0
            if outcome.kind == "pause":
                self._count(dropped=count)
                self._warn_rejected(outcome.status)
                return outcome.delay
            if attempt + 1 == MAX_ATTEMPTS or self._stop.is_set():
                break
            fallback = self._retry_delays[min(attempt, len(self._retry_delays) - 1)]
            self._stop.wait(outcome.delay or fallback)
        self._count(dropped=count)
        self._failures += 1
        if self._failures >= FAILURE_LIMIT:
            self._failures = 0
            return self._failure_pause
        return 0.0

    def _warn_rejected(self, status: int | None) -> None:
        if status in (401, 403) and not self._warned_key:
            self._warned_key = True
            log.warning("SentinAI rejected the key (HTTP %s). Sending is paused.", status)
