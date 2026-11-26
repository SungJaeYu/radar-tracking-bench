"""Keep GUI unit tests independent of USB devices attached to the host."""
import pytest


@pytest.fixture(autouse=True)
def isolated_serial_discovery(monkeypatch):
    # Individual discovery tests supply their own explicit device inventory.
    from serial.tools import list_ports
    monkeypatch.setattr(list_ports, 'comports', lambda: [])
