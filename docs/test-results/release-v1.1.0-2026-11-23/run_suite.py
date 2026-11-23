"""Run the automated v1.1.0 board regression serially; retain every stage log."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
WORKSPACE = Path.home() / 'zephyrproject'
PYTHON = str(WORKSPACE / '.venv/bin/python')
WEST = str(WORKSPACE / '.venv/bin/west')
DATA = '/dev/cu.usbserial-A5069RR4'
CONSOLE = '/dev/cu.usbmodem11203'
state = {'started_utc': datetime.now(timezone.utc).isoformat(), 'complete': False, 'stages': []}


def save():
    (OUT/'suite.json').write_text(json.dumps(state, indent=2)+'\n')


def run(name, command, *, cwd=ROOT, timeout=3600):
    entry = {'name': name, 'command': command, 'started_utc': datetime.now(timezone.utc).isoformat(),
             'status': 'running'}
    state['stages'].append(entry)
    save()
    print(f'START {name}', flush=True)
    start = time.monotonic()
    with (OUT/f'{name}.log').open('w') as stream:
        result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                timeout=timeout, env={**os.environ, 'QT_QPA_PLATFORM':'offscreen', 'PYTHONUNBUFFERED':'1'})
    entry.update(returncode=result.returncode, elapsed_s=time.monotonic()-start,
                 status='passed' if result.returncode==0 else 'failed')
    save()
    print(f'END {name}: {entry["status"]}', flush=True)
    if result.returncode:
        raise RuntimeError(f'{name} failed; inspect {OUT/name}.log')


def flash(name):
    run(name, [WEST,'flash','-d',str(ROOT/'build'),'--runner','openocd'],cwd=WORKSPACE,timeout=90)


try:
    for build in ('build','build_debug','build_perf','build_log_stress','build_transport_stress'):
        run(f'compile-{build}', [WEST,'build','-d',str(ROOT/build)], cwd=WORKSPACE, timeout=180)
    run('perf-smoke',[PYTHON,'fcc_app/tests/test_perf_monitor/board_check.py',
        '--data-port',DATA,'--console-port',CONSOLE,'--output',str(OUT/'perf-smoke'),
        '--workspace',str(WORKSPACE),'--west',WEST,'--git','/usr/bin/git','--duration','10','--smoke'],timeout=120)
    for suffix, extra in [('status',[]),('track',['--track-controls'])]:
        run(f'transport-{suffix}',[PYTHON,'fcc_app/tests/transport_stress/board_check.py',
            '--data-port',DATA,'--console-port',CONSOLE,'--output',str(OUT/f'transport-{suffix}'),
            '--workspace',str(WORKSPACE),'--west',WEST,*extra],timeout=180)
    for mode, build in [('traffic','build_debug'),('producer','build_log_stress')]:
        run(f'logs-{mode}',[PYTHON,'fcc_app/tests/log_stress/board_check.py','--mode',mode,
            '--build-dir',build,'--output-dir',str(OUT/f'logs-{mode}'),'--data-port',DATA,
            '--console-port',CONSOLE,'--west',WEST,'--zephyr-workspace',str(WORKSPACE)],timeout=180)
    flash('restore-before-evaluation')
    for scenario in ('normal','noisy','dropout'):
        run(f'evaluate-{scenario}',[PYTHON,'-m','pc_sim.evaluate','run','--port',DATA,
            '--scenario',scenario,'--output',str(OUT/f'evaluate-{scenario}')],timeout=60)
    run('noise-sweep',[PYTHON,'-m','pc_sim.noise_sweep','--port',DATA,'--output',str(OUT/'noise')],timeout=2400)
    run('spike-sweep',[PYTHON,'-m','pc_sim.spike_sweep','--port',DATA,'--output',str(OUT/'spike')],timeout=1200)
    run('perf-load',[PYTHON,'fcc_app/tests/test_perf_monitor/board_check.py',
        '--data-port',DATA,'--console-port',CONSOLE,'--output',str(OUT/'perf-load'),
        '--workspace',str(WORKSPACE),'--west',WEST,'--git','/usr/bin/git','--duration','1800'],timeout=1920)
    state['complete'] = True
except Exception as error:
    state['failure'] = repr(error)
finally:
    try:
        flash('restore-final')
        run('final-smoke',[PYTHON,str(OUT/'final_smoke.py')],timeout=30)
    except Exception as error:
        state['restore_failure'] = repr(error)
    state['passed'] = state['complete'] and not state.get('failure') and not state.get('restore_failure')
    save()
    print(json.dumps(state,indent=2),flush=True)
raise SystemExit(0 if state['passed'] else 1)
