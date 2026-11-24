"""GUI evaluation launch/lifecycle checks; existing evaluation tests stay untouched."""
import os
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')
pytest.importorskip('pyqtgraph')
from PySide6.QtWidgets import QApplication
from pc_sim.ui.evaluation_panel import preset_arguments
from pc_sim.ui.gui import MainWindow


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def wait_for(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


@pytest.mark.parametrize('preset,command', [
    ('normal', ['evaluate', 'run', '--scenario', 'normal']),
    ('noisy', ['evaluate', 'run', '--scenario', 'noisy']),
    ('dropout', ['evaluate', 'run', '--scenario', 'dropout']),
    ('noise-sweep', ['noise-sweep']), ('spike-sweep', ['spike-sweep']),
])
def test_presets_preserve_cli_defaults(preset, command, tmp_path):
    assert preset_arguments(preset, '/dev/a port', tmp_path) == [
        '-u', '-m', 'pc_sim', *command, '--port', '/dev/a port', '--output', str(tmp_path)]


def test_unknown_preset_rejected(tmp_path):
    with pytest.raises(ValueError):
        preset_arguments('bogus', 'port', tmp_path)


@pytest.fixture
def window(app, tmp_path):
    win = MainWindow()
    win.test_panel.output_directory = tmp_path
    yield win
    if win.test_panel.busy:
        win.test_panel.process.kill()
        wait_for(app, lambda: not win.test_panel.busy)
    if win.worker is not None:
        win.disconnect()
        wait_for(app, lambda: win.worker is None)
    win.close()
    app.processEvents()


def configure_board(win):
    win.mode.setCurrentIndex(1)
    win.data_port.addItem('Missing test port', '/nonexistent/radar-test-port')
    win.data_port.setCurrentIndex(win.data_port.count() - 1)


def test_real_cli_failure_restores_controls(app, window):
    configure_board(window)
    window.start_evaluation()
    assert window.test_panel.busy
    assert not window.connect_button.isEnabled()
    window.toggle_connection()
    assert window.worker is None
    wait_for(app, lambda: not window.test_panel.busy)
    assert 'Failed' in window.test_panel.status.text()
    assert 'radar-test-port' in window.test_panel.log.toPlainText()
    assert window.connect_button.isEnabled()
    assert window.test_panel.run_button.isEnabled()


def test_manual_connection_blocks_test(app, window):
    window.toggle_connection()
    wait_for(app, lambda: window.connected)
    window.start_evaluation()
    assert not window.test_panel.busy
    assert not window.test_panel.run_button.isEnabled()
    window.disconnect()
    wait_for(app, lambda: window.worker is None)


def fake_command(monkeypatch, script):
    monkeypatch.setattr('pc_sim.ui.evaluation_panel.preset_arguments',
                        lambda *args: ['-u', '-c', script])


@pytest.mark.parametrize('exit_code', [0, 2])
def test_child_output_and_exit_status(app, window, monkeypatch, exit_code):
    fake_command(monkeypatch, f'import sys; print("result 한글"); print("diagnostic", file=sys.stderr); sys.exit({exit_code})')
    configure_board(window)
    window.start_evaluation()
    wait_for(app, lambda: not window.test_panel.busy)
    assert 'result 한글' in window.test_panel.log.toPlainText()
    assert 'diagnostic' in window.test_panel.log.toPlainText()
    assert ('Completed' if exit_code == 0 else 'Failed') in window.test_panel.status.text()
    assert 'Passed' not in window.test_panel.status.text()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX graceful cancellation')
def test_cancel_and_close_wait_for_cleanup(app, window, monkeypatch, tmp_path):
    marker = tmp_path / 'closed.txt'
    fake_command(monkeypatch, 'import time\nfrom pathlib import Path\n'
                 'try:\n print("ready", flush=True)\n time.sleep(60)\n'
                 f'finally:\n Path({str(marker)!r}).write_text("closed")\n')
    configure_board(window)
    window.show()
    window.start_evaluation()
    wait_for(app, lambda: 'ready' in window.test_panel.log.toPlainText().splitlines())
    window.close()
    assert window.isVisible()
    wait_for(app, lambda: not window.test_panel.busy)
    wait_for(app, lambda: not window.isVisible())
    assert marker.read_text() == 'closed'
    assert 'Cancelled' in window.test_panel.status.text()


def test_start_failure_and_retry(app, window, monkeypatch):
    configure_board(window)
    executable = sys.executable
    monkeypatch.setattr(sys, 'executable', '/nonexistent/python')
    window.start_evaluation()
    wait_for(app, lambda: not window.test_panel.busy)
    assert 'Failed to start' in window.test_panel.status.text()
    assert window.connect_button.isEnabled()
    monkeypatch.setattr(sys, 'executable', executable)
    fake_command(monkeypatch, 'print("retry 한글")')
    window.start_evaluation()
    wait_for(app, lambda: not window.test_panel.busy)
    assert 'Completed' in window.test_panel.status.text()
    assert 'retry 한글' in window.test_panel.log.toPlainText()
    assert window.test_panel.run_button.isEnabled()


def test_cancel_during_start_then_rerun(app, window, monkeypatch):
    fake_command(monkeypatch, 'import time; time.sleep(60)')
    configure_board(window)
    window.start_evaluation()
    original_directory = window.test_panel.result_directory
    window.start_evaluation()
    assert window.test_panel.result_directory == original_directory
    window.test_panel.cancel()
    wait_for(app, lambda: not window.test_panel.busy)
    assert 'Cancelled' in window.test_panel.status.text()
    assert not window.test_panel.kill_timer.isActive()
    fake_command(monkeypatch, 'print("second run")')
    window.start_evaluation()
    wait_for(app, lambda: not window.test_panel.busy)
    assert window.test_panel.result_directory != original_directory
    assert 'Completed' in window.test_panel.status.text()
    assert 'second run' in window.test_panel.log.toPlainText()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX ignored interrupt')
def test_forced_cancel_retains_incomplete_status(app, window, monkeypatch):
    fake_command(monkeypatch, 'import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); '
                 'print("ready", flush=True); time.sleep(60)')
    configure_board(window)
    window.show()
    window.start_evaluation()
    wait_for(app, lambda: 'ready' in window.test_panel.log.toPlainText().splitlines())
    window.close()
    window.test_panel.kill_timer.start(20)
    wait_for(app, lambda: not window.test_panel.busy)
    assert 'Cancelled' in window.test_panel.status.text()
    assert 'Forced stop' in window.test_panel.log.toPlainText()
    wait_for(app, lambda: not window.isVisible())


def test_output_error_does_not_launch(app, window, tmp_path):
    configure_board(window)
    path = tmp_path / 'not-a-directory'
    path.write_text('existing file')
    window.test_panel.output_directory = path
    window.start_evaluation()
    assert not window.test_panel.busy
    assert 'Cannot create output folder' in window.test_panel.status.text()
    assert path.read_text() == 'existing file'
    assert window.connect_button.isEnabled()


@pytest.mark.parametrize('preset', ['noise-sweep', 'spike-sweep'])
def test_sweep_presets_reach_real_cli_plan(app, window, monkeypatch, preset):
    original = preset_arguments
    monkeypatch.setattr('pc_sim.ui.evaluation_panel.preset_arguments',
                        lambda *args: [*original(*args), '--dry-run'])
    configure_board(window)
    window.test_panel.preset.setCurrentIndex(window.test_panel.preset.findData(preset))
    window.start_evaluation()
    wait_for(app, lambda: not window.test_panel.busy)
    assert 'Completed' in window.test_panel.status.text()
    assert '"run_count": ' + ('100' if preset == 'noise-sweep' else '49') in window.test_panel.log.toPlainText()
    assert not list(window.test_panel.result_directory.iterdir())
