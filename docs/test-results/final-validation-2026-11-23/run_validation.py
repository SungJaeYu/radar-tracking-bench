"""Re-run existing board checks without changing their acceptance criteria."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
WORKSPACE = Path('/Users/yuseungjae/zephyrproject')
PYTHON = str(WORKSPACE / '.venv/bin/python')
WEST = str(WORKSPACE / '.venv/bin/west')
DATA = '/dev/cu.usbserial-A5069RR4'
CONSOLE = '/dev/cu.usbmodem11203'
state = {'started_utc': datetime.now(timezone.utc).isoformat(), 'complete': False, 'stages': [],
         'scope': 'current firmware regression and 1800-second PERF load',
         'prior_evidence_not_rerun': ['100-run noise sweep', '49-run spike sweep']}


def save():
    (OUT / 'suite.json').write_text(json.dumps(state, indent=2) + '\n')


def run(name, command, *, cwd=ROOT, timeout=180):
    entry = {'name': name, 'command': command, 'started_utc': datetime.now(timezone.utc).isoformat(),
             'status': 'running'}
    state['stages'].append(entry)
    save()
    print(f'START {name}', flush=True)
    start = time.monotonic()
    with (OUT / f'{name}.log').open('x') as stream:
        result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                timeout=timeout, env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                                     'PYTHONUNBUFFERED': '1'})
    entry.update(returncode=result.returncode, elapsed_s=time.monotonic() - start,
                 status='passed' if result.returncode == 0 else 'failed')
    save()
    print(f'END {name}: {entry["status"]}', flush=True)
    if result.returncode:
        raise RuntimeError(f'{name} failed; see {name}.log')


def restore(name):
    run(name, [WEST, 'flash', '-d', str(ROOT / 'build'), '--runner', 'openocd'],
        cwd=WORKSPACE, timeout=90)


try:
    for suffix, extra in [('status', []), ('track', ['--track-controls'])]:
        run(f'transport-{suffix}', [PYTHON, 'fcc_app/tests/transport_stress/board_check.py',
            '--data-port', DATA, '--console-port', CONSOLE, '--output', str(OUT / f'transport-{suffix}'),
            '--workspace', str(WORKSPACE), '--west', WEST, *extra])
    for mode, build in [('traffic', 'build_debug'), ('producer', 'build_log_stress')]:
        run(f'logs-{mode}', [PYTHON, 'fcc_app/tests/log_stress/board_check.py', '--mode', mode,
            '--build-dir', build, '--output-dir', str(OUT / f'logs-{mode}'), '--data-port', DATA,
            '--console-port', CONSOLE, '--west', WEST, '--zephyr-workspace', str(WORKSPACE)])
    restore('restore-before-evaluation')
    for scenario in ('normal', 'noisy', 'dropout'):
        run(f'evaluate-{scenario}', [PYTHON, '-m', 'pc_sim.evaluate', 'run', '--port', DATA,
            '--scenario', scenario, '--output', str(OUT / f'evaluate-{scenario}')], timeout=60)
    run('turn', [PYTHON, 'docs/test-results/turn-2026-11-23/board_check.py', '--port', DATA,
                 '--console', CONSOLE, '--output', str(OUT / 'turn')])
    run('turn-audit', [PYTHON, 'docs/test-results/turn-2026-11-23/analyze.py', str(OUT / 'turn')])
    run('protocol-errors', [PYTHON, str(OUT / 'protocol_errors.py')], timeout=30)
    run('perf-load', [PYTHON, 'fcc_app/tests/test_perf_monitor/board_check.py',
        '--data-port', DATA, '--console-port', CONSOLE, '--output', str(OUT / 'perf-load'),
        '--workspace', str(WORKSPACE), '--west', WEST, '--git', '/usr/bin/git',
        '--duration', '1800'], timeout=1920)
    run('perf-audit', [PYTHON, 'docs/test-results/extended-perf-2026-11-23/audit.py',
                      str(OUT / 'perf-load')])
    perf = json.loads((OUT / 'perf-load/results.json').read_text())
    state['board_qualification'] = perf['board_qualification']
    state['requested_profile_qualification'] = perf['requested_profile_qualification']
    state['complete'] = True
except Exception as error:
    state['failure'] = repr(error)
finally:
    try:
        restore('restore-final')
        run('final-smoke', [PYTHON, str(OUT / 'final_smoke.py')], timeout=30)
    except Exception as error:
        state['restore_failure'] = repr(error)
    state['passed'] = state['complete'] and not state.get('failure') and not state.get('restore_failure')
    state['release_profile_verified'] = state['passed'] and state.get('requested_profile_qualification', {}).get('status') == 'passed'
    save()
    print(json.dumps(state, indent=2), flush=True)
raise SystemExit(0 if state['passed'] else 1)
