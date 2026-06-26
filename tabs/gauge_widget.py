"""Donut gauge widget — shows a % of target with a centered label.

Below 100%: blue arc from 0 → value.
At/above 100%: green ring plus blue overflow arc for the >100% portion.
"""
from PySide6.QtCore import Qt, QRectF, QSize, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QWidget


class GaugeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0          # current % (0..∞)
        self._displayed = 0.0      # animated value used by paint
        self.setMinimumSize(160, 100)

        self._anim = QPropertyAnimation(self, b"displayedValue", self)
        self._anim.setDuration(600)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def apply_palette(self, is_light: bool):
        """Force a repaint when theme changes so palette colours refresh."""
        self.update()

    # ── Animated property ─────────────────────────────────────────────────
    def getDisplayedValue(self):
        return self._displayed

    def setDisplayedValue(self, v):
        self._displayed = float(v)
        self.update()

    displayedValue = Property(float, getDisplayedValue, setDisplayedValue)

    # ── Public API ────────────────────────────────────────────────────────
    def setValue(self, pct: float):
        self._value = float(pct or 0.0)
        self._anim.stop()
        self._anim.setStartValue(self._displayed)
        self._anim.setEndValue(self._value)
        self._anim.start()

    def value(self) -> float:
        return self._value

    # ── Painting ──────────────────────────────────────────────────────────
    def sizeHint(self):
        return QSize(180, 110)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Pick the largest semi-circle that fits both width and 2×height,
        # then anchor the bounding square at the top of the widget so the
        # visible top-half arc spans from the widget's top down to its
        # vertical centre.
        margin = 6
        avail_w = self.width() - margin * 2
        avail_h = (self.height() - margin) * 2  # the square extends below
        side = max(0, min(avail_w, avail_h))
        x = (self.width() - side) / 2
        y = margin
        rect = QRectF(x, y, side, side)

        thickness = max(8, side // 14)
        rect_inner = rect.adjusted(thickness / 2, thickness / 2,
                                    -thickness / 2, -thickness / 2)

        v = self._displayed
        # Top-half semi-circle: start at 9 o'clock (180°), sweep clockwise to
        # 3 o'clock (0°). Qt: positive = counter-clockwise, ×16 units.
        START_ANGLE = 180 * 16
        FULL_SWEEP = -180 * 16

        # Track ring + label colours from current palette.
        try:
            from qfluentwidgets.common.style_sheet import isDarkTheme
            from .theme_palette import palette as _gp
            _pal = _gp(not isDarkTheme())
        except Exception:
            _pal = {"border": "#21262D", "text": "#E6EDF3", "muted": "#8B949E"}
        bg_pen = QPen(QColor(_pal["border"]))
        bg_pen.setWidth(thickness)
        bg_pen.setCapStyle(Qt.RoundCap)
        p.setPen(bg_pen)
        p.drawArc(rect_inner, START_ANGLE, FULL_SWEEP)

        capped = max(0.0, min(v, 200.0))
        if capped <= 100:
            color = QColor("#388BFD")  # blue while under target
            arc_pen = QPen(color)
            arc_pen.setWidth(thickness)
            arc_pen.setCapStyle(Qt.RoundCap)
            p.setPen(arc_pen)
            p.drawArc(rect_inner, START_ANGLE, int(FULL_SWEEP * (capped / 100.0)))
        else:
            # Full green semi-circle (100% achieved) ...
            green = QPen(QColor("#3FB950"))
            green.setWidth(thickness)
            green.setCapStyle(Qt.RoundCap)
            p.setPen(green)
            p.drawArc(rect_inner, START_ANGLE, FULL_SWEEP)
            # ... plus a blue overflow arc on top showing how far past target.
            overflow = (capped - 100) / 100.0
            blue = QPen(QColor("#388BFD"))
            blue.setWidth(thickness)
            blue.setCapStyle(Qt.RoundCap)
            p.setPen(blue)
            p.drawArc(rect_inner, START_ANGLE, int(FULL_SWEEP * overflow))

        # Center text positioned inside the arc, just above the diameter
        # line (which sits at rect.center().y()).
        arc_diam_y = rect.center().y()
        big_font = QFont(self.font())
        big_font.setPixelSize(max(22, int(side / 7)))
        big_font.setWeight(QFont.DemiBold)
        p.setPen(QColor(_pal["text"]))
        p.setFont(big_font)
        big_h = side * 0.22
        big_rect = QRectF(rect.x(), arc_diam_y - big_h - 2,
                          rect.width(), big_h)
        p.drawText(big_rect, Qt.AlignHCenter | Qt.AlignBottom,
                   f"{int(round(v))}%")

        small_font = QFont(self.font())
        small_font.setPixelSize(max(9, int(side / 18)))
        p.setFont(small_font)
        p.setPen(QColor(_pal["muted"]))
        sub_rect = QRectF(rect.x(), arc_diam_y - big_h - 2 + big_h - 4,
                          rect.width(), side * 0.13)
        p.drawText(sub_rect, Qt.AlignHCenter | Qt.AlignTop, "production")
