"""Replay the frozen Q campaign on STM32; restore normal KF even after failure."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))
import serial
import prepare
from pc_sim.evaluation.turn_noise import run
from pc_sim.cli.status_client import request_status
from pc_sim.storage.prepared_storage import load_input

spec=importlib.util.spec_from_file_location('perf_check',REPO/'fcc_app/tests/test_perf_monitor/board_check.py')
perf_check=importlib.util.module_from_spec(spec)
spec.loader.exec_module(perf_check)


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording',type=Path)
    parser.add_argument('--data-port',required=True)
    parser.add_argument('--console-port',required=True)
    parser.add_argument('--west',type=Path,required=True)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--preflight-only',action='store_true')
    args=parser.parse_args()
    base=args.recording.resolve()
    plan=json.loads((base/'plan.json').read_text())
    manifest=dict(source_commit=plan['source_commit'],board='stm32f746g_disco',
                  data_port=args.data_port,console_port=args.console_port,baud=115200,
                  complete=False,restored=False,runs=[],builds={},
                  plan_sha256=prepare.sweep.digest(base/'plan.json'),
                  runner_sha256=prepare.sweep.digest(Path(__file__)))
    for case,hashes in plan['input_sha256'].items():
        load_input(base/'inputs'/case)
        for name,digest in hashes.items():
            if prepare.sweep.digest(base/'inputs'/case/name)!=digest:
                raise ValueError('Input changed: '+case)
    configurations={}
    variants=plan['variants']+[dict(name='restore',q=None,build_directory='build')]
    for variant in variants:
        name=variant['name']
        build=REPO/variant['build_directory']/'zephyr'
        config=(build/'.config').read_text()
        settings=dict(line.split('=',1) for line in config.splitlines() if line.startswith('CONFIG_') and '=' in line)
        expected='KF' if variant['q'] is None else 'EKF'
        assert settings[f'CONFIG_RADAR_ESTIMATOR_{expected}_CV']=='y'
        assert (settings.get('CONFIG_RADAR_PERF_MONITOR')=='y')==(name!='restore')
        for key,value in [('CONFIG_RADAR_RANGE_GATE_M','100'),('CONFIG_RADAR_AZIMUTH_GATE_DEG','10'),
                          ('CONFIG_RADAR_MEASUREMENT_TIMEOUT_MS','1000'),
                          ('CONFIG_RADAR_RANGE_MEASUREMENT_VARIANCE_M_SQUARED','25'),
                          ('CONFIG_RADAR_AZIMUTH_MEASUREMENT_VARIANCE_RAD_SQUARED_SCALED_1E9','1218470')]:
            assert settings[key]==value,(name,key,settings[key])
        if variant['q'] is not None:
            assert settings[prepare.sweep.Q_SYMBOL]==str(variant['q'])
        configurations[name]=set(config.splitlines())
        manifest['builds'][name]=dict(directory=variant['build_directory'],q=variant['q'],
            **{filename:prepare.sweep.digest(build/filename) for filename in ['.config','zephyr.hex','zephyr.elf']})
    for name in ['ekf10000','ekf30000']:
        differences=configurations[name]^configurations['ekf100']
        assert len(differences)==2 and all(line.startswith(prepare.sweep.Q_SYMBOL+'=') for line in differences)
    print('PREFLIGHT OK',len(plan['cases']),'inputs',len(plan['board_plan']),'board runs',flush=True)
    if args.preflight_only:
        return
    board=base/'board'
    board.mkdir(exist_ok=False)
    shutil.copy2(__file__,board/'run_board.py')
    for name,build in manifest['builds'].items():
        for filename in ['.config','zephyr.hex']:
            shutil.copy2(REPO/build['directory']/'zephyr'/filename,board/(name+filename))

    def flash(name,log):
        build=manifest['builds'][name]
        for filename in ['zephyr.hex','zephyr.elf','.config']:
            if prepare.sweep.digest(REPO/build['directory']/'zephyr'/filename)!=build[filename]:
                raise RuntimeError('Build changed after preflight: '+name)
        with log.open('w') as stream:
            subprocess.run([str(args.west),'flash','-d',str(REPO/build['directory']),
                            '--skip-rebuild','--runner','openocd'],cwd=args.workspace,
                           stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=60)

    def interrupt(signum,frame):
        raise KeyboardInterrupt(f'Signal {signum}; restoring normal firmware')

    signal.signal(signal.SIGTERM,interrupt)
    caffeinate=subprocess.Popen(['/usr/bin/caffeinate','-dimsu','-w',str(os.getpid())])
    prepare.dump(board/'manifest.json',manifest)
    try:
        for index,item in enumerate(plan['board_plan']):
            name,case=item['variant'],item['case']
            trial=board/name/case
            trial.mkdir(parents=True)
            stop=threading.Event()
            errors=[]
            started=time.monotonic()
            with serial.Serial(args.console_port,115200,timeout=.1,exclusive=True) as console:
                console.reset_input_buffer()
                def capture():
                    try:
                        with (trial/'console.log').open('wb') as stream:
                            while not stop.is_set():
                                raw=console.read(4096)
                                if raw:
                                    stream.write(raw)
                                    stream.flush()
                    except BaseException as error:
                        errors.append(repr(error))
                thread=threading.Thread(target=capture)
                thread.start()
                try:
                    print('START',index+1,'/',len(plan['board_plan']),name,case,flush=True)
                    flash(name,trial/'flash.log')
                    time.sleep(1)
                    session,result=run(args.data_port,trial/'sessions',base/'inputs'/case)
                    time.sleep(6)
                finally:
                    stop.set()
                    thread.join(timeout=2)
            assert not thread.is_alive() and not errors,errors
            console_parser=perf_check.PerfConsole()
            console_parser.feed((trial/'console.log').read_text(errors='replace'))
            perf=dict(boots=console_parser.boots,faults=console_parser.faults,
                      incomplete_summaries=console_parser.incomplete_summaries,snapshots=console_parser.snapshots)
            prepare.dump(trial/'perf.json',perf)
            completed=dict(variant=name,case=case,session=str(session.relative_to(base)),
                           trial=str(trial.relative_to(base)),input_sha256=plan['input_sha256'][case],
                           result=result,elapsed_s=time.monotonic()-started)
            manifest['runs'].append(completed)
            prepare.dump(board/'manifest.json',manifest)
            assert result['integrity_ok'],result
            assert perf['boots']==1 and not perf['faults'] and not perf['incomplete_summaries'],perf
            assert perf['snapshots'],perf
            last=perf['snapshots'][-1]
            assert last['header']['measurements']==755,last['header']
            assert not any(last['header'][key] for key in ['without_submit','submit_failed','invalid_time','rx_capture_lost'])
            assert not last['queue rx']['rejected'] and not last['queue tx']['rejected'] and not last['tx']['encode_failed']
            assert last['rx_to_submit']['over20']==0
            for thread_name,margin in perf_check.STACK_MARGINS.items():
                assert min(s['stack '+thread_name]['min_unused'] for s in perf['snapshots'])>=margin
            print('DONE',index+1,name,case,json.dumps(dict(rmse_m=result['position']['all']['rmse_m'],
                  gates=result['gate_rejected'],lost=result['lost_transitions'],integrity=result['integrity_ok'])),flush=True)
        manifest['complete']=True
    except BaseException as error:
        manifest['error']=repr(error)
        raise
    finally:
        try:
            print('RESTORE normal KF',flush=True)
            flash('restore',board/'restore-flash.log')
            time.sleep(1)
            with serial.Serial(args.data_port,115200,timeout=.05,write_timeout=2,exclusive=True) as data:
                status=request_status(data)
            manifest['restore_status']=status
            manifest['restored']=not any(status.values())
            assert manifest['restored'],status
            print('RESTORED',manifest['restored'],status,flush=True)
        except BaseException as error:
            manifest['restore_error']=repr(error)
            raise
        finally:
            prepare.dump(board/'manifest.json',manifest)
            caffeinate.terminate()
            caffeinate.wait(timeout=2)


if __name__=='__main__':
    main()
