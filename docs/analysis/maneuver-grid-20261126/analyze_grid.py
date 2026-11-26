#!/usr/bin/env python3
"""Analyze saved board captures without emitting samples, UART chunks, or log lines."""
import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from itertools import product

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pc_sim.storage.prepared_storage import load_input
from pc_sim.transport.frame_parser import FrameParser, ParserState
from pc_sim.transport.protocol import (
    FRAME_TYPE_RESET, FRAME_TYPE_STATUS_REPORT, FRAME_TYPE_STATUS_REQUEST,
    FRAME_TYPE_TRACK_REPORT, STATUS_FIELDS, TrackReportResult,
    TrackState, build_init_frame, decode_status_payload, decode_track_payload, encode_frame,
)

VARIANTS = ('kf', 'cv_ekf', 'ct_ekf')
STAGES = ('predict', 'correct')
WARMUP_MS = 2000
TIMING_HZ = 216_000_000
PERF_SUMMARY = re.compile(r'PERF summary: uptime_ms=(\d+) measurements=(\d+)')
PERF_STAGE = re.compile(
    r'PERF estimator_(predict|correct): n=(\d+) (?:min_ns=(\d+) mean_ns=(\d+) max_ns=(\d+)|status=no_samples)'
)


class InvalidCapture(Exception):
    """Only safe rule identifiers may be exposed during capture validation."""


def require(condition, rule):
    if not condition:
        raise InvalidCapture(rule)


def csv_rows(path, name):
    with (path / f'{name}.csv').open(newline='', encoding='utf-8') as stream:
        yield from csv.DictReader(stream)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def polar_error(radius, angle, truth_x, truth_y):
    return math.hypot(radius * math.sin(angle) - truth_x, radius * math.cos(angle) - truth_y)


def compare(measured, errors, cutoff_ms):
    common = set(stamp for stamp in measured if stamp >= cutoff_ms)
    for estimates in errors.values():
        common.intersection_update(estimates)
    stamps = sorted(common)
    return stamps, {
        name: [series[stamp] for stamp in stamps]
        for name, series in {'measured': measured, **errors}.items()
    }


def percentile(sorted_values, fraction):
    return sorted_values[math.ceil(len(sorted_values) * fraction) - 1] if sorted_values else None


def position_stats(values):
    values = sorted(values)
    return dict(rmse_m=math.sqrt(math.fsum(x*x for x in values) / len(values)) if values else None,
                p95_m=percentile(values, .95))


def rtt_stats(values):
    values = sorted(values)
    return dict(samples=len(values), p50_ms=percentile(values, .50), p95_ms=percentile(values, .95),
                p99_ms=percentile(values, .99), max_ms=percentile(values, 1))


@dataclass
class PerfSnapshot:
    uptime_ms: int
    measurements: int
    stages: dict


def perf_snapshots(console):
    current = None
    with console.open(encoding='utf-8', errors='replace') as stream:
        for line in stream:
            header = PERF_SUMMARY.search(line)
            if header:
                current = PerfSnapshot(*map(int, header.groups()), {})
            stage = PERF_STAGE.search(line)
            if stage and current is not None:
                name, n, _, mean, maximum = stage.groups()
                current.stages[name] = (int(n), int(mean or 0), int(maximum or 0))
                if current.stages.keys() == set(STAGES):
                    yield current
                    current = None


def perf_delta(start, end, measurements, predict, correct):
    if start.uptime_ms >= end.uptime_ms or end.measurements - start.measurements != measurements:
        return None
    result = {}
    for name, expected in zip(STAGES, (predict, correct)):
        n0, mean0, max0 = start.stages[name]
        n1, mean1, max1 = end.stages[name]
        diff = n1 * mean1 - n0 * mean0
        if n1 - n0 != expected or expected < 0 or max1 < max0:
            return None
        # Firmware truncates mean cycles, then truncates their conversion to ns.
        per_snapshot_sample_error_ns = 1 + 1e9 / TIMING_HZ
        low = diff - n0 * per_snapshot_sample_error_ns
        high = diff + n1 * per_snapshot_sample_error_ns
        if expected and high <= 0:
            return None
        result[name] = dict(
            samples=expected, mean_us_approx=max(0, diff) / expected / 1000 if expected else None,
            mean_us_rounding_bound=max(abs(max(0, diff) - low), abs(high - max(0, diff)))
            / expected / 1000 if expected else None,
        )
    return result


def verify_replay(session, prepared, archived_hash):
    replay = session / 'input'
    require(sha256(replay / 'samples.jsonl') == archived_hash, 'session input hash mismatch')
    require(load_input(replay) == prepared, 'session input metadata or samples mismatch')
    rows = list(csv_rows(session, 'samples'))
    require(len(rows) == len(prepared.samples), 'session TX sample count')
    sent = {}
    for row, sample in zip(rows, prepared.samples):
        stamp = sample.timestamp_ms
        require(int(row['timestamp_ms']) == stamp and bytes.fromhex(row['frame_hex']) == sample.frame,
                'session TX frame mismatch')
        require(float(row['truth_range_m']) == sample.truth_range_m
                and float(row['truth_azimuth_rad']) == sample.truth_azimuth_rad
                and float(row['measured_range_m']) == sample.wire_range_m
                and float(row['measured_azimuth_rad']) == sample.wire_azimuth_sc * math.pi / 2**31,
                'session sample columns mismatch')
        sent[stamp] = float(row['tx_monotonic_s'])
    expected_tx = [(build_init_frame(), None), (encode_frame(FRAME_TYPE_STATUS_REQUEST, b'\0'), None)]
    expected_tx.extend((sample.frame, sent[sample.timestamp_ms]) for sample in prepared.samples)
    expected_tx.extend(((encode_frame(FRAME_TYPE_STATUS_REQUEST, b'\0'), None),
                        (encode_frame(FRAME_TYPE_RESET, b'\0'), None)))
    return sent, expected_tx


def decode_wire(session, expected_tx):
    parser = FrameParser()
    reports, statuses = [], []
    tx_index = 0
    for row in csv_rows(session, 'wire'):
        raw = bytes.fromhex(row['hex'])
        time = float(row['monotonic_s'])
        if row['direction'] == 'tx':
            require(tx_index < len(expected_tx), 'extra captured TX frame')
            frame, expected_time = expected_tx[tx_index]
            require(frame == raw and (expected_time is None or time == expected_time), 'UART TX mismatch')
            tx_index += 1
        else:
            require(row['direction'] == 'rx', 'unknown wire direction')
            for frame in parser.feed(raw):
                if frame.frame_type == FRAME_TYPE_TRACK_REPORT:
                    reports.append((decode_track_payload(frame.payload), time))
                elif frame.frame_type == FRAME_TYPE_STATUS_REPORT:
                    statuses.append((decode_status_payload(frame.payload), time))
                else:
                    raise InvalidCapture('unexpected decoded RX type')
    require(tx_index == len(expected_tx), 'missing captured TX frames')
    require(not parser.crc_errors and not parser.length_errors and parser.state == ParserState.WAIT_STX,
            'captured RX frame integrity')
    return reports, statuses


def verify_decoded_csv(session, reports, statuses):
    report_rows = list(csv_rows(session, 'reports'))
    status_rows = list(csv_rows(session, 'status'))
    require(len(report_rows) == len(reports) and len(status_rows) == len(statuses) == 2,
            'decoded RX row count')
    for (report, time), row in zip(reports, report_rows):
        require(time == float(row['rx_monotonic_s']) and
                all((float(row[name]) if isinstance(value, float) else int(row[name])) == value
                    for name, value in vars(report).items()), 'decoded TRACK row mismatch')
    keys = {key for key, *_ in STATUS_FIELDS}
    for (status, time), row in zip(statuses, status_rows):
        require(time == float(row['rx_monotonic_s']) and status.keys() == keys
                and all(int(row[key]) == status[key] for key in keys), 'decoded STATUS row mismatch')
    require(statuses[0][0] == statuses[1][0], 'board STATUS counter change')


def summarize_tracking(reports, sent, samples, cutoff_ms):
    counts = Counter()
    valid, responses, rtt = {}, set(), []
    previous = None
    for report, time in reports:
        code, state, stamp = report.result, report.state, report.input_timestamp_ms
        if previous is not None:
            require((report.report_sequence - previous.report_sequence) % 2**32 == 1,
                    'TRACK sequence discontinuity')
        counts['lost_transitions'] += state == TrackState.LOST and (previous is None or previous.state != state)
        previous = report
        counts['track_starts'] += code == TrackReportResult.STARTED
        counts['corrected'] += code == TrackReportResult.UPDATED
        counts['gate_rejected'] += code == TrackReportResult.GATE_REJECTED
        counts['time_rejected'] += code == TrackReportResult.TIME_REJECTED
        if report.input_present:
            require(stamp in sent and stamp not in responses, 'unexpected or duplicate TRACK input stamp')
            responses.add(stamp)
            delay = (time - sent[stamp]) * 1000
            require(math.isfinite(delay) and delay >= 0, 'invalid PC round trip')
            rtt.append(delay)
        else:
            require(code == TrackReportResult.RESET and state == TrackState.EMPTY, 'unexpected unsolicited TRACK')
            counts['reset_reports'] += 1
        if report.estimate_valid:
            estimate_stamp = report.estimate_timestamp_ms
            require(estimate_stamp == stamp and estimate_stamp in samples and estimate_stamp not in valid,
                    'unmatched or duplicate valid estimate stamp')
            if estimate_stamp >= cutoff_ms:
                sample = samples[estimate_stamp]
                valid[estimate_stamp] = polar_error(report.range_m, report.azimuth_rad,
                                                    sample.truth_x_m, sample.truth_y_m)
    require(responses == sent.keys() and counts['reset_reports'] == 2 and not counts['time_rejected'],
            'missing TRACK input or RESET, or time rejection')
    return dict(counts), valid, rtt


def analyze_run(root, row, prepared, cutoff_ms):
    require(row['session_complete'] and not row['console_errors'], 'incomplete session')
    path = root / row['session']
    metadata = read_json(path / 'metadata.json')
    require(metadata['mode'] == 'board' and metadata['complete'] and metadata['closed']
            and metadata['settings'] == prepared.metadata['settings'], 'session metadata mismatch')
    sent, wire_tx = verify_replay(path, prepared, row['input_sha256'])
    reports, statuses = decode_wire(path, wire_tx)
    verify_decoded_csv(path, reports, statuses)
    require(reports[0][0].result == reports[-1][0].result == TrackReportResult.RESET,
            'missing TRACK RESET boundaries')
    samples = {sample.timestamp_ms: sample for sample in prepared.samples}
    counts, valid, rtt = summarize_tracking(reports, sent, samples, cutoff_ms)
    transport = row['transport']
    require(all(transport[key] == len(samples)
                for key in ('sent_samples', 'input_reports', 'unique_input_reports'))
            and all(transport[key] == 0 for key in ('duplicate_input_reports', 'missing_input_reports',
                                                    'pc_crc_errors', 'pc_length_errors'))
            and transport['status_reports'] == transport['reset_reports'] == 2, 'manifest transport mismatch')
    windows = list(perf_snapshots(path.parent.parent / 'console.log'))
    require(all(a.uptime_ms < b.uptime_ms and a.measurements <= b.measurements
                for a, b in zip(windows, windows[1:])), 'nonmonotonic PERF snapshots')
    return counts, valid, rtt, windows


def provenance(root, manifest):
    verification = {}
    for variant, build in manifest['variants'].items():
        result = {}
        for kind in ('config', 'hex'):
            result[kind] = sha256(root / f'{variant}.{kind}') == build[f'{kind}_sha256']
        require(all(result.values()), 'archived build hash mismatch')
        elf = root.parents[1] / build['directory'] / 'zephyr' / 'zephyr.elf'
        result['local_elf_matches'] = sha256(elf) == build['elf_sha256'] if elf.is_file() else None
        verification[variant] = {**build, 'archive_hash_matches': result}
    return dict(
        manifest_sha256=sha256(root / 'manifest.json'), source_commit=manifest['source_commit'],
        board=manifest['board'], baud=manifest['baud'], seed=manifest['seed'], dt_s=manifest['dt_s'],
        noise_profiles=manifest['noise_profiles'], builds=verification,
        restored=manifest['restored'], restore_status=manifest['restore_status'],
    )


def archive_cases(root, manifest):
    inputs = {row['case']: row for row in manifest['inputs']}
    require(len(inputs) == len(manifest['inputs']) == manifest['input_count'], 'input case count')
    require({(row['scenario'].removeprefix('outbound_'), row['direction'], row['profile'])
             for row in inputs.values()}
            == set(product(manifest['maneuvers'], manifest['directions'],
                           [profile['name'] for profile in manifest['noise_profiles']])),
            'input grid is incomplete')
    prepared = {}
    for case, row in inputs.items():
        path = root / 'inputs' / case
        require(sha256(path / 'samples.jsonl') == row['input_sha256'], 'archive input hash mismatch')
        input_data = load_input(path)
        settings = input_data.metadata['settings']
        require(all(settings[key] == row[key] for key in ('dt_s', 'scenario', 'seed',
                    'range_noise_std_m', 'azimuth_noise_std_rad'))
                and settings['dt_s'] == manifest['dt_s'] and settings['seed'] == manifest['seed']
                and len(input_data.samples) == row['samples']
                and input_data.metadata['effective_duration_s'] == row['duration_s'],
                'archive input metadata mismatch')
        prepared[case] = input_data
    return inputs, prepared


def write_csv(path, records):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)


def json_write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def group_summary(rows, case_series, rtt_series):
    summary = []
    for axis in ('all', 'maneuver', 'direction', 'profile', 'maneuver_profile'):
        groups = defaultdict(list)
        for row in rows:
            key = 'all' if axis == 'all' else row.get(axis, f"{row['maneuver']}|{row['profile']}")
            groups[key, row['variant']].append(row)
        for (key, variant), group in sorted(groups.items()):
            cases = [r['case'] for r in group]
            common = sum(r['common_samples'] for r in group)
            eligible = sum(r['eligible_samples'] for r in group)
            valid = sum(r['valid_samples'] for r in group)
            position = position_stats([error for c in cases for error in case_series[c][variant]])
            measured = position_stats([error for c in cases for error in case_series[c]['measured']])
            perf = {}
            for stage in STAGES:
                n = sum(r[f'{stage}_samples'] or 0 for r in group)
                mean = sum((r[f'{stage}_samples'] or 0) * (r[f'{stage}_mean_us_approx'] or 0) for r in group)
                bound = sum((r[f'{stage}_samples'] or 0) * (r[f'{stage}_mean_us_rounding_bound'] or 0)
                            for r in group)
                perf.update({f'{stage}_samples': n, f'{stage}_mean_us_approx': mean / n if n else None,
                             f'{stage}_mean_us_rounding_bound': bound / n if n else None})
            summary.append(dict(
                axis=axis, group=key, variant=variant, cases=len(group),
                common_samples=common, eligible_samples=eligible, valid_samples=valid,
                common_coverage=common / eligible, valid_coverage=valid / eligible,
                position_rmse_m=position['rmse_m'], position_p95_m=position['p95_m'],
                measured_rmse_m=measured['rmse_m'], measured_p95_m=measured['p95_m'],
                mean_case_rmse_m=sum(r['position_rmse_m'] for r in group) / len(group),
                gate_rejected=sum(r['gate_rejected'] for r in group),
                lost_transitions=sum(r['lost_transitions'] for r in group),
                sent_samples=sum(r['sent_samples'] for r in group),
                **{f'rtt_{k}': v for k, v in rtt_stats(
                    [x for case in cases for x in rtt_series[variant, case]]).items()},
                perf_available_runs=sum(r['perf_attribution'] == 'full_session' for r in group), **perf,
            ))
    return summary


def analyze(root, output):
    manifest = read_json(root / 'manifest.json')
    require(manifest['complete'] and manifest['planned_runs'] == len(manifest['runs']),
            'incomplete manifest')
    meta = provenance(root, manifest)
    inputs, prepared = archive_cases(root, manifest)
    expected = set(product(VARIANTS, inputs))
    require({(row['variant'], row['case']) for row in manifest['runs']} == expected
            and len(manifest['runs']) == len(expected), 'manifest run grid mismatch')
    results, valid_series, rtt_series = {}, {}, {}
    # Each estimator image is flashed once. The final post-run snapshot becomes the next
    # session baseline. A run is attributed only if measurement and both stage deltas reconcile.
    baseline = {variant: PerfSnapshot(0, 0, {name: (0, 0, 0) for name in STAGES}) for variant in VARIANTS}
    cumulative = Counter()
    for run in manifest['runs']:
        variant, case = key = run['variant'], run['case']
        try:
            require(all(run[field] == value for field, value in inputs[case].items()), 'run input metadata mismatch')
            cutoff_ms = prepared[case].samples[0].timestamp_ms + WARMUP_MS
            counts, valid, rtt, snapshots = analyze_run(root, run, prepared[case], cutoff_ms)
            perf = None
            expected_start = baseline[variant]
            cumulative[variant] += run['samples']
            if snapshots and snapshots[-1].measurements == cumulative[variant]:
                end = snapshots[-1]
                if expected_start is not None:
                    perf = perf_delta(expected_start, end, run['samples'],
                                      counts['corrected'] + counts['gate_rejected'], counts['corrected'])
                baseline[variant] = end
            else:
                baseline[variant] = None
            results[key] = dict(
                sent_samples=run['samples'], valid_samples=len(valid), **counts,
                perf_attribution='full_session' if perf else 'unavailable',
                **{f'rtt_{k}': v for k, v in rtt_stats(rtt).items()},
                **{f'{stage}_{field}': perf[stage][field] if perf else None
                   for stage in STAGES for field in ('samples', 'mean_us_approx', 'mean_us_rounding_bound')},
            )
            valid_series[key], rtt_series[key] = valid, rtt
        except InvalidCapture as error:
            raise InvalidCapture(f'{variant}/{case}: {error}') from None
        except Exception as error:
            raise InvalidCapture(f'{variant}/{case}: malformed capture ({type(error).__name__})') from None
    runs, pairs, case_series = [], [], {}
    for case, row in inputs.items():
        samples = prepared[case].samples
        cutoff = samples[0].timestamp_ms + WARMUP_MS
        measured = {
            s.timestamp_ms: polar_error(s.wire_range_m, s.wire_azimuth_sc * math.pi / 2**31,
                                        s.truth_x_m, s.truth_y_m)
            for s in samples
        }
        common, values = compare(measured, {v: valid_series[v, case] for v in VARIANTS}, cutoff)
        require(bool(common), 'no shared valid comparison samples')
        case_series[case] = values
        eligible = sum(stamp >= cutoff for stamp in measured)
        labels = dict(case=case, maneuver=row['scenario'].removeprefix('outbound_'),
                      direction=row['direction'], profile=row['profile'], seed=row['seed'],
                      duration_s=row['duration_s'], eligible_samples=eligible, common_samples=len(common),
                      common_coverage=len(common) / eligible)
        metrics = {series: position_stats(errors) for series, errors in values.items()}
        pair = {**labels, 'input_sha256': row['input_sha256'],
                **{f'{series}_{metric}': value for series, stats in metrics.items()
                   for metric, value in stats.items()}}
        for variant in VARIANTS:
            result = results[variant, case]
            pair[f'{variant}_valid_coverage'] = result['valid_samples'] / eligible
            pair[f'{variant}_delta_vs_kf_rmse_m'] = metrics[variant]['rmse_m'] - metrics['kf']['rmse_m']
            runs.append(dict(
                **labels, variant=variant, input_sha256=row['input_sha256'], integrity_ok=True,
                valid_coverage=result['valid_samples'] / eligible,
                **{f'position_{k}': v for k, v in metrics[variant].items()},
                **{f'measured_{k}': v for k, v in metrics['measured'].items()},
                **result,
            ))
        best = min(metrics[v]['rmse_m'] for v in VARIANTS)
        pair['lowest_rmse'] = '|'.join(v for v in VARIANTS if metrics[v]['rmse_m'] == best)
        pairs.append(pair)
    summary = group_summary(runs, case_series, rtt_series)
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / 'runs.csv', runs)
    write_csv(output / 'paired-cases.csv', pairs)
    write_csv(output / 'group-summary.csv', summary)
    json_write(output / 'provenance.json', meta)
    json_write(output / 'summary.json', dict(
        runs=len(runs), paired_cases=len(pairs),
        common_samples=sum(p['common_samples'] for p in pairs),
        eligible_samples=sum(p['eligible_samples'] for p in pairs),
        min_common_coverage=min(p['common_coverage'] for p in pairs),
        lowest_rmse_counts=dict(Counter(p['lowest_rmse'] for p in pairs)),
        perf_final_boot_max_us={
            variant: {stage: baseline[variant].stages[stage][2] / 1000 for stage in STAGES}
            if baseline[variant] else None for variant in VARIANTS
        },
        groups=summary,
    ))
    from plot_grid import write_plots
    write_plots(output, summary, manifest['maneuvers'])
    print(f'Validated {len(runs)} board sessions and {len(pairs)} paired input cases.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    try:
        analyze(args.capture.resolve(), args.output)
    except InvalidCapture as error:
        parser.exit(1, f'Capture analysis failed ({error}).\n')
    except Exception as error:
        parser.exit(1, f'Capture analysis failed ({type(error).__name__}).\n')


if __name__ == '__main__':
    main()
