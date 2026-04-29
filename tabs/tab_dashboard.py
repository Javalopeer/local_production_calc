"""Dashboard Tab — charts (pure Qt), KPI cards, filters, and insights panel.

All charts are drawn with QPainter — no matplotlib / Pillow required.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDateEdit, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QSizePolicy, QScrollArea, QGroupBox,
    QGridLayout, QBoxLayout, QStackedWidget, QButtonGroup,
)
from PySide6.QtCore import QDate, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QBrush

from db.database import get_connection
from .utils import (
    get_resource_path,
    load_units_eq_data,
    get_units_per_case,
    calculate_equivalent_units,
)

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
_BG    = QColor("#1e1e1e")
_AX    = QColor("#2b2b2b")
_GRID  = QColor("#3c3c3c")
_TEXT  = QColor("#e6e6e6")
_MUTED = QColor("#888888")
_BLUE  = QColor("#4aa3ff")
_ORANGE = QColor("#f5a623")
_GREEN  = QColor("#4CAF50")
_RED    = QColor("#e05c5c")

SERIES_COLORS = [
    QColor("#4aa3ff"), QColor("#f5a623"), QColor("#4CAF50"), QColor("#e07b54"),
    QColor("#9b59b6"), QColor("#1abc9c"), QColor("#e74c3c"), QColor("#3498db"),
    QColor("#e5e50a"), QColor("#e056a0"), QColor("#00bcd4"), QColor("#ff7043"),
    QColor("#8bc34a"), QColor("#ab47bc"), QColor("#26a69a"),
]


# ---------------------------------------------------------------------------
# Shared chart helpers
# ---------------------------------------------------------------------------

def _paint_bg(painter: QPainter, widget: QWidget):
    painter.fillRect(widget.rect(), _BG)


def _paint_no_data(widget: QWidget):
    p = QPainter(widget)
    p.fillRect(widget.rect(), _BG)
    p.setPen(QPen(_MUTED))
    f = QFont()
    f.setPointSize(9)
    p.setFont(f)
    p.drawText(widget.rect(), Qt.AlignmentFlag.AlignCenter, "No data")
    p.end()


def _draw_axes(painter: QPainter, rc: QRect):
    painter.fillRect(rc, _AX)
    painter.setPen(QPen(_GRID, 1))
    painter.drawRect(rc)


def _draw_h_grid(painter: QPainter, rc: QRect, max_val: float, lines: int = 4):
    f = QFont()
    f.setPointSize(7)
    painter.setFont(f)
    for i in range(lines + 1):
        frac = i / lines
        y = rc.bottom() - int(frac * rc.height())
        pen = QPen(_GRID)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(rc.x(), y, rc.right(), y)
        label = f"{max_val * frac:.0f}"
        painter.setPen(QPen(_MUTED))
        painter.drawText(
            QRect(0, y - 8, rc.x() - 3, 16),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            label,
        )


def _draw_legend(painter: QPainter, series: list, rc: QRect):
    f = QFont()
    f.setPointSize(7)
    painter.setFont(f)
    fm = QFontMetrics(f)
    x = rc.x()
    y = rc.top() + 4
    for name, color, _ in series:
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(x, y, 10, 10)
        painter.setPen(QPen(_TEXT))
        painter.drawText(x + 13, y + 9, name)
        x += 13 + fm.horizontalAdvance(name) + 12
        if x > rc.right() - 50:
            x = rc.x()
            y += 16


def _label_stride(n: int, max_labels: int = 10) -> int:
    """Return stride for x-axis labels so long ranges stay readable."""
    if n <= 0:
        return 1
    return max(1, math.ceil(n / max_labels))


# ---------------------------------------------------------------------------
# Base chart widget
# ---------------------------------------------------------------------------

class _ChartBase(QWidget):
    PAD_T, PAD_R, PAD_B, PAD_L = 16, 16, 44, 54

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

    def _plot_rect(self) -> QRect:
        return QRect(
            self.PAD_L,
            self.PAD_T,
            self.width() - self.PAD_L - self.PAD_R,
            self.height() - self.PAD_T - self.PAD_B,
        )


# ---------------------------------------------------------------------------
# Stacked bar chart  (daily UE : REG vs OT)
# ---------------------------------------------------------------------------

class StackedBarChart(_ChartBase):
    """series = list of (name: str, color: QColor, values: list[float])"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._x_labels: list[str] = []
        self._series: list[tuple[str, QColor, list[float]]] = []

    def set_data(self, x_labels, series):
        self._x_labels = list(x_labels)
        self._series = list(series)
        self.update()

    def paintEvent(self, _event):
        if not self._x_labels:
            _paint_no_data(self)
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rc = self._plot_rect()
        _paint_bg(p, self)
        _draw_axes(p, rc)

        n = len(self._x_labels)
        slot = rc.width() / max(n, 1)
        bar_w = max(1, int(slot * 0.72))
        if bar_w > 40:
            bar_w = 40
        totals = [
            sum(s[2][i] for s in self._series if i < len(s[2]))
            for i in range(n)
        ]
        max_val = max(totals) if totals else 1.0
        if max_val == 0:
            max_val = 1.0

        _draw_h_grid(p, rc, max_val)

        f = QFont()
        f.setPointSize(7)
        p.setFont(f)
        stride = _label_stride(n, max_labels=10)
        val_stride = _label_stride(n, max_labels=12)

        for i, lbl in enumerate(self._x_labels):
            x = rc.x() + int(i * slot + (slot - bar_w) / 2)
            bottom = rc.bottom()
            acc = 0.0
            for _name, color, vals in self._series:
                v = vals[i] if i < len(vals) else 0.0
                h = int(v / max_val * rc.height())
                if h > 0:
                    p.setBrush(QBrush(color))
                    p.setPen(Qt.PenStyle.NoPen)
                    y_top = bottom - int((acc + v) / max_val * rc.height())
                    p.drawRect(x, y_top, bar_w, h)
                acc += v
            # Show total UE above selected bars for readability.
            if acc > 0 and bar_w >= 8 and (i == n - 1 or i % val_stride == 0):
                y_top_total = bottom - int(acc / max_val * rc.height())
                y_text = max(rc.y() + 2, y_top_total - 12)
                p.setPen(QPen(_TEXT))
                p.drawText(
                    QRect(x - 10, y_text, max(22, bar_w + 20), 12),
                    Qt.AlignmentFlag.AlignCenter,
                    f"{acc:.1f}",
                )
            # x-axis label
            if i == 0 or i == n - 1 or i % stride == 0:
                p.setPen(QPen(_MUTED))
                p.drawText(
                    QRect(x - 10, rc.bottom() + 4, bar_w + 20, 20),
                    Qt.AlignmentFlag.AlignCenter,
                    lbl,
                )

        _draw_legend(p, self._series, rc)
        p.end()


# ---------------------------------------------------------------------------
# Line chart  (efficiency % trend)
# ---------------------------------------------------------------------------

class LineChart(_ChartBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._x_labels: list[str] = []
        self._values: list[float] = []
        self._ref_line: float | None = None

    def set_data(self, x_labels, values, ref_line=None):
        self._x_labels = list(x_labels)
        self._values = list(values)
        self._ref_line = ref_line
        self.update()

    def paintEvent(self, _event):
        if not self._values:
            _paint_no_data(self)
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rc = self._plot_rect()
        _paint_bg(p, self)
        _draw_axes(p, rc)

        raw_values = [max(0.0, float(v or 0.0)) for v in self._values]
        plot_values = list(raw_values)
        capped = False
        if len(raw_values) >= 8:
            sorted_vals = sorted(raw_values)
            idx = int((len(sorted_vals) - 1) * 0.90)
            p90 = sorted_vals[idx]
            cap = max(300.0, p90 * 3.0, float(self._ref_line or 0.0))
            if any(v > cap for v in raw_values):
                plot_values = [min(v, cap) for v in raw_values]
                capped = True

        all_v = list(plot_values)
        if self._ref_line is not None:
            all_v.append(self._ref_line)
        max_val = max(all_v) if all_v else 1.0
        if max_val == 0:
            max_val = 1.0

        _draw_h_grid(p, rc, max_val)

        n = len(self._values)
        xs = [
            rc.x() + int((i / max(n - 1, 1)) * rc.width())
            for i in range(n)
        ]
        ys = [
            rc.bottom() - int(v / max_val * rc.height())
            for v in plot_values
        ]

        # Reference line
        if self._ref_line is not None:
            ry = rc.bottom() - int(self._ref_line / max_val * rc.height())
            pen = QPen(_GREEN)
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DotLine)
            p.setPen(pen)
            p.drawLine(rc.x(), ry, rc.right(), ry)

        # Trend line
        pen = QPen(_ORANGE)
        pen.setWidth(2)
        p.setPen(pen)
        for i in range(len(xs) - 1):
            p.drawLine(xs[i], ys[i], xs[i + 1], ys[i + 1])

        # Dots
        p.setBrush(QBrush(_ORANGE))
        p.setPen(Qt.PenStyle.NoPen)
        for x, y in zip(xs, ys):
            p.drawEllipse(x - 4, y - 4, 8, 8)

        # X labels
        f = QFont()
        f.setPointSize(7)
        p.setFont(f)
        p.setPen(QPen(_MUTED))
        stride = _label_stride(len(xs), max_labels=10)
        for i, (x, lbl) in enumerate(zip(xs, self._x_labels)):
            if i == 0 or i == len(xs) - 1 or i % stride == 0:
                p.drawText(
                    QRect(x - 24, rc.bottom() + 4, 48, 20),
                    Qt.AlignmentFlag.AlignCenter,
                    lbl,
                )
        if capped:
            p.setPen(QPen(_MUTED))
            p.drawText(
                QRect(rc.x(), rc.y() - 12, rc.width(), 12),
                Qt.AlignmentFlag.AlignRight,
                "Scaled for outliers",
            )
        p.end()


# ---------------------------------------------------------------------------
# Pie / Donut chart
# ---------------------------------------------------------------------------

class PieChart(_ChartBase):
    PAD_T, PAD_R, PAD_B, PAD_L = 8, 8, 8, 8
    LEGEND_H = 84

    def __init__(self, hole: float = 0.0, parent=None):
        super().__init__(parent)
        self._hole = hole   # 0 = full pie,  0.5 = donut
        self._labels: list[str] = []
        self._values: list[float] = []

    def set_data(self, labels, values):
        self._labels = list(labels)
        self._values = list(values)
        self.update()

    def paintEvent(self, _event):
        if not self._values or sum(self._values) == 0:
            _paint_no_data(self)
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_bg(p, self)

        total = sum(self._values)
        w, h = self.width(), self.height()
        margin = 12
        side = min(w - margin * 2, h - self.LEGEND_H - margin * 2)
        side = max(side, 20)
        ox = margin + (w - margin * 2 - side) // 2
        oy = margin
        rect = QRectF(ox, oy, side, side)

        start_angle = 90 * 16          # Qt units = 1/16 degree
        for i, (lbl, val) in enumerate(zip(self._labels, self._values)):
            span = int(val / total * 360 * 16)
            color = SERIES_COLORS[i % len(SERIES_COLORS)]
            p.setBrush(QBrush(color))
            p.setPen(QPen(_BG, 1.5))
            p.drawPie(rect, start_angle, -span)    # negative = clockwise
            start_angle -= span

        # Donut hole
        if self._hole > 0:
            inner = side * self._hole
            ix = ox + (side - inner) / 2
            iy = oy + (side - inner) / 2
            p.setBrush(QBrush(_BG))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(ix, iy, inner, inner))

        # Legend
        f = QFont()
        f.setPointSize(7)
        p.setFont(f)
        lx = margin
        ly = h - self.LEGEND_H + 4
        col_w = max(60, (w - margin * 2) // 2)
        for i, (lbl, val) in enumerate(zip(self._labels, self._values)):
            color = SERIES_COLORS[i % len(SERIES_COLORS)]
            cx = lx + (i % 2) * col_w
            cy = ly + (i // 2) * 17
            if cy + 14 > h:
                break
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(cx, cy + 3, 10, 10)
            p.setPen(QPen(_TEXT))
            pct = val / total * 100
            short_lbl = lbl[:14] if len(lbl) > 14 else lbl
            p.drawText(
                QRect(cx + 14, cy, col_w - 16, 17),
                Qt.AlignmentFlag.AlignVCenter,
                f"{short_lbl} {pct:.0f}% ({val:.1f})",
            )
        p.end()


# ---------------------------------------------------------------------------
# KPI card
# ---------------------------------------------------------------------------

class _Card(QFrame):
    def __init__(self, title: str, value: str = "—", accent: str = "#4aa3ff", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(110)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        self._title_lbl = QLabel(title)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setStyleSheet("color: #8B949E; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;")

        self._val_lbl = QLabel(value)
        self._val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont()
        f.setPointSize(16)
        f.setBold(True)
        self._val_lbl.setFont(f)
        self._val_lbl.setStyleSheet(f"color: {accent};")

        lay.addWidget(self._title_lbl)
        lay.addWidget(self._val_lbl)

    def set_value(self, v: str):
        self._val_lbl.setText(v)


# ---------------------------------------------------------------------------
# Advice / insight item
# ---------------------------------------------------------------------------

_ADVICE_ICON  = {"warning": "⚠", "info": "ℹ", "good": "✓", "tip": "💡"}
_ADVICE_COLOR = {"warning": "#f5a623", "info": "#4aa3ff", "good": "#4CAF50", "tip": "#e07b54"}


class _AdviceItem(QFrame):
    def __init__(self, kind: str, text: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        color = _ADVICE_COLOR.get(kind, "#4aa3ff")
        self.setStyleSheet(
            f"QFrame {{ border-left: 3px solid {color}; border-radius: 4px; }}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(12)

        icon_lbl = QLabel(_ADVICE_ICON.get(kind, "•"))
        icon_lbl.setStyleSheet(f"color: {color}; font-size: 14px; border: none;")
        icon_lbl.setFixedWidth(18)

        msg_lbl = QLabel(text)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet("font-size: 11px; border: none;")

        lay.addWidget(icon_lbl)
        lay.addWidget(msg_lbl)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _chart_group(title: str, widget: QWidget) -> QGroupBox:
    box = QGroupBox(title)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(6, 10, 6, 8)
    lay.addWidget(widget)
    return box


def _make_table(headers: list[str]) -> QTableWidget:
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.verticalHeader().setVisible(False)
    t.setMinimumHeight(160)
    return t


def _fill_row(table: QTableWidget, row: int, values: list[str]):
    for col, val in enumerate(values):
        item = QTableWidgetItem(str(val))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(row, col, item)


# ---------------------------------------------------------------------------
# Dashboard Tab
# ---------------------------------------------------------------------------

class DashboardTab(QWidget):

    def __init__(self):
        super().__init__()
        self._standards: dict = {}
        self._load_metadata()
        self._init_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _load_metadata(self):
        try:
            path = get_resource_path(os.path.join("data", "standards.json"))
            with open(path, "r", encoding="utf-8") as fh:
                self._standards = json.load(fh)
        except Exception:
            self._standards = {}

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Top bar with view toggle (Personal | Equipo) ──────────────
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(20, 14, 20, 6)
        top_bar.setSpacing(8)
        self.title_label = QLabel("Dashboard")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #E6EDF3; letter-spacing: 0.5px;")
        top_bar.addWidget(self.title_label)
        top_bar.addStretch()

        self.btn_view_team = QPushButton("Equipo")
        self.btn_view_personal = QPushButton("Personal")
        for b in (self.btn_view_team, self.btn_view_personal):
            b.setCheckable(True)
            b.setMinimumWidth(82)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        # Default: Equipo
        self.btn_view_team.setChecked(True)
        view_group = QButtonGroup(self)
        view_group.setExclusive(True)
        view_group.addButton(self.btn_view_team, 0)
        view_group.addButton(self.btn_view_personal, 1)
        view_group.idClicked.connect(self._on_view_changed)
        self._view_group = view_group
        top_bar.addWidget(self.btn_view_team)
        top_bar.addWidget(self.btn_view_personal)
        outer.addLayout(top_bar)
        self._apply_view_button_styles()

        # ── Stacked container: index 0 = team, 1 = personal ────────────
        self._view_stack = QStackedWidget()
        outer.addWidget(self._view_stack)

        team_page = self._build_team_page()
        self._view_stack.addWidget(team_page)

        # The original personal dashboard goes inside its own page
        personal_page = QWidget()
        personal_outer = QVBoxLayout(personal_page)
        personal_outer.setContentsMargins(0, 0, 0, 0)
        self._view_stack.addWidget(personal_page)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        personal_outer.addWidget(scroll)

        container = QWidget()
        container.setMinimumWidth(440)
        scroll.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(20, 18, 20, 22)
        root.setSpacing(18)

        # ── Filters ────────────────────────────────────────────────────
        fb = QGroupBox("Filters")
        flay = QGridLayout(fb)
        flay.setContentsMargins(16, 14, 16, 14)
        flay.setHorizontalSpacing(8)
        flay.setVerticalSpacing(8)

        self.date_from = QDateEdit(QDate.currentDate().addDays(-30))
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_from.setMinimumWidth(118)

        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        self.date_to.setMinimumWidth(118)

        self.cmb_region = QComboBox()
        self.cmb_region.setMinimumWidth(140)
        self.cmb_region.addItem("All Regions", None)
        for r in sorted(self._standards.keys()):
            self.cmb_region.addItem(r, r)

        self.cmb_type = QComboBox()
        self.cmb_type.setMinimumWidth(130)
        self.cmb_type.addItem("All Types", None)
        all_types: set = set()
        for reg_data in self._standards.values():
            if isinstance(reg_data, dict):
                for sub in reg_data.values():
                    if isinstance(sub, dict):
                        all_types.update(sub.keys())
        for t in sorted(all_types):
            self.cmb_type.addItem(t, t)

        self.cmb_source = QComboBox()
        self.cmb_source.setMinimumWidth(110)
        for label, val in [("REG + OT", "both"), ("REG only", "reg"), ("OT only", "ot")]:
            self.cmb_source.addItem(label, val)

        btn_refresh = QPushButton("Refresh")
        btn_refresh.setMinimumWidth(90)
        btn_refresh.clicked.connect(self.refresh)

        lbl_from = QLabel("From:")
        lbl_to = QLabel("To:")
        lbl_region = QLabel("Region:")
        lbl_type = QLabel("Type:")
        lbl_source = QLabel("Source:")
        for lbl in (lbl_from, lbl_to, lbl_region, lbl_type, lbl_source):
            lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        # Row 0: From | To
        flay.addWidget(lbl_from, 0, 0)
        flay.addWidget(self.date_from, 0, 1)
        flay.addWidget(lbl_to, 0, 2)
        flay.addWidget(self.date_to, 0, 3)

        # Row 1: Region full width
        flay.addWidget(lbl_region, 1, 0)
        flay.addWidget(self.cmb_region, 1, 1, 1, 5)

        # Row 2: Type | Source | Refresh
        flay.addWidget(lbl_type, 2, 0)
        flay.addWidget(self.cmb_type, 2, 1)
        flay.addWidget(lbl_source, 2, 2)
        flay.addWidget(self.cmb_source, 2, 3)
        flay.addWidget(btn_refresh, 2, 4, 1, 2, Qt.AlignmentFlag.AlignLeft)

        flay.setColumnStretch(1, 1)
        flay.setColumnStretch(3, 1)
        flay.setColumnStretch(5, 2)

        # Row 3: Date preset shortcuts
        presets_lbl = QLabel("Quick:")
        presets_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        flay.addWidget(presets_lbl, 3, 0)

        presets_bar = QWidget()
        presets_layout = QHBoxLayout(presets_bar)
        presets_layout.setContentsMargins(0, 0, 0, 0)
        presets_layout.setSpacing(6)

        btn_today = QPushButton("Today")
        btn_today.setMaximumWidth(70)
        btn_week  = QPushButton("This Week")
        btn_week.setMaximumWidth(80)
        btn_month = QPushButton("This Month")
        btn_month.setMaximumWidth(90)

        def _set_today():
            today = QDate.currentDate()
            self.date_from.setDate(today)
            self.date_to.setDate(today)
            self.refresh()

        def _set_week():
            today = QDate.currentDate()
            self.date_from.setDate(today.addDays(-today.dayOfWeek() + 1))  # Monday
            self.date_to.setDate(today)
            self.refresh()

        def _set_month():
            today = QDate.currentDate()
            self.date_from.setDate(QDate(today.year(), today.month(), 1))
            self.date_to.setDate(today)
            self.refresh()

        btn_today.clicked.connect(_set_today)
        btn_week.clicked.connect(_set_week)
        btn_month.clicked.connect(_set_month)

        presets_layout.addWidget(btn_today)
        presets_layout.addWidget(btn_week)
        presets_layout.addWidget(btn_month)
        presets_layout.addStretch()

        flay.addWidget(presets_bar, 3, 1, 1, 5)

        root.addWidget(fb)

        # ── KPI cards (3 + 2 grid so they wrap before squishing) ───────
        card_grid = QGridLayout()
        card_grid.setSpacing(14)
        self.kpi_reg  = _Card("REG Cases", accent="#388BFD")
        self.kpi_ot   = _Card("OT Cases",  accent="#F0883E")
        self.kpi_ue   = _Card("Total UE",  accent="#3FB950")
        self.kpi_eff  = _Card("Avg Eff %", accent="#A371F7")
        self.kpi_down = _Card("Downtime",  accent="#F85149")
        for i, card in enumerate(
            (self.kpi_reg, self.kpi_ot, self.kpi_ue, self.kpi_eff, self.kpi_down)
        ):
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            card_grid.addWidget(card, i // 3, i % 3)
        for c in range(3):
            card_grid.setColumnStretch(c, 1)
        root.addLayout(card_grid)

        # ── Charts row 1 ──────────────────────────────────────────────
        self._ch1 = QHBoxLayout()
        self._ch1.setSpacing(16)
        self._bar  = StackedBarChart()
        self._bar.setMinimumSize(220, 220)
        self._line = LineChart()
        self._line.setMinimumSize(220, 220)
        self._bar_grp  = _chart_group("Daily UE — REG vs OT", self._bar)
        self._line_grp = _chart_group("Efficiency % Trend",   self._line)
        self._bar_grp.setMinimumHeight(260)
        self._line_grp.setMinimumHeight(260)
        self._ch1.addWidget(self._bar_grp)
        self._ch1.addWidget(self._line_grp)
        root.addLayout(self._ch1)

        # ── Charts row 2 ──────────────────────────────────────────────
        self._ch2 = QHBoxLayout()
        self._ch2.setSpacing(16)
        self._pie   = PieChart(hole=0.0)
        self._pie.setMinimumSize(220, 240)
        self._donut = PieChart(hole=0.5)
        self._donut.setMinimumSize(220, 240)
        self._pie_grp   = _chart_group("UE by Region",    self._pie)
        self._donut_grp = _chart_group("UE by Case Type", self._donut)
        self._pie_grp.setMinimumHeight(280)
        self._donut_grp.setMinimumHeight(280)
        self._ch2.addWidget(self._pie_grp)
        self._ch2.addWidget(self._donut_grp)
        root.addLayout(self._ch2)

        # ── Insights panel ────────────────────────────────────────────
        self._advice_box = QGroupBox("Insights & Suggestions")
        self._advice_layout = QVBoxLayout(self._advice_box)
        self._advice_layout.setContentsMargins(14, 12, 14, 12)
        self._advice_layout.setSpacing(8)
        root.addWidget(self._advice_box)

        # ── Tables ────────────────────────────────────────────────────
        self._tbl_row = QHBoxLayout()
        self._tbl_row.setSpacing(16)

        daily_grp = QGroupBox("Daily Summary")
        dl = QVBoxLayout(daily_grp)
        dl.setContentsMargins(8, 10, 8, 10)
        self.tbl_daily = _make_table(
            ["Date", "REG", "OT", "UE (REG)", "UE (OT)", "Avg Eff %", "Downtime (m)"]
        )
        self.tbl_daily.setMinimumHeight(180)
        dl.addWidget(self.tbl_daily)

        region_grp = QGroupBox("Region Breakdown")
        rl = QVBoxLayout(region_grp)
        rl.setContentsMargins(8, 10, 8, 10)
        self.tbl_region = _make_table(
            ["Region", "REG Cases", "OT Cases", "Total UE", "Avg Eff %"]
        )
        self.tbl_region.setMinimumHeight(180)
        rl.addWidget(self.tbl_region)

        self._tbl_row.addWidget(daily_grp, 3)
        self._tbl_row.addWidget(region_grp, 2)
        root.addLayout(self._tbl_row)

    # ------------------------------------------------------------------
    # Responsive layout
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "_tbl_row"):   # guard: fires before _init_ui completes
            return
        two_col = event.size().width() >= 980
        direction = (
            QBoxLayout.Direction.LeftToRight
            if two_col
            else QBoxLayout.Direction.TopToBottom
        )
        for layout in (self._ch1, self._ch2, self._tbl_row):
            layout.setDirection(direction)

    # ------------------------------------------------------------------
    # Team view (reads shared Excel: Productions/<Designer>/_Summary.xlsx)
    # ------------------------------------------------------------------

    _TEAM_POLL_MS = 30_000  # 30 seconds — match the user's stated cadence
    _FRESHNESS_TICK_MS = 1_000

    def _build_team_page(self) -> QWidget:
        """Compact team-wide view rendered from the shared SharePoint folder."""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 18, 20, 22)
        v.setSpacing(14)

        header_row = QHBoxLayout()
        self.team_date_picker = QDateEdit(QDate.currentDate())
        self.team_date_picker.setCalendarPopup(True)
        self.team_date_picker.setDisplayFormat("yyyy-MM-dd")
        self.team_date_picker.setMinimumWidth(120)
        self.team_date_picker.dateChanged.connect(lambda _d: self._refresh_team_view())
        header_row.addWidget(QLabel("Fecha:"))
        header_row.addWidget(self.team_date_picker)
        header_row.addStretch()
        self.team_freshness_label = QLabel("Cargando…")
        self.team_freshness_label.setStyleSheet(
            "color: #8B949E; font-size: 11px;"
        )
        header_row.addWidget(self.team_freshness_label)
        v.addLayout(header_row)

        # 4 KPI cards
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self.kpi_team_size   = _Card("Enrolados",        accent="#388BFD")
        self.kpi_team_active = _Card("Activos hoy",      accent="#3FB950")
        self.kpi_team_avg    = _Card("Avg Production %", accent="#A371F7")
        self.kpi_team_ue     = _Card("Total UE",         accent="#F0883E")
        for c in (self.kpi_team_size, self.kpi_team_active, self.kpi_team_avg, self.kpi_team_ue):
            c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            kpi_row.addWidget(c)
        v.addLayout(kpi_row)

        # People table
        self.tbl_team = _make_table(["Designer", "Production %", "UE", "Cases"])
        self.tbl_team.setMinimumHeight(360)
        self.tbl_team.setSortingEnabled(False)  # we sort manually by % desc
        v.addWidget(self.tbl_team, 1)

        # Polling timer
        self._team_poll_timer = QTimer(self)
        self._team_poll_timer.setInterval(self._TEAM_POLL_MS)
        self._team_poll_timer.timeout.connect(self._refresh_team_view)
        self._team_poll_timer.start()

        # Freshness ticker (updates "hace X seg" every second)
        self._team_last_load_ts: float | None = None
        self._team_last_load_ok: bool = False
        self._team_freshness_timer = QTimer(self)
        self._team_freshness_timer.setInterval(self._FRESHNESS_TICK_MS)
        self._team_freshness_timer.timeout.connect(self._update_freshness_label)
        self._team_freshness_timer.start()

        # Stop timers when widget is destroyed so they don't fire on a dead C++ obj.
        self.destroyed.connect(self._stop_team_timers)

        # Kick the first load shortly after the UI is up
        QTimer.singleShot(250, self._refresh_team_view)

        return page

    def _stop_team_timers(self, *_):
        for attr in ("_team_poll_timer", "_team_freshness_timer"):
            t = getattr(self, attr, None)
            if t is not None:
                try:
                    t.stop()
                except Exception:
                    pass

    def _on_view_changed(self, view_id: int):
        # 0 = Equipo, 1 = Personal
        self._view_stack.setCurrentIndex(view_id)
        self._apply_view_button_styles()
        if view_id == 0:
            # Refresh team data immediately when re-entering the team view
            self._refresh_team_view()

    def _apply_view_button_styles(self):
        sel = (
            "QPushButton { background-color: #1F6FEB; color: white; "
            "border: none; border-radius: 4px; padding: 5px 14px; "
            "font-weight: 600; font-size: 12px; }"
        )
        unsel = (
            "QPushButton { background-color: transparent; color: #8B949E; "
            "border: 1px solid #30363D; border-radius: 4px; padding: 5px 14px; "
            "font-size: 12px; } "
            "QPushButton:hover { color: #E6EDF3; border-color: #5A6068; }"
        )
        self.btn_view_team.setStyleSheet(sel if self.btn_view_team.isChecked() else unsel)
        self.btn_view_personal.setStyleSheet(sel if self.btn_view_personal.isChecked() else unsel)

    def _refresh_team_view(self):
        """Read the shared folder, repopulate KPIs + table. Silent on failure."""
        from datetime import datetime
        target_date = self.team_date_picker.date().toString("yyyy-MM-dd")
        try:
            rows = self._load_team_summaries(target_date)
        except Exception as exc:
            print(f"[Dashboard team] load failed: {exc}")
            self._team_last_load_ok = False
            self._update_freshness_label()
            return

        # KPIs
        enrolled = rows["enrolled_count"]
        active = sum(1 for r in rows["people"] if r["pct"] > 0 or r["cases"] > 0)
        active_rows = [r for r in rows["people"] if r["pct"] > 0 or r["cases"] > 0]
        avg_pct = (sum(r["pct"] for r in active_rows) / len(active_rows)) if active_rows else 0.0
        total_ue = sum(r["ue"] for r in rows["people"])

        self.kpi_team_size.set_value(str(enrolled))
        self.kpi_team_active.set_value(str(active))
        self.kpi_team_avg.set_value(f"{avg_pct:.1f}%")
        self.kpi_team_ue.set_value(f"{total_ue:.1f}")

        # Table — only people with any activity today, sorted by % desc.
        visible = sorted(active_rows, key=lambda r: r["pct"], reverse=True)
        self.tbl_team.setRowCount(len(visible))
        for i, r in enumerate(visible):
            it_name = QTableWidgetItem(r["designer"])
            it_pct  = QTableWidgetItem(f"{r['pct']:.1f}%")
            it_ue   = QTableWidgetItem(f"{r['ue']:.2f}")
            it_cs   = QTableWidgetItem(str(r["cases"]))
            it_pct.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it_ue.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it_cs.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # Soft colour cue on the % cell
            if r["pct"] >= 100:
                it_pct.setForeground(QBrush(QColor("#3FB950")))
            elif r["pct"] >= 85:
                it_pct.setForeground(QBrush(QColor("#D29922")))
            else:
                it_pct.setForeground(QBrush(QColor("#F85149")))
            for col, item in enumerate((it_name, it_pct, it_ue, it_cs)):
                self.tbl_team.setItem(i, col, item)

        import time as _time
        self._team_last_load_ts = _time.time()
        self._team_last_load_ok = True
        self._update_freshness_label()

    def _update_freshness_label(self):
        import time as _time
        if not self._team_last_load_ok or self._team_last_load_ts is None:
            self.team_freshness_label.setText("Sin datos del equipo")
            self.team_freshness_label.setStyleSheet("color: #F85149; font-size: 11px;")
            return
        age = int(_time.time() - self._team_last_load_ts)
        if age < 60:
            text = f"Última actualización: hace {age} seg"
        elif age < 3600:
            text = f"Última actualización: hace {age // 60} min"
        else:
            text = f"Última actualización: hace {age // 3600} h"
        # Amber if older than 5 minutes (sync probably stalled)
        color = "#F0883E" if age > 300 else "#8B949E"
        self.team_freshness_label.setText(text)
        self.team_freshness_label.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _load_team_summaries(self, target_date: str) -> dict:
        """Walk Productions/<Designer>/_Summary.xlsx and pull the row for `target_date`.

        Returns {"enrolled_count": int, "people": [ {designer, pct, ue, cases} ] }.
        Returns empty if the shared folder isn't configured.
        """
        try:
            import openpyxl
        except Exception:
            return {"enrolled_count": 0, "people": []}

        from sync.app_config import load_config
        cfg = load_config()
        export_folder = (cfg.get("export_folder") or "").strip()
        if not export_folder or not os.path.isdir(export_folder):
            return {"enrolled_count": 0, "people": []}

        productions_dir = os.path.join(export_folder, "Productions")
        if not os.path.isdir(productions_dir):
            return {"enrolled_count": 0, "people": []}

        people = []
        designer_dirs = []
        try:
            for entry in os.listdir(productions_dir):
                full = os.path.join(productions_dir, entry)
                if not os.path.isdir(full):
                    continue
                summary = os.path.join(full, "_Summary.xlsx")
                if os.path.isfile(summary):
                    designer_dirs.append((entry, summary))
        except Exception as exc:
            print(f"[Dashboard team] scan dir failed: {exc}")

        for designer_name, summary_path in designer_dirs:
            display = designer_name.replace("_", " ")
            pct, ue, cases = 0.0, 0.0, 0
            try:
                wb = openpyxl.load_workbook(summary_path, read_only=True, data_only=True)
                ws = wb.active
                for row in ws.iter_rows(min_row=2, values_only=True):
                    if not row or row[0] != target_date:
                        continue
                    pct = self._parse_pct(row[4]) if len(row) > 4 else 0.0
                    ue = float(row[7] or 0) if len(row) > 7 else 0.0
                    reg_cases = int(row[5] or 0) if len(row) > 5 else 0
                    ot_cases = int(row[6] or 0) if len(row) > 6 else 0
                    cases = reg_cases + ot_cases
                    break
                wb.close()
            except Exception as exc:
                # File might be locked by Excel on the other machine; skip silently.
                continue
            people.append({
                "designer": display,
                "pct": pct,
                "ue": ue,
                "cases": cases,
            })

        return {"enrolled_count": len(designer_dirs), "people": people}

    @staticmethod
    def _parse_pct(value) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip().rstrip("%")
        try:
            return float(s)
        except ValueError:
            return 0.0

    # ------------------------------------------------------------------
    # Refresh (Personal view)
    # ------------------------------------------------------------------

    def refresh(self):
        d_from  = self.date_from.date().toString("yyyy-MM-dd")
        d_to    = self.date_to.date().toString("yyyy-MM-dd")
        region  = self.cmb_region.currentData()
        tipo    = self.cmb_type.currentData()
        source  = self.cmb_source.currentData()

        reg_rows = self._query_cases("cases",    d_from, d_to, region, tipo) \
                   if source in ("both", "reg") else []
        ot_rows  = self._query_cases("ot_cases", d_from, d_to, region, tipo) \
                   if source in ("both", "ot") else []
        down_map = self._query_downtime(d_from, d_to)

        self._update_kpis(reg_rows, ot_rows, down_map)
        self._update_charts(reg_rows, ot_rows)
        self._update_daily_table(reg_rows, ot_rows, down_map)
        self._update_region_table(reg_rows, ot_rows)
        self._update_advice(reg_rows, ot_rows, down_map, d_from, d_to)

    # ------------------------------------------------------------------
    # DB queries
    # ------------------------------------------------------------------

    def _query_cases(
        self, table: str, d_from: str, d_to: str,
        region, tipo
    ) -> list[dict]:
        params = [d_from, d_to]
        where  = "fecha BETWEEN ? AND ?"
        if region:
            where += " AND region = ?"
            params.append(region)
        if tipo:
            where += " AND tipo_caso = ?"
            params.append(tipo)
        sql = (
            f"SELECT fecha, region, tipo_caso, "
            f"COUNT(*) AS cnt_cases, "
            f"SUM(CASE WHEN efficiency BETWEEN 0 AND 1000 THEN efficiency ELSE 0 END) AS sum_eff, "
            f"SUM(CASE WHEN efficiency BETWEEN 0 AND 1000 THEN 1 ELSE 0 END) AS cnt_eff, "
            f"SUM(case_value) AS sum_cv "
            f"FROM {table} "
            f"WHERE {where} "
            f"GROUP BY fecha, region, tipo_caso "
            f"ORDER BY fecha"
        )
        units_eq = load_units_eq_data()
        result: list[dict] = []
        try:
            conn = get_connection()
            cur  = conn.cursor()
            cur.execute(sql, params)
            for fecha, reg, tipo_c, cnt, sum_eff, cnt_eff, sum_cv in cur.fetchall():
                ue = calculate_equivalent_units(
                    units_eq,
                    reg or "",
                    tipo_c or "",
                    (sum_cv or 0.0),
                    count=(cnt or 0),
                )
                result.append({
                    "fecha":    fecha,
                    "region":   reg,
                    "tipo":     tipo_c,
                    "count":    cnt or 0,
                    "sum_eff":  sum_eff or 0.0,
                    "eff_count": cnt_eff or 0,
                    "ue":       ue,
                })
            conn.close()
        except Exception as exc:
            print(f"[Dashboard] {table}: {exc}")
        return result

    def _query_downtime(self, d_from: str, d_to: str) -> dict[str, float]:
        result: dict[str, float] = {}
        try:
            conn = get_connection()
            cur  = conn.cursor()
            cur.execute(
                "SELECT fecha, SUM(duracion) FROM downtimes "
                "WHERE fecha BETWEEN ? AND ? GROUP BY fecha",
                [d_from, d_to],
            )
            for fecha, total in cur.fetchall():
                result[fecha] = float(total or 0)
            conn.close()
        except Exception as exc:
            print(f"[Dashboard] downtime: {exc}")
        return result

    # ------------------------------------------------------------------
    # KPI update
    # ------------------------------------------------------------------

    def _update_kpis(self, reg_rows, ot_rows, down_map):
        total_reg  = sum(r["count"]   for r in reg_rows)
        total_ot   = sum(r["count"]   for r in ot_rows)
        total_ue   = sum(r["ue"]      for r in reg_rows) + sum(r["ue"] for r in ot_rows)
        all_rows   = reg_rows + ot_rows
        sum_eff    = sum(r["sum_eff"] for r in all_rows)
        eff_count  = sum(r.get("eff_count", 0) for r in all_rows)
        avg_eff    = sum_eff / eff_count if eff_count else 0.0
        total_down = sum(down_map.values())

        self.kpi_reg.set_value(str(total_reg))
        self.kpi_ot.set_value(str(total_ot))
        self.kpi_ue.set_value(f"{total_ue:.2f}")
        self.kpi_eff.set_value(f"{avg_eff:.1f}%")
        h, m = divmod(int(total_down), 60)
        self.kpi_down.set_value(f"{int(total_down)}m" if h == 0 else f"{h}h {m}m")

    # ------------------------------------------------------------------
    # Charts update
    # ------------------------------------------------------------------

    def _update_charts(self, reg_rows, ot_rows):
        daily: dict[str, dict] = defaultdict(
            lambda: {"ue_reg": 0.0, "ue_ot": 0.0, "sum_eff": 0.0, "cnt_eff": 0}
        )
        for r in reg_rows:
            d = daily[r["fecha"]]
            d["ue_reg"]  += r["ue"]
            d["sum_eff"] += r["sum_eff"]
            d["cnt_eff"] += r.get("eff_count", 0)
        for r in ot_rows:
            d = daily[r["fecha"]]
            d["ue_ot"] += r["ue"]
            d["sum_eff"] += r["sum_eff"]
            d["cnt_eff"] += r.get("eff_count", 0)

        dates  = sorted(daily.keys())
        years = {d[:4] for d in dates}
        if len(years) > 1:
            short = [f"{d[2:4]}-{d[5:]}" for d in dates]   # YY-MM-DD
        else:
            short = [d[5:] for d in dates]                 # MM-DD
        ue_reg = [daily[d]["ue_reg"] for d in dates]
        ue_ot  = [daily[d]["ue_ot"]  for d in dates]
        avg_eff = [
            daily[d]["sum_eff"] / daily[d]["cnt_eff"]
            if daily[d]["cnt_eff"] else 0.0
            for d in dates
        ]

        self._bar.set_data(short, [("REG", _BLUE, ue_reg), ("OT", _ORANGE, ue_ot)])
        self._line.set_data(short, avg_eff, ref_line=100.0)

        by_region: dict[str, float] = defaultdict(float)
        by_type:   dict[str, float] = defaultdict(float)
        for r in reg_rows + ot_rows:
            by_region[r["region"] or "Unknown"] += r["ue"]
            by_type[r["tipo"]     or "Unknown"] += r["ue"]

        sr = sorted(by_region.items(), key=lambda x: -x[1])
        self._pie.set_data([x[0] for x in sr], [x[1] for x in sr])

        st = sorted(by_type.items(), key=lambda x: -x[1])
        self._donut.set_data([x[0] for x in st], [x[1] for x in st])

        total_ue = sum(v for _, v in sr)
        if hasattr(self, "_pie_grp"):
            self._pie_grp.setTitle(f"UE by Region (% of {total_ue:.2f} total UE)")
        if hasattr(self, "_donut_grp"):
            self._donut_grp.setTitle(f"UE by Case Type (% of {total_ue:.2f} total UE)")

    # ------------------------------------------------------------------
    # Advice update
    # ------------------------------------------------------------------

    def _query_period_summary(self, d_from: str, d_to: str):
        """Return (total_cases, avg_eff, total_ue) for REG cases in a date range."""
        units_eq = load_units_eq_data()
        total_cases = 0
        sum_eff = 0.0
        total_ue = 0.0
        try:
            conn = get_connection()
            cur  = conn.cursor()
            cur.execute(
                "SELECT region, tipo_caso, COUNT(*), SUM(efficiency), SUM(case_value) "
                "FROM cases WHERE fecha BETWEEN ? AND ? "
                "GROUP BY region, tipo_caso",
                [d_from, d_to],
            )
            for reg, tipo_c, cnt, s_eff, sum_cv in cur.fetchall():
                total_cases += cnt or 0
                sum_eff     += s_eff or 0.0
                total_ue    += calculate_equivalent_units(
                    units_eq,
                    reg or "",
                    tipo_c or "",
                    (sum_cv or 0.0),
                    count=(cnt or 0),
                )
            conn.close()
        except Exception:
            pass
        avg_eff = sum_eff / total_cases if total_cases else 0.0
        return total_cases, avg_eff, total_ue

    def _query_top_doctor(self, d_from: str, d_to: str):
        """Return (doctor_name, count) for the doctor with most REG cases, or None."""
        try:
            conn = get_connection()
            cur  = conn.cursor()
            cur.execute(
                "SELECT doctor, COUNT(*) AS cnt FROM cases "
                "WHERE fecha BETWEEN ? AND ? AND doctor != '' "
                "GROUP BY doctor ORDER BY cnt DESC LIMIT 1",
                [d_from, d_to],
            )
            row = cur.fetchone()
            conn.close()
            return (row[0], row[1]) if row else None
        except Exception:
            return None

    def _query_non_counting(self, d_from: str, d_to: str) -> int:
        """Return count of REG cases with count_production = 0 in range."""
        try:
            conn = get_connection()
            cur  = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM cases "
                "WHERE fecha BETWEEN ? AND ? AND count_production = 0",
                [d_from, d_to],
            )
            row = cur.fetchone()
            conn.close()
            return row[0] if row else 0
        except Exception:
            return 0

    def _update_advice(self, reg_rows, ot_rows, down_map, d_from: str, d_to: str):
        # Clear previous items
        while self._advice_layout.count():
            item = self._advice_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        advice: list[tuple[str, str]] = []

        total_reg = sum(r["count"] for r in reg_rows)
        total_ot  = sum(r["count"] for r in ot_rows)
        total_all = total_reg + total_ot

        # Per-row efficiency checks — consolidated to avoid visual noise
        high_eff_rows = []   # (avg, loc)
        low_eff_rows  = []   # (avg, loc)
        for r in reg_rows:
            eff_n = r.get("eff_count", 0)
            if eff_n > 0:
                avg = r["sum_eff"] / eff_n
                loc = f"{r['fecha']} | {r['region']} | {r['tipo']}"
                if avg > 300:
                    high_eff_rows.append((avg, loc))
                elif avg < 20 and eff_n >= 3:
                    low_eff_rows.append((avg, loc))

        if len(high_eff_rows) == 1:
            avg, loc = high_eff_rows[0]
            advice.append(("warning",
                f"Avg efficiency {avg:.0f}% on {loc}. Verify std_time in Standards."))
        elif len(high_eff_rows) > 1:
            worst_avg, worst_loc = max(high_eff_rows, key=lambda x: x[0])
            advice.append(("warning",
                f"{len(high_eff_rows)} combos with unusually high efficiency (>300%). "
                f"Worst: {worst_avg:.0f}% on {worst_loc}. Verify std_time in Standards."))

        if len(low_eff_rows) == 1:
            avg, loc = low_eff_rows[0]
            advice.append(("warning",
                f"Low avg efficiency {avg:.0f}% on {loc}. Review these cases."))
        elif len(low_eff_rows) > 1:
            advice.append(("warning",
                f"{len(low_eff_rows)} combos with low efficiency (<20%). Review these cases."))

        # OT ratio
        if total_all > 0:
            ot_ratio = total_ot / total_all
            if ot_ratio > 0.5:
                advice.append(("warning",
                    f"OT cases are {ot_ratio*100:.0f}% of work ({total_ot}/{total_all}). "
                    "Review workload balance."))
            elif total_ot > 0 and ot_ratio <= 0.15:
                advice.append(("good",
                    f"Healthy OT ratio — only {ot_ratio*100:.0f}% ({total_ot}) overtime cases."))
            elif total_ot == 0:
                advice.append(("info", "No OT cases in this period."))

        # Downtime with no cases logged
        all_dates = {r["fecha"] for r in reg_rows + ot_rows}
        for fecha, mins in down_map.items():
            if fecha not in all_dates and mins > 0:
                advice.append(("info",
                    f"{fecha}: {mins:.0f} min downtime logged but no cases registered."))

        # Top region
        by_region: dict[str, float] = defaultdict(float)
        for r in reg_rows + ot_rows:
            by_region[r["region"] or "Unknown"] += r["ue"]
        if by_region:
            top_r, top_ue = max(by_region.items(), key=lambda x: x[1])
            advice.append(("good", f"Top region: {top_r} — {top_ue:.2f} UE."))

        # Top case type
        by_type: dict[str, float] = defaultdict(float)
        for r in reg_rows + ot_rows:
            by_type[r["tipo"] or "Unknown"] += r["ue"]
        if by_type:
            top_t, top_t_ue = max(by_type.items(), key=lambda x: x[1])
            advice.append(("tip",
                f"Most productive type: {top_t} ({top_t_ue:.2f} UE). "
                "Consider prioritising on high-load days."))

        # ── NEW: Trend vs previous equal-length period ─────────────────
        try:
            from datetime import date as _date, timedelta as _td
            dt_from = _date.fromisoformat(d_from)
            dt_to   = _date.fromisoformat(d_to)
            span    = (dt_to - dt_from).days + 1
            prev_to   = dt_from - _td(days=1)
            prev_from = prev_to  - _td(days=span - 1)
            _, cur_avg,  cur_ue  = self._query_period_summary(d_from, d_to)
            _, prev_avg, prev_ue = self._query_period_summary(
                prev_from.isoformat(), prev_to.isoformat()
            )
            if prev_avg > 0:
                delta_eff = cur_avg - prev_avg
                delta_ue  = cur_ue  - prev_ue
                icon = "good" if delta_eff >= 0 else "warning"
                sign_e = "+" if delta_eff >= 0 else ""
                sign_u = "+" if delta_ue  >= 0 else ""
                advice.append((icon,
                    f"vs previous {span}-day period: Avg Eff {sign_e}{delta_eff:.1f}% "
                    f"({prev_avg:.1f}% → {cur_avg:.1f}%), "
                    f"UE {sign_u}{delta_ue:.2f} ({prev_ue:.2f} → {cur_ue:.2f})."))
        except Exception:
            pass

        # ── NEW: Inactive days (no cases, no downtime) ─────────────────
        try:
            from datetime import date as _date, timedelta as _td
            dt_from = _date.fromisoformat(d_from)
            dt_to   = _date.fromisoformat(d_to)
            active  = {r["fecha"] for r in reg_rows + ot_rows} | set(down_map.keys())
            inactive = []
            cur_d = dt_from
            while cur_d <= dt_to:
                if cur_d.isoformat() not in active:
                    inactive.append(cur_d.isoformat())
                cur_d += _td(days=1)
            if inactive:
                if len(inactive) <= 3:
                    advice.append(("info",
                        f"No activity on: {', '.join(inactive)}."))
                else:
                    advice.append(("info",
                        f"{len(inactive)} days with no cases or downtime "
                        f"({inactive[0]} … {inactive[-1]})."))
        except Exception:
            pass

        # ── NEW: Top doctor ────────────────────────────────────────────
        top_doc = self._query_top_doctor(d_from, d_to)
        if top_doc:
            doc_name, doc_cnt = top_doc
            advice.append(("tip",
                f"Most active doctor: {doc_name} ({doc_cnt} REG cases)."))

        # ── NEW: Non-counting cases ────────────────────────────────────
        nc_count = self._query_non_counting(d_from, d_to)
        if nc_count > 0 and total_reg > 0:
            nc_pct = nc_count / total_reg * 100
            icon = "warning" if nc_pct >= 20 else "info"
            advice.append((icon,
                f"{nc_count} REG case{'s' if nc_count > 1 else ''} "
                f"({nc_pct:.1f}%) marked as not counting for production."))

        # ── NEW: Consecutive days below 100% efficiency ────────────────
        try:
            daily_eff: dict[str, float] = defaultdict(
                lambda: {"s": 0.0, "n": 0}
            )
            for r in reg_rows:
                daily_eff[r["fecha"]]["s"] += r["sum_eff"]
                daily_eff[r["fecha"]]["n"] += r["count"]
            eff_by_day = {
                d: v["s"] / v["n"]
                for d, v in daily_eff.items()
                if v["n"] > 0
            }
            sorted_days = sorted(eff_by_day.keys())
            streak, max_streak, streak_start = 0, 0, None
            ms_start = None
            for d in sorted_days:
                if eff_by_day[d] < 100:
                    if streak == 0:
                        streak_start = d
                    streak += 1
                    if streak > max_streak:
                        max_streak = streak
                        ms_start   = streak_start
                else:
                    streak = 0
            if max_streak >= 3:
                advice.append(("warning",
                    f"{max_streak} consecutive days below 100% efficiency "
                    f"(starting {ms_start}). Check workload or standards."))
        except Exception:
            pass

        if total_all == 0:
            advice.append(("info", "No cases found for the selected filters and date range."))

        for kind, text in advice:
            self._advice_layout.addWidget(_AdviceItem(kind, text))

        if not advice:
            self._advice_layout.addWidget(
                _AdviceItem("good", "Everything looks normal for the selected period.")
            )

    # ------------------------------------------------------------------
    # Daily table update
    # ------------------------------------------------------------------

    def _update_daily_table(self, reg_rows, ot_rows, down_map):
        daily: dict[str, dict] = defaultdict(
            lambda: {"reg": 0, "ot": 0, "ue_reg": 0.0, "ue_ot": 0.0,
                     "sum_eff": 0.0, "eff_count": 0, "down": 0.0}
        )
        for r in reg_rows:
            d = daily[r["fecha"]]
            d["reg"]     += r["count"]
            d["ue_reg"]  += r["ue"]
            d["sum_eff"] += r["sum_eff"]
            d["eff_count"] += r.get("eff_count", 0)
        for r in ot_rows:
            d = daily[r["fecha"]]
            d["ot"]    += r["count"]
            d["ue_ot"] += r["ue"]
            d["sum_eff"] += r["sum_eff"]
            d["eff_count"] += r.get("eff_count", 0)
        for fecha, mins in down_map.items():
            daily[fecha]["down"] = mins

        dates = sorted(daily.keys())
        self.tbl_daily.setRowCount(len(dates))
        for i, fecha in enumerate(dates):
            d   = daily[fecha]
            avg = d["sum_eff"] / d["eff_count"] if d["eff_count"] else 0.0
            _fill_row(self.tbl_daily, i, [
                fecha,
                str(d["reg"]),
                str(d["ot"]),
                f"{d['ue_reg']:.2f}",
                f"{d['ue_ot']:.2f}",
                f"{avg:.1f}%",
                f"{d['down']:.0f}",
            ])

    # ------------------------------------------------------------------
    # Region table update
    # ------------------------------------------------------------------

    def _update_region_table(self, reg_rows, ot_rows):
        by_region: dict[str, dict] = defaultdict(
            lambda: {"reg": 0, "ot": 0, "ue": 0.0, "sum_eff": 0.0, "eff_count": 0}
        )
        for r in reg_rows:
            d = by_region[r["region"] or "Unknown"]
            d["reg"]     += r["count"]
            d["ue"]      += r["ue"]
            d["sum_eff"] += r["sum_eff"]
            d["eff_count"] += r.get("eff_count", 0)
        for r in ot_rows:
            d = by_region[r["region"] or "Unknown"]
            d["ot"] += r["count"]
            d["ue"] += r["ue"]
            d["sum_eff"] += r["sum_eff"]
            d["eff_count"] += r.get("eff_count", 0)

        regions = sorted(by_region.keys())
        self.tbl_region.setRowCount(len(regions))
        for i, region in enumerate(regions):
            d   = by_region[region]
            avg = d["sum_eff"] / d["eff_count"] if d["eff_count"] else 0.0
            _fill_row(self.tbl_region, i, [
                region,
                str(d["reg"]),
                str(d["ot"]),
                f"{d['ue']:.2f}",
                f"{avg:.1f}%",
            ])

    # ------------------------------------------------------------------
    # Theme hook (no-op — charts use dark palette regardless)
    # ------------------------------------------------------------------

    def update_theme_labels(self, is_light: bool):
        if is_light:
            self.title_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #111; letter-spacing: 0.5px;")
        else:
            self.title_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #E6EDF3; letter-spacing: 0.5px;")
