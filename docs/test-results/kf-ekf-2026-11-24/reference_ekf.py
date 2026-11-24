"""Compare board estimates with an independent NumPy float64 CV-EKF calculation.

This covers the two recorded runs with no gate rejection or track restart, not
all tracker states or arbitrary inputs. It never sends measurements to hardware.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import numpy as np

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('recording',type=Path)
parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent)
args=parser.parse_args()
manifest=json.loads((args.recording/'manifest.json').read_text())
results={}
all_rows=[]
for run in manifest['runs']:
    if run['estimator']!='ekf':continue
    assert run['result']['gate_rejected']==0 and run['result']['track_starts']==1
    case=run['case']
    samples=[json.loads(line) for line in (args.recording/'inputs'/case/'samples.jsonl').read_text().splitlines()]
    with (args.recording/run['session']/'reports.csv').open() as stream:
        reports={int(r['input_timestamp_ms']):r for r in csv.DictReader(stream) if int(r['flags'])&1}
    first=samples[0]
    radius=first['wire_range_m'];theta=first['wire_azimuth_sc']*math.pi/(2**31)
    sine,cosine=math.sin(theta),math.cos(theta)
    jacobian=np.array([[sine,radius*cosine,0,0],[cosine,-radius*sine,0,0],
                       [0,0,sine,radius*cosine],[0,0,cosine,-radius*sine]])
    covariance=jacobian@np.diag([25,.00121847,10000,.03046174])@jacobian.T
    state=np.array([radius*sine,radius*cosine,0.,0.])
    noise=np.diag([25.,.00121847])
    differences=[];errors=[];min_eigenvalue=float('inf');previous=first['timestamp_ms']
    for index,sample in enumerate(samples):
        stamp=sample['timestamp_ms']
        measurement=np.array([sample['wire_range_m'],sample['wire_azimuth_sc']*math.pi/(2**31)])
        if index:
            dt=(stamp-previous)/1000
            transition=np.eye(4);transition[0,2]=dt;transition[1,3]=dt
            acceleration=np.array([[dt*dt/2,0],[0,dt*dt/2],[dt,0],[0,dt]])
            state=transition@state
            covariance=transition@covariance@transition.T+100*(acceleration@acceleration.T)
            x,y=state[:2];r=math.hypot(x,y)
            model=np.array([r,math.atan2(x,y)])
            h=np.array([[x/r,y/r,0,0],[y/(r*r),-x/(r*r),0,0]])
            innovation=measurement-model
            innovation[1]=(innovation[1]+math.pi)%(2*math.pi)-math.pi
            s=h@covariance@h.T+noise
            gain=np.linalg.solve(s,(covariance@h.T).T).T
            state=state+gain@innovation
            attenuation=np.eye(4)-gain@h
            covariance=attenuation@covariance@attenuation.T+gain@noise@gain.T
            covariance=(covariance+covariance.T)/2
        min_eigenvalue=min(min_eigenvalue,float(np.linalg.eigvalsh(covariance)[0]))
        previous=stamp
        report=reports[stamp]
        assert int(report['flags'])&2 and int(report['estimate_timestamp_ms'])==stamp
        r,a=float(report['range_m']),float(report['azimuth_rad'])
        bx,by=r*math.sin(a),r*math.cos(a)
        difference=math.hypot(state[0]-bx,state[1]-by)
        error=math.hypot(state[0]-sample['truth_x_m'],state[1]-sample['truth_y_m'])
        differences.append(difference)
        if stamp>=2000:errors.append(error)
        all_rows.append(dict(case=case,sensor_ms=stamp,x_m=state[0],y_m=state[1],
                             board_difference_m=difference,truth_error_m=error))
    results[case]={'samples':len(samples),'max_board_position_difference_m':max(differences),
                   'rmse_board_position_difference_m':math.sqrt(sum(v*v for v in differences)/len(differences)),
                   'reference_position_rmse_after_2s_m':math.sqrt(sum(e*e for e in errors)/len(errors)),
                   'minimum_reference_covariance_eigenvalue':min_eigenvalue}
assert set(results)=={'baseline','noisy'}
assert all(r['max_board_position_difference_m']<.1 and r['minimum_reference_covariance_eigenvalue']>0 for r in results.values())
args.output.mkdir(parents=True,exist_ok=True)
(args.output/'reference-ekf.json').write_text(json.dumps(results,indent=2)+'\n')
with (args.output/'reference-ekf.csv').open('w') as stream:
    writer=csv.DictWriter(stream,fieldnames=all_rows[0].keys(),lineterminator='\n');writer.writeheader();writer.writerows(all_rows)
print(json.dumps(results,indent=2))
