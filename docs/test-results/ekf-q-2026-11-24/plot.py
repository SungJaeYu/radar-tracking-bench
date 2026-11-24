"""Export the offline C Q sweep as standalone figures; requires GUI dependencies."""
import argparse
import csv
import gzip
import json
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PySide6.QtWidgets import QApplication
import pyqtgraph as pg
import pyqtgraph.exporters


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    base = parser.parse_args().directory
    summaries = json.loads((base / 'summary.json').read_text())
    with gzip.open(base / 'series.csv.gz', 'rt') as stream:
        series = list(csv.DictReader(stream))
    app = QApplication.instance() or QApplication([])
    pg.setConfigOptions(background='w', foreground='#24344a', antialias=True)
    titles = ['No added noise', 'Range sigma 10 m | azimuth sigma 0.01 rad']

    def window(title):
        widget = pg.GraphicsLayoutWidget()
        widget.resize(1600, 750)
        widget.addLabel(title, row=0, col=0, colspan=2, size='18pt', color='#16293f')
        return widget

    def export(widget, name, note):
        widget.addLabel(note, row=2, col=0, colspan=2, size='11pt', color='#41536a')
        widget.show()
        app.processEvents()
        exporter = pg.exporters.ImageExporter(widget.ci)
        exporter.parameters()['width'] = 1800
        exporter.export(str(base / name))
        widget.close()

    widget = window('Cartesian CV-EKF | changing only acceleration variance q')
    phases = [('all', 'Overall', '#16293f'), ('straight_before', 'Before turn', '#1976b5'),
              ('turn', 'Turning', '#ce7a12'), ('straight_after', 'After turn', '#b93e5c')]
    for column, case in enumerate(['baseline', 'noisy']):
        plot = widget.addPlot(row=1, col=column, title=titles[column])
        plot.setLabel('left', 'Position RMSE (m, log scale)')
        plot.setLabel('bottom', 'q (m^2/s^4, log scale)')
        plot.setLogMode(x=True, y=True)
        plot.showGrid(x=True, y=True, alpha=.18)
        plot.addLegend(offset=(12, 12), brush=pg.mkBrush(255, 255, 255, 235))
        rows = [row for row in summaries if row['case'] == case and row['q'] > 0]
        for phase, label, color in phases:
            plot.plot([row['q'] for row in rows], [row[phase + '_rmse_m'] for row in rows],
                      pen=pg.mkPen(color, width=2.5 if phase == 'all' else 1.5),
                      symbol='o', symbolSize=5, symbolBrush=color, name=label)
        plot.addItem(pg.InfiniteLine(pos=2, pen=pg.mkPen('#667788', width=1),
                                    label='default q=100',
                                    labelOpts={'position': .55, 'color': '#526578'}))
        region = pg.LinearRegionItem([4, float(np.log10(30000))], movable=False,
                                     brush=pg.mkBrush(87, 154, 129, 22), pen=pg.mkPen(None))
        plot.addItem(region)
        region.setZValue(-10)
        plot.setYRange(-1.2, 3)
    export(widget, 'q-response.png',
           'Host C replay, seed 42 | same 735 eligible samples for every q > 0 | R, initial P and gates fixed<br>'
           'Shading: q=10000 to 30000 candidates. q=0 omitted from log axis; it lost tracking twice per case. Default remains 100.')

    widget = window('Position error over time | default and exploratory candidates')
    for column, case in enumerate(['baseline', 'noisy']):
        plot = widget.addPlot(row=1, col=column, title=titles[column])
        plot.setLabel('left', 'Position error (m)')
        plot.setLabel('bottom', 'Sensor time (s)')
        plot.showGrid(x=True, y=True, alpha=.18)
        plot.addLegend(offset=(12, 12), brush=pg.mkBrush(255, 255, 255, 235))
        region = pg.LinearRegionItem([10, 65.4867], movable=False,
                                     brush=pg.mkBrush(87, 154, 129, 22), pen=pg.mkPen(None))
        plot.addItem(region)
        region.setZValue(-10)
        for q, color in [(100, '#b93e5c'), (10000, '#1976b5'), (30000, '#267b4c')]:
            rows = [row for row in series if row['case'] == case and int(row['q']) == q
                    and row['eligible'] == '1']
            plot.plot(np.array([float(row['sensor_s']) for row in rows]),
                      np.array([float(row['error_m']) for row in rows]),
                      pen=pg.mkPen(color, width=2), name=f'q={q}')
        plot.setYRange(0, 200)
    export(widget, 'candidate-errors.png',
           'Host production C estimates, not new board measurements | first 2 s after STARTED excluded<br>'
           'Green shading: turning. Equal y scales. Candidate choice uses this seed and needs independent-seed and board validation.')


if __name__ == '__main__':
    main()
