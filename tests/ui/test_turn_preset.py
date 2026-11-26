"""GUI turn preset uses the same command as the validated board run."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6')
from pc_sim.ui.evaluation_panel import PRESETS, preset_arguments


def test_turn_preset_dispatches_shared_cli(tmp_path):
    assert any(key=='turn-noise' and title=='Turn + noise' for key,title,_ in PRESETS)
    assert preset_arguments('turn-noise','/dev/uart',tmp_path)==[
        '-u','-m','pc_sim','turn-noise','--port','/dev/uart','--output',str(tmp_path)]


@pytest.mark.parametrize('preset,range_flag,angle_flag,expected_angle', [
    ('turn-noise','--noise','--azimuth-noise',.002),
    ('normal','--range-noise','--azimuth-noise-deg',.002*180/3.141592653589793),
    ('noisy','--range-noise','--azimuth-noise-deg',.002*180/3.141592653589793),
    ('dropout','--range-noise','--azimuth-noise-deg',.002*180/3.141592653589793),
])
def test_gui_noise_values_reach_process(preset,range_flag,angle_flag,expected_angle):
    from PySide6.QtWidgets import QApplication
    from pc_sim.ui.evaluation_panel import EvaluationPanel
    import tempfile
    from pathlib import Path
    app=QApplication.instance() or QApplication([])
    panel=EvaluationPanel()
    with tempfile.TemporaryDirectory() as directory:
        panel.output_directory=Path(directory)
        panel.preset.setCurrentIndex(panel.preset.findData(preset))
        panel.range_noise.setValue(3.5)
        panel.angle_noise.setValue(.002)
        panel.set_available(True)
        panel.start('/nonexistent/radar-port')
        try:
            args=panel.process.arguments()
            assert args[args.index(range_flag)+1]=='3.5'
            assert float(args[args.index(angle_flag)+1]) == pytest.approx(expected_angle)
            assert not panel.noise_settings.isEnabled()
            panel.process.waitForFinished(5000)
            app.processEvents()
            assert not panel.busy
            assert panel.noise_settings.isEnabled()
        finally:
            if panel.busy:
                panel.process.kill()
                panel.process.waitForFinished(3000)
            panel.close()
