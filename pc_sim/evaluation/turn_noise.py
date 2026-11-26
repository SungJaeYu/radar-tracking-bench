"""Replay saved straight-turn-straight input and record actual board TRACK reports."""
import argparse
import csv
import json
import math
from pathlib import Path
import time

import serial

from pc_sim.simulation.prepared_input import InputSettings, generate_input
from pc_sim.storage.prepared_storage import load_input, save_input
from pc_sim.storage.recording import SessionRecorder, evaluate_session, session_path
from pc_sim.transport.frame_parser import FrameParser
from pc_sim.transport.protocol import (
    build_init_frame, encode_frame, decode_track_payload, decode_status_payload,
    FRAME_TYPE_TRACK_REPORT, FRAME_TYPE_STATUS_REPORT, STATUS_FIELDS,
)


class TurnRecorder(SessionRecorder):
    """Record changing truth azimuth and the exact quantized transmitted measurement."""

    def record_sample(self, sample, sent_at):
        self._row('samples', dict(timestamp_ms=sample.timestamp_ms,
            truth_range_m=sample.truth_range_m, truth_azimuth_rad=sample.truth_azimuth_rad,
            measured_range_m=sample.wire_range_m,
            measured_azimuth_rad=sample.wire_azimuth_sc * math.pi / 2**31,
            tx_monotonic_s=sent_at, frame_hex=sample.frame.hex()))


def position_metrics(path: Path, prepared) -> dict:
    """Position errors after 2 s warmup, restarted on STARTED as in evaluate_session."""
    truth = {s.timestamp_ms: s for s in prepared.samples}
    boundary = prepared.metadata['segments'][0]['duration_s']
    turn_end = boundary + prepared.metadata['segments'][1]['duration_s']
    errors = {name: [] for name in ('all', 'straight_before', 'turn', 'straight_after')}
    seen = set()
    segment_start = None
    with (path / 'reports.csv').open() as stream:
        for row in csv.DictReader(stream):
            stamp = int(row['estimate_timestamp_ms'])
            if not int(row['flags']) & 2:
                continue
            if int(row['result']) == 0 or segment_start is None:
                segment_start = stamp
            if stamp in seen or stamp not in truth:
                continue
            seen.add(stamp)
            if stamp - segment_start < 2000:
                continue
            sample = truth[stamp]
            radius, angle = float(row['range_m']), float(row['azimuth_rad'])
            error = math.hypot(radius * math.sin(angle) - sample.truth_x_m,
                               radius * math.cos(angle) - sample.truth_y_m)
            segment = ('straight_before' if stamp / 1000 < boundary else
                       'turn' if stamp / 1000 < turn_end else 'straight_after')
            errors['all'].append(error)
            errors[segment].append(error)
    return {key: dict(count=len(values), rmse_m=math.sqrt(sum(x*x for x in values)/len(values))
                     if values else None, max_m=max(values) if values else None)
            for key, values in errors.items()}


def run(port: str, output: Path, input_directory: Path | None = None, *,
        noise: float | None = None, azimuth_noise: float | None = None) -> tuple[Path, dict]:
    if input_directory is not None and (noise is not None or azimuth_noise is not None):
        raise ValueError('Saved input already defines noise; do not override it during replay')
    prepared = load_input(input_directory) if input_directory else generate_input(InputSettings(
        scenario='straight_turn_straight', duration_s=80, dt_s=.1,
        range_noise_std_m=10 if noise is None else noise,
        azimuth_noise_std_rad=.01 if azimuth_noise is None else azimuth_noise, seed=42))
    settings = InputSettings(**prepared.metadata['settings'])
    segments = prepared.metadata['segments']
    if (settings.scenario != 'straight_turn_straight' or len(segments) != 3
            or segments[0]['turn_rate_radps'] != 0 or segments[1]['turn_rate_radps'] == 0
            or segments[2]['turn_rate_radps'] != 0):
        raise ValueError('A three-segment straight_turn_straight input is required')
    if not .02 <= settings.dt_s <= .2 or any(s.frame is None for s in prepared.samples):
        raise ValueError('Turn replay requires 5..50 Hz and a frame at every sample')
    path = session_path(output)
    parser = FrameParser()
    statuses, resets = [], []
    complete = False
    with TurnRecorder(path, settings, 'board') as recorder:
        save_input(path / 'input', prepared)
        recorder.metadata.update(scenario='straight_turn_straight', complete=False,
                                 pacing='FIFO; collect for dt after each write; no skipped input or catch-up')
        recorder._metadata()
        print(f'Session: {path}', flush=True)
        try:
            with serial.Serial(port, 115200, timeout=.005, write_timeout=1, exclusive=True) as data:
                def send(frame):
                    now = time.monotonic()
                    if data.write(frame) != len(frame):
                        raise OSError('Short UART write')
                    recorder.record_wire('tx', frame, now)
                    return now

                def collect(seconds):
                    deadline = time.monotonic() + seconds
                    while time.monotonic() < deadline:
                        raw = data.read(min(data.in_waiting or 1, 4096))
                        now = time.monotonic()
                        recorder.record_wire('rx', raw, now)
                        for frame in parser.feed(raw):
                            if frame.frame_type == FRAME_TYPE_TRACK_REPORT:
                                report = decode_track_payload(frame.payload)
                                recorder.record_report(report, now)
                                if not report.input_present and report.result == 4 and report.state == 0:
                                    resets.append(report)
                            elif frame.frame_type == FRAME_TYPE_STATUS_REPORT:
                                stats = decode_status_payload(frame.payload)
                                statuses.append(stats)
                                recorder.record_status(stats, now)
                            else:
                                raise ValueError(f'Unexpected TYPE {frame.frame_type}')
                send(build_init_frame())
                collect(.3)
                if not resets:
                    raise TimeoutError('No INIT reset report')
                send(encode_frame(3, b'\0'))
                collect(.2)
                if len(statuses) != 1:
                    raise TimeoutError('No unique initial STATUS')
                for index, sample in enumerate(prepared.samples):
                    sent_at = send(sample.frame)
                    recorder.record_sample(sample, sent_at)
                    collect(settings.dt_s)
                    if index % 100 == 0 or index == len(prepared.samples)-1:
                        print(f'Sent {index+1}/{len(prepared.samples)}; sensor {sample.timestamp_ms/1000:.1f} s', flush=True)
                collect(.2)
                send(encode_frame(3, b'\0'))
                collect(.2)
                send(encode_frame(5, b'\0'))
                collect(.2)
                if len(statuses) != 2 or len(resets) != 2:
                    raise TimeoutError('Missing final STATUS or RESET report')
                complete = True
        finally:
            recorder.metadata['complete'] = complete
            recorder._metadata()
    result = evaluate_session(path)
    result['position'] = position_metrics(path, prepared)
    result['pc_crc_errors'] = parser.crc_errors
    result['pc_length_errors'] = parser.length_errors
    result['status_delta'] = {key: (statuses[-1][key]-statuses[0][key]) % 2**32
                              for key, *_ in STATUS_FIELDS if key in statuses[0] and key in statuses[-1]}
    result['integrity_ok'] = (len(result['status_delta']) == len(STATUS_FIELDS)
        and not any(result['status_delta'].values())
        and not parser.crc_errors and not parser.length_errors
        and all(result[key] == 0 for key in ('missing_input_reports', 'duplicate_input_reports',
                    'unmatched_input_reports', 'sequence_gaps', 'sequence_discontinuities', 'time_rejected'))
        and result['sent_samples'] == len(prepared.samples) and result['matched_estimates'] > 0)
    result['accuracy_pass_criterion'] = None
    (path / 'evaluation.json').write_text(json.dumps(result, indent=2) + '\n')
    return path, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--output', type=Path, default=Path('runs'))
    parser.add_argument('--input', type=Path, help='Existing prepared input; default generates 10 m / 0.01 rad, seed42')
    parser.add_argument('--noise', type=float, help='Range noise standard deviation (m); default 10')
    parser.add_argument('--azimuth-noise', type=float, help='Azimuth noise standard deviation (rad); default 0.01')
    args = parser.parse_args(argv)
    try:
        path, result = run(args.port, args.output, args.input,
                           noise=args.noise, azimuth_noise=args.azimuth_noise)
    except (OSError, ValueError, TimeoutError) as error:
        parser.exit(1, f'Turn replay failed: {error}\n')
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result['integrity_ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
