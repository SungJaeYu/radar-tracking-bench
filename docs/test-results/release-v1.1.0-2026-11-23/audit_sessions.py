"""Replay recorded UART bytes independently of each board-test verdict."""
import csv
from dataclasses import asdict
import json
from pathlib import Path
import sys

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT))
from pc_sim.frame_parser import FrameParser
from pc_sim.protocol import decode_track_payload, decode_status_payload


def rows(path):
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


results=[]
for metadata in sorted(OUT.rglob('session/metadata.json')) + sorted(OUT.glob('gui/session/*/metadata.json')) + sorted(OUT.glob('noise/*/*/metadata.json')) + sorted(OUT.glob('spike/*/*/metadata.json')) + sorted(OUT.glob('evaluate-*/*/metadata.json')):
    path=metadata.parent
    if not (path/'wire.csv').exists():
        continue
    receiver=FrameParser()
    decoded=[]
    status=[]
    for row in rows(path/'wire.csv'):
        if row['direction']!='rx':
            continue
        for frame in receiver.feed(bytes.fromhex(row['hex'])):
            if frame.frame_type==7:
                decoded.append(asdict(decode_track_payload(frame.payload)))
            elif frame.frame_type==6:
                status.append(decode_status_payload(frame.payload))
            else:
                raise AssertionError(f'Unexpected type {frame.frame_type} in {path}')
    saved=rows(path/'reports.csv')
    assert len(saved)==len(decoded),path
    for actual,record in zip(decoded,saved):
        for key,value in actual.items():
            assert value==float(record[key]),(path,key,value,record[key])
    saved_status=rows(path/'status.csv')
    assert len(saved_status)==len(status),path
    for actual,record in zip(status,saved_status):
        for key,value in actual.items():
            assert value==int(record[key]),(path,key)
    assert receiver.crc_errors==receiver.length_errors==0,path
    assert json.loads(metadata.read_text())['closed'],path
    results.append(dict(path=str(path.relative_to(OUT)),reports=len(decoded),status=len(status),
                        samples=len(rows(path/'samples.csv')),passed=True))
assert results
result=dict(passed=True,sessions=len(results),samples=sum(r['samples'] for r in results),
            reports=sum(r['reports'] for r in results),records=results)
(OUT/'wire-audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({key:value for key,value in result.items() if key!='records'},indent=2))
