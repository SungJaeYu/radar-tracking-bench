"""Capture one noise-free segmented trajectory and real STM32 TRACK responses."""
import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import serial
from pc_sim.frame_parser import FrameParser
from pc_sim.protocol import (build_init_frame, build_measurement_frame_from_radians,
                             encode_frame, decode_track_payload, decode_status_payload,
                             FRAME_TYPE_STATUS_REQUEST, FRAME_TYPE_STATUS_REPORT,
                             FRAME_TYPE_TRACK_REPORT, TrackState, TrackReportResult)
from pc_sim.targets import scenario_straight_turn_straight


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--console', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    scenario = scenario_straight_turn_straight()
    samples = []
    step_s = 0.1
    while len(samples) * step_s < scenario.duration_s:
        stamp = len(samples) * 100
        target = scenario.target
        frame = build_measurement_frame_from_radians(stamp, target.range_m, target.azimuth_rad)
        _, distance, angle = struct.unpack('>IHi', frame[3:-2])
        samples.append(dict(timestamp_ms=stamp, x_m=target.x_m, y_m=target.y_m,
                            truth_range_m=target.range_m, truth_azimuth_rad=target.azimuth_rad,
                            measured_range_m=distance, measured_azimuth_rad=angle*math.pi/2**31,
                            segment=scenario.segment_index, frame_hex=frame.hex()))
        scenario.update(step_s)
    args.output.mkdir(parents=True, exist_ok=False)
    files = ['pc_sim/targets.py', 'pc_sim/protocol.py', 'pc_sim/frame_parser.py',
             'build/zephyr/zephyr.elf', 'build/zephyr/.config', str(Path(__file__).relative_to(ROOT))]
    metadata = dict(started_utc=datetime.now(timezone.utc).isoformat(),
                    head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    port=args.port, console=args.console, hz=10, noise=0, warmup_ms=2000,
                    scenario_duration_s=scenario.duration_s,
                    sha256={name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files})
    (args.output/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    reports, statuses, wire = [], [], []
    receiver = FrameParser()
    checks = {}
    with (args.output/'wire.jsonl').open('w') as raw_file, (args.output/'console.log').open('wb') as console_file:
        with serial.Serial(args.port, 115200, timeout=.005, write_timeout=1) as data, \
                serial.Serial(args.console, 115200, timeout=0) as console:
            def send(frame):
                now = time.monotonic()
                if data.write(frame) != len(frame):
                    raise OSError('Short UART write')
                raw_file.write(json.dumps(dict(direction='tx', time=now, hex=frame.hex()))+'\n')
                raw_file.flush()
                return now

            def collect(until):
                while time.monotonic() < until:
                    raw = data.read(min(data.in_waiting or 1, 4096))
                    now = time.monotonic()
                    if raw:
                        raw_file.write(json.dumps(dict(direction='rx', time=now, hex=raw.hex()))+'\n')
                        raw_file.flush()
                    for frame in receiver.feed(raw):
                        if frame.frame_type == FRAME_TYPE_TRACK_REPORT:
                            reports.append({**asdict(decode_track_payload(frame.payload)), 'rx_monotonic_s': now})
                        elif frame.frame_type == FRAME_TYPE_STATUS_REPORT:
                            statuses.append(decode_status_payload(frame.payload))
                        else:
                            raise ValueError(f'Unexpected type {frame.frame_type}')
                    console_file.write(console.read(console.in_waiting))
                    console_file.flush()

            send(encode_frame(FRAME_TYPE_STATUS_REQUEST, b'\x00'))
            collect(time.monotonic()+.2)
            checks['initial_status_zero'] = len(statuses)==1 and all(v==0 for v in statuses[0].values())
            send(build_init_frame())
            collect(time.monotonic()+.2)
            checks['initial_reset'] = bool(reports) and reports[-1]['result']==TrackReportResult.RESET
            start = time.monotonic()
            for index, sample in enumerate(samples):
                collect(start+index*step_s)
                sample['tx_monotonic_s'] = send(bytes.fromhex(sample['frame_hex']))
                if index % 100 == 0:
                    print(f'sent={index+1}/{len(samples)} segment={sample["segment"]}', flush=True)
            collect(time.monotonic()+.2)
            send(encode_frame(FRAME_TYPE_STATUS_REQUEST, b'\x00'))
            collect(time.monotonic()+.2)
            send(build_init_frame())
            collect(time.monotonic()+.2)
            checks['final_reset'] = bool(reports) and reports[-1]['result']==TrackReportResult.RESET and reports[-1]['state']==0
            checks['final_status_zero'] = len(statuses)==2 and all(v==0 for v in statuses[-1].values())
    for name, value in [('samples',samples), ('reports',reports), ('status',statuses)]:
        (args.output/f'{name}.json').write_text(json.dumps(value,indent=2)+'\n')
    inputs = [r for r in reports if r['flags'] & 1]
    counts = Counter(r['input_timestamp_ms'] for r in inputs)
    checks['one_report_per_measurement'] = len(inputs)==len(samples) and all(counts[s['timestamp_ms']]==1 for s in samples)
    checks['valid_estimates'] = all(r['flags'] & 2 for r in inputs)
    checks['accepted_measurements'] = all(r['result'] in (0,1) for r in inputs)
    checks['confirmed_after_warmup'] = all(r['state']==TrackState.CONFIRMED for r in inputs if r['input_timestamp_ms']>=2000)
    checks['aligned_estimate_time'] = all(r['input_timestamp_ms']==r['estimate_timestamp_ms'] for r in inputs)
    checks['contiguous_reports'] = all((b['report_sequence']-a['report_sequence']) % 2**32 == 1 for a,b in zip(reports,reports[1:]))
    checks['parser_clean'] = receiver.crc_errors==0 and receiver.length_errors==0
    console_text = (args.output/'console.log').read_text(errors='replace').lower()
    checks['console_no_fatal'] = not any(word in console_text for word in ('assertion fail','fatal error','hard fault'))
    by_stamp = {s['timestamp_ms']: s for s in samples}
    groups = {name: [] for name in ('all','straight_before','turn','straight_after')}
    rtts = []
    for report in inputs:
        sample = by_stamp.get(report['input_timestamp_ms'])
        if sample is None:
            continue
        rtts.append(1000*(report['rx_monotonic_s']-sample['tx_monotonic_s']))
        if sample['timestamp_ms'] < 2000 or not report['flags'] & 2:
            continue
        angle_error = (report['azimuth_rad']-sample['truth_azimuth_rad']+math.pi)%(2*math.pi)-math.pi
        x = report['range_m']*math.sin(report['azimuth_rad'])
        y = report['range_m']*math.cos(report['azimuth_rad'])
        errors = (report['range_m']-sample['truth_range_m'], math.degrees(angle_error), math.hypot(x-sample['x_m'],y-sample['y_m']))
        groups['all'].append(errors)
        groups[('straight_before','turn','straight_after')[sample['segment']]].append(errors)
    metrics = {}
    for name, errors in groups.items():
        metrics[name] = {'count':len(errors)}
        for index, quantity in enumerate(('range_m','azimuth_deg','position_m')):
            values = [row[index] for row in errors]
            metrics[name][quantity] = dict(rmse=math.sqrt(sum(v*v for v in values)/len(values)), max_abs=max(map(abs,values))) if values else None
    rtts.sort()
    timing = {name:rtts[math.ceil(len(rtts)*fraction)-1] for name,fraction in [('p50',.5),('p99',.99),('max',1)]}
    result = dict(checks=checks, passed=all(checks.values()), sent=len(samples), reports=len(reports),
                  states=dict(Counter(r['state'] for r in inputs)), results=dict(Counter(r['result'] for r in inputs)),
                  metrics=metrics, pc_roundtrip_ms=timing,
                  accuracy_verdict='observational; no accuracy acceptance threshold defined')
    (args.output/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
