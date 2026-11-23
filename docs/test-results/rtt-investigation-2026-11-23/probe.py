"""Wrap the existing board test with bounded, in-memory host timing diagnostics.

No firmware, RTT boundary, acceptance threshold or recorder behavior is changed.
Only operations taking at least 5 ms retain individual events. Wall time includes
blocking and descheduling; thread CPU time does not identify their cause alone.
"""
import functools
import gc
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'fcc_app/tests/test_perf_monitor/board_check.py'
spec = importlib.util.spec_from_file_location('diagnosed_board_check', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from pc_sim.recording import SessionRecorder
clock = time.monotonic
cpu_clock = time.thread_time
events = []
summary = {}


def timed(name, function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        start_cpu = cpu_clock()
        start = clock()
        try:
            return function(*args, **kwargs)
        finally:
            end = clock()
            wall_ms = (end - start) * 1000
            cpu_ms = (cpu_clock() - start_cpu) * 1000
            key = name
            if args and hasattr(args[0], 'port'):
                key += ':' + str(args[0].port)
            if name == 'record_row':
                key += ':' + args[1]
            record = summary.setdefault(key, dict(count=0, max_wall_ms=0, over_5ms=0))
            record['count'] += 1
            record['max_wall_ms'] = max(record['max_wall_ms'], wall_ms)
            if wall_ms >= 5:
                record['over_5ms'] += 1
                if len(events) < 20000:
                    event = dict(operation=key, start_s=start, end_s=end,
                                 wall_ms=wall_ms, thread_cpu_ms=cpu_ms)
                    if name == 'sleep':
                        event['requested_ms'] = args[0] * 1000
                    events.append(event)
    return wrapped


original_serial = module.serial.Serial


class TimedSerial(original_serial):
    read = timed('serial_read', original_serial.read)
    write = timed('serial_write', original_serial.write)
    in_waiting = property(timed('serial_in_waiting', original_serial.in_waiting.fget))


module.serial.Serial = TimedSerial
SessionRecorder._row = timed('record_row', SessionRecorder._row)
module.PerfConsole.feed = timed('console_parse', module.PerfConsole.feed)
module.make_sample = timed('make_sample', module.make_sample)
original_sleep = time.sleep
time.sleep = timed('sleep', original_sleep)
gc_started = {}


def gc_event(phase, info):
    generation = info['generation']
    if phase == 'start':
        gc_started[generation] = (clock(), cpu_clock())
    elif generation in gc_started:
        start, start_cpu = gc_started.pop(generation)
        end = clock()
        events.append(dict(operation='gc', generation=generation, start_s=start,
                           end_s=end, wall_ms=(end-start)*1000,
                           thread_cpu_ms=(cpu_clock()-start_cpu)*1000))


gc.callbacks.append(gc_event)
output = Path(sys.argv[sys.argv.index('--output') + 1])
try:
    module.main()
finally:
    time.sleep = original_sleep
    gc.callbacks.remove(gc_event)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'host-timing.json').write_text(json.dumps(
        dict(threshold_ms=5, event_cap=20000, summary=summary, events=events), indent=2) + '\n')
