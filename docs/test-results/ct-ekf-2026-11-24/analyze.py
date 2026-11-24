"""Audit captured UART bytes, compare board/host estimates, and aggregate fixed seeds."""
import argparse
from collections import Counter
import csv
from dataclasses import asdict
import gzip
import importlib.util
import json
import math
from pathlib import Path
import statistics

import prepare
from pc_sim.storage.prepared_storage import load_input
from pc_sim.transport.frame_parser import FrameParser, ParserState
from pc_sim.transport.protocol import (decode_track_payload, decode_status_payload,
                                       FRAME_TYPE_TRACK_REPORT, FRAME_TYPE_STATUS_REPORT)


def rows(path: Path) -> list[dict]:
    with path.open() as stream:
        return list(csv.DictReader(stream))


def trace_rows(prepared, reports, case: str, variant: str, q):
    by_time={int(row['input_timestamp_ms']):row for row in reports if int(row['flags'])&1}
    assert Counter(int(row['input_timestamp_ms']) for row in reports if int(row['flags'])&1)==Counter(s.timestamp_ms for s in prepared.samples)
    boundary=prepared.metadata['segments'][0]['duration_s']
    end=boundary+prepared.metadata['segments'][1]['duration_s']
    start_ms=None
    trace=[]
    for sample in prepared.samples:
        report=by_time[sample.timestamp_ms]
        state,result=int(report['state']),int(report['result'])
        valid=bool(int(report['flags'])&2) and int(report['estimate_timestamp_ms'])==sample.timestamp_ms
        if valid and (result==0 or start_ms is None):
            start_ms=sample.timestamp_ms
        eligible=valid and sample.timestamp_ms-start_ms>=2000
        t=sample.timestamp_ms/1000
        phase='straight_before' if t<boundary else 'turn' if t<end else 'straight_after'
        radius,angle=float(report['range_m']),float(report['azimuth_rad'])
        x_m,y_m=radius*math.sin(angle),radius*math.cos(angle)
        measured_angle=sample.wire_azimuth_sc*math.pi/2**31
        mx,my=sample.wire_range_m*math.sin(measured_angle),sample.wire_range_m*math.cos(measured_angle)
        trace.append(dict(case=case,q=q,variant=variant,timestamp_ms=sample.timestamp_ms,sensor_s=t,
                          phase=phase,state=state,result=result,valid=int(valid),eligible=int(eligible),
                          truth_x_m=sample.truth_x_m,truth_y_m=sample.truth_y_m,
                          measurement_x_m=mx,measurement_y_m=my,
                          estimate_x_m=x_m if valid else None,estimate_y_m=y_m if valid else None,
                          error_m=math.hypot(x_m-sample.truth_x_m,y_m-sample.truth_y_m) if valid else None,
                          measurement_error_m=math.hypot(mx-sample.truth_x_m,my-sample.truth_y_m)))
    return trace


def aggregate_host(summaries, cases, variants):
    output=[]
    for geometry in ['original','outbound']:
        for profile in ['range', 'angle', 'nominal', 'strong']:
            for variant in variants:
                subset=[r for r in summaries if r['variant']==variant and r['role']=='independent_seed'
                        and r['profile']==profile and cases[r['case']]['geometry']==geometry]
                assert len(subset)==10
                errors=[r['common_rmse_m'] for r in subset]
                output.append(dict(geometry=geometry,profile=profile,variant=variant,seeds=10,
                                   mean_per_seed_rmse_m=statistics.mean(errors),
                                   min_per_seed_rmse_m=min(errors),max_per_seed_rmse_m=max(errors),
                                   sample_stddev_per_seed_rmse_m=statistics.stdev(errors),
                                   gates=sum(r['gates'] for r in subset),lost=sum(r['lost'] for r in subset),
                                   starts=sum(r['starts'] for r in subset),
                                   minimum_valid_count=min(r['valid_count'] for r in subset),
                                   minimum_common_count=min(r['common_count'] for r in subset)))
    return output


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--partial',action='store_true',help='Audit completed runs only; never label campaign complete')
    args=parser.parse_args()
    base,out=args.recording,args.output
    plan=json.loads((base/'plan.json').read_text())
    manifest=json.loads((base/'board/manifest.json').read_text())
    if not args.partial:
        assert manifest['complete'] and manifest['restored']
        assert Counter((r['variant'],r['case']) for r in manifest['runs'])==Counter((r['variant'],r['case']) for r in plan['board_plan'])
    assert prepare.sweep.digest(base/'plan.json')==manifest['plan_sha256']
    cases={case['case']:case for case in plan['cases']}
    variants = [variant['name'] for variant in plan['variants']]
    assert set(variants) == {'kf', 'ekf10000', 'ct'}
    host_summary=json.loads((base/'host-summary.json').read_text())
    assert len(host_summary) == len(plan['cases']) * len(variants) == 252
    with gzip.open(base/'host-series.csv.gz','rt') as stream:
        host_trace={(r['variant'],r['case'],int(r['timestamp_ms'])):r for r in csv.DictReader(stream)}
    spec=importlib.util.spec_from_file_location('ct_perf_check', prepare.REPO/'fcc_app/tests/test_perf_monitor/board_check.py')
    perf_check=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(perf_check)
    summary,series=[],[]
    for item in manifest['runs']:
        name,case=item['variant'],item['case']
        prepared=load_input(base/'inputs'/case)
        for filename,digest in item['input_sha256'].items():
            assert digest==prepare.sweep.digest(base/'inputs'/case/filename)
        session=base/item['session']
        assert (session/'input/samples.jsonl').read_bytes()==(base/'inputs'/case/'samples.jsonl').read_bytes()
        assert (session/'input/metadata.json').read_bytes()==(base/'inputs'/case/'metadata.json').read_bytes()
        samples,reports,statuses=rows(session/'samples.csv'),rows(session/'reports.csv'),rows(session/'status.csv')
        assert [r['frame_hex'] for r in samples]==[s.frame.hex() for s in prepared.samples]
        assert [int(r['timestamp_ms']) for r in samples]==[s.timestamp_ms for s in prepared.samples]
        receiver=FrameParser()
        decoded,decoded_status,transmitted=[],[],[]
        for row in rows(session/'wire.csv'):
            raw=bytes.fromhex(row['hex'])
            if row['direction']=='tx':
                if len(raw)==15 and raw[2]==2:
                    transmitted.append(raw)
            else:
                for frame in receiver.feed(raw):
                    if frame.frame_type==FRAME_TYPE_TRACK_REPORT:
                        decoded.append(asdict(decode_track_payload(frame.payload)))
                    elif frame.frame_type==FRAME_TYPE_STATUS_REPORT:
                        decoded_status.append(decode_status_payload(frame.payload))
                    else:
                        raise AssertionError('Unexpected response type')
        assert transmitted==[s.frame for s in prepared.samples]
        assert not receiver.crc_errors and not receiver.length_errors and receiver.state==ParserState.WAIT_STX
        assert len(decoded)==len(reports)==len(prepared.samples)+2 and len(decoded_status)==len(statuses)==2
        for actual,stored in zip(decoded,reports):
            assert all(float(stored[key])==value for key,value in actual.items())
        for actual,stored in zip(decoded_status,statuses):
            assert all(int(stored[key])==value for key,value in actual.items())
            assert not any(actual.values())
        q=manifest['builds'][name]['q']
        trace=trace_rows(prepared,reports,case,name,q)
        metrics=prepare.sweep.summarize(trace)
        original=item['result']['position']
        for phase in ['all','straight_before','turn','straight_after']:
            assert math.isclose(metrics[phase+'_rmse_m'],original[phase]['rmse_m'],rel_tol=1e-10)
        differences=[]
        for row in trace:
            host=host_trace[name,case,row['timestamp_ms']]
            assert row['state']==int(host['state']) and row['result']==int(host['result'])
            assert row['valid']==int(host['valid']) and row['eligible']==int(host['eligible'])
            if row['valid']:
                differences.append(math.hypot(row['estimate_x_m']-float(host['estimate_x_m']),
                                               row['estimate_y_m']-float(host['estimate_y_m'])))
        stored_perf=json.loads((base/item['trial']/'perf.json').read_text())
        console_parser=perf_check.PerfConsole()
        console_parser.feed((base/item['trial']/'console.log').read_text(errors='replace'))
        perf=dict(boots=console_parser.boots, faults=console_parser.faults,
                  incomplete_summaries=console_parser.incomplete_summaries, snapshots=console_parser.snapshots)
        assert perf == stored_perf, 'Raw console PERF does not match saved parser output'
        assert perf['boots']==1 and not perf['faults'] and not perf['incomplete_summaries']
        last=perf['snapshots'][-1]
        assert last['header']['measurements']==len(prepared.samples)
        assert not any(last['header'][key] for key in ['without_submit','submit_failed','invalid_time','rx_capture_lost'])
        assert not last['queue rx']['rejected'] and not last['queue tx']['rejected'] and not last['tx']['encode_failed']
        assert last['rx_to_submit']['over20']==0
        gaps=[(float(b['tx_monotonic_s'])-float(a['tx_monotonic_s']))*1000 for a,b in zip(samples,samples[1:])]
        metrics.update(variant=name,geometry=cases[case]['geometry'],profile=cases[case]['profile'],
                       seed=cases[case]['seed'],role=cases[case]['role'],wire_audit=True,reports=len(reports),
                       host_max_position_difference_m=max(differences),
                       max_position_error_m=max(r['error_m'] for r in trace if r['eligible']),
                       predict=last['estimator_predict'],correct=last['estimator_correct'],
                       stack_min_unused_bytes={n:min(s['stack '+n]['min_unused'] for s in perf['snapshots'])
                                               for n in ['rx','handler','tx','main']},
                       rx_to_submit=last['rx_to_submit'],processing=last['processing'],
                       pc_roundtrip_ms=item['result']['pc_roundtrip_ms'],
                       status_delta=item['result']['status_delta'],
                       send_gap_ms=dict(min=min(gaps),mean=statistics.mean(gaps),max=max(gaps)))
        summary.append(metrics)
        series.extend(trace)
    pairs=[]
    for case in sorted({r['case'] for r in summary}):
        names=[r['variant'] for r in summary if r['case']==case]
        if set(names)!=set(variants):
            continue
        subsets={name:{r['timestamp_ms']:r for r in series if r['case']==case and r['variant']==name and r['eligible']}
                 for name in names}
        common=set.intersection(*(set(rows) for rows in subsets.values()))
        for name in names:
            paired=[subsets[name][stamp] for stamp in sorted(common)]
            pairs.append(dict(case=case,variant=name,common_count=len(common),
                              common_rmse_m=prepare.sweep.rmse(paired)))
    aggregated=aggregate_host(host_summary,cases,variants)
    out.mkdir(parents=True,exist_ok=True)
    result=dict(complete=not args.partial and manifest['complete'] and manifest['restored'] and len(summary)==len(plan['board_plan']),
                source_commit=manifest['source_commit'],restored=manifest['restored'],
                frozen_candidate=plan['frozen_candidate'],
                restore_status=manifest.get('restore_status'),runs=summary,paired=pairs,
                host_aggregate=aggregated,planned_runs=len(plan['board_plan']))
    prepare.dump(out/'summary.json',result)
    (out/'host-aggregate.csv').write_text(prepare.sweep.csv_text(aggregated))
    if summary:
        flattened=[]
        for row in summary:
            flat={key:value for key,value in row.items() if not isinstance(value,dict)}
            flat.update(predict_mean_us=row['predict']['mean_ns']/1000,
                        predict_max_us=row['predict']['max_ns']/1000,
                        correct_mean_us=row['correct']['mean_ns']/1000,
                        correct_max_us=row['correct']['max_ns']/1000,
                        handler_min_unused_bytes=row['stack_min_unused_bytes']['handler'])
            flattened.append(flat)
        (out/'summary.csv').write_text(prepare.sweep.csv_text(flattened))
        (out/'board-series.csv.gz').write_bytes(gzip.compress(prepare.sweep.csv_text(series).encode(),mtime=0))
    if pairs:
        (out/'paired.csv').write_text(prepare.sweep.csv_text(pairs))
    print(json.dumps(dict(complete=result['complete'],audited_board_runs=len(summary),
                         measurements=len(series),host_runs=len(host_summary),restored=manifest['restored'])))


if __name__=='__main__':
    main()
