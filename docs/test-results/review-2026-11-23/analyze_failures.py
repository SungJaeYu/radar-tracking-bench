"""Read immutable captures; write only a new offline review (never access UART).

Independent frame CRC uses binascii.crc_hqx, not the production FrameParser.
Host timing correlation is observation, never attribution of physical fault cause.
"""
from collections import Counter, defaultdict, deque
from dataclasses import asdict
import binascii
import csv
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'docs/test-results'
sys.path.insert(0, str(ROOT))
from pc_sim.protocol import decode_status_payload, decode_track_payload

RUNS = [
    'release-v1.1.0-2026-11-23/perf-load',
    'rtt-investigation-2026-11-23/run-1',
    'rtt-investigation-2026-11-23/threaded-smoke',
    'rtt-investigation-2026-11-23/threaded-probe',
    'extended-perf-2026-11-23/smoke-1',
    'extended-perf-2026-11-23/load-30min',
    'extended-perf-2026-11-23/smoke-2',
    'irq-safe-perf-2026-11-23/run-300s',
]


def read_session(run, name):
    path = run / 'session' / name
    if path.exists():
        return path.read_text()
    with tarfile.open(run.parent / 'perf-load-session.tar.gz') as archive:
        return archive.extractfile('perf-load/session/' + name).read().decode()


def rows(run, name):
    return list(csv.DictReader(io.StringIO(read_session(run, name))))


class IndependentFrames:
    def __init__(self):
        self.pending = bytearray()
        self.bytes = self.crc_errors = self.length_errors = self.nonframe_bytes = 0
        self.types = Counter()

    def feed(self, raw):
        self.bytes += len(raw)
        self.pending.extend(raw)
        frames = []
        while self.pending:
            if self.pending[0] != 0x7e:
                self.nonframe_bytes += 1
                del self.pending[0]
                continue
            if len(self.pending) < 2:
                break
            size = self.pending[1]
            if not 1 <= size <= 32:
                self.length_errors += 1
                del self.pending[:2]
                continue
            if len(self.pending) < size + 5:
                break
            frame = bytes(self.pending[:size + 5])
            del self.pending[:size + 5]
            if binascii.crc_hqx(frame[1:-2], 0xffff) != int.from_bytes(frame[-2:], 'big'):
                self.crc_errors += 1
                continue
            self.types[frame[2]] += 1
            frames.append((frame[2], frame[3:-2], frame))
        return frames

    def summary(self):
        return dict(bytes=self.bytes, frame_types=dict(self.types), crc_errors=self.crc_errors,
                    length_errors=self.length_errors, nonframe_bytes=self.nonframe_bytes,
                    trailing_partial_bytes=len(self.pending))


def stats(values):
    values = sorted(values)
    return dict(count=len(values), p99=values[max(0, math.ceil(len(values)*.99)-1)] if values else None,
                max=values[-1] if values else None)


def audit(relative):
    run = BASE / relative
    result = json.loads((run / 'results.json').read_text())
    meta = json.loads((run / 'metadata.json').read_text())
    samples = rows(run, 'samples.csv')
    saved_reports, saved_status = rows(run, 'reports.csv'), rows(run, 'status.csv')
    wire = rows(run, 'wire.csv')
    parsers = {'tx': IndependentFrames(), 'rx': IndependentFrames()}
    reports, status, measurement_frames = [], [], []
    for row in wire:
        direction, now = row['direction'], float(row['monotonic_s'])
        for kind, payload, frame in parsers[direction].feed(bytes.fromhex(row['hex'])):
            if direction == 'tx' and kind == 2 and int.from_bytes(payload[4:6], 'big'):
                measurement_frames.append(dict(timestamp_ms=int.from_bytes(payload[:4], 'big'),
                                               tx_monotonic_s=now, frame_hex=frame.hex()))
            elif direction == 'rx' and kind in (6, 7):
                decoded = asdict(decode_track_payload(payload)) if kind == 7 else decode_status_payload(payload)
                decoded['rx_monotonic_s'] = now
                (reports if kind == 7 else status).append(decoded)
    assert len(measurement_frames) == len(samples)
    assert all(all(str(s[k]) == str(f[k]) if k == 'frame_hex' else float(s[k]) == f[k]
                       for k in f) for s, f in zip(samples, measurement_frames))
    for decoded, saved in ((reports, saved_reports), (status, saved_status)):
        assert len(decoded) == len(saved)
        assert all(all(float(s[k]) == v for k, v in d.items()) for d, s in zip(decoded, saved))
    assert all(p.crc_errors == p.length_errors == p.nonframe_bytes == len(p.pending) == 0 for p in parsers.values())
    queues = defaultdict(deque)
    for index, sample in enumerate(measurement_frames):
        queues[sample['timestamp_ms']].append((index, sample))
    matches = []
    for report in reports:
        if report['flags'] & 1:
            index, sample = queues[report['input_timestamp_ms']].popleft()
            matches.append(dict(index=index, sensor_ms=sample['timestamp_ms'],
                                tx_s=sample['tx_monotonic_s'], rx_s=report['rx_monotonic_s'],
                                rtt_ms=(report['rx_monotonic_s']-sample['tx_monotonic_s'])*1000))
    unmatched = [dict(index=i, **s) for q in queues.values() for i, s in q]
    load_n = result.get('load_measurements') or len(measurement_frames)
    load = measurement_frames[:load_n]
    load_matches = [m for m in matches if m['index'] < load_n]
    gaps = [dict(start_s=a['tx_monotonic_s'], end_s=b['tx_monotonic_s'],
                 gap_ms=(b['tx_monotonic_s']-a['tx_monotonic_s'])*1000)
            for a, b in zip(load, load[1:])]
    tails = []
    for match in load_matches:
        if match['rtt_ms'] <= 100:
            continue
        i = match['index']
        item = dict(match)
        next_tx = load[i+1]['tx_monotonic_s'] if i+1 < len(load) else None
        item['next_tx_gap_ms'] = (next_tx-match['tx_s'])*1000 if next_tx else None
        item['rx_after_next_tx_ms'] = (match['rx_s']-next_tx)*1000 if next_tx else None
        overlap = [g for g in gaps if g['start_s'] < match['rx_s'] and g['end_s'] > match['tx_s']]
        item['max_overlapping_send_gap_ms'] = max((g['gap_ms'] for g in overlap), default=0)
        tails.append(item)
    crc_window = None
    for index, event in enumerate(status):
        if event['crc_errors']:
            prev = status[index-1] if index else None
            left, right = prev['rx_monotonic_s'] if prev else load[0]['tx_monotonic_s'], event['rx_monotonic_s']
            interval_gaps = [g['gap_ms'] for g in gaps if g['start_s'] < right and g['end_s'] > left]
            crc_window = dict(last_zero_status=prev, first_nonzero_status=event,
                              host_observation_interval_s=right-left,
                              first_nonzero_status_after_first_load_tx_s=right-load[0]['tx_monotonic_s'],
                              send_gaps_overlapping_status_observation_interval_ms=stats(interval_gaps),
                              unmatched_samples=[dict(**s, seconds_before_first_error_status=right-s['tx_monotonic_s'],
                                  later_inputs_already_matched=sum(m['index'] > s['index'] for m in matches)) for s in unmatched],
                              attribution_limit='STATUS timestamps bound host observations, not the physical fault instant; later inputs were answered while these replies remained absent, but CRC-to-input mapping is unmeasured.')
            break
    performance = json.loads((run / 'performance.json').read_text())
    if crc_window:
        crc_window['last_summary_measurement_count'] = performance[-1]['header']['measurements']
        crc_window['first_unmatched_index_equals_last_summary_count'] = min(s['index'] for s in unmatched) == performance[-1]['header']['measurements']
        crc_window['summary_correlation_limit'] = 'Count adjacency only; console has no host capture timestamps and neither UART-error registers nor physical waveforms were captured. This does not prove a summary-triggered fault.'
    acceptance_hash = meta.get('acceptance_sha256')
    candidates = [ROOT / 'pc_sim/perf_acceptance.py',
                  BASE / 'extended-perf-2026-11-23/perf_acceptance-snapshot.py',
                  BASE / 'review-2026-11-23/acceptance-before.py']
    selected = next((p for p in candidates if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==acceptance_hash), None)
    replay = dict(recorded_sha256=acceptance_hash, matching_source=str(selected.relative_to(ROOT)) if selected else None)
    if selected:
        spec = importlib.util.spec_from_file_location('captured_acceptance', selected)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        reevaluated = module.evaluate_acceptance(result, performance)
        replay['differing_fields'] = [key for key, value in reevaluated.items() if result.get(key) != value]
        replay['original_verdict_reproduced'] = not replay['differing_fields']
    all_rtts = stats([m['rtt_ms'] for m in load_matches])
    if result.get('pc_latency_ms'):
        assert all(result['pc_latency_ms'][k] == all_rtts[k] for k in all_rtts)
    return dict(run=relative, raw_validation_passed=True, independent_crc_method='binascii.crc_hqx(init=0xffff)',
                wire={k:p.summary() for k,p in parsers.items()}, samples=len(samples), reports=len(reports), statuses=len(status),
                sample_and_decoded_csv_matches_raw=True, load_samples=load_n,
                rtt_ms=all_rtts, rtt_over_100ms=tails,
                send_gaps_ms=stats([g['gap_ms'] for g in gaps]),
                crc_window=crc_window,
                unmatched_samples=unmatched,
                session_metadata_closed=json.loads(read_session(run,'metadata.json')).get('closed'),
                result_recording_complete=result.get('recording_complete'), recording=result.get('recording'),
                historical_passed=result.get('passed'), historical_verdicts=result.get('verdicts'),
                original_acceptance_replay=replay,
                input_sha256={name:hashlib.sha256(read_session(run,name).encode()).hexdigest() for name in
                              ('samples.csv','reports.csv','status.csv','wire.csv','metadata.json')},
                final_two_performance_snapshots=performance[-2:])


def main():
    evidence = dict(scope='Offline review only; no new board run, no mutation of prior evidence.',
                    timing_limit='PC times include host scheduling, writes, device/transport, reads. Correlation does not identify an exclusive cause.',
                    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    protocol_decoder_sha256=hashlib.sha256((ROOT/'pc_sim/protocol.py').read_bytes()).hexdigest(),
                    session_text_hash_scope='UTF-8 text after Python universal-newline normalization; hashes validate this replay input, not byte-identical archive membership.',
                    runs=[audit(run) for run in RUNS])
    destination = Path(__file__).with_name('failure-analysis.json')
    destination.write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps(dict(output=str(destination), runs=[dict(run=r['run'], rtt=r['rtt_ms'],
          tails=len(r['rtt_over_100ms']), raw_validation_passed=r['raw_validation_passed'],
          crc_observed=r['crc_window'] is not None, replay=r['original_acceptance_replay'])
          for r in evidence['runs']]), indent=2))


if __name__ == '__main__':
    main()
