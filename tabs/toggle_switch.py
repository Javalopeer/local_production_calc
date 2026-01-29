from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property, Signal
from PySide6.QtGui import QPainter, QColor, QPen


class ToggleSwitch(QWidget):
    toggled = Signal(bool)
    
    def __init__(self, parent=None, checked=True):
        super().__init__(parent)
        self._checked = checked
        self._circle_position = 22 if checked else 2
        self.setFixedSize(44, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Animation
        self._animation = QPropertyAnimation(self, b"circle_position", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
    
    def get_circle_position(self):
        return self._circle_position
    
    def set_circle_position(self, pos):
        self._circle_position = pos
        self.update()
    
    circle_position = Property(float, get_circle_position, set_circle_position)
    
    def isChecked(self):
        return self._checked
    
    def setChecked(self, checked):
        if self._checked != checked:
            self._checked = checked
            self._animation.setStartValue(self._circle_position)
            self._animation.setEndValue(22 if checked else 2)
            self._animation.start()
            self.toggled.emit(checked)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Background
        if self._checked:
            bg_color = QColor(76, 175, 80)  # Green when ON
        else:
            bg_color = QColor(158, 158, 158)  # Gray when OFF
        
        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, 44, 22, 11, 11)
        
        # Circle
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(int(self._circle_position), 2, 18, 18)
