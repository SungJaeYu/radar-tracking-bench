"""Tune CT on seed42 only, freeze, then replay the existing 84 saved inputs."""
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from pc_sim.storage.prepared_storage import load_input
spec = importlib.util.spec_from_file_location('previous_prepare', HERE.parent/'ekf-q-board-2026-11-24/prepare.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
sweep, dump = previous.sweep, previous.dump
ACC = 'CONFIG_RADAR_CT_ACCELERATION_VARIANCE_M_SQUARED_PER_S_FOURTH'
ALPHA = 'CONFIG_RADAR_CT_ANGULAR_ACCELERATION_VARIANCE_RAD_SQUARED_PER_S_FOURTH_SCALED_1E9'
OMEGA = 'CONFIG_RADAR_CT_INITIAL_TURN_RATE_VARIANCE_RAD_SQUARED_PER_S_SQUARED_SCALED_1E9'


def compile_ct(acc, alpha_scaled, build):
    build.mkdir(parents=True, exist_ok=True)
    library = build/'replay.dylib'
    sources = [source.replace('cartesian_cv_ekf.c', 'cartesian_ct_ekf.c').replace('ekf_cv_2d.c', 'ekf_ct_2d.c') for source in sweep.SOURCES]
    definitions = [v for v in sweep.DEFINITIONS if 'CONFIG_RADAR_ESTIMATOR_' not in v]
    definitions += ['CONFIG_RADAR_ESTIMATOR_EKF_CT=1', 'MATRIX_MAX_ROWS=5U', 'MATRIX_MAX_COLUMNS=5U',
                    f'{ACC}={acc}', f'{ALPHA}={alpha_scaled}', f'{OMEGA}=10000000']
    command = ['/usr/bin/clang', '-shared', '-fPIC', '-O0', '-ffp-contract=off', '-std=c11', '-Wall', '-Wextra', '-Werror',
               *['-I'+str(p) for p in sweep.INCLUDES], *['-D'+v for v in definitions],
               *[str(REPO/p) for p in sources], '-lm', '-o', str(library)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    return library, dict(command=command, library_sha256=sweep.digest(library), sources={p:sweep.digest(REPO/p) for p in sources})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    old = json.loads((args.prior/'plan.json').read_text())
    shutil.copytree(args.prior/'inputs', out/'inputs')
    cases = old['cases']
    assert len(cases) == 84
    tuning, builds = [], []
    candidates = []
    for acc in [10, 100, 1000]:
        for alpha in [1000, 100000, 10000000]:
            library, build = compile_ct(acc, alpha, out/'host-build'/f'ct-{acc}-{alpha}')
            builds.append(build)
            results = []
            for case in ['baseline42', 'nominal42']:
                rows, _ = sweep.replay(library, load_input(out/'inputs'/case), case, acc)
                result = sweep.summarize(rows)
                result.update(acceleration_variance=acc, angular_acceleration_variance=alpha/1e9)
                tuning.append(result)
                results.append(result)
            if all(r['coverage'] == 1 and r['lost'] == 0 for r in results):
                candidates.append((results[1]['all_rmse_m'], acc, alpha, library))
    dump(out/'tuning.json', tuning)
    if not candidates:
        raise RuntimeError('No eligible CT candidate; retain results and stop')
    score, acc, alpha, library = min(candidates)
    frozen = dict(acceleration_variance=acc, angular_acceleration_variance_scaled_1e9=alpha,
                  initial_turn_rate_variance_scaled_1e9=10000000, selection_case='nominal42', selection_rmse_m=score,
                  rule='minimum nominal42 position RMSE after 2s; full coverage and no LOST on baseline42 and nominal42')
    dump(out/'frozen-candidate.json', frozen)
    variants = [dict(name='kf', q=None, build_directory='build_ct_kf'),
                dict(name='ekf10000', q=10000, build_directory='build_ct_cv'),
                dict(name='ct', q=acc, alpha_scaled=alpha, build_directory='build_ct_perf')]
    board_cases = [c['case'] for c in cases if c['source_case'] in ['baseline42', 'nominal6', 'strong6']]
    assert len(board_cases) == 6
    board_plan = [dict(variant=v['name'], case=c) for i,c in enumerate(board_cases) for v in variants[i%3:]+variants[:i%3]]
    plan = dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
                frozen_candidate=frozen, variants=variants, cases=cases, board_plan=board_plan,
                board_subset_fixed_before_host_results=True, input_sha256=old['input_sha256'])
    dump(out/'plan.json', plan)
    summaries, traces, unchanged = [], [], []
    for variant in variants:
        name, q = variant['name'], variant['q']
        if name != 'ct':
            lib, build = previous.compile_variant(name, q, out/'host-build'/name)
            builds.append(build)
        else:
            lib = library
        for case in cases:
            prepared = load_input(out/'inputs'/case['case'])
            rows, binary = sweep.replay(lib, prepared, case['case'], q)
            if name != 'ct':
                prior_binary = sweep.replay(args.prior/'host-build'/name/'replay.dylib', prepared, case['case'], q)[1]
                if binary != prior_binary:
                    raise RuntimeError('Existing filter changed: '+name+' '+case['case'])
                unchanged.append(dict(variant=name, case=case['case'], byte_identical=True))
            for row in rows:
                row['variant'] = name
            result = sweep.summarize(rows)
            result.update(variant=name, profile=case['profile'], seed=case['seed'], role=case['role'], geometry=case['geometry'])
            summaries.append(result)
            traces.extend(rows)
        print('HOST DONE',name,len(cases),flush=True)
    for case in cases:
        by_variant = {v['name']:{r['timestamp_ms']:r for r in traces if r['case']==case['case'] and r['variant']==v['name'] and r['eligible']} for v in variants}
        common = set.intersection(*(set(rows) for rows in by_variant.values()))
        for result in summaries:
            if result['case'] == case['case']:
                result.update(common_count=len(common), common_rmse_m=sweep.rmse([by_variant[result['variant']][t] for t in sorted(common)]))
    dump(out/'host-summary.json', summaries)
    (out/'host-summary.csv').write_text(sweep.csv_text(summaries))
    (out/'host-series.csv.gz').write_bytes(gzip.compress(sweep.csv_text(traces).encode(),mtime=0))
    dump(out/'host-manifest.json', dict(builds=builds, old_filter_checks=unchanged))
    config_dir = HERE/'configs'
    config_dir.mkdir(exist_ok=True)
    (config_dir/'ct.conf').write_text(f'CONFIG_RADAR_ESTIMATOR_EKF_CT=y\n{ACC}={acc}\n{ALPHA}={alpha}\n{OMEGA}=10000000\n')
    for name in ['kf','ekf10000']:
        shutil.copy2(HERE.parent/'ekf-q-board-2026-11-24/configs'/f'{name}.conf', config_dir/f'{name}.conf')
    print('FROZEN',json.dumps(frozen),flush=True)

if __name__ == '__main__':
    main()
