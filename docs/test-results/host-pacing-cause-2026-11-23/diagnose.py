"""Measure host stages around the unchanged board fixture; never change verdicts."""
import argparse
from collections import defaultdict
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import serial
from pc_sim.recording import SessionRecorder


class Trace:
    """Retain slow calls in memory and write them only after the board run."""

    def __init__(self):
        self.stats = defaultdict(lambda: dict(n=0, wall_ns=0, cpu_ns=0, max_ns=0))
        self.events = []
        self.gc_started = {}

    def record(self, name, begin, finish, cpu, process, detail=None, always=False):
        wall = finish - begin
        stats = self.stats[name]
        stats['n'] += 1
        stats['wall_ns'] += wall
        stats['cpu_ns'] += cpu
        stats['max_ns'] = max(stats['max_ns'], wall)
        if always or wall >= 2_000_000:
            self.events.append(dict(name=name, start_s=begin / 1e9, end_s=finish / 1e9,
                                    wall_ms=wall / 1e6, thread_cpu_ms=cpu / 1e6,
                                    process_cpu_ms=process / 1e6,
                                    thread_id=threading.get_ident(), detail=detail))

    def call(self, name, function, args=(), kwargs=None, detail=None, always=False):
        cpu, process = time.thread_time_ns(), time.process_time_ns()
        begin = time.monotonic_ns()
        try:
            return function(*args, **(kwargs or {}))
        finally:
            finish = time.monotonic_ns()
            self.record(name, begin, finish, time.thread_time_ns() - cpu,
                        time.process_time_ns() - process, detail, always)

    def gc_event(self, phase, info):
        key = (threading.get_ident(), info['generation'])
        if phase == 'start':
            self.gc_started[key] = (time.monotonic_ns(), time.thread_time_ns(), time.process_time_ns())
        elif key in self.gc_started:
            begin, cpu, process = self.gc_started.pop(key)
            self.record('gc', begin, time.monotonic_ns(), time.thread_time_ns() - cpu,
                        time.process_time_ns() - process, dict(info))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=int, default=120)
    args = parser.parse_args()
    assert 10 <= args.duration <= 180
    source = ROOT / 'fcc_app/tests/test_perf_monitor/board_check.py'
    spec = importlib.util.spec_from_file_location('original_board_fixture', source)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    trace = Trace()
    start = time.monotonic_ns()
    for _ in range(10000):
        trace.call('observer_noop', lambda: None)
    overhead_us = (time.monotonic_ns() - start) / 10000 / 1000
    original_serial = serial.Serial
    original_time = fixture.time
    replacements = []

    class ObservedSerial(original_serial):
        @property
        def role(self):
            return 'console' if 'usbmodem' in str(self.port) else 'data'

        @property
        def in_waiting(self):
            return trace.call(self.role + '.in_waiting', original_serial.in_waiting.fget, (self,))

        def read(self, size=1):
            return trace.call(self.role + '.read', original_serial.read, (self, size), detail=size)

        def write(self, data):
            detail = {'bytes': len(data)}
            if len(data) >= 3:
                detail['type'] = data[2]
            if len(data) == 15 and data[2] == 2:
                detail['sensor_ms'] = int.from_bytes(data[3:7], 'big')
            return trace.call(self.role + '.write', original_serial.write, (self, data),
                              detail=detail, always=True)

    def wrap(owner, attribute, label):
        original = getattr(owner, attribute)
        replacements.append((owner, attribute, original))
        def measured(*positional, **keywords):
            return trace.call(label, original, positional, keywords)
        setattr(owner, attribute, measured)

    serial.Serial = ObservedSerial
    fixture.time = SimpleNamespace(monotonic=time.monotonic,
        sleep=lambda seconds: trace.call('sleep', time.sleep, (seconds,), detail=seconds))
    wrap(fixture.PerfConsole, 'feed', 'console.parse')
    wrap(fixture.FrameParser, 'feed', 'data.parse')
    wrap(fixture, 'make_sample', 'sample.make')
    wrap(fixture.AsyncRecorder, '_put', 'recorder.enqueue')
    wrap(fixture.AsyncRecorder, 'check', 'recorder.check')
    wrap(SessionRecorder, '_row', 'recorder.csv_write')
    gc.callbacks.append(trace.gc_event)
    run_args = SimpleNamespace(output=args.output, duration=args.duration, smoke=False,
        data_port='/dev/cu.usbserial-A5069RR4', console_port='/dev/cu.usbmodem11203',
        workspace=Path('/Users/yuseungjae/zephyrproject'),
        west='/Users/yuseungjae/zephyrproject/.venv/bin/west',
        git='/Applications/Xcode.app/Contents/Developer/usr/bin/git',
        pc_rtt_p99_ms=20.0, pc_rtt_max_ms=100.0)
    try:
        result = fixture.run(run_args)
    finally:
        gc.callbacks.remove(trace.gc_event)
        serial.Serial = original_serial
        fixture.time = original_time
        for owner, attribute, original in reversed(replacements):
            setattr(owner, attribute, original)
        args.output.mkdir(parents=True, exist_ok=True)
        output = dict(kind='instrumented diagnostic run, not release qualification',
            fixture_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            main_thread_id=threading.get_ident(), python=sys.version,
            gil_switch_interval_s=sys.getswitchinterval(),
            observer_noop_mean_us=overhead_us, event_threshold_ms=2,
            notes=['Original fixture and acceptance files unchanged; wrappers add timing overhead.',
                   'Every serial write is retained; other calls retained when wall time >=2ms.',
                   'Wall minus thread CPU includes waiting and descheduling, not just OS scheduling.',
                   'Process CPU includes both fixture and recorder threads; not total machine CPU.',
                   'No trace file I/O during the measured run.'],
            stats=dict(trace.stats), events=sorted(trace.events, key=lambda event:event['start_s']))
        (args.output / 'host-stages.json').write_text(json.dumps(output, indent=2) + '\n')
    return result


if __name__ == '__main__':
    raise SystemExit(main())
