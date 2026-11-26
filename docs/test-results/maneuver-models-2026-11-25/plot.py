"""Render deterministic PC truth trajectories and speed/turn-rate schedules."""
import os
from pathlib import Path
import sys
import math
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from pc_sim.simulation.targets import SCENARIOS
from PySide6.QtWidgets import QApplication
import pyqtgraph as pg
import pyqtgraph.exporters


def main():
    app=QApplication.instance() or QApplication([])
    pg.setConfigOptions(background='w',foreground='#24344a',antialias=True)
    names=['straight_200','turn_1deg','turn_4deg','s_turn','accel_decel_5','turn_rate_ramp']
    trajectories=pg.GraphicsLayoutWidget()
    trajectories.resize(1500,950)
    trajectories.addLabel('PC truth trajectories | east / north outbound starts | no measurement noise',row=0,col=0,colspan=3,size='16pt')
    controls=pg.GraphicsLayoutWidget()
    controls.resize(1500,950)
    controls.addLabel('PC truth motion schedules | continuous states, segment boundary changes',row=0,col=0,colspan=3,size='16pt')
    for index,name in enumerate(names):
        row,col=1+index//3,index%3
        p=trajectories.addPlot(row=row,col=col,title=name)
        p.setLabel('bottom','East (m)');p.setLabel('left','North (m)');p.showGrid(x=True,y=True,alpha=.15)
        p.setAspectLocked(True);p.addLegend()
        for prefix,color in [('', '#1976b5'),('outbound_', '#b87915')]:
            scenario=SCENARIOS[prefix+name]();xs=[];ys=[];times=[];speeds=[];rates=[]
            for step in range(round(scenario.duration_s*10)+1):
                target=scenario.target
                xs.append(target.x_m);ys.append(target.y_m);times.append(step/10)
                speeds.append(math.hypot(target.vx_mps,target.vy_mps));rates.append(math.degrees(target.turn_rate_radps))
                scenario.update(.1)
            p.plot(xs,ys,pen=pg.mkPen(color,width=2),name='North start' if prefix else 'East start')
            if not prefix:
                c=controls.addPlot(row=row,col=col,title=name)
                c.setLabel('bottom','Sensor time (s)');c.showGrid(x=True,y=True,alpha=.15)
                acceleration='accel' in name or 'straight' in name
                c.setLabel('left','Speed (m/s)' if acceleration else 'Clockwise turn rate (deg/s)')
                c.plot(times,speeds if acceleration else rates,pen=pg.mkPen('#1976b5',width=2))
        p.plot([0],[0],pen=None,symbol='+',symbolSize=10,symbolPen='#333333')
    for widget,name in [(trajectories,'trajectories.png'),(controls,'motion-schedules.png')]:
        widget.show();app.processEvents()
        exporter=pg.exporters.ImageExporter(widget.ci);exporter.parameters()['width']=1800
        exporter.export(str(Path(__file__).parent/name));widget.close()

if __name__=='__main__':
    main()
