"""Freeze two post-hoc gate diagnostics separately from the primary comparison."""
import argparse
import json
from pathlib import Path
import shutil

import prepare


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('primary',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    source,out=args.primary,args.output
    out.mkdir(parents=True,exist_ok=False)
    # Keep a self-contained input/host bundle for the same auditing tools.
    shutil.copytree(source/'inputs',out/'inputs')
    for name in ['host-summary.json','host-summary.csv','host-series.csv.gz','host-manifest.json',
                 'outbound-host-summary.json','outbound-host-summary.csv','outbound-host-series.csv.gz',
                 'input-checks.json']:
        shutil.copy2(source/name,out/name)
    plan=json.loads((source/'plan.json').read_text())
    plan['board_plan']=[dict(variant='ekf30000',case=case)
                        for case in ['strong10','outbound-strong10']]
    plan['board_subset_fixed_before_host_results']=False
    plan['diagnostic_selection']={
        'role':'post_hoc_diagnostic',
        'reason':'Host q=30000 rejects one measurement at sensor31.5s in strong-noise seed10 for each geometry',
        'primary_plan_sha256':prepare.sweep.digest(source/'plan.json'),
        'excluded_from_primary_comparison':True,
    }
    prepare.dump(out/'plan.json',plan)
    shutil.copy2(__file__,out/'prepare_diagnostic.py')
    print('Prepared separate diagnostic board runs:',len(plan['board_plan']))


if __name__=='__main__':
    main()
