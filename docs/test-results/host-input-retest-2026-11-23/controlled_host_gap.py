"""Pause only our bench process to verify real-board host-interruption handling."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
WORKSPACE = Path('/Users/yuseungjae/zephyrproject')
CAPTURE = OUT / 'controlled-host-gap'
command = [str(WORKSPACE / '.venv/bin/python'),
           'fcc_app/tests/test_perf_monitor/board_check.py',
           '--data-port', '/dev/cu.usbserial-A5069RR4',
           '--console-port', '/dev/cu.usbmodem11203',
           '--workspace', str(WORKSPACE), '--west', str(WORKSPACE / '.venv/bin/west'),
           '--git', '/usr/bin/git', '--output', str(CAPTURE), '--duration', '30']
evidence = {'kind': 'controlled host process pause on a real board',
            'started_utc': datetime.now(timezone.utc).isoformat(), 'command': command,
            'requested_pause_s': 1.2, 'passed': False}
with (OUT / 'controlled-host-gap.log').open('x') as stream:
    process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    paused = False
    try:
        deadline = time.monotonic() + 90
        samples = CAPTURE / 'session/samples.csv'
        while process.poll() is None and time.monotonic() < deadline:
            if samples.exists() and len(samples.read_text().splitlines()) >= 101:
                break
            time.sleep(.25)
        else:
            raise RuntimeError('Bench did not reach 100 recorded measurements')
        evidence['child_pid'] = process.pid
        evidence['stop_monotonic_s'] = time.monotonic()
        os.kill(process.pid, signal.SIGSTOP)
        paused = True
        try:
            time.sleep(evidence['requested_pause_s'])
        finally:
            os.kill(process.pid, signal.SIGCONT)
            paused = False
            evidence['continue_monotonic_s'] = time.monotonic()
        evidence['signal_interval_s'] = evidence['continue_monotonic_s'] - evidence['stop_monotonic_s']
        evidence['returncode'] = process.wait(timeout=120)
        result = json.loads((CAPTURE / 'results.json').read_text())
        evidence['checks'] = {
            'bench_returns_nonzero': evidence['returncode'] == 1,
            'interruption_recorded': bool(result['host_input_interruption']),
            'no_runtime_board_failure': result['failure'] is None,
            'normal_image_restored': result['restore_failure'] is None and
                any(c['name'] == 'restored normal STATUS zero' and c['passed'] for c in result['checks']),
            'board_inconclusive': result['board_qualification']['status'] == 'inconclusive',
            'requested_profile_inconclusive': result['requested_profile_qualification']['status'] == 'inconclusive',
            'load_not_completed_or_passed': not result['run_completed'] and not result['passed'],
        }
        evidence['passed'] = all(evidence['checks'].values())
        if not evidence['passed']:
            raise AssertionError('Controlled pause verdict mismatch; inspect captured results')
    finally:
        if paused:
            os.kill(process.pid, signal.SIGCONT)
        if process.poll() is None:
            # Let the bench execute its normal finally/restoration path.
            process.send_signal(signal.SIGINT)
            process.wait(timeout=120)
        (OUT / 'controlled-host-gap-check.json').write_text(json.dumps(evidence, indent=2) + '\n')
print(json.dumps(evidence, indent=2))
