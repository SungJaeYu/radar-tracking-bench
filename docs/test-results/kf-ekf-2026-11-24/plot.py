"""Export standalone figures from independently audited STM32 comparison data."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import argparse
import csv
import json
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import QApplication
import pyqtgraph as pg
import pyqtgraph.exporters

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory',type=Path)
args=parser.parse_args()
base=args.directory
summary=json.loads((base/'summary.json').read_text())
with (base/'series.csv').open() as stream: data=list(csv.DictReader(stream))
app=QApplication.instance() or QApplication([])
pg.setConfigOptions(background='w',foreground='#24344a',antialias=True)
colors={'truth':'#16293f','measurement':'#b87a15','kf':'#1976b5','ekf':'#be3f57'}
labels={'measurement':'Measurement','kf':'Polar CV KF','ekf':'Cartesian CV EKF'}
segments=['all','straight_before','turn','straight_after']

def subset(case, estimator='kf', eligible=False):
    return [r for r in data if r['case']==case and r['estimator']==estimator and (not eligible or r['eligible']=='1')]

def array(rows,key):
    return np.array([float(r[key]) if r[key] else np.nan for r in rows])

def window(title,height=800):
    w=pg.GraphicsLayoutWidget();w.resize(1600,height)
    w.addLabel(title,row=0,col=0,colspan=2,size='18pt',color='#16293f')
    return w

def plot(w,col,title,ylabel):
    p=w.addPlot(row=1,col=col,title=title)
    p.setLabel('left',ylabel);p.showGrid(x=True,y=True,alpha=.15)
    p.addLegend(offset=(12,12),brush=pg.mkBrush(255,255,255,235))
    return p

def export(w,name,note):
    w.addLabel(note,row=2,col=0,colspan=2,size='11pt',color='#41536a')
    w.show();app.processEvents()
    exporter=pg.exporters.ImageExporter(w.ci);exporter.parameters()['width']=1800
    exporter.export(str(base/(name+'.png')))
    w.close()

w=window('STM32 turn tracking | identical truth and measurement bytes')
for col,case in enumerate(['baseline','noisy']):
    p=plot(w,col,'No added noise' if case=='baseline' else 'Range sigma 10 m | azimuth sigma 0.01 rad','North (m)')
    p.setLabel('bottom','East (m)');p.setAspectLocked(True)
    samples=subset(case)
    p.plot(array(samples,'truth_x_m'),array(samples,'truth_y_m'),pen=pg.mkPen(colors['truth'],width=2.5),name='Truth')
    p.plot(array(samples,'measurement_x_m'),array(samples,'measurement_y_m'),pen=None,symbol='o',symbolSize=3,
           symbolPen=None,symbolBrush=colors['measurement'],name=labels['measurement'])
    for estimator in ['kf','ekf']:
        rows=subset(case,estimator)
        p.plot(array(rows,'estimate_x_m'),array(rows,'estimate_y_m'),pen=pg.mkPen(colors[estimator],width=2),name=labels[estimator],connect='finite')
export(w,'trajectories','755 measurements per run | east 10 s, right 90-degree turn, south 10 s | synthetic sensor time 10 Hz, seed 42<br>Actual STM32 estimates; equal spatial scales. This single trajectory and seed do not establish general estimator superiority.')

w=window('Position error | measurement and actual STM32 estimates')
for col,case in enumerate(['baseline','noisy']):
    p=plot(w,col,'No added noise' if case=='baseline' else 'Added range and azimuth noise','Position error (m)')
    p.setLabel('bottom','Sensor time (s)')
    region=pg.LinearRegionItem([10,65.4867],movable=False,brush=pg.mkBrush(87,154,129,24),pen=pg.mkPen(None))
    p.addItem(region);region.setZValue(-10)
    rows=subset(case,eligible=True)
    p.plot(array(rows,'sensor_s'),array(rows,'measurement_error_m'),pen=pg.mkPen(colors['measurement'],width=1),name=labels['measurement'])
    for estimator in ['kf','ekf']:
        rows=subset(case,estimator,True)
        p.plot(array(rows,'sensor_s'),array(rows,'estimate_error_m'),pen=pg.mkPen(colors[estimator],width=2),name=labels[estimator])
export(w,'position-errors','First 2 s after STARTED excluded; only timestamp-matched valid estimates | green shading: constant-turn interval<br>Values are actual position-error magnitudes; panel y scales differ. CSV retains initialization and invalid-state flags.')

w=window('Position RMSE by flight segment | matched evaluation samples')
for col,case in enumerate(['baseline','noisy']):
    p=plot(w,col,'No added noise' if case=='baseline' else 'Added range and azimuth noise','Position RMSE (m)')
    p.legend.hide()
    title='No added noise' if case=='baseline' else 'Added range and azimuth noise'
    p.setTitle(title+'<br>'+ ' &nbsp; '.join(f'<span style="color:{colors[name]}">{labels[name]}</span>' for name in ['measurement','kf','ekf']))
    p.getAxis('bottom').setTicks([list(enumerate(['Overall','Before turn','Turning','After turn']))])
    for offset,name in [(-.25,'measurement'),(0,'kf'),(.25,'ekf')]:
        if name=='measurement':
            rows=subset(case,eligible=True)
            vals=[]
            for phase in segments:
                errors=[float(r['measurement_error_m']) for r in rows if phase=='all' or r['phase']==phase]
                vals.append(float(np.sqrt(np.mean(np.square(errors)))))
        else:
            run=next(r for r in summary['runs'] if r['estimator']==name and r['case']==case)
            vals=[run['position'][phase]['rmse_m'] for phase in segments]
        bars=pg.BarGraphItem(x=np.arange(4)+offset,height=vals,width=.22,brush=colors[name],pen=None)
        p.addItem(bars)
        # Legend uses line samples; plotted values remain bars.
        p.plot([],[],pen=pg.mkPen(colors[name],width=8),name=labels[name])
    p.enableAutoRange(axis='y',enable=True)
export(w,'segment-rmse','Same 735 eligible timestamps per estimator: 80 before turn, 555 turning, 100 after turn<br>Observed errors for seed 42 with unchanged default R/Q and zero initial velocity; no accuracy pass threshold.')

w=window('On-board estimator execution | same PERF instrumentation')
for col,case in enumerate(['baseline','noisy']):
    p=plot(w,col,'No added noise' if case=='baseline' else 'Added range and azimuth noise','Execution time (microseconds)')
    p.getAxis('bottom').setTicks([list(enumerate(['KF predict','KF correct','EKF predict','EKF correct']))])
    for index,(estimator,operation) in enumerate([('kf','predict'),('kf','correct'),('ekf','predict'),('ekf','correct')]):
        run=next(r for r in summary['runs'] if r['estimator']==estimator and r['case']==case)
        metric=run[operation]
        mean,lo,hi=[metric[key]/1000 for key in ['mean_ns','min_ns','max_ns']]
        p.addItem(pg.BarGraphItem(x=[index],height=[mean],width=.5,brush=colors[estimator],pen=None))
        p.addItem(pg.ErrorBarItem(x=np.array([index]),y=np.array([mean]),bottom=np.array([mean-lo]),top=np.array([hi-mean]),beam=.18,pen=pg.mkPen('#24344a',width=1.5)))
        text=pg.TextItem(f'mean {mean:.2f}',anchor=(.5,1),color='#24344a');text.setPos(index,hi);p.addItem(text)
    p.setYRange(0,max(r[op]['max_ns']/1000 for r in summary['runs'] for op in ['predict','correct'])*1.2)
export(w,'execution-time','Bars: measured mean | whiskers: observed min to max, not confidence intervals | 754 calls of each operation per run<br>Fresh flash before each run. Timer-hook intervals differ from PC RTT; short observations are not WCET or load qualification.')
print('Exported four PNG figures')
