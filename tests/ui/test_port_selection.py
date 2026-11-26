"""Port suggestions must remain conservative and overridable."""
from types import SimpleNamespace
import os
import pytest
from pc_sim.ui.port_selection import suggest_ports


def port(device, description):
    return SimpleNamespace(device=device, description=description)


def test_current_board_names():
    assert suggest_ports([port('board', 'STM32 STLink'), port('uart', 'FT232R USB UART'),
                          port('bluetooth', 'n/a')]) == {'data': 'uart', 'console': 'board'}


def test_ambiguous_and_unknown_ports():
    assert suggest_ports([port('a', 'USB UART'), port('b', 'USB UART'),
                          port('c', None)]) == {'data': None, 'console': None}
    assert suggest_ports([port('a', 'STM32'), port('b', 'ST-Link')])['console'] is None


def test_manual_choices_survive_refresh(monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    from PySide6.QtWidgets import QApplication
    from pc_sim.ui.gui import MainWindow
    ports = [port('board', 'STM32 STLink'), port('uart', 'FT232R USB UART')]
    monkeypatch.setattr('pc_sim.ui.gui.list_ports.comports', lambda: ports)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.data_port.currentData() == 'uart'
        assert window.console_port.currentData() == 'board'
        assert window.worker is None
        window.console_port.setCurrentIndex(0)
        window.console_port.activated.emit(0)
        window.refresh_ports()
        assert window.console_port.currentData() is None
        assert window.data_port.currentData() == 'uart'
        window.data_port.setCurrentIndex(window.data_port.findData('board'))
        window.data_port.activated.emit(window.data_port.currentIndex())
        window.refresh_ports()
        assert window.data_port.currentData() == 'board'
    finally:
        window.close()
