"""Explain observed q=30000 gate misses using raw measurements and coast predictions."""
import argparse
import csv
import gzip
import json
import math
from pathlib import Path

import prepare
from pc_sim.storage.prepared_storage import load_input


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('primary',type=Path)
    parser.add_argument('--diagnostic',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    summaries=[]
    windows=[]
    for prefix in ['', 'outbound-']:
        case=prefix+'strong10'
        prepared=load_input(args.primary/'inputs'/case)
        with gzip.open(args.primary/(prefix+'host-series.csv.gz'),'rt') as stream:
            host=[r for r in csv.DictReader(stream) if r['variant']=='ekf30000' and r['case']==case]
        datasets=[('host',host)]
        if args.diagnostic:
            manifest=json.loads((args.diagnostic/'board/manifest.json').read_text())
            assert manifest['complete'] and manifest['restored']
            item=next(r for r in manifest['runs'] if r['case']==case)
            with (args.diagnostic/item['session']/'reports.csv').open() as stream:
                datasets.append(('board',[dict(r,timestamp_ms=r['input_timestamp_ms'])
                                          for r in csv.DictReader(stream) if int(r['flags'])&1]))
        for origin,rows in datasets:
            by_time={int(row['timestamp_ms']):row for row in rows}
            for index,row in enumerate(rows):
                if int(row['result'])!=2:
                    continue
                stamp=int(row['timestamp_ms'])
                sample=prepared.samples[stamp//100]
                predicted_range=float(row['range_m'])
                predicted_angle=float(row['azimuth_rad'])
                measured_angle=sample.wire_azimuth_sc*math.pi/2**31
                residual_angle=(measured_angle-predicted_angle+math.pi)%(2*math.pi)-math.pi
                following=rows[index+1] if index+1<len(rows) else None
                summaries.append(dict(origin=origin,case=case,timestamp_ms=stamp,
                    range_noise_m=sample.measured_range_m-sample.truth_range_m,
                    azimuth_noise_rad=sample.measured_azimuth_rad-sample.truth_azimuth_rad,
                    quantized_range_error_m=sample.wire_range_m-sample.truth_range_m,
                    predicted_range_error_m=predicted_range-sample.truth_range_m,
                    range_gate_residual_m=sample.wire_range_m-predicted_range,
                    azimuth_gate_residual_deg=math.degrees(residual_angle),
                    state=int(row['state']),next_state=int(following['state']) if following else None,
                    next_result=int(following['result']) if following else None,
                    next_sample_sensor_delay_ms=int(following['timestamp_ms'])-stamp if following else None))
                for nearby in range(stamp-500,stamp+600,100):
                    if nearby not in by_time:
                        continue
                    value=by_time[nearby]
                    truth=prepared.samples[nearby//100]
                    windows.append(dict(origin=origin,case=case,timestamp_ms=nearby,
                                        state=value['state'],result=value['result'],
                                        truth_range_m=truth.truth_range_m,measured_wire_range_m=truth.wire_range_m,
                                        estimate_range_m=value['range_m'],
                                        range_noise_m=truth.measured_range_m-truth.truth_range_m,
                                        azimuth_noise_rad=truth.measured_azimuth_rad-truth.truth_azimuth_rad))
    args.output.mkdir(parents=True,exist_ok=True)
    prepare.dump(args.output/'gate-diagnostic.json',summaries)
    (args.output/'gate-diagnostic.csv').write_text(prepare.sweep.csv_text(summaries))
    (args.output/'gate-window.csv').write_text(prepare.sweep.csv_text(windows))
    print(json.dumps(summaries,indent=2))


if __name__=='__main__':
    main()
