"""Reintegrate saved outbound motion and verify preserved noise and wire bytes."""
import argparse
import json
import math
from pathlib import Path

import prepare
from pc_sim.storage.prepared_storage import load_input
from pc_sim.simulation.targets import Target, MotionSegment, SegmentedScenario


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording',type=Path)
    args=parser.parse_args()
    base=args.recording
    plan=json.loads((base/'plan.json').read_text())
    count=0
    maximum_position_m=maximum_range_noise_m=maximum_angle_noise_rad=0
    geometry=[]
    for case in plan['cases']:
        prepared=load_input(base/'inputs'/case['case'])
        for filename,digest in plan['input_sha256'][case['case']].items():
            assert prepare.sweep.digest(base/'inputs'/case['case']/filename)==digest
        assert len(prepared.samples)==755 and all(s.frame is not None for s in prepared.samples)
        if case['geometry']!='outbound':
            continue
        original=load_input(base/'inputs'/case['source_case'])
        scenario=SegmentedScenario(Target(**prepared.metadata['initial_target']),
                                   [MotionSegment(**segment) for segment in prepared.metadata['segments']])
        for before,after in zip(original.samples,prepared.samples):
            difference=math.hypot(after.truth_x_m-scenario.target.x_m,
                                  after.truth_y_m-scenario.target.y_m)
            range_difference=abs((before.measured_range_m-before.truth_range_m)-
                                 (after.measured_range_m-after.truth_range_m))
            angle_difference=abs((before.measured_azimuth_rad-before.truth_azimuth_rad)-
                                 (after.measured_azimuth_rad-after.truth_azimuth_rad))
            maximum_position_m=max(maximum_position_m,difference)
            maximum_range_noise_m=max(maximum_range_noise_m,range_difference)
            maximum_angle_noise_rad=max(maximum_angle_noise_rad,angle_difference)
            assert difference<1e-7 and range_difference<2e-10 and angle_difference<1e-12
            assert math.isclose(math.hypot(after.truth_vx_mps,after.truth_vy_mps),200,abs_tol=1e-9)
            assert after.truth_x_m*after.truth_vx_mps+after.truth_y_m*after.truth_vy_mps>0
            scenario.update(.1)
            count+=1
        increments=[b.truth_range_m-a.truth_range_m for a,b in zip(prepared.samples,prepared.samples[1:])]
        assert min(increments)>0
        geometry.append(dict(case=case['case'],start_range_m=prepared.samples[0].truth_range_m,
                             end_range_m=prepared.samples[-1].truth_range_m,min_range_step_m=min(increments)))
    result=dict(inputs_validated=len(plan['cases']),outbound_samples_reintegrated=count,
                max_position_difference_m=maximum_position_m,
                max_preserved_range_noise_difference_m=maximum_range_noise_m,
                max_preserved_angle_noise_difference_rad=maximum_angle_noise_rad,geometry=geometry)
    prepare.dump(base/'input-checks.json',result)
    print(json.dumps({key:value for key,value in result.items() if key!='geometry'}))


if __name__=='__main__':
    main()
