"""Display changes must preserve sample values and raw logging semantics."""
import os
import random
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from pc_sim.ui.display_helpers import AnsiFilter


def test_ansi_filter_all_chunk_boundaries():
    raw = '[00:29:46.190,000] \x1b[1;33m<wrn> frame_handler: Radar measurement timeout: track=cleared\x1b[0m\r\n'
    expected = '[00:29:46.190,000] <wrn> frame_handler: Radar measurement timeout: track=cleared\n'
    for index in range(len(raw) + 1):
        parser = AnsiFilter()
        assert parser.feed(raw[:index]) + parser.feed(raw[index:]) == expected
    parser = AnsiFilter()
    assert ''.join(parser.feed(c) for c in raw) == expected


def test_ui_display_modes():
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    from PySide6.QtWidgets import QApplication
    from pc_sim.ui.gui import MainWindow
    from pc_sim.simulation.gui_model import Settings, make_sample
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    try:
        window.control_tabs.setCurrentIndex(4)
        app.processEvents()
        assert not window.start_button.isVisible()
        window.test_panel.preset.setCurrentIndex(4)
        assert window.test_panel.run_button.text() == 'Run Spike sweep'
        window.control_tabs.setCurrentIndex(1)
        assert window.start_button.isVisible()
        samples = [make_sample(Settings(), stamp, random.Random(stamp)) for stamp in range(0, 2100, 100)]
        window.samples.extend(samples)
        window.draw_samples()
        follow = window.map_plot.viewRange()
        assert follow[1][1] - follow[1][0] < 300
        window.map_view.setCurrentIndex(1)
        full = window.map_plot.viewRange()
        assert full[1][1] - full[1][0] >= 2400
        window.map_view.setCurrentIndex(2)
        window.map_plot.setRange(xRange=(1, 20), yRange=(2, 30), padding=0)
        manual = window.map_plot.viewRange()
        window.draw_samples()
        assert window.map_plot.viewRange() == manual
        assert list(window.samples) == samples
        window.append_console('\x1b[1;')
        window.append_console('33mwarning\x1b[0m\n')
        assert window.console_text.toPlainText() == 'warning\n'
    finally:
        window.close()


def test_left_panel_can_resize():
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    from PySide6.QtWidgets import QApplication
    from pc_sim.ui.gui import MainWindow
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1280, 850)
    window.show()
    try:
        app.processEvents()
        before = window.main_split.sizes()[0]
        window.main_split.setSizes([480, 760])
        app.processEvents()
        assert window.main_split.sizes()[0] > before + 50
        assert window.main_split.widget(0).minimumWidth() < window.main_split.widget(0).maximumWidth()
    finally:
        window.close()
