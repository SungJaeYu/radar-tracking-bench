"""Audit recorded STM32 wire data and compare paired filter runs; no hardware I/O."""
import argparse
from collections import Counter
import csv
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from pc_sim.storage.prepared_storage import load_input
from pc_sim.transport.frame_parser import FrameParser, ParserState
from pc_sim.transport.protocol import decode_track_payload, FRAME_TYPE_TRACK_REPORT


def rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def stats(values):
    return {'count': len(values), 'rmse_m': math.sqrt(sum(v*v for v in values)/len(values)),
            'max_m': max(values)} if values else {'count': 0, 'rmse_m': None, 'max_m': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    base, out = args.recording, args.output
    manifest = json.loads((base/'manifest.json').read_text())
    assert manifest['complete'] and manifest['restored']
    assert len(manifest['runs']) == 4
    result = {'source_commit': manifest['source_commit'], 'runs': [], 'paired': {},
              'restored_normal_kf': manifest['restored'], 'restore_status': manifest['restore_status']}
    series = []
    masks = {}
    for item in manifest['runs']:
        estimator, case = item['estimator'], item['case']
        session = base/item['session']
        prepared = load_input(base/'inputs'/case)
        copy = load_input(session/'input')
        assert [s.frame for s in prepared.samples] == [s.frame for s in copy.samples]
        assert (session/'input/samples.jsonl').read_bytes() == (base/'inputs'/case/'samples.jsonl').read_bytes()
        sample_rows, reports = rows(session/'samples.csv'), rows(session/'reports.csv')
        assert [r['frame_hex'] for r in sample_rows] == [s.frame.hex() for s in prepared.samples]
        assert [int(r['timestamp_ms']) for r in sample_rows] == [s.timestamp_ms for s in prepared.samples]
        # Independently decode captured raw RX and compare it with reports.csv.
        rx = FrameParser()
        decoded, transmitted = [], []
        for row in rows(session/'wire.csv'):
            raw = bytes.fromhex(row['hex'])
            if row['direction'] == 'tx':
                if len(raw) == 15 and raw[2] == 2:
                    transmitted.append(raw)
            else:
                for frame in rx.feed(raw):
                    if frame.frame_type == FRAME_TYPE_TRACK_REPORT:
                        decoded.append(asdict(decode_track_payload(frame.payload)))
        assert not rx.crc_errors and not rx.length_errors and rx.state == ParserState.WAIT_STX
        assert transmitted == [s.frame for s in prepared.samples]
        assert len(decoded) == len(reports) == 757
        for actual, stored in zip(decoded, reports):
            assert all(float(stored[key]) == value for key, value in actual.items())
        input_reports = {int(r['input_timestamp_ms']): r for r in reports if int(r['flags']) & 1}
        assert len(input_reports) == len(prepared.samples) == 755
        assert Counter(int(r['input_timestamp_ms']) for r in reports if int(r['flags']) & 1) == Counter(s.timestamp_ms for s in prepared.samples)
        turn_start = prepared.metadata['segments'][0]['duration_s']
        turn_end = turn_start + prepared.metadata['segments'][1]['duration_s']
        groups = {key: [] for key in ['all', 'straight_before', 'turn', 'straight_after']}
        measured, all_valid, errors_by_time = [], [], {}
        start_ms = None
        for sample in prepared.samples:
            report = input_reports[sample.timestamp_ms]
            t = sample.timestamp_ms/1000
            angle = sample.wire_azimuth_sc*math.pi/2**31
            mx, my = sample.wire_range_m*math.sin(angle), sample.wire_range_m*math.cos(angle)
            measurement_error = math.hypot(mx-sample.truth_x_m, my-sample.truth_y_m)
            valid = bool(int(report['flags']) & 2) and int(report['estimate_timestamp_ms']) == sample.timestamp_ms
            if valid and (int(report['result']) == 0 or start_ms is None):
                start_ms = sample.timestamp_ms
            eligible = valid and sample.timestamp_ms-start_ms >= 2000
            radius, azimuth = float(report['range_m']), float(report['azimuth_rad'])
            ex, ey = radius*math.sin(azimuth), radius*math.cos(azimuth)
            error = math.hypot(ex-sample.truth_x_m, ey-sample.truth_y_m) if valid else None
            phase = 'straight_before' if t < turn_start else 'turn' if t < turn_end else 'straight_after'
            row = dict(estimator=estimator, case=case, sensor_s=t, phase=phase,
                       truth_x_m=sample.truth_x_m, truth_y_m=sample.truth_y_m,
                       measurement_x_m=mx, measurement_y_m=my,
                       estimate_x_m=ex if valid else None, estimate_y_m=ey if valid else None,
                       measurement_error_m=measurement_error, estimate_error_m=error,
                       valid=int(valid), eligible=int(eligible), state=int(report['state']), result=int(report['result']))
            series.append(row)
            if valid:
                all_valid.append(error)
            if eligible:
                groups['all'].append(error)
                groups[phase].append(error)
                measured.append(measurement_error)
                errors_by_time[sample.timestamp_ms] = error
        independent = {key: stats(values) for key, values in groups.items()}
        for phase, values in independent.items():
            original = item['result']['position'][phase]
            assert values['count'] == original['count']
            assert math.isclose(values['rmse_m'], original['rmse_m'], rel_tol=1e-10)
        masks[estimator, case] = errors_by_time
        perf = json.loads((base/estimator/case/'perf.json').read_text())
        assert perf['boots'] == 1 and not perf['faults'] and not perf['incomplete_summaries']
        last = perf['snapshots'][-1]
        assert last['header']['measurements'] == 755
        faults = {key: last['header'][key] for key in ['without_submit','submit_failed','invalid_time','rx_capture_lost']}
        assert not any(faults.values())
        for queue in ['queue rx','queue tx']:
            assert last[queue]['rejected'] == 0
        assert last['tx']['encode_failed'] == 0
        stack = {name: min(s['stack '+name]['min_unused'] for s in perf['snapshots']) for name in ['rx','handler','tx','main']}
        gaps = [(float(b['tx_monotonic_s'])-float(a['tx_monotonic_s']))*1000 for a,b in zip(sample_rows,sample_rows[1:])]
        summary = dict(estimator=estimator,case=case,position=independent,
                       all_valid_position=stats(all_valid),measurement_position=stats(measured),
                       sent=755,reports=757,wire_audit=True,input_sha256=item['input_samples_sha256'],
                       gates=item['result']['gate_rejected'],lost=item['result']['lost_transitions'],
                       starts=item['result']['track_starts'],eligible_count=len(measured),
                       predict=last['estimator_predict'],correct=last['estimator_correct'],stack_min_unused_bytes=stack,
                       processing=last['processing'],rx_to_submit=last['rx_to_submit'],
                       pc_roundtrip_ms=item['result']['pc_roundtrip_ms'],status_delta=item['result']['status_delta'],
                       send_gap_ms={'min':min(gaps),'mean':sum(gaps)/len(gaps),'max':max(gaps)})
        assert not any(summary['status_delta'].values())
        result['runs'].append(summary)
    for case in ['baseline','noisy']:
        kf, ekf = masks['kf',case], masks['ekf',case]
        common = sorted(kf.keys() & ekf.keys())
        result['paired'][case] = {'common_count':len(common), 'kf':stats([kf[t] for t in common]),
                                  'ekf':stats([ekf[t] for t in common])}
    out.mkdir(parents=True,exist_ok=True)
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    with (out/'series.csv').open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=series[0].keys(),lineterminator='\n');writer.writeheader();writer.writerows(series)
    flattened=[]
    for run in result['runs']:
        flattened.append({**{key:run[key] for key in ['estimator','case','sent','reports','gates','lost','starts','eligible_count']},
                          **{phase+'_rmse_m':run['position'][phase]['rmse_m'] for phase in run['position']},
                          'measurement_rmse_m':run['measurement_position']['rmse_m'],
                          'predict_mean_us':run['predict']['mean_ns']/1000,
                          'predict_max_us':run['predict']['max_ns']/1000,
                          'correct_mean_us':run['correct']['mean_ns']/1000,
                          'correct_max_us':run['correct']['max_ns']/1000,
                          'handler_min_unused_bytes':run['stack_min_unused_bytes']['handler']})
    with (out/'summary.csv').open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=flattened[0].keys(),lineterminator='\n');writer.writeheader();writer.writerows(flattened)
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
