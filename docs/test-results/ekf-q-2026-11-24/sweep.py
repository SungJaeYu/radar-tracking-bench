"""Replay saved inputs through the production C processor; no UART or board timing."""
import argparse
import csv
import ctypes
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from pc_sim.storage.prepared_storage import load_input

Q_SYMBOL = 'CONFIG_RADAR_EKF_ACCELERATION_VARIANCE_M_SQUARED_PER_S_FOURTH'
Q_VALUES = [0, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000, 300000, 1000000]
BASE_COMMIT = 'cee58d7390139317179dc70d372a88e9992ebeb2'
ADAPTER = 'fcc_app/src/tracking/estimators/cartesian_cv_ekf.c'
SOURCES = [
    'docs/test-results/ekf-q-2026-11-24/replay.c',
    'fcc_app/src/application/radar_processor.c', ADAPTER,
    'fcc_app/src/tracking/estimators/filters/ekf_cv_2d.c',
    'fcc_app/src/tracking/angle_utils.c', 'fcc_app/src/tracking/gating.c',
    'fcc_app/src/tracking/track.c', 'fcc_app/src/common/matrix.c',
    'fcc_app/src/protocol/measurement_message.c',
]
DEFINITIONS = [
    '__ASSERT_ON=0', 'CONFIG_RADAR_ESTIMATOR_EKF_CV=1',
    'CONFIG_RADAR_MEASUREMENT_TIMEOUT_MS=1000',
    'CONFIG_RADAR_RANGE_GATE_M=100', 'CONFIG_RADAR_AZIMUTH_GATE_DEG=10',
    'CONFIG_RADAR_RANGE_MEASUREMENT_VARIANCE_M_SQUARED=25',
    'CONFIG_RADAR_AZIMUTH_MEASUREMENT_VARIANCE_RAD_SQUARED_SCALED_1E9=1218470',
]
INCLUDES = [HERE / 'include', REPO / 'fcc_app/tests/common/include', REPO / 'fcc_app/src']


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compile_library(compiler: str, directory: Path, q: int, adapter: Path | None = None):
    directory.mkdir(parents=True, exist_ok=True)
    library = directory / ('replay.dylib' if sys.platform == 'darwin' else 'replay.so')
    sources = [str(adapter if source == ADAPTER and adapter else REPO / source)
               for source in SOURCES]
    command = [compiler, '-shared', '-fPIC', '-O0', '-ffp-contract=off', '-std=c11',
               '-Wall', '-Wextra', '-Werror', *['-I' + str(path) for path in INCLUDES],
               *['-D' + value for value in DEFINITIONS], f'-D{Q_SYMBOL}={q}',
               *sources, '-lm', '-o', str(library)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    return library, command


def replay(library: Path, prepared, case: str, q: int):
    c_library = ctypes.CDLL(str(library.resolve()))
    c_library.replay_reset.argtypes = []
    c_library.replay_reset.restype = None
    c_library.replay_step.argtypes = [ctypes.POINTER(ctypes.c_uint8),
                                    ctypes.POINTER(ctypes.c_float),
                                    ctypes.POINTER(ctypes.c_uint32)]
    c_library.replay_step.restype = ctypes.c_int
    c_library.replay_reset()
    turn_start_s = prepared.metadata['segments'][0]['duration_s']
    turn_end_s = turn_start_s + prepared.metadata['segments'][1]['duration_s']
    rows, binary = [], bytearray()
    start_ms = None
    for sample in prepared.samples:
        if sample.frame is None:
            raise ValueError('This comparison requires a detection at every saved sample')
        payload = (ctypes.c_uint8 * 10).from_buffer_copy(sample.frame[3:13])
        values, meta = (ctypes.c_float * 4)(), (ctypes.c_uint32 * 3)()
        processed = c_library.replay_step(payload, values, meta)
        if processed != 1:
            raise RuntimeError(f'Invalid payload at {case}:{sample.index}')
        binary.extend(bytes(values) + bytes(meta))
        state, result, estimate_ms = meta
        valid = state in (1, 2, 3) and estimate_ms == sample.timestamp_ms
        if valid and (result == 0 or start_ms is None):
            start_ms = sample.timestamp_ms
        eligible = valid and sample.timestamp_ms - start_ms >= 2000
        sensor_s = sample.timestamp_ms / 1000
        phase = ('straight_before' if sensor_s < turn_start_s else
                 'turn' if sensor_s < turn_end_s else 'straight_after')
        radius, angle, range_rate, angle_rate = values
        estimate_x_m, estimate_y_m = radius * math.sin(angle), radius * math.cos(angle)
        measurement_angle = sample.wire_azimuth_sc * math.pi / 2**31
        measurement_x_m = sample.wire_range_m * math.sin(measurement_angle)
        measurement_y_m = sample.wire_range_m * math.cos(measurement_angle)
        error_m = (math.hypot(estimate_x_m - sample.truth_x_m,
                              estimate_y_m - sample.truth_y_m) if valid else None)
        if valid and not all(math.isfinite(v) for v in [*values, error_m]):
            raise RuntimeError(f'Non-finite estimate at {case}:{sample.index}')
        rows.append(dict(case=case, q=q, timestamp_ms=sample.timestamp_ms,
                         sensor_s=sensor_s, phase=phase, state=state, result=result,
                         estimate_timestamp_ms=estimate_ms, valid=int(valid),
                         eligible=int(eligible), range_m=radius, azimuth_rad=angle,
                         range_rate_mps=range_rate, azimuth_rate_radps=angle_rate,
                         truth_x_m=sample.truth_x_m, truth_y_m=sample.truth_y_m,
                         estimate_x_m=estimate_x_m if valid else None,
                         estimate_y_m=estimate_y_m if valid else None,
                         error_m=error_m,
                         measurement_error_m=math.hypot(measurement_x_m - sample.truth_x_m,
                                                        measurement_y_m - sample.truth_y_m)))
    return rows, bytes(binary)


def rmse(rows: list[dict], key: str = 'error_m'):
    return math.sqrt(math.fsum(row[key]**2 for row in rows) / len(rows)) if rows else None


def summarize(rows: list[dict]) -> dict:
    eligible = [row for row in rows if row['eligible']]
    valid = [row for row in rows if row['valid']]
    longest, consecutive = 0, 0
    for row in rows:
        consecutive = consecutive + 1 if row['result'] == 2 else 0
        longest = max(longest, consecutive)
    return dict(case=rows[0]['case'], q=rows[0]['q'], input_count=len(rows),
                valid_count=len(valid), coverage=len(valid)/len(rows),
                eligible_count=len(eligible),
                gates=sum(row['result'] == 2 for row in rows),
                max_consecutive_gates=longest, lost=sum(row['state'] == 4 for row in rows),
                starts=sum(row['result'] == 0 for row in rows),
                first_confirmed_s=next((row['sensor_s'] for row in rows if row['state'] == 2), None),
                all_valid_rmse_m=rmse(valid),
                warmup_rmse_m=rmse([row for row in valid if not row['eligible']]),
                measurement_rmse_m=rmse(eligible, 'measurement_error_m'),
                **{phase + '_rmse_m': rmse([row for row in eligible
                                          if phase == 'all' or row['phase'] == phase])
                   for phase in ['all', 'straight_before', 'turn', 'straight_after']})


def csv_text(rows: list[dict]) -> str:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path, help='Directory containing baseline/ and noisy/')
    parser.add_argument('--output', type=Path, default=HERE)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--compiler', default='/usr/bin/clang')
    parser.add_argument('--before-library', type=Path,
                        help='Optional locally preserved pre-edit library for an extra byte comparison')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.build_dir.mkdir(parents=True, exist_ok=True)
    inputs = {case: load_input(args.inputs / case) for case in ('baseline', 'noisy')}
    source_paths = {REPO / source for source in SOURCES}
    for directory in INCLUDES:
        source_paths.update(directory.rglob('*.h'))
    source_paths.update([HERE / 'sweep.py', REPO / 'fcc_app/Kconfig'])
    source_hashes = {str(path.relative_to(REPO)): digest(path) for path in sorted(source_paths)}
    # Only the adapter differs from the recorded baseline production sources.
    for path in sorted(source_paths):
        relative = str(path.relative_to(REPO))
        if relative.startswith('fcc_app/src/') and relative != ADAPTER:
            previous = subprocess.run(['git', 'show', BASE_COMMIT + ':' + relative], cwd=REPO,
                                      check=True, capture_output=True).stdout
            if previous != path.read_bytes():
                raise RuntimeError(f'Baseline production source changed: {relative}')
    old_adapter = subprocess.run(['git', 'show', BASE_COMMIT + ':' + ADAPTER], cwd=REPO,
                                 check=True, capture_output=True).stdout
    old_path = args.build_dir / 'original_adapter.c'
    old_path.write_bytes(old_adapter)
    old_library, old_command = compile_library(args.compiler, args.build_dir / 'original',
                                               100, old_path)
    original = {case: replay(old_library, prepared, case, 100)[1]
                for case, prepared in inputs.items()}
    rows, summaries, builds, default_checks = [], [], [], {}
    for q in Q_VALUES:
        library, command = compile_library(args.compiler, args.build_dir / f'q-{q}', q)
        builds.append(dict(q=q, command=command, library_sha256=digest(library)))
        config_dir = args.output / 'configs'
        config_dir.mkdir(exist_ok=True)
        (config_dir / f'q-{q}.conf').write_text(
            'CONFIG_RADAR_ESTIMATOR_EKF_CV=y\n' + f'{Q_SYMBOL}={q}\n')
        for case, prepared in inputs.items():
            trace, binary = replay(library, prepared, case, q)
            if q == 100:
                if binary != original[case]:
                    raise RuntimeError(f'Default Q no longer preserves baseline: {case}')
                if args.before_library:
                    before = replay(args.before_library, prepared, case, q)[1]
                    if binary != before:
                        raise RuntimeError(f'Pre-edit library differs: {case}')
                default_checks[case] = dict(samples=len(trace), bytes_equal=True,
                                            trace_sha256=hashlib.sha256(binary).hexdigest(),
                                            preserved_library_checked=bool(args.before_library))
            rows.extend(trace)
            summaries.append(summarize(trace))
    # Pair each Q against Q=100 on identical eligible timestamps; keep own coverage visible.
    for summary in summaries:
        case, q = summary['case'], summary['q']
        baseline = {row['timestamp_ms']: row for row in rows
                    if row['case'] == case and row['q'] == 100 and row['eligible']}
        candidate = [row for row in rows if row['case'] == case and row['q'] == q
                     and row['eligible'] and row['timestamp_ms'] in baseline]
        summary.update(common_with_default_count=len(candidate),
                       common_candidate_rmse_m=rmse(candidate),
                       common_default_rmse_m=rmse([baseline[row['timestamp_ms']]
                                                  for row in candidate]))
    # Compare the host default to prior real-board estimates; this is not a new board run.
    with (HERE.parent / 'kf-ekf-2026-11-24/series.csv').open() as stream:
        board = {(row['case'], round(float(row['sensor_s'])*1000)): row
                 for row in csv.DictReader(stream) if row['estimator'] == 'ekf'}
    board_checks = {}
    for case in inputs:
        selected = [row for row in rows if row['q'] == 100 and row['case'] == case and row['valid']]
        differences = [math.hypot(row['estimate_x_m'] - float(board[case, row['timestamp_ms']]['estimate_x_m']),
                                 row['estimate_y_m'] - float(board[case, row['timestamp_ms']]['estimate_y_m']))
                       for row in selected]
        board_checks[case] = dict(samples=len(differences), max_position_difference_m=max(differences))
    manifest = dict(baseline_commit=BASE_COMMIT,
                    compiler_version=subprocess.run([args.compiler, '--version'], check=True,
                                                    capture_output=True, text=True).stdout,
                    compile_definitions=DEFINITIONS, q_values=Q_VALUES,
                    source_sha256=source_hashes, original_adapter_sha256=digest(old_path),
                    input_sha256={case: {name: digest(args.inputs/case/name)
                                         for name in ['metadata.json', 'samples.jsonl']} for case in inputs},
                    original_compile_command=old_command, builds=builds,
                    default_preservation=default_checks, prior_board_comparison=board_checks)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2, allow_nan=False)+'\n')
    (args.output / 'summary.json').write_text(json.dumps(summaries, indent=2, allow_nan=False)+'\n')
    (args.output / 'summary.csv').write_text(csv_text(summaries))
    (args.output / 'series.csv.gz').write_bytes(gzip.compress(csv_text(rows).encode(), mtime=0))
    print(csv_text(summaries))
    print(json.dumps(dict(default_preservation=default_checks, prior_board_comparison=board_checks)))


if __name__ == '__main__':
    main()
