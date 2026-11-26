"""Run existing board evaluation commands without sharing the manual UART worker."""
import codecs
import math
import os
from pathlib import Path
import shlex
import signal
import sys
import time

from PySide6.QtCore import QProcess, QTimer, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, QFileDialog, QPlainTextEdit,
    QDoubleSpinBox, QFormLayout,
)

from pc_sim.storage.recording import session_path

PRESETS = (
    ('normal', 'Normal', 'One run · 120 samples at 10 Hz · default: no added noise. Set noise below.'),
    ('noisy', 'Noisy', 'One run · 120 samples at 10 Hz · default range σ = 8 m. Set noise below.'),
    ('dropout', 'Dropout', 'One run · 120 samples at 10 Hz · omit measurements from 4.0 to 5.5 s.'),
    ('noise-sweep', 'Noise sweep', '100 runs · range / angle noise, 10 seeds. Allow about 25 minutes.'),
    ('spike-sweep', 'Spike sweep', '49 runs · range / angle outliers. Allow about 12 minutes. Assumes 100 m / 10° gates.'),
    ('turn-noise', 'Turn + noise', 'Straight → 90° right turn → straight. 755 samples at 10 Hz; seed 42. Set noise below (0 = no noise). About 80 s. Saves input and board results.'),
)


def preset_arguments(preset: str, port: str, output: Path) -> list[str]:
    """Leave numerical settings and evaluation logic with the existing CLI."""
    if preset in ('normal', 'noisy', 'dropout'):
        command = ['evaluate', 'run', '--scenario', preset]
    elif preset in ('noise-sweep', 'spike-sweep', 'turn-noise'):
        command = [preset]
    else:
        raise ValueError(f'Unknown evaluation preset: {preset}')
    return ['-u', '-m', 'pc_sim', *command, '--port', port, '--output', str(output)]


class EvaluationPanel(QWidget):
    run_requested = Signal()
    busy_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.busy = False
        self.cancelled = False
        self.allowed = False
        self.output_directory = Path.cwd() / 'runs' / 'tests'
        self.result_directory = None
        layout = QVBoxLayout(self)
        self.preset = QComboBox()
        for key, title, _ in PRESETS:
            self.preset.addItem(title, key)
        layout.addWidget(self.preset)
        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.preset.currentIndexChanged.connect(self.describe)
        self.describe()
        self.noise_settings = QWidget()
        noise_form = QFormLayout(self.noise_settings)
        noise_form.setContentsMargins(0, 0, 0, 0)
        noise_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.range_noise = QDoubleSpinBox()
        self.range_noise.setDecimals(2)
        self.range_noise.setRange(0, 1000)
        self.range_noise.setValue(10)
        self.angle_noise = QDoubleSpinBox()
        self.angle_noise.setDecimals(5)
        self.angle_noise.setSingleStep(.001)
        self.angle_noise.setRange(0, 3.14159)
        self.angle_noise.setValue(.01)
        noise_form.addRow('Range noise σ (m)', self.range_noise)
        noise_form.addRow('Azimuth noise σ (rad)', self.angle_noise)
        layout.addWidget(self.noise_settings)
        self.preset.currentIndexChanged.connect(self.update_noise_visibility)
        self.update_noise_visibility()
        note = QLabel('Board required. Select a data port in Connection; leave the manual session disconnected.\n\n'
                      'Independent of manual Settings. Results appear in Test results; live plots are for manual sessions.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.folder_button = QPushButton('Choose output folder')
        self.folder_button.clicked.connect(self.choose_output)
        layout.addWidget(self.folder_button)
        self.folder_label = QLabel(str(self.output_directory))
        self.folder_label.setWordWrap(True)
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.folder_label)
        self.run_button = QPushButton('Run test')
        self.preset.currentTextChanged.connect(lambda title: self.run_button.setText('Run ' + title))
        self.run_button.setText('Run ' + self.preset.currentText())
        self.run_button.setObjectName('primary')
        self.run_button.clicked.connect(self.run_requested.emit)
        self.cancel_button = QPushButton('Cancel test')
        self.cancel_button.clicked.connect(self.cancel)
        layout.addWidget(self.run_button)
        layout.addWidget(self.cancel_button)
        self.status = QLabel('Select Board UART and a data port.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.elapsed = QLabel('Elapsed: —')
        layout.addWidget(self.elapsed)
        self.open_button = QPushButton('Open results folder')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_results)
        layout.addWidget(self.open_button)
        layout.addStretch()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.started.connect(self.on_started)
        self.process.finished.connect(self.on_finished)
        self.process.errorOccurred.connect(self.on_error)
        self.kill_timer = QTimer(self)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.timeout.connect(self.force_stop)
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(200)
        self.elapsed_timer.timeout.connect(self.update_elapsed)
        self.update_buttons()

    def describe(self) -> None:
        self.description.setText(PRESETS[self.preset.currentIndex()][2])

    def update_noise_visibility(self) -> None:
        preset = self.preset.currentData()
        self.noise_settings.setVisible(preset in ('normal', 'noisy', 'dropout', 'turn-noise'))
        self.range_noise.setValue(10 if preset == 'turn-noise' else
                                  8 if preset in ('noisy', 'dropout') else 0)
        self.angle_noise.setValue(.01 if preset == 'turn-noise' else 0)

    def set_available(self, allowed: bool) -> None:
        self.allowed = allowed
        self.update_buttons()

    def update_buttons(self) -> None:
        self.run_button.setEnabled(self.allowed and not self.busy)
        self.cancel_button.setEnabled(self.busy and not self.cancelled)
        self.preset.setEnabled(not self.busy)
        self.folder_button.setEnabled(not self.busy)
        self.noise_settings.setEnabled(not self.busy)

    def choose_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, 'Test output folder', str(self.output_directory))
        if path:
            self.output_directory = Path(path)
            self.folder_label.setText(path)

    def open_results(self) -> None:
        if self.result_directory is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result_directory)))

    def start(self, port: str | None) -> None:
        if self.busy or not self.allowed or not port:
            return
        self.result_directory = session_path(self.output_directory).resolve()
        try:
            self.result_directory.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            self.status.setText(f'Cannot create output folder: {exc}')
            self.open_button.setEnabled(False)
            return
        args = preset_arguments(self.preset.currentData(), port, self.result_directory)
        if self.preset.currentData() == 'turn-noise':
            args.extend(['--noise', str(self.range_noise.value()),
                         '--azimuth-noise', str(self.angle_noise.value())])
        elif self.preset.currentData() in ('normal', 'noisy', 'dropout'):
            args.extend(['--range-noise', str(self.range_noise.value()),
                         '--azimuth-noise-deg', str(math.degrees(self.angle_noise.value()))])
        self.log.setPlainText('Command: ' + shlex.join([sys.executable, *args]) + '\n'
                              'Results: ' + str(self.result_directory) + '\n')
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.cancelled = False
        self.busy = True
        self.started_at = time.monotonic()
        self.status.setText('Running · waiting for CLI output…')
        self.open_button.setEnabled(True)
        self.update_buttons()
        self.busy_changed.emit(True)
        self.update_elapsed()
        self.elapsed_timer.start()
        self.process.start(sys.executable, args)

    def update_elapsed(self) -> None:
        self.elapsed.setText(f'Elapsed: {time.monotonic() - self.started_at:.1f} s')

    def read_output(self) -> None:
        self.append_output(self.decoder.decode(bytes(self.process.readAllStandardOutput())))

    def append_output(self, text: str) -> None:
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def on_started(self) -> None:
        if self.cancelled:
            self.interrupt()

    def cancel(self) -> None:
        if not self.busy or self.cancelled:
            return
        self.cancelled = True
        self.status.setText('Cancelling · waiting for port cleanup…')
        self.update_buttons()
        self.interrupt()
        self.kill_timer.start(5000)

    def interrupt(self) -> None:
        pid = self.process.processId()
        if not pid:
            return
        if os.name == 'posix':
            try:
                os.kill(pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        else:
            self.process.terminate()

    def force_stop(self) -> None:
        if self.busy:
            self.append_output('\nForced stop: partial files may be incomplete.\n')
            self.process.kill()

    def on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.finish('Failed to start: ' + self.process.errorString())

    def on_finished(self, code: int, exit_status: QProcess.ExitStatus) -> None:
        self.read_output()
        self.append_output(self.decoder.decode(b'', final=True))
        if self.cancelled:
            message = 'Cancelled · incomplete; partial files retained.'
        elif code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            message = 'Completed · see CLI metrics and checks in Test results.'
        else:
            message = f'Failed · exit {code}; see Test results.'
        self.finish(message)

    def finish(self, message: str) -> None:
        self.kill_timer.stop()
        self.elapsed_timer.stop()
        self.update_elapsed()
        self.status.setText(message)
        self.append_output('\n' + message + '\n')
        self.busy = False
        self.update_buttons()
        self.busy_changed.emit(False)
