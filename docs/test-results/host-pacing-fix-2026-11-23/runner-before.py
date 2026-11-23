"""Record bounded performance-image HIL traffic, then restore normal firmware."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re
import subprocess
import sys
import time

import serial

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from pc_sim.frame_parser import FrameParser
from pc_sim.gui_model import Settings, make_sample
from pc_sim.protocol import (build_init_frame, build_measurement_frame, encode_frame,
                             decode_status_payload, decode_track_payload)
from pc_sim.async_recording import AsyncRecorder
from pc_sim.perf_acceptance import evaluate_acceptance, STACK_ALLOCATED, STACK_MARGINS, ACCEPTANCE_REVISION
from pc_sim.status_client import request_status

# Match radar_processor.c: a larger forward sensor interval clears the track.
MAX_SENSOR_INTERVAL_MS = 1000


class HostInputInterrupted(Exception):
    """The host no longer supplies the steady input this fixture assesses."""

    def __init__(self, details):
        self.details = details
        super().__init__('Host input continuity lost: ' + ', '.join(details['reasons']))


def check_input_continuity(previous_sensor_ms, previous_sent_s, sensor_ms, sent_s,
                           receive_timeout_ms):
    """Pre-write times show host input quality, not physical UART arrival times."""
    if previous_sent_s is None:
        return
    host_gap_ms = (sent_s - previous_sent_s) * 1000
    sensor_interval_ms = (sensor_ms - previous_sensor_ms) & 0xffffffff
    reasons = []
    if host_gap_ms >= receive_timeout_ms:
        reasons.append('host send gap reaches board receive timeout')
    if MAX_SENSOR_INTERVAL_MS < sensor_interval_ms < 0x80000000:
        reasons.append('sensor timestamp gap exceeds prediction interval limit')
    if reasons:
        raise HostInputInterrupted({
            'reasons': reasons, 'host_gap_ms': host_gap_ms,
            'sensor_interval_ms': sensor_interval_ms,
            'previous_sensor_ms': previous_sensor_ms, 'sensor_ms': sensor_ms,
            'previous_write_monotonic_s': previous_sent_s, 'write_monotonic_s': sent_s,
            'receive_timeout_ms': receive_timeout_ms,
            'sensor_interval_limit_ms': MAX_SENSOR_INTERVAL_MS,
        })


class PerfConsole:
    """Require the base snapshot fields; retain optional estimator summaries."""

    def __init__(self):
        self.pending = ''
        self.current = None
        self.snapshots = []
        self.faults = []
        self.boots = 0
        self.incomplete_summaries = 0

    def feed(self, text):
        self.pending += text
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            line = re.sub(r'\x1b\[[0-9;]*m', '', line)
            if 'FCC ready:' in line:
                self.boots += 1
            if re.search(r'ASSERTION|FATAL|Fault|stack overflow|messages dropped', line, re.I):
                self.faults.append(line)
            if 'PERF ' not in line:
                continue
            body = line.split('PERF ', 1)[1]
            values = {key: int(value) for key, value in re.findall(r'(\w+)=(-?\d+)', body)}
            # Keep the stored evidence schema compatible with earlier captures.
            if body.startswith('stack ') and 'status=unavailable' in body and 'error' in values:
                values['unavailable'] = values.pop('error')
            for current, legacy in (('unused_bytes', 'unused'), ('min_unused_bytes', 'min_unused'),
                                    ('over_budget_count', 'over20')):
                if current in values:
                    values[legacy] = values.pop(current)
            if body.startswith(('uptime_ms=', 'summary: uptime_ms=')):
                if self.current is not None:
                    self.incomplete_summaries += 1
                self.current = {'header': values}
            elif self.current is not None:
                name = body.split(':', 1)[0]
                self.current[name] = values
                if name == 'stack tx':
                    required = {'header', 'queue_wait', 'processing', 'rx_to_submit',
                                'queue rx', 'queue tx', 'tx', 'stack rx', 'stack handler', 'stack tx'}
                    if required.issubset(self.current):
                        self.snapshots.append(self.current)
                    else:
                        self.incomplete_summaries += 1
                    self.current = None


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else None


def timing_summary(latencies, send_times, duration, skipped_slots):
    """Report host RTT and pacing; qualification is assessed independently."""
    gaps = [(b - a) * 1000 for a, b in zip(send_times, send_times[1:])]
    return {
        'primary_metric': 'observed_board_delivery_evidence',
        'pc_latency_ms': {
            'count': len(latencies),
            'p50': percentile(latencies, .5), 'p95': percentile(latencies, .95),
            'p99': percentile(latencies, .99),
            'max': max(latencies) if latencies else None,
        },
        'actual_measurement_hz': len(send_times) / duration,
        'host_send_gap_ms': {'count': len(gaps), 'min': min(gaps, default=None),
                             'p50': percentile(gaps, .5), 'p99': percentile(gaps, .99),
                             'max': max(gaps, default=None)},
        'host_absolute_period_error_ms': {
            'p99': percentile([abs(gap - 20) for gap in gaps], .99),
            'max': max((abs(gap - 20) for gap in gaps), default=None)},
        'host_skipped_slots': skipped_slots,
        'host_max_send_gap_ms': max(gaps, default=0),
        'host_pacing_is_acceptance_gate': False,
        'host_pacing_is_requested_profile_gate': True,
        'host_rtt_is_acceptance_gate': False,
    }


def rtt_budget_checks(summary, p99_limit=20.0, max_limit=100.0):
    """Project budgets: one 50Hz period at p99, five periods at maximum."""
    for key, limit in (('p99', p99_limit), ('max', max_limit)):
        if limit is not None:
            value = summary['pc_latency_ms'][key]
            yield f'PC RTT {key} <= {limit:g}ms', value is not None and value <= limit


def runtime_failure(checks, name, category):
    """Preserve a known failure before aborting; missing evidence stays distinct."""
    checks.append({'name': name, 'passed': False, 'category': category})
    raise AssertionError(name)


def run(args):
    # Check both images before any flash; the finally path always attempts restoration.
    for build, enabled in [('build_perf', True), ('build', False)]:
        config = (ROOT / build / 'zephyr/.config').read_text()
        if ('CONFIG_RADAR_PERF_MONITOR=y' in config) != enabled:
            raise ValueError(f'Unexpected performance setting: {build}')
        for option in ('RADAR_LOG_STRESS_TEST', 'RADAR_TRANSPORT_STRESS_TEST'):
            if f'CONFIG_{option}=y' in config:
                raise ValueError(f'Synthetic stress must be off: {build}/{option}')
        if not (ROOT / build / 'zephyr/zephyr.hex').is_file():
            raise ValueError(f'Missing image: {build}')
    perf_config = (ROOT / 'build_perf/zephyr/.config').read_text()
    timeout = re.search(r'^CONFIG_RADAR_MEASUREMENT_TIMEOUT_MS=(\d+)$', perf_config, re.M)
    if timeout is None or int(timeout[1]) <= 0:
        raise ValueError('PERF image receive timeout is missing or invalid')
    receive_timeout_ms = int(timeout[1])
    args.output.mkdir(parents=True, exist_ok=False)
    metadata = {'started_utc': datetime.now(timezone.utc).isoformat(),
                'duration_s': args.duration, 'measurement_hz': 50, 'status_hz': 1,
                'baud': 115200, 'smoke': args.smoke,
                'acceptance_revision': ACCEPTANCE_REVISION,
                'passed_scope': 'observed_board_delivery_evidence',
                'host_rtt_is_acceptance_gate': False,
                'board_latency_limit_ms': 20,
                'cpu_scheduler_non_idle_limit_percent': 80,
                'sampled_stack_minimum_bytes': STACK_MARGINS,
                'stack_allocated_bytes': STACK_ALLOCATED,
                'requested_load_policy': 'all 50Hz scheduled slots, no skips, full duration',
                'host_input_interruption_policy': 'stop inconclusive before steady-input response checks',
                'board_receive_timeout_ms': receive_timeout_ms,
                'sensor_prediction_interval_limit_ms': MAX_SENSOR_INTERVAL_MS,
                'acceptance_sha256': hashlib.sha256((ROOT / 'pc_sim/perf_acceptance.py').read_bytes()).hexdigest(),
                'pc_rtt_limits_ms': {'p99': args.pc_rtt_p99_ms, 'max': args.pc_rtt_max_ms},
                'source_commit': subprocess.check_output([args.git, 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'recording_mode': 'bounded-worker', 'recording_queue_capacity': 1024,
                'recording_sha256': hashlib.sha256((ROOT / 'pc_sim/async_recording.py').read_bytes()).hexdigest(),
                'data_port': args.data_port, 'console_port': args.console_port}
    for build in ('build_perf', 'build'):
        metadata[build + '_elf_sha256'] = hashlib.sha256((ROOT / build / 'zephyr/zephyr.elf').read_bytes()).hexdigest()
        (args.output / (build + '.config')).write_text((ROOT / build / 'zephyr/.config').read_text())
    (args.output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (args.output / 'acceptance-snapshot.py').write_bytes((ROOT / 'pc_sim/perf_acceptance.py').read_bytes())
    (args.output / 'runner-snapshot.py').write_bytes(Path(__file__).read_bytes())
    checks, reports, statuses, sent_at, latencies, send_times = [], [], [], {}, [], []
    snapshot_parser = PerfConsole()
    decoder = FrameParser()
    valid_count = invalid_count = status_sent = 0
    received_measurements = 0
    sent_wire_bytes = 0
    sequence = None
    failure = restore_failure = None
    host_input_interruption = None
    result = {}
    recorder = None
    start = None
    skipped_slots = 0
    aborted_elapsed = None
    collecting_final_checks = False
    run_completed = recording_complete = False

    def check(name, condition):
        if name.startswith('PC RTT') or name == 'load contains measurement RTT samples':
            category = 'host_rtt'
        elif name in ('single firmware boot', 'performance summaries remain continuous',
                      'idle performance summary', 'restored normal STATUS zero'):
            category = 'evidence'
        elif name in ('all measurements matched once', 'all STATUS requests answered',
                      'one post-load timeout report', 'initial STATUS zero',
                      'INIT reset report received', 'RX accepted frame count',
                      'TX queued and polling counts match received frames'):
            category = 'delivery'
        else:
            category = 'board_internal'
        checks.append({'name': name, 'passed': bool(condition), 'category': category})
        if not condition and not collecting_final_checks:
            raise AssertionError(name)

    def flash(build, filename):
        with (args.output / filename).open('w') as stream:
            subprocess.run([args.west, 'flash', '-d', str(ROOT / build), '--runner', 'openocd'],
                           cwd=args.workspace, stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=60)

    settings = Settings(range_rate_mps=0, range_noise_std_m=0,
                        sample_rate_hz=50, duration_s=args.duration)
    settings.validate()
    try:
        with serial.Serial(args.console_port, 115200, timeout=0) as console:
            console.reset_input_buffer()
            flash('build_perf', 'perf-flash.log')
            with serial.Serial(args.data_port, 115200, timeout=0, write_timeout=1) as data, \
                 AsyncRecorder(args.output / 'session', settings, 'board-performance',
                               args.output / 'console.log') as recorder:
                def send(raw):
                    nonlocal sent_wire_bytes
                    now = time.monotonic()
                    if data.write(raw) != len(raw):
                        raise OSError('Short serial write')
                    sent_wire_bytes += len(raw)
                    recorder.record_wire('tx', raw, now)
                    return now

                def pump_until(deadline):
                    nonlocal sequence, received_measurements
                    while time.monotonic() < deadline:
                        recorder.check()
                        text = console.read(min(console.in_waiting, 16384)).decode(errors='replace')
                        if text:
                            recorder.record_console(text)
                            snapshot_parser.feed(text)
                        raw = data.read(min(data.in_waiting, 4096))
                        now = time.monotonic()
                        recorder.record_wire('rx', raw, now)
                        for frame in decoder.feed(raw):
                            if frame.frame_type == 7:
                                report = decode_track_payload(frame.payload)
                                if sequence is not None and report.report_sequence != ((sequence + 1) & 0xffffffff):
                                    runtime_failure(checks, 'TRACK sequence gap/duplicate/reset', 'delivery')
                                sequence = report.report_sequence
                                recorder.record_report(report, now)
                                reports.append(report)
                                if report.input_present:
                                    if report.input_timestamp_ms not in sent_at:
                                        runtime_failure(checks, 'Unexpected/duplicate measurement reply', 'delivery')
                                    latencies.append((now - sent_at.pop(report.input_timestamp_ms)) * 1000)
                                    if not report.estimate_valid or report.result not in (0, 1):
                                        runtime_failure(checks, 'Normal stationary measurement rejected', 'board_internal')
                                    if abs(report.range_m - 1000) > .01 or abs(report.azimuth_rad - math.radians(15)) > .0001:
                                        runtime_failure(checks, 'Unexpected stationary estimate', 'board_internal')
                                    # Keep progress reporting constant-time as the capture grows.
                                    received_measurements += 1
                            elif frame.frame_type == 6:
                                status = decode_status_payload(frame.payload)
                                recorder.record_status(status, now)
                                statuses.append(status)
                                if any(status.values()):
                                    runtime_failure(checks, f'Nonzero board error statistics: {status}', 'delivery')
                            else:
                                runtime_failure(checks, 'Unexpected response TYPE', 'delivery')
                        if decoder.crc_errors or decoder.length_errors:
                            runtime_failure(checks, 'PC CRC/LEN receive error', 'delivery')
                        if snapshot_parser.faults or snapshot_parser.boots > 1:
                            runtime_failure(checks, 'Console fatal/log loss/unexpected reboot', 'evidence')
                        time.sleep(min(.001, max(0, deadline - time.monotonic())))

                def status_request():
                    nonlocal status_sent
                    send(encode_frame(3, b'\0'))
                    status_sent += 1

                # Observe the first idle summary and all three stack scans before load.
                pump_until(time.monotonic() + 6)
                check('idle performance summary', bool(snapshot_parser.snapshots))
                idle = snapshot_parser.snapshots[-1]
                check('idle timing has no samples', idle['queue_wait']['n'] == 0)
                check('idle stack queries available', all('unused' in idle['stack ' + name] for name in ('rx', 'handler', 'tx', 'main')))
                send(build_init_frame())
                status_request()
                pump_until(time.monotonic() + .25)
                check('INIT reset report received', len(reports) == 1 and not reports[0].input_present and reports[0].result == 4)
                check('initial STATUS zero', len(statuses) == 1)
                rng = random.Random(42)
                start = time.monotonic()
                end = start + args.duration
                next_send, next_status, next_progress = start, start + 1, start + 60
                index = skipped_slots = 0
                previous_sensor_ms = previous_sent_s = None
                while time.monotonic() < end:
                    pump_until(min(next_send, next_status, end))
                    now = time.monotonic()
                    if now >= end:
                        break
                    if now >= next_send:
                        # Skip missed host deadlines instead of generating catch-up bursts.
                        skipped = int(max(0, now - next_send) / .02)
                        skipped_slots += skipped
                        index += skipped
                        sample = make_sample(settings, index * 20, rng)
                        sent = send(sample.frame)
                        recorder.record_sample(sample, sent)
                        sent_at[sample.timestamp_ms] = sent
                        send_times.append(sent)
                        valid_count += 1
                        # Preserve the sent input before stopping an invalid load.
                        # Do not relabel its documented RESET as a board rejection.
                        check_input_continuity(previous_sensor_ms, previous_sent_s,
                                               sample.timestamp_ms, sent, receive_timeout_ms)
                        previous_sensor_ms, previous_sent_s = sample.timestamp_ms, sent
                        index += 1
                        next_send = start + index * .02
                    if now >= next_status:
                        status_request()
                        next_status += 1
                    if now >= next_progress:
                        latest = snapshot_parser.snapshots[-1]
                        print(json.dumps({'elapsed_s': round(now - start), 'sent': valid_count,
                                          'received': received_measurements,
                                          'status': len(statuses), 'perf': latest['rx_to_submit'],
                                          'stack': {n: latest['stack ' + n] for n in ('rx', 'handler', 'tx')}}), flush=True)
                        next_progress += 60
                    if len(sent_at) > 100:
                        runtime_failure(checks, 'More than two seconds of measurement replies outstanding', 'delivery')
                load_elapsed = time.monotonic() - start
                # Drain replies and observe exactly one no-measurement timeout event.
                pump_until(time.monotonic() + 1.3)
                collecting_final_checks = True
                result.update(timing_summary(latencies, send_times, load_elapsed, skipped_slots))
                result['pc_rtt_limits_ms'] = metadata['pc_rtt_limits_ms']
                result['pc_rtt_budget_configured'] = any(v is not None for v in metadata['pc_rtt_limits_ms'].values())
                check('load contains measurement RTT samples', bool(latencies) and bool(send_times))
                check('one post-load timeout report', sum(not r.input_present for r in reports) == 2)
                if args.smoke:
                    # No production fault-injection settings are used in this short check.
                    send(build_init_frame())
                    pump_until(time.monotonic() + .1)
                    send(build_measurement_frame(0, 0, 0))
                    invalid_count += 1
                    pump_until(time.monotonic() + .1)
                    send(encode_frame(5, b'\0'))
                    pump_until(time.monotonic() + .1)
                    for stamp in (0, 20, 40):
                        sample = make_sample(settings, stamp, rng)
                        sent = send(sample.frame)
                        recorder.record_sample(sample, sent)
                        sent_at[stamp] = sent
                        valid_count += 1
                        pump_until(time.monotonic() + .03)
                    check('tracking recovers after invalid input and RESET', reports[-1].state == 2)
                    send(encode_frame(5, b'\0'))
                    pump_until(time.monotonic() + .1)
                status_request()
                pump_until(time.monotonic() + 6)
                last = snapshot_parser.snapshots[-1]
                check('all measurements matched once', not sent_at and sum(r.input_present for r in reports) == valid_count)
                check('all STATUS requests answered', len(statuses) == status_sent)
                check('single firmware boot', snapshot_parser.boots == 1)
                check('measurement count reconciles', last['header']['measurements'] == valid_count + invalid_count)
                check('no submit failures or invalid times', last['header']['submit_failed'] == last['header']['invalid_time'] == 0)
                check('invalid measurement is counted without submission', last['header']['without_submit'] == invalid_count)
                for metric in ('processing', 'rx_to_submit'):
                    check(metric + ' successful sample count', last[metric]['n'] == valid_count)
                check('queue wait count includes invalid input', last['queue_wait']['n'] == valid_count + invalid_count)
                check('20ms board latency budget', last['rx_to_submit']['over20'] == 0 and last['rx_to_submit']['max_ms'] <= 20)
                check('no queue rejection', last['queue rx']['rejected'] == last['queue tx']['rejected'] == 0)
                controls = 4 if args.smoke else 1
                check('RX accepted frame count', last['queue rx']['accepted'] == valid_count + invalid_count + status_sent + controls)
                check('TX queued and polling counts match received frames',
                      last['queue tx']['accepted'] == last['tx']['poll_completed'] == len(reports) + len(statuses))
                check('no TX encoder failures', last['tx']['encode_failed'] == 0)
                check('all sampled stacks have headroom', all('unused' in s.get('stack ' + n, {}) and s['stack ' + n]['min_unused'] >= margin
                                                            for s in snapshot_parser.snapshots for n, margin in STACK_MARGINS.items()))
                gaps = [b - a for a, b in zip(send_times, send_times[1:])]
                rate = len(send_times) / load_elapsed
                check('performance summaries remain continuous', len(snapshot_parser.snapshots) >= 2 and all(0 < b['header']['uptime_ms'] - a['header']['uptime_ms'] < 6000
                                                                   for a, b in zip(snapshot_parser.snapshots, snapshot_parser.snapshots[1:])))
                result.update({'load_elapsed_s': load_elapsed, 'load_measurements': len(send_times),
                          'valid_measurements_total': valid_count, 'invalid_measurements': invalid_count,
                          'status_requests': status_sent, 'status_responses': len(statuses),
                          'track_reports': len(reports), 'actual_measurement_hz': rate,
                          'host_skipped_slots': skipped_slots, 'host_max_send_gap_ms': max(gaps, default=0) * 1000,
                          'performance_summary_count': len(snapshot_parser.snapshots), 'last_performance': last,
                          'final_status': statuses[-1] if statuses else None, 'pc_crc_errors': decoder.crc_errors,
                          'pc_length_errors': decoder.length_errors})
                for name, passed in rtt_budget_checks(result, args.pc_rtt_p99_ms, args.pc_rtt_max_ms):
                    check(name, passed)
                run_completed = True
            recording_complete = True
    except HostInputInterrupted as error:
        host_input_interruption = error.details
        aborted_elapsed = time.monotonic() - start if start is not None else None
    except BaseException as error:
        failure = repr(error)
        aborted_elapsed = time.monotonic() - start if start is not None else None
    finally:
        # Preserve observations even when a runtime guard aborts before assessment.
        partial = {'load_elapsed_s': aborted_elapsed, 'load_measurements': len(send_times),
                   'valid_measurements_total': valid_count, 'invalid_measurements': invalid_count,
                   'status_requests': status_sent, 'status_responses': len(statuses),
                   'track_reports': len(reports), 'host_skipped_slots': skipped_slots,
                   'performance_summary_count': len(snapshot_parser.snapshots),
                   'last_performance': snapshot_parser.snapshots[-1] if snapshot_parser.snapshots else {},
                   'final_status': statuses[-1] if statuses else None,
                   'pc_crc_errors': decoder.crc_errors, 'pc_length_errors': decoder.length_errors}
        if aborted_elapsed is not None and aborted_elapsed > 0:
            partial.update(timing_summary(latencies, send_times, aborted_elapsed, skipped_slots))
        for key, value in partial.items():
            result.setdefault(key, value)
        if recorder is not None:
            result['recording'] = recorder.stats
            recording_complete = recorder.complete
        try:
            flash('build', 'restore-flash.log')
            time.sleep(.3)
            with serial.Serial(args.data_port, 115200, timeout=.05, write_timeout=1) as data:
                restored = request_status(data)
                check('restored normal STATUS zero', not any(restored.values()))
                if any(restored.values()):
                    raise AssertionError('restored normal STATUS zero')
                (args.output / 'restored-status.json').write_text(json.dumps(restored, indent=2) + '\n')
        except BaseException as error:
            restore_failure = repr(error)
        result.update({'failure': failure, 'restore_failure': restore_failure, 'checks': checks,
                       'host_input_interruption': host_input_interruption,
                       'run_completed': run_completed, 'recording_complete': recording_complete,
                       'duration_s': args.duration, 'sent_wire_bytes': sent_wire_bytes,
                       'console_complete': snapshot_parser.incomplete_summaries == 0 and
                                           snapshot_parser.current is None and not snapshot_parser.pending.strip(),
                       'console_incomplete_summaries': snapshot_parser.incomplete_summaries,
                       'console_boots': snapshot_parser.boots, 'console_faults': snapshot_parser.faults})
        result.update(evaluate_acceptance(result, snapshot_parser.snapshots))
        (args.output / 'performance.json').write_text(json.dumps(snapshot_parser.snapshots, indent=2) + '\n')
        (args.output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2), flush=True)
    return 0 if result['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-port', required=True)
    parser.add_argument('--console-port', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--west', default='west')
    parser.add_argument('--git', default='git')
    parser.add_argument('--duration', type=int, default=1800)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--pc-rtt-p99-ms', type=float, default=20.0, help='Diagnostic host RTT p99 limit; not a board pass gate (default: 20ms)')
    parser.add_argument('--pc-rtt-max-ms', type=float, default=100.0, help='Diagnostic host RTT maximum; not a board pass gate (default: 100ms)')
    args = parser.parse_args()
    for limit in (args.pc_rtt_p99_ms, args.pc_rtt_max_ms):
        if limit is not None and (not math.isfinite(limit) or limit <= 0):
            parser.error('PC RTT budgets must be finite and positive')
    if args.pc_rtt_p99_ms > 20 or args.pc_rtt_max_ms > 100:
        parser.error('PC RTT budgets cannot exceed the project 20ms/100ms limits')
    if not 10 <= args.duration <= 3600:
        parser.error('duration must be 10..3600 seconds')
    raise SystemExit(run(args))


if __name__ == '__main__':
    main()
