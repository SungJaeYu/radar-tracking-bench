"""Independently replay captured wire bytes and plot aligned board estimates."""
import csv
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from pc_sim.frame_parser import FrameParser
from pc_sim.protocol import decode_track_payload, decode_status_payload

path = Path(sys.argv[1])
samples = json.loads((path/'samples.json').read_text())
reports = json.loads((path/'reports.json').read_text())
statuses = json.loads((path/'status.json').read_text())
receiver = FrameParser()
replayed, replayed_status = [], []
tx_parser = FrameParser()
tx_measurements = []
for line in (path/'wire.jsonl').read_text().splitlines():
    row = json.loads(line)
    raw = bytes.fromhex(row['hex'])
    if row['direction'] == 'rx':
        for frame in receiver.feed(raw):
            if frame.frame_type == 7:
                replayed.append({**asdict(decode_track_payload(frame.payload)), 'rx_monotonic_s': row['time']})
            elif frame.frame_type == 6:
                replayed_status.append(decode_status_payload(frame.payload))
            else:
                raise AssertionError('Unexpected RX type')
    else:
        for frame in tx_parser.feed(raw):
            if frame.frame_type == 2:
                tx_measurements.append(frame.payload.hex())
assert receiver.crc_errors == receiver.length_errors == 0
assert tx_parser.crc_errors == tx_parser.length_errors == 0
assert replayed == reports and replayed_status == statuses
assert tx_measurements == [bytes.fromhex(s['frame_hex'])[3:-2].hex() for s in samples]
by_stamp = {s['timestamp_ms']:s for s in samples}
rows = []
for report in reports:
    if not report['flags'] & 1:
        continue
    sample = by_stamp[report['input_timestamp_ms']]
    assert report['estimate_timestamp_ms'] == sample['timestamp_ms']
    assert report['flags'] & 2
    x = report['range_m']*math.sin(report['azimuth_rad'])
    y = report['range_m']*math.cos(report['azimuth_rad'])
    rows.append(dict(timestamp_ms=sample['timestamp_ms'],segment=sample['segment'],
                     truth_x_m=sample['x_m'],truth_y_m=sample['y_m'],estimate_x_m=x,estimate_y_m=y,
                     position_error_m=math.hypot(x-sample['x_m'],y-sample['y_m']),
                     range_error_m=report['range_m']-sample['truth_range_m'],
                     azimuth_error_deg=math.degrees((report['azimuth_rad']-sample['truth_azimuth_rad']+math.pi)%(2*math.pi)-math.pi),
                     state=report['state'],result=report['result']))
with (path/'aligned.csv').open('w',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
    writer.writeheader();writer.writerows(rows)
import pyqtgraph as pg
import pyqtgraph.exporters
pg.setConfigOptions(background='w',foreground='k')
app=pg.mkQApp()
window=pg.GraphicsLayoutWidget(title='STM32 segmented-turn HIL')
window.resize(1400,750)
trajectory=window.addPlot(title='PC truth and real STM32 TRACK estimates')
trajectory.addLegend()
trajectory.setLabel('bottom','East',units='m');trajectory.setLabel('left','North',units='m')
trajectory.setAspectLocked(True);trajectory.showGrid(x=True,y=True,alpha=.2)
trajectory.plot([r['truth_x_m'] for r in rows],[r['truth_y_m'] for r in rows],pen=pg.mkPen('#1f8a60',width=3),name='PC truth')
trajectory.plot([r['estimate_x_m'] for r in rows],[r['estimate_y_m'] for r in rows],pen=pg.mkPen('#306fbe',width=1),name='Board estimate')
errors=window.addPlot(title='Position error (all samples; summary excludes first 2 s)')
errors.setLabel('bottom','Sensor time',units='s');errors.setLabel('left','Position error',units='m')
errors.showGrid(x=True,y=True,alpha=.2)
errors.plot([r['timestamp_ms']/1000 for r in rows],[r['position_error_m'] for r in rows],pen=pg.mkPen('#306fbe',width=2))
for boundary in (10,65.486818564):
    errors.addItem(pg.InfiniteLine(pos=boundary,angle=90,pen=pg.mkPen('#c77b25',width=2)))
window.show();app.processEvents()
export=pg.exporters.ImageExporter(window.scene())
export.parameters()['width']=1800
export.export(str(path/'trajectory-errors.png'))
window.close()
audit=dict(passed=True,tx_measurements=len(tx_measurements),rx_tracks=len(replayed),rx_status=len(replayed_status),
           aligned_samples=len(rows),wire_replay_matches_saved_records=True,crc_errors=0,length_errors=0)
(path/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')
print(json.dumps(audit,indent=2))
