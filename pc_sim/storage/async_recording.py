"""Bounded single-producer recording queue for the performance board test."""
from queue import Empty, Full, Queue
from threading import Event, Thread

from pc_sim.storage.recording import SessionRecorder


class AsyncRecorder:
    """Own CSV/console files in one worker; callers retain UART timestamps.

    Enqueue never waits for disk I/O. Queue saturation permanently fails the
    recording. Close drains accepted events, joins the worker, and reports errors.
    Only the UART owner may enqueue or close; payloads must be immutable snapshots.
    """

    def __init__(self, directory, settings, mode, console_path, capacity=1024):
        if capacity < 1:
            raise ValueError('capacity must be positive')
        self._queue = Queue(maxsize=capacity)
        self._stop = Event()
        self._ready = Event()
        self._error = None
        self._producer_error = None
        self._closed = False
        self._enqueued = 0
        self._written = 0
        self.thread = Thread(target=self._run, args=(directory, settings, mode, console_path),
                             name='hil-recorder', daemon=True)
        self.thread.start()
        if not self._ready.wait(5):
            self._closed = True
            self._stop.set()
            raise RuntimeError('recording startup timed out')
        if self._error is not None:
            self.thread.join(timeout=10)
        self.check()

    @property
    def complete(self):
        """Whether accepted events were saved and the writer closed successfully.

        A board-test exception in the caller does not imply a recording failure.
        """
        return (self._closed and not self.thread.is_alive() and
                self._error is None and self._producer_error is None and
                self._enqueued == self._written)

    @property
    def stats(self):
        """Read final counts after close; live counts may be in flight."""
        return dict(enqueued=self._enqueued, written=self._written,
                    capacity=self._queue.maxsize)

    def check(self):
        if self._error is not None:
            raise RuntimeError('recording failed') from self._error
        if self._producer_error is not None:
            raise RuntimeError(self._producer_error)

    def _put(self, operation, *payload):
        self.check()
        if self._closed:
            raise RuntimeError('recording is closed')
        try:
            self._queue.put_nowait((operation, payload))
        except Full:
            self._producer_error = 'recording queue full'
            raise RuntimeError(self._producer_error) from None
        self._enqueued += 1

    def record_wire(self, direction, raw, now):
        if raw:
            self._put('record_wire', direction, bytes(raw), now)

    def record_sample(self, sample, sent_at):
        # Sample and TrackReport are frozen dataclasses.
        self._put('record_sample', sample, sent_at)

    def record_report(self, report, received_at):
        self._put('record_report', report, received_at)

    def record_status(self, stats, received_at):
        self._put('record_status', dict(stats), received_at)

    def record_console(self, text):
        if text:
            self._put('console', text)

    def _run(self, directory, settings, mode, console_path):
        try:
            with SessionRecorder(directory, settings, mode) as recorder, \
                 console_path.open('w', encoding='utf-8') as console:
                self._ready.set()
                while not self._stop.is_set() or not self._queue.empty():
                    try:
                        operation, payload = self._queue.get(timeout=.05)
                    except Empty:
                        continue
                    if operation == 'console':
                        console.write(payload[0])
                        console.flush()
                    else:
                        getattr(recorder, operation)(*payload)
                    self._written += 1
        except BaseException as error:
            self._error = error
        finally:
            self._ready.set()

    def close(self):
        self._closed = True
        self._stop.set()
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise RuntimeError('recording shutdown timed out; evidence incomplete')
        self.check()
        if self._written != self._enqueued:
            raise RuntimeError('recording event count mismatch')

    def __enter__(self):
        return self

    def __exit__(self, exc_type, error, traceback):
        try:
            self.close()
        except RuntimeError as recording_error:
            if error is None:
                raise
            raise RuntimeError(f'{error!r}; {recording_error}') from recording_error
