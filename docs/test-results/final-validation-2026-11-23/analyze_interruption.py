"""Explain the captured interruption without rewriting the original verdict."""
import csv
import hashlib
import json
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
from pc_sim.frame_parser import FrameParser, ParserState


def rows(name):
    with (OUT / 'perf-load/session' / f'{name}.csv').open() as stream:
        return list(csv.DictReader(stream))


result = json.loads((OUT / 'perf-load/results.json').read_text())
snapshots = json.loads((OUT / 'perf-load/performance.json').read_text())
samples, reports, statuses = rows('samples'), rows('reports'), rows('status')
index = max(range(1, len(samples)), key=lambda i:
            float(samples[i]['tx_monotonic_s']) - float(samples[i - 1]['tx_monotonic_s']))
previous, delayed, following = samples[index - 1:index + 2]
send_gap_ms = 1000 * (float(delayed['tx_monotonic_s']) - float(previous['tx_monotonic_s']))
sensor_jump_ms = int(following['timestamp_ms']) - int(delayed['timestamp_ms'])
input_reports = [r for r in reports if int(r['flags']) & 1]
resets = [r for r in input_reports if int(r['result']) == 4]
assert len(resets) == 1
reset = resets[0]
assert send_gap_ms > 1000 and sensor_jump_ms == 1140
assert int(reset['input_timestamp_ms']) == int(following['timestamp_ms'])
assert int(reset['state']) == 0 and int(reset['flags']) == 1
sequence = int(reset['report_sequence'])
transition = [r for r in reports if sequence - 2 <= int(r['report_sequence']) <= sequence]
assert [(int(r['result']), int(r['flags'])) for r in transition] == [(4, 0), (0, 3), (4, 1)]
assert all(all(int(v) == 0 for k, v in s.items() if k != 'rx_monotonic_s') for s in statuses)

receiver = FrameParser()
for row in rows('wire'):
    if row['direction'] == 'rx':
        receiver.feed(bytes.fromhex(row['hex']))
assert receiver.crc_errors == receiver.length_errors == 0
received_stamps = {int(r['input_timestamp_ms']) for r in input_reports}
missing_stamps = [int(s['timestamp_ms']) for s in samples if int(s['timestamp_ms']) not in received_stamps]
latency_names = ('rx_byte_wait', 'tx_queue_wait', 'tx_poll', 'parsed_to_tx_poll',
                 'queue_wait', 'processing', 'rx_to_submit')
sources = json.loads((OUT / 'source-sha256.json').read_text())
changed = [name for name, digest in sources.items()
           if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
assert not changed
analysis = {
    'original_verdict_preserved': True,
    'original_failure': result['failure'],
    'release_complete': False,
    'load_elapsed_s': result['load_elapsed_s'],
    'interpretation': 'documented timeout and sensor-gap RESET misclassified as a board rejection by the fixture',
    'board_defect_established_by_this_failure': False,
    'continuous_requested_load_verified': False,
    'host_send_gap_ms': send_gap_ms,
    'next_sensor_timestamp_jump_ms': sensor_jump_ms,
    'gap_measurements': [previous, delayed, following],
    'reset_restart_reset_reports': transition,
    'sent_measurements': len(samples),
    'input_reports': len(input_reports),
    'missing_input_timestamps_at_abort': missing_stamps,
    'status_responses': len(statuses),
    'all_observed_status_counters_zero': True,
    'rx_tail_incomplete': receiver.state != ParserState.WAIT_STX,
    'rx_tail_state': receiver.state.name,
    'rx_tail_type': receiver.frame_type,
    'rx_tail_payload_bytes': len(receiver.payload),
    'rx_tail_expected_payload_bytes': receiver.payload_length,
    'recording_complete': result['recording_complete'],
    'observed_latency_maxima_ms': {name: max(s[name]['max_ms'] for s in snapshots) for name in latency_names},
    'observed_cpu_window_max_percent': max(w['non_idle_percent'] for w in result['cpu_scheduler_windows']),
    'observed_stack_min_unused_bytes': {name: min(s['stack ' + name]['min_unused'] for s in snapshots)
                                        for name in ('rx', 'handler', 'tx', 'main')},
    'source_changes_during_validation': changed,
    'limits': [
        'Host write timestamps are not physical UART line timestamps.',
        'The exact source of the host pause was not recorded.',
        'Abort prevents final traffic reconciliation and a full-duration verdict.',
        'Snapshot maxima are observations, not WCET guarantees.',
        'Historical CRC failures are not explained by this event.',
    ],
}
(OUT / 'interruption-analysis.json').write_text(json.dumps(analysis, indent=2) + '\n')
print(json.dumps({k: v for k, v in analysis.items()
                  if k not in ('gap_measurements', 'reset_restart_reset_reports')}, indent=2))
