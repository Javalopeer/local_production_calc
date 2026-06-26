"""Floating toast notification — top-level window, bubble shape.

Lives as an independent top-level frameless window so it's never destroyed
by parent reparenting and it can use windowOpacity for fade animation.
Anchored to the host window's top-right corner.

Usage:
    Toast.get(parent).show_message("Saved!", level="success")

Levels: "success" | "info" | "warning" | "error".
"""
from __future__ import annotations

from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QTimer, QPoint, QEvent,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QGraphicsDropShadowEffect, QWidget, QSizePolicy,
)


_LEVEL_COLORS = {
    "success": "#3FB950",
    "info":    "#388BFD",
    "warning": "#D29922",
    "error":   "#F85149",
}

_LEVEL_TITLES = {
    "success": "Success",
    "info":    "Info",
    "warning": "Heads up",
    "error":   "Error",
}


class Toast(QFrame):
    """Top-level floating cloud-bubble notification."""

    _INSTANCES = {}

    @classmethod
    def get(cls, host) -> "Toast":
        win = host.window() if host is not None else None
        key = id(win)
        inst = cls._INSTANCES.get(key)
        if inst is None:
            inst = cls(win)
            cls._INSTANCES[key] = inst
        return inst

    def __init__(self, host_window: QWidget | None):
        super().__init__(None)  # top-level
        self._host = host_window
        self.setObjectName("toast")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
            | Qt.NoDropShadowWindowHint
        )
        self.setMinimumWidth(320)
        self.setMaximumWidth(460)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        # Bubble inner frame so the drop-shadow can paint around it on a
        # transparent top-level window.
        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(18, 18, 18, 18)  # space for the shadow
        outer_lay.setSpacing(0)

        self._bubble = QFrame(self)
        self._bubble.setObjectName("toastBubble")
        outer_lay.addWidget(self._bubble)

        shadow = QGraphicsDropShadowEffect(self._bubble)
        shadow.setBlurRadius(34)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 6)
        self._bubble.setGraphicsEffect(shadow)

        b_lay = QHBoxLayout(self._bubble)
        b_lay.setContentsMargins(22, 16, 14, 16)
        b_lay.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(3)
        self._title = QLabel("")
        self._title.setObjectName("toastTitle")
        self._title.setWordWrap(True)
        self._body = QLabel("")
        self._body.setObjectName("toastBody")
        self._body.setWordWrap(True)
        text_col.addWidget(self._title)
        text_col.addWidget(self._body)
        b_lay.addLayout(text_col, 1)

        self._close = QPushButton("×", self._bubble)
        self._close.setObjectName("toastClose")
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.setFixedSize(24, 24)
        self._close.clicked.connect(self.dismiss)
        b_lay.addWidget(self._close, 0, Qt.AlignTop)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(220)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(260)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)

        self._apply_style("#388BFD")
        if host_window is not None:
            host_window.installEventFilter(self)
        self.hide()

    # ── Public API ───────────────────────────────────────────────────────

    def show_message(
        self, message: str, *, title: str = "", level: str = "info",
        duration_ms: int = 5500,
    ):
        color = _LEVEL_COLORS.get(level, _LEVEL_COLORS["info"])
        self._apply_style(color)
        self._title.setText(title or _LEVEL_TITLES.get(level, ""))
        self._title.setVisible(bool(self._title.text()))
        self._body.setText(message)
        self.adjustSize()
        self._show_animated()
        self._timer.start(duration_ms)

    def dismiss(self):
        self._timer.stop()
        self._fade_out()

    # ── Style ────────────────────────────────────────────────────────────

    def _apply_style(self, accent: str):
        self.setStyleSheet(
            # Outer container is fully transparent so the shadow can bleed.
            "#toast { background: transparent; }"
            # The bubble itself — generous radius, soft border, dark fill.
            "#toastBubble {"
            "  background-color: rgba(22, 27, 34, 250);"
            "  border: 1px solid rgba(255,255,255,0.10);"
            "  border-radius: 22px;"
            "}"
            f"#toastTitle {{ color: {accent}; font-size: 12px; font-weight: 700;"
            "  background: transparent; }"
            "#toastBody {"
            "  color: #E6EDF3; font-size: 11.5px; font-weight: 500;"
            "  background: transparent;"
            "}"
            "#toastClose {"
            "  background: transparent; color: #8B949E;"
            "  border: none; font-size: 18px; font-weight: 700;"
            "  padding: 0; margin: 0; border-radius: 12px;"
            "}"
            "#toastClose:hover { color: #FFFFFF;"
            "  background: rgba(255,255,255,0.10); }"
        )

    # ── Positioning ──────────────────────────────────────────────────────

    def _target_pos(self) -> QPoint:
        if self._host is None:
            return QPoint(60, 60)
        host_geom = self._host.geometry()
        # Anchor inside the host window's top-right, accounting for the
        # transparent shadow margin we added on the outer layout.
        margin = 12
        x = host_geom.x() + host_geom.width() - self.width() - margin
        y = host_geom.y() + margin
        # If the host has a title bar / frame, push a bit lower.
        try:
            frame = self._host.frameGeometry().height() - host_geom.height()
            if frame > 0:
                y += frame
        except Exception:
            pass
        return QPoint(x, y)

    def _show_animated(self):
        end = self._target_pos()
        start = QPoint(end.x() + 50, end.y())
        self.move(start)
        self.setWindowOpacity(0.0)
        # Cleanly drop any leftover finished handlers from a previous cycle
        # so the slide-out's "hide on finish" doesn't fire mid-show.
        for anim in (self._slide, self._fade):
            try:
                anim.finished.disconnect()
            except Exception:
                pass
        self.show()
        self.raise_()

        self._slide.stop()
        self._slide.setStartValue(start)
        self._slide.setEndValue(end)
        self._slide.start()

        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def _fade_out(self):
        # Skip if we're not actually visible (e.g. already dismissed).
        if not self.isVisible():
            return
        self._slide.stop()
        self._fade.stop()
        try:
            self._fade.finished.disconnect()
        except Exception:
            pass
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.hide)
        self._fade.start()
        # Slight slide-out for flair.
        cur = self.pos()
        self._slide.setStartValue(cur)
        self._slide.setEndValue(QPoint(cur.x() + 30, cur.y()))
        self._slide.start()

    def eventFilter(self, obj, ev):
        if obj is self._host and ev.type() in (
            QEvent.Resize, QEvent.Move, QEvent.WindowStateChange
        ):
            if self.isVisible():
                self.move(self._target_pos())
        return super().eventFilter(obj, ev)
