"""Desktop HIL console. Launch with python -m pc_sim.ui.gui."""
from collections import deque
import math
from datetime import datetime
from pathlib import Path
import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QComboBox, QDoubleSpinBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit, QPushButton,
    QSplitter, QTabWidget, QVBoxLayout, QWidget, QScrollArea, QLayout, QSizePolicy,
)
import pyqtgraph as pg
from serial.tools import list_ports

from pc_sim.simulation.gui_model import Settings, TrackMonitor
from pc_sim.ui.gui_worker import SessionWorker
from pc_sim.ui.evaluation_panel import EvaluationPanel
from pc_sim.ui.display_helpers import AnsiFilter
from pc_sim.ui.port_selection import suggest_ports
from pc_sim.ui.section_tabs import SectionTabs
from pc_sim.storage.recording import session_path
from pc_sim.transport.protocol import STATUS_FIELDS

STYLE = '''
QWidget { background: #101820; color: #dce8ef; font-size: 13px; }
QLabel#title { font-size: 25px; font-weight: 700; color: #ffffff; }
QLabel#subtitle { color: #8fa8b9; }
QFrame#panel { background: #17232e; border: 1px solid #293c4c; border-radius: 8px; }
QComboBox, QDoubleSpinBox { background: #0d151e; border: 1px solid #365064;
    border-radius: 4px; padding: 6px; min-height: 22px; }
QPushButton { background: #253d50; border: 1px solid #36546a;
    border-radius: 5px; padding: 9px 14px; font-weight: 600; }
QPushButton:hover { background: #34576e; }
QPushButton#primary { background: #147e75; border: 1px solid #30c9b8; }
QPushButton#primary:disabled { background: #20413e; border-color: #305550; color: #809390; }
QPushButton:disabled { color: #647788; background: #1b2935; border-color: #293c4c; }
QPlainTextEdit { background: #0c131b; border: 1px solid #293c4c;
    font-family: Menlo, monospace; font-size: 12px; }
QTabBar::tab { background: #1a2b39; padding: 8px 10px; }
QTabBar::tab:selected { background: #305064; }
QSplitter::handle { background: #293c4c; }
'''


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.closing = False
        self.connected = False
        self.status_pending = False
        self.console_filter = AnsiFilter()
        self.port_overrides = set()
        self.samples = deque(maxlen=2000)
        self.sample_count = 0
        self.track_monitor = TrackMonitor()
        self.setWindowTitle('Radar Lab · HIL Console')
        self.resize(1280, 850)
        self.setMinimumSize(950, 600)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1280, screen.width() - 40), min(850, screen.height() - 80))
        self.setStyleSheet(STYLE)
        pg.setConfigOptions(antialias=True, background='#101820', foreground='#9db3c2')
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 14, 16, 14)
        title = QLabel('RADAR LAB  /  HIL CONSOLE')
        title.setObjectName('title')
        layout.addWidget(title)
        subtitle = QLabel('Single-target simulator  ·  115200 baud / 8N1  ·  PC truth / board estimates / diagnostics')
        subtitle.setObjectName('subtitle')
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        body = QHBoxLayout()
        layout.addLayout(body, 1)
        self.main_split = QSplitter(Qt.Orientation.Horizontal)
        self.main_split.setChildrenCollapsible(False)
        self.main_split.setHandleWidth(7)
        body.addWidget(self.main_split)
        panel = QFrame()
        panel.setObjectName('panel')
        panel.setMinimumWidth(280)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 12, 10, 12)
        self.main_split.addWidget(panel)
        self.control_tabs = QTabWidget()
        self.control_tabs.setStyleSheet('QTabBar::tab { padding: 8px 6px; font-size: 12px; }')

        def tab_page(title):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            content = QWidget()
            page_layout = QVBoxLayout(content)
            page_layout.setContentsMargins(8, 12, 8, 12)
            page_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
            scroll.setWidget(content)
            self.control_tabs.addTab(scroll, title)
            return scroll, page_layout

        _, controls = tab_page('Connection')
        self.mode = QComboBox()
        self.mode.addItems(['Preview · no board', 'Board UART · live transmission'])
        controls.addWidget(self.mode)
        self.data_port = QComboBox()
        self.console_port = QComboBox()
        self.data_port.activated.connect(lambda: self.port_overrides.add('data'))
        self.console_port.activated.connect(lambda: self.port_overrides.add('console'))
        for label, combo in (('Data port · USB-UART', self.data_port),
                             ('Console port · ST-Link', self.console_port)):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(16)
            controls.addWidget(QLabel(label))
            controls.addWidget(combo)
        self.refresh_button = QPushButton('Refresh ports')
        self.refresh_button.clicked.connect(self.refresh_ports)
        controls.addWidget(self.refresh_button)
        self.connect_button = QPushButton('Connect preview')
        self.connect_button.clicked.connect(self.toggle_connection)
        controls.addWidget(self.connect_button)
        self.connection_label = QLabel('Disconnected')
        self.connection_label.setWordWrap(True)
        controls.addWidget(self.connection_label)
        controls.addStretch()
        self.controls_scroll, controls = tab_page('Settings')
        scope_note = QLabel('Single target · fixed azimuth / constant range rate')
        scope_note.setWordWrap(True)
        controls.addWidget(scope_note)
        self.record_directory = Path.cwd() / 'runs'
        self.record_checkbox = QCheckBox('Record CSV (folder per run)')
        controls.addWidget(self.record_checkbox)
        self.record_button = QPushButton('Choose output folder')
        self.record_button.clicked.connect(self.choose_record_directory)
        controls.addWidget(self.record_button)
        self.record_label = QLabel(str(self.record_directory))
        self.record_label.setWordWrap(True)
        controls.addWidget(self.record_label)
        self.settings_form = QWidget()
        fields = QFormLayout(self.settings_form)
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        fields.setVerticalSpacing(10)
        fields.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.inputs = {}
        definitions = [
            ('initial_range_m', 'Initial range (m)', 1, 65535, 1000, 1),
            ('range_rate_mps', 'Range rate (m/s)', -1000, 1000, -20, 1),
            ('azimuth_deg', 'Azimuth (°)', -180, 180, 15, 1),
            ('range_noise_std_m', 'Range noise σ (m)', 0, 1000, 5, 1),
            ('sample_rate_hz', 'Sample rate (Hz)', 1, 50, 10, 0),
            ('duration_s', 'Duration (s)', 1, 3600, 30, 0),
        ]
        for key, label, low, high, default, decimals in definitions:
            field = QDoubleSpinBox()
            field.setRange(low, high)
            field.setDecimals(decimals)
            field.setValue(default)
            field.setMinimumHeight(max(38, field.sizeHint().height()))
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.inputs[key] = field
            fields.addRow(label, field)
        controls.addWidget(self.settings_form)
        note = QLabel('Negative range rate = approaching\nAzimuth: north 0°, east +90°\nINIT is sent automatically on start.')
        note.setWordWrap(True)
        note.setObjectName('subtitle')
        controls.addWidget(note)
        _, status_layout = tab_page('STATUS')
        self.status_button = QPushButton('Query STATUS')
        self.status_button.clicked.connect(self.request_status)
        status_layout.addWidget(self.status_button)
        self.status_message = QLabel('Connect a board to query STATUS.')
        self.status_message.setWordWrap(True)
        status_layout.addWidget(self.status_message)
        status_form = QFormLayout()
        status_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.status_values = {}
        for key, _, label in STATUS_FIELDS:
            value = QLabel('—')
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.status_values[key] = value
            status_form.addRow(label, value)
        status_layout.addLayout(status_form)
        self.status_updated = QLabel('Last successful query: —')
        self.status_updated.setWordWrap(True)
        status_layout.addWidget(self.status_updated)
        note = QLabel('Cumulative board RX counters, not BIT results. Previous values are retained if a query fails.')
        note.setWordWrap(True)
        status_layout.addWidget(note)
        status_layout.addStretch()

        self.track_scroll, track_layout = tab_page('TRACK')
        self.track_message = QLabel('Waiting for board TRACK')
        self.track_message.setWordWrap(True)
        track_layout.addWidget(self.track_message)
        track_form = QFormLayout()
        track_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.track_values = {}
        for key, label in (
            ('report_sequence', 'Report sequence'), ('state', 'Last board state'),
            ('result', 'Result'), ('input_timestamp_ms', 'Input time (ms)'),
            ('estimate_timestamp_ms', 'Estimate time (ms)'), ('range_m', 'Range (m)'),
            ('azimuth_rad', 'Azimuth (rad)'), ('range_rate_mps', 'Range rate (m/s)'),
            ('azimuth_rate_radps', 'Azimuth rate (rad/s)'),
            ('sequence_gaps', 'Sequence gaps'), ('discontinuities', 'Discontinuities'),
        ):
            value = QLabel('—')
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.track_values[key] = value
            track_form.addRow(label, value)
        track_layout.addLayout(track_form)
        note = QLabel('STALE: no new TRACK for 2 s. This is separate from board LOST.\n'
                      'Sequence gaps do not identify where or why reports were lost.\n'
                      'Range history uses estimates whose timestamps match PC measurements.')
        note.setWordWrap(True)
        note.setObjectName('subtitle')
        track_layout.addWidget(note)
        track_layout.addStretch()

        _, test_layout = tab_page('Tests')
        self.test_panel = EvaluationPanel(self)
        test_layout.addWidget(self.test_panel)
        self.test_panel.run_requested.connect(self.start_evaluation)
        self.test_panel.busy_changed.connect(self.on_evaluation_busy)
        self.control_sections = SectionTabs(self.control_tabs)
        panel_layout.addWidget(self.control_sections, 1)

        self.start_button = QPushButton('▶  Start manual simulation')
        self.start_button.setObjectName('primary')
        self.start_button.clicked.connect(self.start_simulation)
        self.stop_button = QPushButton('■  Stop sending')
        self.stop_button.clicked.connect(self.stop_simulation)
        controls.addStretch()
        panel_layout.addWidget(self.start_button)
        panel_layout.addWidget(self.stop_button)
        self.control_tabs.currentChanged.connect(self.update_manual_buttons)

        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(0, 0, 0, 0)
        self.main_split.addWidget(right_widget)
        self.main_split.setSizes([360, 900])
        self.main_split.setStretchFactor(0, 0)
        self.main_split.setStretchFactor(1, 1)
        self.metrics = QLabel('Idle  ·  Generated/sent 0  ·  Elapsed 0.0 s')
        self.metrics.setWordWrap(True)
        right.addWidget(self.metrics)
        self.map_view = QComboBox()
        self.map_view.addItems(['Target position: Follow target', 'Target position: Full range',
                                'Target position: Manual zoom'])
        self.map_view.setToolTip('Follow uses recent motion and noise spread. Manual zoom allows wheel/drag.')
        self.map_view.currentIndexChanged.connect(self.update_map_view)
        self.content_split = split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        right.addWidget(split, 1)
        self.plots_split = plots = QSplitter(Qt.Orientation.Vertical)
        plots.setChildrenCollapsible(False)
        plot_panel = QWidget()
        plot_layout = QVBoxLayout(plot_panel)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(4)
        plot_layout.addWidget(self.map_view)
        plot_layout.addWidget(plots, 1)
        split.addWidget(plot_panel)
        self.map_plot = pg.PlotWidget(title='Target position')
        self.map_plot.setLabel('bottom', 'East', units='m')
        self.map_plot.setLabel('left', 'North', units='m')
        self.map_plot.setAspectLocked(True)
        self.map_plot.showGrid(x=True, y=True, alpha=0.2)
        self.map_plot.addLegend(offset=(10, 10))
        self.map_plot.plot([0], [0], pen=None, symbol='t', symbolSize=14,
                           symbolBrush='#ffffff')
        self.truth_point = self.map_plot.plot([], [], pen=None, symbol='o', symbolSize=12,
                                              symbolBrush='#3ce0b1', name='Truth (synthetic)')
        self.measured_points = self.map_plot.plot([], [], pen=None, symbol='+', symbolSize=10,
                                                  symbolPen='#f4bf65', name='Measured (PC)')
        self.estimated_point = self.map_plot.plot([], [], pen=None, symbol='d', symbolSize=12,
                                                  symbolBrush='#75bfff', name='Estimated (board)')
        plots.addWidget(self.map_plot)
        self.range_plot = pg.PlotWidget(title='Range history · sensor time')
        self.range_plot.setLabel('bottom', 'Time', units='s')
        self.range_plot.setLabel('left', 'Range', units='m')
        self.range_plot.showGrid(x=True, y=True, alpha=0.2)
        self.range_plot.addLegend(offset=(10, 10))
        self.truth_curve = self.range_plot.plot(pen=pg.mkPen('#3ce0b1', width=2), name='Truth (synthetic)')
        self.measured_curve = self.range_plot.plot(pen=pg.mkPen('#f4bf65', width=1), name='Measured (PC)')
        self.estimated_curve = self.range_plot.plot(pen=pg.mkPen('#75bfff', width=2),
                                                     connect='finite', name='Estimated (board)')
        plots.addWidget(self.range_plot)
        plots.setSizes([360, 300])
        plots.setStretchFactor(0, 1)
        plots.setStretchFactor(1, 1)
        self.log_tabs = tabs = QTabWidget()
        self.console_text = QPlainTextEdit()
        self.event_text = QPlainTextEdit()
        for widget in (self.console_text, self.event_text):
            widget.setReadOnly(True)
            widget.setMaximumBlockCount(2000)
        tabs.addTab(self.console_text, 'Console')
        tabs.setTabToolTip(0, 'Board console · ST-Link')
        tabs.addTab(self.event_text, 'TX log')
        tabs.addTab(self.test_panel.log, 'Test results')
        self.log_sections = SectionTabs(tabs)
        self.log_sections.ensurePolished()
        self.map_view.setFixedHeight(self.log_sections.layout().itemAt(0).sizeHint().height())
        split.addWidget(self.log_sections)
        split.setSizes([650, 250])
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        self.board_note = QLabel('Waiting for board TRACK · Preview does not generate board estimates.')
        self.board_note.setWordWrap(True)
        self.board_note.setObjectName('subtitle')
        right.addWidget(self.board_note)
        self.mode.currentIndexChanged.connect(self.update_controls)
        self.refresh_ports()
        self.data_port.currentIndexChanged.connect(self.update_test_availability)
        self.update_controls()
        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self.draw_samples)
        self.plot_timer.start(100)

    def refresh_ports(self):
        ports = list(list_ports.comports())
        suggestions = suggest_ports(ports)
        for role, combo in (('data', self.data_port), ('console', self.console_port)):
            selected = combo.currentData()
            if selected is None and role not in self.port_overrides:
                selected = suggestions[role]
            combo.clear()
            combo.addItem('None', None)
            for port in ports:
                combo.addItem(f'{port.device} · {port.description}', port.device)
            index = combo.findData(selected)
            combo.setCurrentIndex(max(0, index))

    def update_manual_buttons(self):
        manual = self.control_tabs.currentIndex() != 4
        self.start_button.setVisible(manual)
        self.stop_button.setVisible(manual)

    def update_map_view(self):
        if self.map_view.currentIndex() == 1:
            extent = self.inputs['initial_range_m'].value() * 1.2
            self.map_plot.setRange(xRange=(-extent, extent), yRange=(-extent, extent), padding=0)
        self.draw_samples()

    def update_controls(self):
        busy = self.worker is not None
        board = self.mode.currentIndex() == 1
        self.mode.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.data_port.setEnabled(board and not busy)
        self.console_port.setEnabled(board and not busy)
        self.connect_button.setText('Disconnect' if busy else ('Connect board' if board else 'Connect preview'))
        self.connect_button.setEnabled(not busy or self.connected)
        self.start_button.setEnabled(self.connected)
        self.stop_button.setEnabled(False)
        self.status_button.setEnabled(self.connected and board and not self.status_pending)
        if self.test_panel.busy:
            for control in (self.mode, self.refresh_button, self.data_port, self.console_port,
                            self.connect_button, self.start_button, self.stop_button, self.status_button):
                control.setEnabled(False)
        self.update_test_availability()

    def update_test_availability(self):
        self.test_panel.set_available(self.worker is None and self.mode.currentIndex() == 1
                                      and bool(self.data_port.currentData()) and not self.closing)

    def start_evaluation(self):
        self.update_test_availability()
        self.test_panel.start(self.data_port.currentData())

    def on_evaluation_busy(self, busy):
        self.update_controls()
        if busy:
            self.log_tabs.setCurrentWidget(self.test_panel.log)
            self.samples.clear()
            self.sample_count = 0
            self.reset_track_display()
            for curve in (self.truth_curve, self.measured_curve, self.truth_point, self.measured_points):
                curve.setData([], [])
            self.metrics.setText('Preset test · see Test results · live plots inactive')
        elif self.closing:
            self.close()

    def toggle_connection(self):
        if self.test_panel.busy or self.closing:
            return
        if self.worker is not None:
            self.disconnect()
            return
        board = self.mode.currentIndex() == 1
        data = self.data_port.currentData() if board else None
        console = self.console_port.currentData() if board else None
        if board and not data:
            self.show_error('Select a data port.')
            return
        if data and data == console:
            self.show_error('Data and console ports must be different.')
            return
        self.worker = SessionWorker(data, console, self)
        self.worker.recording_started.connect(self.on_recording_started)
        self.worker.track_received.connect(self.on_track_received)
        self.worker.status_received.connect(self.on_status_received)
        self.worker.status_failed.connect(self.on_status_failed)
        self.worker.connected.connect(self.on_connected)
        self.worker.sample.connect(self.on_sample)
        self.worker.console.connect(self.append_console)
        self.worker.event.connect(self.event_text.appendPlainText)
        self.worker.error.connect(self.show_error)
        self.worker.running_changed.connect(self.on_running)
        self.worker.finished.connect(self.on_disconnected)
        self.connection_label.setText('Connecting…')
        self.update_controls()
        self.worker.start()

    def on_connected(self):
        self.connected = True
        board = self.mode.currentIndex() == 1
        self.connection_label.setText('Board ports connected' if board else 'Preview ready · UART unused')
        self.event_text.appendPlainText(self.connection_label.text())
        self.status_pending = False
        for value in self.status_values.values():
            value.setText('—')
        self.status_updated.setText('Last successful query: —')
        self.status_message.setText('Ready to query' if board else 'STATUS is unavailable in preview.')
        self.console_text.clear()
        self.console_filter = AnsiFilter()
        self.reset_track_display()
        if not self.worker.console_port:
            self.console_text.setPlainText('No console port connected.\nDiagnostics arrive via the ST-Link console; estimates arrive via TRACK on the data port.\n')
        self.update_controls()

    def request_status(self):
        if not self.connected or self.worker is None or self.status_pending:
            return
        if self.worker.request_status():
            self.status_pending = True
            self.status_button.setEnabled(False)
            self.status_message.setText('Waiting for response…')

    def on_status_received(self, stats):
        if not self.connected:
            return
        self.status_pending = False
        for key, value in self.status_values.items():
            value.setText(str(stats[key]) if key in stats else "Unsupported")
        self.status_updated.setText('Last successful query: ' + datetime.now().strftime('%H:%M:%S'))
        self.status_message.setText('Query successful')
        self.status_button.setEnabled(True)

    def on_status_failed(self, message):
        self.status_pending = False
        self.status_message.setText(message)
        self.status_button.setEnabled(self.connected and self.mode.currentIndex() == 1)

    def reset_track_display(self):
        self.track_monitor.reset()
        for value in self.track_values.values():
            value.setText('—')
        self.estimated_curve.setData([], [])
        self.estimated_point.setData([], [])
        self.draw_track()

    def on_track_received(self, report, received_at):
        if not self.connected or not self.track_monitor.receive(report, received_at):
            return
        self.track_values['report_sequence'].setText(str(report.report_sequence))
        self.track_values['state'].setText(report.state.name)
        self.track_values['result'].setText(report.result.name)
        self.track_values['input_timestamp_ms'].setText(
            str(report.input_timestamp_ms) if report.input_present else '—')
        self.track_values['estimate_timestamp_ms'].setText(
            str(report.estimate_timestamp_ms) if report.estimate_valid else '—')
        for key in ('range_m', 'azimuth_rad', 'range_rate_mps', 'azimuth_rate_radps'):
            self.track_values[key].setText(f'{getattr(report, key):.3f}' if report.estimate_valid else '—')
        self.track_values['sequence_gaps'].setText(str(self.track_monitor.sequence_gaps))
        self.track_values['discontinuities'].setText(str(self.track_monitor.discontinuities))
        self.draw_track()

    def draw_track(self):
        monitor = self.track_monitor
        report = monitor.latest
        stale = monitor.is_stale(time.monotonic())
        live = self.connected and not stale and report is not None and report.estimate_valid
        if live:
            self.estimated_point.setData([report.range_m * math.sin(report.azimuth_rad)],
                                         [report.range_m * math.cos(report.azimuth_rad)])
        else:
            self.estimated_point.setData([], [])
        times, ranges = monitor.range_history(self.samples)
        self.estimated_curve.setData(times, ranges)
        self.estimated_curve.setOpacity(1.0 if self.connected and not stale else 0.35)
        if report is None:
            message = ('Waiting for board TRACK' if self.mode.currentIndex() == 1 else
                       'Preview · no board estimates')
        else:
            age = max(0.0, time.monotonic() - monitor.received_at)
            freshness = ('Disconnected · previous result' if not self.connected else
                         'STALE · old result' if stale else 'Receiving')
            validity = 'Estimate valid' if report.estimate_valid else 'Estimate invalid'
            message = f'{freshness} · #{report.report_sequence} · {age:.1f} s ago · {validity}'
        self.track_message.setText(message)
        self.board_note.setText('Preset test running · see Test results; live plots inactive.'
                                if self.test_panel.busy else message)

    def choose_record_directory(self):
        directory = QFileDialog.getExistingDirectory(self, 'CSV output folder', str(self.record_directory))
        if directory:
            self.record_directory = Path(directory)
            self.record_label.setText(directory)

    def on_recording_started(self, path):
        self.record_label.setText(path)
        self.event_text.appendPlainText('CSV recording: ' + path)

    def start_simulation(self):
        if not self.connected or self.test_panel.busy:
            return
        settings = Settings(**{key: field.value() for key, field in self.inputs.items()})
        settings.validate()
        self.samples.clear()
        self.sample_count = 0
        self.reset_track_display()
        for curve in (self.truth_curve, self.measured_curve, self.truth_point, self.measured_points):
            curve.setData([], [])
        extent = settings.initial_range_m * 1.2
        self.map_plot.setRange(xRange=(-extent, extent), yRange=(-extent, extent), padding=0)
        self.start_button.setEnabled(False)
        self.settings_form.setEnabled(False)
        path = session_path(self.record_directory) if self.record_checkbox.isChecked() else None
        self.worker.start_simulation(settings, path)

    def stop_simulation(self):
        if self.worker:
            self.stop_button.setEnabled(False)
            self.worker.stop_simulation()

    def on_running(self, running):
        self.record_checkbox.setEnabled(not running)
        self.record_button.setEnabled(not running)
        self.start_button.setEnabled(self.connected and not running)
        self.stop_button.setEnabled(self.connected and running)
        self.settings_form.setEnabled(not running)
        self.statusBar().showMessage('Running' if running else 'Sending idle / stopped')

    def on_sample(self, sample):
        self.samples.append(sample)
        self.sample_count += 1
        verb = 'UART write' if self.mode.currentIndex() else 'Preview generated'
        self.metrics.setText(f'{verb}  {self.sample_count}  ·  {sample.timestamp_ms / 1000:.1f} s'
                             f'  ·  Truth {sample.truth_range_m:.1f} m  ·  Measured {sample.measured_range_m} m')
        self.event_text.appendPlainText(f'{sample.timestamp_ms:>7} ms  {verb}  {sample.frame.hex(" ")}')

    def draw_samples(self):
        # Freshness must still update when simulation is stopped or no samples exist.
        self.draw_track()
        if not self.samples:
            return
        values = list(self.samples)
        times = [s.timestamp_ms / 1000 for s in values]
        self.truth_curve.setData(times, [s.truth_range_m for s in values])
        self.measured_curve.setData(times, [s.measured_range_m for s in values])
        last = values[-1]
        self.truth_point.setData([last.truth_range_m * math.sin(last.azimuth_rad)],
                                 [last.truth_range_m * math.cos(last.azimuth_rad)])
        trail = values[-100:]
        self.measured_points.setData([s.measured_range_m * math.sin(s.azimuth_rad) for s in trail],
                                     [s.measured_range_m * math.cos(s.azimuth_rad) for s in trail])
        if self.map_view.currentIndex() == 0:
            # A short time window keeps noise visible while accommodating target speed.
            recent = [s for s in trail if last.timestamp_ms - s.timestamp_ms <= 2000]
            points = [(s.measured_range_m * math.sin(s.azimuth_rad),
                       s.measured_range_m * math.cos(s.azimuth_rad)) for s in recent]
            center_x = last.truth_range_m * math.sin(last.azimuth_rad)
            center_y = last.truth_range_m * math.cos(last.azimuth_rad)
            report = self.track_monitor.latest
            if (self.connected and report is not None and report.estimate_valid
                    and not self.track_monitor.is_stale(time.monotonic())):
                points.append((report.range_m * math.sin(report.azimuth_rad),
                               report.range_m * math.cos(report.azimuth_rad)))
            radius = max(10.0, self.inputs['range_noise_std_m'].value() * 4,
                         *(max(abs(x - center_x), abs(y - center_y)) * 1.2 for x, y in points))
            self.map_plot.setRange(xRange=(center_x - radius, center_x + radius),
                                   yRange=(center_y - radius, center_y + radius), padding=0)

    def append_console(self, text):
        cursor = self.console_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(self.console_filter.feed(text))
        self.console_text.setTextCursor(cursor)
        self.console_text.ensureCursorVisible()

    def show_error(self, text):
        self.event_text.appendPlainText('Error: ' + text)
        self.statusBar().showMessage('Error: ' + text)

    def disconnect(self):
        self.connected = False
        self.draw_track()
        self.connect_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.status_button.setEnabled(False)
        self.connection_label.setText('Disconnecting…')
        self.worker.requestInterruption()

    def on_disconnected(self):
        self.worker.deleteLater()
        self.worker = None
        self.connected = False
        self.status_pending = False
        self.status_message.setText('Disconnected · values are from the previous query.')
        self.connection_label.setText('Disconnected')
        self.settings_form.setEnabled(True)
        self.update_controls()
        if self.closing:
            self.close()

    def closeEvent(self, event):
        if self.test_panel.busy:
            self.closing = True
            self.test_panel.cancel()
            event.ignore()
        elif self.worker is not None:
            self.closing = True
            self.disconnect()
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
