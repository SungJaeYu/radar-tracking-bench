"""Prepare independent-seed Q validation inputs and replay production C on the host."""
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
from pc_sim.simulation.prepared_input import InputSettings, generate_input
from pc_sim.storage.prepared_storage import load_input, save_input

spec = importlib.util.spec_from_file_location('q_sweep', HERE.parent/'ekf-q-2026-11-24/sweep.py')
sweep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sweep)
VARIANTS = [('kf', None), ('ekf100', 100), ('ekf10000', 10000), ('ekf30000', 30000)]
PROFILES = [('range', 10, 0), ('angle', 0, .01), ('nominal', 10, .01), ('strong', 20, .02)]
BOARD_CASES = ['baseline42', 'nominal42', 'nominal3', 'nominal6', 'nominal9',
               'range6', 'angle6', 'strong6']


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def compile_variant(name: str, q: int | None, build: Path):
    build.mkdir(parents=True, exist_ok=True)
    library = build/('replay.dylib' if sys.platform == 'darwin' else 'replay.so')
    sources = list(sweep.SOURCES)
    definitions = [value for value in sweep.DEFINITIONS if 'CONFIG_RADAR_ESTIMATOR_' not in value]
    if q is None:
        sources[sources.index(sweep.ADAPTER)] = 'fcc_app/src/tracking/estimators/polar_cv_kf.c'
        sources[sources.index('fcc_app/src/tracking/estimators/filters/ekf_cv_2d.c')] = \
            'fcc_app/src/tracking/estimators/filters/kf_cv_1d.c'
        definitions.append('CONFIG_RADAR_ESTIMATOR_KF_CV=1')
    else:
        definitions.extend(['CONFIG_RADAR_ESTIMATOR_EKF_CV=1', f'{sweep.Q_SYMBOL}={q}'])
    command = ['/usr/bin/clang', '-shared', '-fPIC', '-O0', '-ffp-contract=off', '-std=c11',
               '-Wall', '-Wextra', '-Werror', *['-I'+str(path) for path in sweep.INCLUDES],
               *['-D'+value for value in definitions], *[str(REPO/source) for source in sources],
               '-lm', '-o', str(library)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    return library, dict(name=name, q=q, command=command, library_sha256=sweep.digest(library),
                         sources={source:sweep.digest(REPO/source) for source in sources})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prior-inputs', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    shutil.copy2(__file__, out/'prepare.py')
    cases = []
    for case, previous in [('baseline42', 'baseline'), ('nominal42', 'noisy')]:
        shutil.copytree(args.prior_inputs/previous, out/'inputs'/case)
        prepared = load_input(out/'inputs'/case)
        cases.append(dict(case=case, profile='baseline' if previous=='baseline' else 'nominal',
                          seed=42, role='selection_control', settings=prepared.metadata['settings']))
    for seed in range(1, 11):
        for profile, range_std_m, angle_std_rad in PROFILES:
            case = profile+str(seed)
            settings = InputSettings(scenario='straight_turn_straight', duration_s=80, dt_s=.1,
                                     range_noise_std_m=range_std_m,
                                     azimuth_noise_std_rad=angle_std_rad, seed=seed)
            prepared = generate_input(settings)
            save_input(out/'inputs'/case, prepared)
            cases.append(dict(case=case, profile=profile, seed=seed, role='independent_seed',
                              settings=prepared.metadata['settings']))
    # Fix the board subset before examining host results; rotate variant order per case.
    board_plan = []
    for index, case in enumerate(BOARD_CASES):
        order = VARIANTS[index % 4:] + VARIANTS[:index % 4]
        board_plan.extend(dict(variant=variant, case=case) for variant, _ in order)
    plan = dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
                variants=[dict(name=name,q=q,build_directory='build_q_'+name) for name,q in VARIANTS],
                cases=cases, board_plan=board_plan, board_subset_fixed_before_host_results=True,
                input_sha256={case['case']:{name:sweep.digest(out/'inputs'/case['case']/name)
                                           for name in ['metadata.json','samples.jsonl']} for case in cases})
    dump(out/'plan.json',plan)
    summary, traces, builds = [], [], []
    for variant, q in VARIANTS:
        library, build = compile_variant(variant,q,out/'host-build'/variant)
        builds.append(build)
        for case in cases:
            prepared = load_input(out/'inputs'/case['case'])
            rows, _ = sweep.replay(library,prepared,case['case'],q)
            for row in rows:
                row['variant'] = variant
            result = sweep.summarize(rows)
            result.update(variant=variant,profile=case['profile'],seed=case['seed'],role=case['role'])
            summary.append(result)
            traces.extend(rows)
        print('HOST DONE',variant,len(cases),flush=True)
    for case in cases:
        by_variant = {variant:{row['timestamp_ms']:row for row in traces
                               if row['case']==case['case'] and row['variant']==variant and row['eligible']}
                      for variant,_ in VARIANTS}
        common = set.intersection(*(set(rows) for rows in by_variant.values()))
        for result in summary:
            if result['case']==case['case']:
                result.update(common_count=len(common),
                              common_rmse_m=sweep.rmse([by_variant[result['variant']][stamp]
                                                       for stamp in sorted(common)]))
    headers = {str(path.relative_to(REPO)):sweep.digest(path)
               for directory in sweep.INCLUDES for path in directory.rglob('*.h')}
    dump(out/'host-manifest.json',dict(builds=builds,headers=headers,
                                      compiler=subprocess.check_output(['/usr/bin/clang','--version'],text=True)))
    dump(out/'host-summary.json',summary)
    (out/'host-summary.csv').write_text(sweep.csv_text(summary))
    (out/'host-series.csv.gz').write_bytes(gzip.compress(sweep.csv_text(traces).encode(),mtime=0))
    print('HOST COMPLETE',len(summary),'runs',len(traces),'samples; BOARD',len(board_plan),'runs',flush=True)


if __name__ == '__main__':
    main()
