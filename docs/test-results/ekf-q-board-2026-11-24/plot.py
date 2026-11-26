"""Render host seed comparisons and audited STM32 trajectories/costs to PNG."""
import argparse
import csv
import gzip
import json
import os
from pathlib import Path
import statistics

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PySide6.QtWidgets import QApplication
import pyqtgraph as pg
import pyqtgraph.exporters

COLORS={'kf':'#1976b5','ekf100':'#bf3f58','ekf10000':'#217d62','ekf30000':'#b87915'}
LABELS={'kf':'Polar KF','ekf100':'EKF q=100','ekf10000':'EKF q=10000','ekf30000':'EKF q=30000'}


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--outbound-only',action='store_true',help='Plot completed outbound cases during the campaign')
    args=parser.parse_args()
    base=args.directory
    result=json.loads((base/'summary.json').read_text())
    assert result['complete'] or args.outbound_only
    with gzip.open(base/'board-series.csv.gz','rt') as stream:
        series=list(csv.DictReader(stream))
    app=QApplication.instance() or QApplication([])
    pg.setConfigOptions(background='w',foreground='#24344a',antialias=True)

    def window(title,height=800):
        widget=pg.GraphicsLayoutWidget()
        widget.resize(1600,height)
        widget.addLabel(title,row=0,col=0,colspan=2,size='18pt',color='#16293f')
        return widget

    def plot(widget,row,col,title,ylabel,xlabel):
        panel=widget.addPlot(row=row,col=col,title=title)
        panel.setLabel('left',ylabel)
        panel.setLabel('bottom',xlabel)
        panel.showGrid(x=True,y=True,alpha=.17)
        panel.addLegend(offset=(12,12),brush=pg.mkBrush(255,255,255,235))
        return panel

    def export(widget,name,note,row=2):
        widget.addLabel(note,row=row,col=0,colspan=2,size='11pt',color='#41536a')
        widget.show()
        app.processEvents()
        exporter=pg.exporters.ImageExporter(widget.ci)
        exporter.parameters()['width']=1800
        exporter.export(str(base/name))
        widget.close()

    def subset(case,variant,eligible=False):
        return [r for r in series if r['case']==case and r['variant']==variant
                and (not eligible or r['eligible']=='1')]

    def array(rows,key):
        return np.array([float(r[key]) if r[key] else np.nan for r in rows])

    outbound_cases=['outbound-nominal6','outbound-strong6']
    available={(r['case'],r['variant']) for r in result['runs']}
    assert all((case,variant) in available for case in outbound_cases for variant in COLORS)
    widget=window('STM32 receding turn | noise and candidate Q comparison')
    maximum=max(float(r['error_m']) for r in series if r['case'] in outbound_cases and r['eligible']=='1')*1.08
    for column,case in enumerate(outbound_cases):
        title='Range sigma 10 m | azimuth sigma 0.01 rad' if column==0 else 'Range sigma 20 m | azimuth sigma 0.02 rad'
        panel=plot(widget,1,column,title,'Position error (m)','Sensor time (s)')
        region=pg.LinearRegionItem([10,65.4867],movable=False,brush=pg.mkBrush(87,154,129,22),pen=pg.mkPen(None))
        panel.addItem(region)
        region.setZValue(-10)
        for variant in COLORS:
            sample=subset(case,variant,True)
            panel.plot(array(sample,'sensor_s'),array(sample,'error_m'),
                       pen=pg.mkPen(COLORS[variant],width=2),name=LABELS[variant])
        panel.setYRange(0,maximum)
    suffix='Full primary campaign complete.' if result['complete'] else 'These cases are complete; the full campaign is still running.'
    export(widget,'outbound-board-errors.png',
           'Actual STM32 estimates | seed 6, northbound then eastbound | equal y scales; green shading: turn<br>'
           'First 2 s excluded. '+suffix)
    if args.outbound_only:
        return

    widget=window('Same noise draws | original and initially receding turn geometry',1000)
    for column,(case,title) in enumerate([('nominal6','Eastbound then southbound'),
                                         ('outbound-nominal6','Initially receding: northbound then eastbound')]):
        panel=plot(widget,1,column,title,'North (m)','East (m)')
        panel.setAspectLocked(True)
        samples=subset(case,'kf')
        panel.plot(array(samples,'truth_x_m'),array(samples,'truth_y_m'),pen=pg.mkPen('#16293f',width=2.5),name='Truth')
        panel.plot(array(samples,'measurement_x_m'),array(samples,'measurement_y_m'),pen=None,
                   symbol='o',symbolSize=3,symbolPen=None,symbolBrush='#b8aa91',name='Measurement')
        for variant in COLORS:
            sample=subset(case,variant)
            panel.plot(array(sample,'estimate_x_m'),array(sample,'estimate_y_m'),
                       pen=pg.mkPen(COLORS[variant],width=1.5),name=LABELS[variant],connect='finite')
        panel.plot([0],[0],pen=None,symbol='+',symbolSize=16,symbolPen=pg.mkPen('#16293f',width=2),name='Radar')
        panel.setXRange(-800,10500)
        panel.setYRange(-9500,11500)
        distance=plot(widget,2,column,'True radar range','Range (km)','Sensor time (s)')
        distance.legend.hide()
        distance.plot(array(samples,'sensor_s'),np.hypot(array(samples,'truth_x_m'),array(samples,'truth_y_m'))/1000,
                      pen=pg.mkPen('#16293f',width=2))
        distance.setYRange(0,15)
    export(widget,'geometry-and-range.png',
           'Actual STM32 estimates | seed 6, range sigma 10 m / azimuth sigma 0.01 rad | speed 200 m/s, 30-degree bank<br>'
           'Both paths recede. New path begins radially outward; range/angular geometry changes. Equal east/north scale; preserved additive noise.',3)

    widget=window('Independent seeds 1-10 | mean per-seed position RMSE')
    profiles=['range','angle','nominal','strong']
    for column,geometry in enumerate(['original','outbound']):
        panel=plot(widget,1,column,'Original geometry' if geometry=='original' else 'Initially receding geometry',
                   'Position RMSE (m)','Noise profile')
        panel.getAxis('bottom').setTicks([list(enumerate(['10 m only','0.01 rad only','10 m + 0.01 rad','20 m + 0.02 rad']))])
        for offset,variant in zip([-.27,-.09,.09,.27],COLORS):
            metrics=[next(r for r in result['host_aggregate'] if r['geometry']==geometry
                          and r['profile']==profile and r['variant']==variant) for profile in profiles]
            mean=np.array([r['mean_per_seed_rmse_m'] for r in metrics])
            low=np.array([r['min_per_seed_rmse_m'] for r in metrics])
            high=np.array([r['max_per_seed_rmse_m'] for r in metrics])
            x=np.arange(4)+offset
            panel.addItem(pg.BarGraphItem(x=x,height=mean,width=.16,brush=COLORS[variant],pen=None))
            panel.addItem(pg.ErrorBarItem(x=x,y=mean,bottom=mean-low,top=high-mean,beam=.1,
                                         pen=pg.mkPen('#24344a',width=1)))
            panel.plot([],[],pen=pg.mkPen(COLORS[variant],width=6),name=LABELS[variant])
        panel.setYRange(0,max(r['max_per_seed_rmse_m'] for r in result['host_aggregate'])*1.2)
    export(widget,'host-independent-seeds.png',
           'Host production C | candidates fixed using seed 42, excluded here | common eligible timestamps per input; first 2 s excluded<br>'
           'Bars: mean of 10 per-seed RMSE values. Whiskers: observed seed minimum/maximum, not confidence intervals.')

    for profile,title in [('nominal','Range sigma 10 m | azimuth sigma 0.01 rad'),
                          ('strong','Range sigma 20 m | azimuth sigma 0.02 rad')]:
        widget=window('STM32 position error | '+title)
        selected=[r for r in series if r['case'] in [profile+'6','outbound-'+profile+'6'] and r['eligible']=='1']
        maximum=max(float(r['error_m']) for r in selected)*1.08
        for column,case in enumerate([profile+'6','outbound-'+profile+'6']):
            panel=plot(widget,1,column,'Original geometry' if column==0 else 'Initially receding geometry',
                       'Position error (m)','Sensor time (s)')
            region=pg.LinearRegionItem([10,65.4867],movable=False,brush=pg.mkBrush(87,154,129,22),pen=pg.mkPen(None))
            panel.addItem(region)
            region.setZValue(-10)
            for variant in COLORS:
                sample=subset(case,variant,True)
                panel.plot(array(sample,'sensor_s'),array(sample,'error_m'),
                           pen=pg.mkPen(COLORS[variant],width=2),name=LABELS[variant])
            panel.setYRange(0,maximum)
        export(widget,profile+'-board-errors.png',
               'Actual STM32 estimates, seed 6 | same timestamp-matched inputs per configuration | equal y scales<br>'
               'Green shading: turn. Initial 2 s excluded; full traces preserve initialization, invalid states and coverage.')

    widget=window('STM32 estimator execution | identical PERF instrumentation')
    for column,(operation,title) in enumerate([('predict','Prediction'),('correct','Correction')]):
        panel=plot(widget,1,column,title,'Time (microseconds)','Configuration')
        panel.legend.hide()
        panel.getAxis('bottom').setTicks([list(enumerate(LABELS.values()))])
        for index,variant in enumerate(COLORS):
            values=[r[operation] for r in result['runs'] if r['variant']==variant]
            mean=statistics.mean(v['mean_ns'] for v in values)/1000
            low=min(v['min_ns'] for v in values)/1000
            high=max(v['max_ns'] for v in values)/1000
            panel.addItem(pg.BarGraphItem(x=[index],height=[mean],width=.5,brush=COLORS[variant],pen=None))
            panel.addItem(pg.ErrorBarItem(x=np.array([index]),y=np.array([mean]),
                                         bottom=np.array([mean-low]),top=np.array([high-mean]),beam=.2))
            label=pg.TextItem(f'{mean:.2f} / {high:.2f}',anchor=(.5,1),color='#24344a')
            label.setPos(index,high)
            panel.addItem(label)
        panel.setYRange(0,max(r[operation]['max_ns'] for r in result['runs'])/1000*1.2)
    margins=' | '.join(LABELS[v]+': '+str(min(r['stack_min_unused_bytes']['handler'] for r in result['runs'] if r['variant']==v))+' B'
                       for v in COLORS)
    export(widget,'board-execution.png',
           'Labels: mean of run means / maximum observed call. Whiskers: observed call min/max, not confidence intervals or WCET.<br>'
           'Handler minimum unused stack (2048 B allocated): '+margins)


if __name__=='__main__':
    main()
