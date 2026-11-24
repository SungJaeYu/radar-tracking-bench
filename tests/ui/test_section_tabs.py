"""Navigation names remain visible at the smallest supported window size."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')
pytest.importorskip('pyqtgraph')
from PySide6.QtWidgets import QApplication
from pc_sim.ui.gui import MainWindow


def test_all_section_names_fit_and_select_pages():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(950, 600)
    window.show()
    window.main_split.setSizes([280, 650])
    window.content_split.setSizes([400, 230])
    try:
        app.processEvents()
        for selector, tabs in [(window.control_sections, window.control_tabs),
                               (window.log_sections, window.log_tabs)]:
            assert not tabs.tabBar().isVisible()
            for button in selector.buttons.buttons():
                assert button.isVisible()
                assert button.width() >= button.sizeHint().width()
                button.click()
                assert tabs.currentIndex() == selector.buttons.id(button)
                assert button.isChecked()
    finally:
        window.close()
