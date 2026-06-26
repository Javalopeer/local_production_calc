"""Small UI helpers shared by Register / OT views.

These were inlined methods of RegisterTab. Pulling them out keeps the
tab file focused on flow, not paint details.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy,
    QToolButton,
)


def paint_efficiency_cell(item, eff_value):
    """Color the Eff% TEXT green/amber/red — leaves cell bg alone."""
    try:
        ev = float(eff_value)
    except (TypeError, ValueError):
        return
    if ev >= 100:
        color = "#3FB950"
    elif ev >= 95:
        color = "#D29922"
    else:
        color = "#F85149"
    item.setForeground(QBrush(QColor(color)))


def paint_time_cell(item, tiempo_real, std_time):
    """Colour the Time TEXT (cell bg stays neutral):
        green  → within standard
        amber  → over but within 2-min grace
        red    → exceeded standard by more than 2 minutes
    """
    try:
        real = float(tiempo_real)
        std = float(std_time)
    except (TypeError, ValueError):
        return
    if std <= 0:
        return
    if real <= std:
        color = "#3FB950"
    elif real <= std + 2:
        color = "#D29922"
    else:
        color = "#F85149"
    item.setForeground(QBrush(QColor(color)))


def case_id_widget(case_id: str, status_color: str) -> QWidget:
    """Case ID cell: coloured left strip + bold ID centred to the right."""
    wrap = QWidget()
    wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    wrap.setStyleSheet("background: transparent;")
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    strip = QFrame()
    strip.setFixedWidth(3)
    strip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    strip.setStyleSheet(f"background: {status_color}; border: none;")

    lbl = QLabel(case_id)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    def _apply(is_light: bool, _w=lbl):
        try:
            from .theme_palette import palette
            p = palette(is_light)
        except Exception:
            p = {"text": "#E6EDF3"}
        _w.setStyleSheet(
            f"color: {p['text']}; font-size: 12px;"
            f" background: transparent; padding-left: 6px;"
        )
    wrap.apply_palette = _apply
    try:
        from qfluentwidgets.common.style_sheet import isDarkTheme
        _apply(not isDarkTheme())
    except Exception:
        _apply(False)
    lay.addWidget(strip, 0, Qt.AlignmentFlag.AlignLeft)
    lay.addWidget(lbl, 1)
    return wrap


def build_empty_state(title: str, subtitle: str,
                       icon_svg: str = "tabler_inbox.svg",
                       icon_color: str = "#444C56") -> QWidget:
    """Inbox-style placeholder used by Today's Cases / Today's OT Cases."""
    from .tabler_icons import TablerIcon

    wrap = QWidget()
    v = QVBoxLayout(wrap)
    v.setContentsMargins(0, 16, 0, 16)
    v.setSpacing(6)
    v.addStretch(1)

    icon = QToolButton()
    icon.setEnabled(False)
    icon.setIcon(TablerIcon(icon_svg).icon(color=QColor(icon_color)))
    icon.setIconSize(QSize(56, 56))
    icon.setStyleSheet("border: none; background: transparent;")
    v.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)

    t = QLabel(title)
    t.setAlignment(Qt.AlignmentFlag.AlignCenter)
    s = QLabel(subtitle)
    s.setAlignment(Qt.AlignmentFlag.AlignCenter)
    s.setWordWrap(True)

    def _apply(is_light: bool):
        try:
            from .theme_palette import palette
            p = palette(is_light)
        except Exception:
            p = {"text_2": "#C9D1D9", "muted_2": "#6E7681"}
        t.setStyleSheet(
            f"color: {p['text_2']}; font-size: 14px; font-weight: 700;"
            f" background: transparent;"
        )
        s.setStyleSheet(
            f"color: {p['muted_2']}; font-size: 11px; background: transparent;"
        )
    wrap.apply_palette = _apply
    try:
        from qfluentwidgets.common.style_sheet import isDarkTheme
        _apply(not isDarkTheme())
    except Exception:
        _apply(False)

    v.addWidget(t)
    v.addWidget(s)
    v.addStretch(1)
    return wrap
