"""Reassess one proven fixture misclassification; leave the raw capture intact."""
from copy import deepcopy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
CAPTURE = OUT.parent / 'final-validation-2026-11-23/perf-load'


def snapshot_module(name, source, filename):
    path = OUT / filename
    if not path.exists():
        path.write_bytes(source.read_bytes())
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = snapshot_module('captured_runner_v3', ROOT / 'fcc_app/tests/test_perf_monitor/board_check.py',
                         'runner-snapshot.py')
acceptance = snapshot_module('captured_acceptance_v3', ROOT / 'pc_sim/perf_acceptance.py',
                             'acceptance-snapshot.py')
original_bytes = (CAPTURE / 'results.json').read_bytes()
original = json.loads(original_bytes)
with (CAPTURE / 'session/samples.csv').open() as stream:
    samples = list(csv.DictReader(stream))
with (CAPTURE / 'session/reports.csv').open() as stream:
    reports = list(csv.DictReader(stream))
snapshots = json.loads((CAPTURE / 'performance.json').read_text())
config = (CAPTURE / 'build_perf.config').read_text()
timeout = int(next(line.split('=')[1] for line in config.splitlines()
                   if line.startswith('CONFIG_RADAR_MEASUREMENT_TIMEOUT_MS=')))
interruption = None
for previous, current in zip(samples, samples[1:]):
    try:
        runner.check_input_continuity(int(previous['timestamp_ms']), float(previous['tx_monotonic_s']),
                                     int(current['timestamp_ms']), float(current['tx_monotonic_s']), timeout)
    except runner.HostInputInterrupted as error:
        interruption = error.details
        break
assert interruption and interruption['sensor_ms'] == 1537200

# Prove this exact failed response is the documented reset, not an arbitrary rejection.
reset = reports[-1]
assert (int(reset['report_sequence']), int(reset['input_timestamp_ms']), int(reset['state']),
        int(reset['result']), int(reset['flags'])) == (75801, 1538340, 0, 4, 1)
assert [(int(r['result']), int(r['flags'])) for r in reports[-3:]] == [(4, 0), (0, 3), (4, 1)]
assert 1538340 - interruption['sensor_ms'] > runner.MAX_SENSOR_INTERVAL_MS
known_check = {'name': 'Normal stationary measurement rejected', 'passed': False,
               'category': 'board_internal'}
assert original['checks'].count(known_check) == 1
assert original['failure'] == "AssertionError('Normal stationary measurement rejected')"

result = deepcopy(original)
result['checks'].remove(known_check)
result['failure'] = None
result['host_input_interruption'] = interruption
result['run_completed'] = False
verdict = acceptance.evaluate_acceptance(result, snapshots)
assert verdict['board_qualification']['status'] == 'inconclusive'
assert not verdict['passed'] and not verdict['requested_profile_passed']
document = {
    'kind': 'offline reassessment, not a new board run',
    'source_result': str((CAPTURE / 'results.json').relative_to(ROOT)),
    'source_result_sha256': hashlib.sha256(original_bytes).hexdigest(),
    'original_acceptance_revision': original['acceptance_revision'],
    'original_board_qualification': original['board_qualification']['status'],
    'guard_replay': interruption,
    'correction': 'Remove only the independently proven RESET misclassification; preserve all other checks and observations.',
    'boundary': 'New runner would stop earlier. This reassessment retains the actual old capture and does not invent the earlier stop or missing replies.',
    'snapshots_sha256': {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest()
                        for name in ('runner-snapshot.py', 'acceptance-snapshot.py')},
    **verdict,
}
(OUT / 'reassessment.json').write_text(json.dumps(document, indent=2) + '\n')
assert (CAPTURE / 'results.json').read_bytes() == original_bytes
print(json.dumps({key: document[key] for key in ('kind', 'acceptance_revision', 'guard_replay',
                 'original_board_qualification', 'board_qualification', 'requested_profile_passed', 'passed')}, indent=2))
