"""Tab pages with a wrapping selector instead of an overflowing tab strip."""
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QPushButton, QTabWidget, QVBoxLayout, QWidget


class SectionTabs(QWidget):
    """Display two columns of fully named buttons above existing tab pages."""

    def __init__(self, tabs: QTabWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self.buttons = QButtonGroup(self)
        for index in range(tabs.count()):
            button = QPushButton(tabs.tabText(index))
            button.setCheckable(True)
            button.setToolTip(tabs.tabToolTip(index))
            button.setStyleSheet('QPushButton { padding: 7px 6px; } '
                                'QPushButton:checked { background: #305064; border-color: #30c9b8; }')
            self.buttons.addButton(button, index)
            grid.addWidget(button, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.buttons.idClicked.connect(tabs.setCurrentIndex)
        tabs.currentChanged.connect(self.select)
        tabs.tabBar().hide()
        layout.addLayout(grid)
        layout.addWidget(tabs, 1)
        self.select(tabs.currentIndex())

    def select(self, index: int) -> None:
        button = self.buttons.button(index)
        if button is not None:
            button.setChecked(True)
