"""Reconcile immutable extended HIL captures without changing their verdicts."""
import csv
from dataclasses import asdict
import importlib.util
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from pc_sim.frame_parser import FrameParser
from pc_sim.protocol import decode_track_payload, decode_status_payload


def rows(path):
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


def audit(path):
    result = json.loads((path / 'results.json').read_text())
    snapshots = json.loads((path / 'performance.json').read_text())
    session = path / 'session'
    tx, rx = FrameParser(), FrameParser()
    reports, statuses, measurements = [], [], []
    wire_bytes = 0
    for row in rows(session / 'wire.csv'):
        raw = bytes.fromhex(row['hex'])
        if row['direction'] == 'tx':
            wire_bytes += len(raw)
            for frame in tx.feed(raw):
                if frame.frame_type == 2:
                    measurements.append(frame.payload.hex())
        else:
            assert row['direction'] == 'rx'
            for frame in rx.feed(raw):
                if frame.frame_type == 7:
                    reports.append(asdict(decode_track_payload(frame.payload)))
                elif frame.frame_type == 6:
                    statuses.append(decode_status_payload(frame.payload))
                else:
                    raise AssertionError(('unexpected RX', frame.frame_type))
    for actual, filename in ((reports, 'reports.csv'), (statuses, 'status.csv')):
        saved = rows(session / filename)
        assert len(actual) == len(saved), filename
        for decoded, record in zip(actual, saved):
            for key, value in decoded.items():
                assert value == float(record[key]), (filename, key)
    samples = rows(session / 'samples.csv')
    # Invalid zero-range injection is not a simulator sample.
    valid_payloads = [p for p in measurements if int(p[8:12], 16) != 0]
    assert valid_payloads == [bytes.fromhex(s['frame_hex'])[3:-2].hex() for s in samples]
    assert len(measurements) == result['valid_measurements_total'] + result['invalid_measurements']
    assert wire_bytes == result['sent_wire_bytes']
    assert len(reports) == result['track_reports']
    assert len(statuses) == result['status_responses']
    assert tx.crc_errors == tx.length_errors == rx.crc_errors == rx.length_errors == 0
    assert json.loads((session / 'metadata.json').read_text())['closed']
    # Reparse raw console, independent of the stored parsed JSON.
    spec = importlib.util.spec_from_file_location('extended_bench', ROOT / 'fcc_app/tests/test_perf_monitor/board_check.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    console = module.PerfConsole()
    console.feed((path / 'console.log').read_text())
    assert console.snapshots == snapshots
    expected_hash = json.loads((path / 'metadata.json').read_text())['acceptance_sha256']
    candidates = [path / 'acceptance-snapshot.py', ROOT / 'pc_sim/perf_acceptance.py',
                  Path(__file__).with_name('perf_acceptance-snapshot.py'),
                  ROOT / 'docs/test-results/review-2026-11-23/acceptance-before.py']
    source = next(p for p in candidates if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == expected_hash)
    spec = importlib.util.spec_from_file_location('captured_acceptance', source)
    acceptance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acceptance)
    reevaluated = acceptance.evaluate_acceptance(result, snapshots)
    assert all(result[key] == value for key, value in reevaluated.items())
    evidence = dict(audit_passed=True, original_passed=result['passed'],
                    samples=len(samples), reports=len(reports), statuses=len(statuses),
                    sent_wire_bytes=wire_bytes, summaries=len(snapshots),
                    wire_matches_csv=True, console_matches_json=True, verdict_reproduced=True)
    (path / 'audit.json').write_text(json.dumps(evidence, indent=2) + '\n')
    return evidence


if __name__ == '__main__':
    print(json.dumps(audit(Path(sys.argv[1])), indent=2))
