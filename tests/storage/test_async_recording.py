"""Recording must not block UART work or silently lose evidence."""
import csv
import json
import random
from threading import Event, get_ident

import pytest

from pc_sim.storage.async_recording import AsyncRecorder
from pc_sim.simulation.gui_model import Settings, make_sample
from pc_sim.storage.recording import SessionRecorder
from pc_sim.transport.protocol import TrackReport, STATUS_FIELDS


def test_writer_owns_files_and_drains_in_order(tmp_path, monkeypatch):
    owners = []
    original = SessionRecorder._row
    def row(self, name, value):
        owners.append(get_ident())
        return original(self, name, value)
    monkeypatch.setattr(SessionRecorder, '_row', row)
    raw = bytearray(b'abc')
    with AsyncRecorder(tmp_path/'session', Settings(), 'test', tmp_path/'console.log') as writer:
        for stamp in range(100):
            writer.record_wire('rx', raw, stamp + .25)
        raw[:] = b'xyz'
        writer.record_console('first\n')
        writer.record_console('second\n')
    with (tmp_path/'session/wire.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    assert [float(r['monotonic_s']) for r in rows] == [i+.25 for i in range(100)]
    assert {r['hex'] for r in rows} == {'616263'}
    assert set(owners) == {writer.thread.ident}
    assert get_ident() not in owners
    assert (tmp_path/'console.log').read_text() == 'first\nsecond\n'
    assert json.loads((tmp_path/'session/metadata.json').read_text())['closed']
    assert writer.stats == {'enqueued': 102, 'written': 102, 'capacity': 1024}
    assert not writer.thread.is_alive()
    with pytest.raises(RuntimeError, match='closed'):
        writer.record_wire('rx', b'a', 1)


def test_slow_writer_does_not_block_and_full_queue_fails(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    original = SessionRecorder._row
    def slow(self, name, value):
        entered.set()
        assert release.wait(3)
        return original(self, name, value)
    monkeypatch.setattr(SessionRecorder, '_row', slow)
    writer = AsyncRecorder(tmp_path/'session', Settings(), 'test', tmp_path/'console.log', capacity=1)
    try:
        writer.record_wire('rx', b'a', 1)
        assert entered.wait(1)
        writer.record_wire('rx', b'b', 2)
        with pytest.raises(RuntimeError, match='queue full'):
            writer.record_wire('rx', b'c', 3)
    finally:
        release.set()
        with pytest.raises(RuntimeError, match='queue full'):
            writer.close()
    assert writer.stats['written'] == 2
    assert not writer.thread.is_alive()


def test_write_error_is_reported_and_thread_exits(tmp_path, monkeypatch):
    failed = Event()
    def broken(*args):
        failed.set()
        raise OSError('disk full')
    monkeypatch.setattr(SessionRecorder, '_row', broken)
    writer = AsyncRecorder(tmp_path/'session', Settings(), 'test', tmp_path/'console.log')
    writer.record_wire('rx', b'a', 1)
    assert failed.wait(1)
    with pytest.raises(RuntimeError, match='recording failed') as error:
        writer.close()
    assert isinstance(error.value.__cause__, OSError)
    assert not writer.thread.is_alive()


def test_startup_error_is_reported(tmp_path):
    (tmp_path/'session').mkdir()
    with pytest.raises(RuntimeError, match='recording failed'):
        AsyncRecorder(tmp_path/'session', Settings(), 'test', tmp_path/'console.log')


def test_body_error_still_drains(tmp_path):
    with pytest.raises(ValueError, match='test failed'):
        with AsyncRecorder(tmp_path/'session', Settings(), 'test', tmp_path/'console.log') as writer:
            writer.record_wire('rx', b'a', 1)
            raise ValueError('test failed')
    assert writer.stats['written'] == 1
    assert not writer.thread.is_alive()


def test_all_payloads_preserve_values_and_status_snapshot(tmp_path):
    settings = Settings()
    sample = make_sample(settings, 123, random.Random(42))
    report = TrackReport(7, 123, 123, 1000., .1, 0., 0., 2, 1, 3)
    status = {name: 0 for name, *_ in STATUS_FIELDS}
    with AsyncRecorder(tmp_path/'session', settings, 'test', tmp_path/'console.log') as writer:
        writer.record_sample(sample, 12.5)
        writer.record_report(report, 12.6)
        writer.record_status(status, 12.7)
        status['crc_errors'] = 999
    for name, key, expected in [('samples', 'tx_monotonic_s', '12.5'),
                                ('reports', 'rx_monotonic_s', '12.6'),
                                ('status', 'crc_errors', '0')]:
        with (tmp_path/f'session/{name}.csv').open() as stream:
            row, = list(csv.DictReader(stream))
        assert row[key] == expected


def test_shutdown_write_failure_is_not_hidden_by_body_error(tmp_path, monkeypatch):
    def broken(*args):
        raise OSError('disk full')
    monkeypatch.setattr(SessionRecorder, '_row', broken)
    with pytest.raises(RuntimeError, match='original.*recording failed'):
        with AsyncRecorder(tmp_path/'session', Settings(), 'test', tmp_path/'console.log') as writer:
            writer.record_wire('rx', b'a', 1)
            raise ValueError('original')


def test_invalid_queue_capacity(tmp_path):
    with pytest.raises(ValueError, match='capacity'):
        AsyncRecorder(tmp_path/'session', Settings(), 'test', tmp_path/'console.log', capacity=0)


def test_body_failure_does_not_mean_recording_failed(tmp_path):
    with pytest.raises(ValueError, match='board failure'):
        with AsyncRecorder(tmp_path/'session', Settings(), 'test', tmp_path/'console.log') as writer:
            assert not writer.complete
            writer.record_console('captured before board failure\n')
            raise ValueError('board failure')
    assert writer.complete
    assert writer.stats['written'] == writer.stats['enqueued'] == 1
