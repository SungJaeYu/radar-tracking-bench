"""Add northbound-away then eastbound turn inputs, preserving each saved noise draw."""
from copy import deepcopy
from dataclasses import replace
import argparse
import gzip
import json
import math
from pathlib import Path
import shutil
import struct

import prepare
from pc_sim.simulation.prepared_input import PreparedInput
from pc_sim.storage.prepared_storage import load_input, save_input
from pc_sim.transport.protocol import build_measurement_frame_from_radians


def transform(original: PreparedInput) -> PreparedInput:
    metadata = deepcopy(original.metadata)
    initial = metadata['initial_target']
    initial_y = initial['y_m']
    if initial['x_m'] != 0 or initial['vy_mps'] != 0:
        raise ValueError('Expected the original eastbound initial geometry')
    initial['vx_mps'], initial['vy_mps'] = 0, initial['vx_mps']
    samples = []
    for sample in original.samples:
        x_m, y_m = initial_y - sample.truth_y_m, initial_y + sample.truth_x_m
        vx_mps, vy_mps = -sample.truth_vy_mps, sample.truth_vx_mps
        radius, angle = math.hypot(x_m,y_m), math.atan2(x_m,y_m)
        # Preserve additive pre-quantization errors; geometry alone changes.
        measured_range = radius + sample.measured_range_m - sample.truth_range_m
        measured_angle = angle + sample.measured_azimuth_rad - sample.truth_azimuth_rad
        frame = build_measurement_frame_from_radians(sample.timestamp_ms,measured_range,measured_angle)
        _, wire_range, wire_angle = struct.unpack('>IHi',frame[3:-2])
        samples.append(replace(sample,truth_x_m=x_m,truth_y_m=y_m,
                               truth_vx_mps=vx_mps,truth_vy_mps=vy_mps,
                               truth_range_m=radius,truth_azimuth_rad=angle,
                               measured_range_m=measured_range,measured_azimuth_rad=measured_angle,
                               wire_range_m=wire_range,wire_azimuth_sc=wire_angle,frame=frame))
    # Check receding truth, including the entire turn, independently of sensor noise.
    assert all(b.truth_range_m > a.truth_range_m for a,b in zip(samples,samples[1:]))
    assert all(s.truth_x_m*s.truth_vx_mps+s.truth_y_m*s.truth_vy_mps > 0 for s in samples)
    assert samples[0].truth_vx_mps == 0 and samples[0].truth_vy_mps == 200
    assert math.isclose(samples[-1].truth_vx_mps,200,abs_tol=1e-9)
    assert abs(samples[-1].truth_vy_mps)<1e-9
    return PreparedInput(metadata,tuple(samples))


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording',type=Path)
    base=parser.parse_args().recording.resolve()
    shutil.copy2(__file__,base/'add_outbound.py')
    plan=json.loads((base/'plan.json').read_text())
    if 'outbound_extension' in plan:
        raise ValueError('Outward cases already added')
    shutil.copy2(base/'plan.json',base/'plan-before-outbound.json')
    cases=[]
    geometry=[]
    for case in plan['cases']:
        original=load_input(base/'inputs'/case['case'])
        prepared=transform(original)
        new_case='outbound-'+case['case']
        save_input(base/'inputs'/new_case,prepared)
        cases.append(dict(case,case=new_case,geometry='outbound',source_case=case['case']))
        geometry.append(dict(case=new_case,start_range_m=prepared.samples[0].truth_range_m,
                             end_range_m=prepared.samples[-1].truth_range_m,
                             min_range_step_m=min(b.truth_range_m-a.truth_range_m
                                                  for a,b in zip(prepared.samples,prepared.samples[1:]))))
        plan['input_sha256'][new_case]={name:prepare.sweep.digest(base/'inputs'/new_case/name)
                                       for name in ['metadata.json','samples.jsonl']}
    for case in plan['cases']:
        case.update(geometry='original',source_case=case['case'])
    plan['cases'].extend(cases)
    extension=[]
    for index,case in enumerate(['outbound-baseline42','outbound-nominal6','outbound-strong6']):
        order=prepare.VARIANTS[index:]+prepare.VARIANTS[:index]
        extension.extend(dict(variant=name,case=case) for name,_ in order)
    plan['board_plan']=extension+plan['board_plan']
    plan['outbound_extension']=dict(script_sha256=prepare.sweep.digest(Path(__file__)),
                                    noise_draws_preserved=True,geometry=geometry,
                                    board_subset_fixed_before_outbound_results=True)
    prepare.dump(base/'plan.json',plan)
    summaries=[]
    traces=[]
    for variant,q in prepare.VARIANTS:
        library=base/'host-build'/variant/('replay.dylib' if prepare.sys.platform=='darwin' else 'replay.so')
        for case in cases:
            rows,_=prepare.sweep.replay(library,load_input(base/'inputs'/case['case']),case['case'],q)
            for row in rows:
                row.update(variant=variant)
            result=prepare.sweep.summarize(rows)
            result.update(variant=variant,profile=case['profile'],seed=case['seed'],role=case['role'])
            summaries.append(result)
            traces.extend(rows)
        print('OUTBOUND HOST DONE',variant,len(cases),flush=True)
    for case in cases:
        subsets={name:{r['timestamp_ms']:r for r in traces if r['case']==case['case']
                       and r['variant']==name and r['eligible']} for name,_ in prepare.VARIANTS}
        common=set.intersection(*(set(rows) for rows in subsets.values()))
        for result in summaries:
            if result['case']==case['case']:
                result.update(common_count=len(common),common_rmse_m=prepare.sweep.rmse(
                    [subsets[result['variant']][stamp] for stamp in sorted(common)]))
    prepare.dump(base/'outbound-host-summary.json',summaries)
    (base/'outbound-host-summary.csv').write_text(prepare.sweep.csv_text(summaries))
    (base/'outbound-host-series.csv.gz').write_bytes(gzip.compress(prepare.sweep.csv_text(traces).encode(),mtime=0))
    print('OUTBOUND COMPLETE',len(summaries),'host runs; BOARD TOTAL',len(plan['board_plan']),flush=True)


if __name__=='__main__':
    main()
