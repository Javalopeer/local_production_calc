"""
Shared PySide6 widgets used across multiple tabs.

Centralises widgets that were previously copy-pasted between tab_register.py
and tab_overtime.py so that behaviour stays consistent in both places.
"""
from PySide6.QtWidgets import QTimeEdit, QDateEdit, QGroupBox, QVBoxLayout, QWidget
from PySide6.QtCore import QTime, QDate, Qt


class TimeEditWithShortcut(QTimeEdit):
    """QTimeEdit with Ctrl+Shift+: shortcut to stamp current time.

    Also selects all text on double-click for faster keyboard editing.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDisplayFormat("HH:mm")
        self.setCorrectionMode(QTimeEdit.CorrectToNearestValue)
        self.setAcceptDrops(True)

    def keyPressEvent(self, event):
        if event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if event.key() == Qt.Key.Key_Colon:
                self.setTime(QTime.currentTime())
                return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        if hasattr(self, 'lineEdit') and self.lineEdit():
            self.lineEdit().selectAll()


class DateEditWithShortcut(QDateEdit):
    """QDateEdit with Ctrl+Shift+; shortcut to stamp current date.

    Also selects all text on double-click for faster keyboard editing.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDisplayFormat("yyyy-MM-dd")
        self.setCalendarPopup(True)
        self.setAcceptDrops(True)

    def keyPressEvent(self, event):
        if event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if event.key() == Qt.Key.Key_Semicolon:
                self.setDate(QDate.currentDate())
                return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        if hasattr(self, 'lineEdit') and self.lineEdit():
            self.lineEdit().selectAll()


def card(title: str, widget) -> QGroupBox:
    """Wrap a widget or layout in a titled QGroupBox card."""
    box = QGroupBox(title)
    layout = QVBoxLayout()
    layout.addWidget(widget) if isinstance(widget, QWidget) else layout.addLayout(widget)
    box.setLayout(layout)
    return box
