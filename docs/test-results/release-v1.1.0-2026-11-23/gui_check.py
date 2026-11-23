"""Capture the English GUI using actual UART TRACK and STATUS responses."""
import json
import os
from pathlib import Path
import sys
import time

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_SCALE_FACTOR'] = '2'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from pc_sim.gui import MainWindow

out = Path(__file__).resolve().parent / 'gui'
out.mkdir(exist_ok=False)
app = QApplication([])
window = MainWindow()
window.resize(1440,900)
errors, statuses, tracks = [], [], []


def wait(predicate, timeout=20):
    end = time.monotonic()+timeout
    while time.monotonic()<end:
        app.processEvents()
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError('GUI condition timeout')


try:
    window.mode.setCurrentIndex(1)
    for combo,port in ((window.data_port,'/dev/cu.usbserial-A5069RR4'),
                       (window.console_port,'/dev/cu.usbmodem11203')):
        index=combo.findData(port)
        assert index>=0
        combo.setCurrentIndex(index)
    window.inputs['range_rate_mps'].setValue(-10)
    window.inputs['range_noise_std_m'].setValue(5)
    window.inputs['duration_s'].setValue(15)
    window.inputs['sample_rate_hz'].setValue(10)
    window.record_directory = out.relative_to(ROOT)/'session'
    window.record_label.setText(str(window.record_directory))
    window.record_checkbox.setChecked(True)
    window.content_split.setSizes([680,390])
    window.show()
    window.connect_button.click()
    wait(lambda: window.connected)
    window.worker.error.connect(errors.append)
    window.worker.status_received.connect(statuses.append)
    window.worker.track_received.connect(lambda report,at: tracks.append(report))
    window.start_button.click()
    wait(lambda: window.sample_count>=100 and window.track_monitor.latest is not None)
    window.status_button.click()
    wait(lambda: len(statuses)==1)
    window.control_tabs.setCurrentIndex(3)
    window.log_tabs.setCurrentIndex(0)
    window.draw_samples()
    app.processEvents()
    assert window.track_monitor.latest.estimate_valid
    assert window.track_monitor.latest.state==2
    assert window.grab().save(str(ROOT/'docs/images/radar-gui-board.png'))
    assert window.grab().save(str(out/'gui-track.png'))
    window.control_tabs.setCurrentIndex(1)
    app.processEvents()
    assert window.grab().save(str(out/'gui-settings.png'))
    wait(lambda: window.start_button.isEnabled())
    console=window.console_text.toPlainText()
    assert 'INIT: track=reset measurement_monitor=reset' in console
    assert 'Track state: previous=TENTATIVE current=CONFIRMED' in console
    assert not errors and not any(statuses[0].values())
    assert len(tracks)>=100
    assert 'CONFIRMED' in window.track_values['state'].text()
    (out/'console.log').write_text(console)
    result=dict(passed=True,qt_platform='offscreen',hardware='STM32F746G-DISCO',
                samples=window.sample_count,track_reports=len(tracks),status=statuses[0],
                console_display_checked=True,estimate_display_checked=True,errors=errors)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
finally:
    if window.worker:
        window.worker.requestInterruption()
        window.worker.wait(3000)
    app.processEvents()
    window.close()
