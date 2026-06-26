"""Multi-state sync status pill for the status bar.

States:
- "live"     — green pill, dot indicator, "All changes synced".
- "syncing"  — blue pill, spinning circle, "Syncing changes…".
- "pending"  — gray pill, dotted circle, "Pending sync…".
- "failed"   — red pill, alert-triangle, "Sync failed".

Public API mirrors the previous QLabel just enough for drop-in use:
    pill.setText(...)        # parses simple prefixes for back-compat
    pill.setStyleSheet(...)  # no-op (styling is internal)
    pill.setToolTip(...)     # forwarded to the whole pill
    pill.setProperty(k, v)   # stored; read via .property()
    pill.setCursor(...)      # forwarded
    pill.mousePressEvent     # standard Qt
"""
from __future__ import annotations

from PySide6.QtCore import (
    Qt, QSize, QPropertyAnimation, QEasingCurve, Property, QRectF, QTimer,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QToolButton, QWidget,
)


# Colors per state.
_STATES = {
    "live": {
        "fg":     "#3FB950",
        "border": "rgba(63,185,80,0.45)",
        "bg":     "rgba(63,185,80,0.08)",
        "msg":    "All changes synced",
    },
    "syncing": {
        "fg":     "#58A6FF",
        "border": "rgba(88,166,255,0.45)",
        "bg":     "rgba(88,166,255,0.08)",
        "msg":    "Syncing changes…",
    },
    "pending": {
        "fg":     "#8B949E",
        "border": "rgba(139,148,158,0.45)",
        "bg":     "rgba(139,148,158,0.10)",
        "msg":    "Pending sync…",
    },
    "failed": {
        "fg":     "#F85149",
        "border": "rgba(248,81,73,0.55)",
        "bg":     "rgba(248,81,73,0.10)",
        "msg":    "Sync failed",
    },
}


class _StateIcon(QWidget):
    """Compact 14×14 icon that swaps shape per sync state.

    - live    → solid filled dot
    - syncing → spinning ring with a brighter arc
    - pending → dashed/dotted ring
    - failed  → alert triangle with !
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._state = "pending"
        self._color = QColor("#8B949E")
        self._angle = 0.0
        self._spin = QPropertyAnimation(self, b"angle", self)
        self._spin.setStartValue(0.0)
        self._spin.setEndValue(360.0)
        self._spin.setDuration(1100)
        self._spin.setLoopCount(-1)
        self._spin.setEasingCurve(QEasingCurve.Linear)

    def get_angle(self):
        return self._angle

    def set_angle(self, v):
        self._angle = float(v)
        self.update()

    angle = Property(float, get_angle, set_angle)

    def set_state(self, state: str, color: QColor):
        self._state = state
        self._color = QColor(color)
        if state == "syncing":
            if self._spin.state() != QPropertyAnimation.Running:
                self._spin.start()
        else:
            self._spin.stop()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self._color
        if self._state == "live":
            p.setBrush(c)
            p.setPen(Qt.NoPen)
            p.drawEllipse(2, 2, 10, 10)
        elif self._state == "syncing":
            # Background ring (faint).
            faint = QColor(c); faint.setAlpha(80)
            pen = QPen(faint, 2)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(QRectF(2, 2, 10, 10), 0, 360 * 16)
            # Foreground arc rotating ~120°.
            pen2 = QPen(c, 2)
            pen2.setCapStyle(Qt.RoundCap)
            p.setPen(pen2)
            start_deg = int(90 - self._angle) * 16
            p.drawArc(QRectF(2, 2, 10, 10), start_deg, -120 * 16)
        elif self._state == "pending":
            pen = QPen(c, 2, Qt.DotLine)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(QRectF(2, 2, 10, 10), 0, 360 * 16)
        else:  # failed
            pen = QPen(c, 1.6)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            # Triangle.
            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            poly = QPolygonF([
                QPointF(7, 2), QPointF(13, 12), QPointF(1, 12),
            ])
            p.drawPolygon(poly)
            # Exclamation.
            p.drawLine(7, 6, 7, 9)
            p.setBrush(c)
            p.setPen(Qt.NoPen)
            p.drawEllipse(6, 10, 2, 2)


class SyncStatusPill(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("syncStatusPill")
        self._state = "pending"
        self._timestamp = ""
        self._props: dict = {}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 6, 4)
        lay.setSpacing(8)

        self._icon = _StateIcon(self)
        lay.addWidget(self._icon, 0, Qt.AlignVCenter)

        self._ts_lbl = QLabel("")
        self._ts_lbl.setStyleSheet("color: #8B949E; font-size: 10px;"
                                    " background: transparent;")
        lay.addWidget(self._ts_lbl, 0, Qt.AlignVCenter)

        self._msg_lbl = QLabel(_STATES["pending"]["msg"])
        self._msg_lbl.setStyleSheet("font-size: 10px; font-weight: 700;"
                                     " background: transparent;")
        lay.addWidget(self._msg_lbl, 0, Qt.AlignVCenter)

        # Chevron — clickable, opens a popover with sync detail rows
        # (last sync time, files updated, etc).
        self._chev = QToolButton()
        self._chev.setCursor(Qt.PointingHandCursor)
        self._chev.setFixedSize(20, 20)
        self._chev.setIconSize(QSize(12, 12))
        self._chev.setStyleSheet(
            "QToolButton { background: transparent; border: none;"
            " border-radius: 10px; }"
            "QToolButton:hover { background: rgba(255,255,255,0.08); }"
        )
        try:
            from .tabler_icons import TablerIcon as _TI
            self._chev.setIcon(_TI("tabler_chevron_up.svg").icon(color=QColor("#8B949E")))
        except Exception:
            pass
        self._chev.clicked.connect(self._open_detail_popover)
        lay.addWidget(self._chev, 0, Qt.AlignVCenter)

        # Holds the latest structured sync details — populated by set_details
        # from MainWindow's sync done handler.
        self._details: dict = {}
        self._detail_popover = None

        self.set_state("pending")

    # ── State ──
    def set_state(self, state: str, *, timestamp: str | None = None,
                  message: str | None = None):
        if state not in _STATES:
            state = "pending"
        self._state = state
        cfg = _STATES[state]
        msg = message if message else cfg["msg"]
        if timestamp is not None:
            self._timestamp = timestamp
        self._ts_lbl.setText(self._timestamp or "")
        self._ts_lbl.setVisible(bool(self._timestamp))
        self._msg_lbl.setText(msg)
        self._msg_lbl.setStyleSheet(
            f"color: {cfg['fg']}; font-size: 10px; font-weight: 700;"
            " background: transparent;"
        )
        self._icon.set_state(state, QColor(cfg["fg"]))
        self.setStyleSheet(
            f"#syncStatusPill {{ background: {cfg['bg']};"
            f" border: 1px solid {cfg['border']}; border-radius: 8px; }}"
            "QLabel { background: transparent; }"
        )

    # ── Drop-in shims so the rest of the app doesn't break ──
    def setText(self, text: str):
        """Parse legacy prefix-based status strings → call set_state()."""
        s = (text or "").strip()
        if not s:
            self.set_state("pending", message="")
            return
        low = s.lower()
        if "syncing" in low or "↻" in s and "sync" in low and "pending" not in low:
            self.set_state("syncing")
        elif "pending" in low:
            self.set_state("pending")
        elif "error" in low or "failed" in low or "⚠" in s:
            self.set_state("failed")
        elif "⬆" in s:
            ts = s.replace("⬆", "").strip()
            self.set_state("live", timestamp=ts)
        else:
            # Fallback — just use as message under current state.
            self._msg_lbl.setText(s)

    def setStyleSheet(self, _ss: str = ""):
        # The pill paints itself; ignore external stylesheet calls so the
        # legacy `_sync_label_style(...)` writes don't override our look.
        # Still call super for QFrame internals (root selector).
        # We just absorb it — set_state handles styling.
        return

    def setProperty(self, name: str, value):
        self._props[name] = value

    def property(self, name: str):
        return self._props.get(name)

    def setToolTip(self, text: str):
        super().setToolTip(text)
        self._msg_lbl.setToolTip(text)

    def setCursor(self, cursor):
        super().setCursor(cursor)

    # ── Detail popover ──
    def set_details(self, details: dict):
        """Populate the detail popover. Expected keys (all optional):
            last_sync, report_file, summary_file, dashboard_file,
            destination, error.
        """
        self._details = dict(details or {})

    def _open_detail_popover(self):
        try:
            from .tabler_icons import TablerIcon as _TI
        except Exception:
            _TI = None

        # Toggle behaviour — second click closes the open popover.
        existing = self._detail_popover
        if existing is not None and existing.isVisible():
            existing.close()
            existing.deleteLater()
            self._detail_popover = None
            self._set_chev_icon(direction="up")
            return
        self._detail_popover = None

        state = self._state
        cfg = _STATES.get(state, _STATES["pending"])
        fg = cfg["fg"]

        # Don't use Qt.Popup — its "click anywhere outside closes" eats the
        # chevron's second click, so the toggle never re-fires. Use a plain
        # top-level frame the chevron alone controls.
        host = self.window()
        pop = QFrame(host)
        pop.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        pop.setAttribute(Qt.WA_ShowWithoutActivating, True)
        pop.setObjectName("syncDetailPop")
        pop.setStyleSheet(
            "#syncDetailPop { background: #0B0F14; border: 1px solid #21262D;"
            " border-radius: 12px; }"
            "QLabel { background: transparent; border: none; }"
        )
        root = QHBoxLayout(pop)
        root.setContentsMargins(0, 0, 0, 0)

        from PySide6.QtWidgets import QVBoxLayout
        body_w = QWidget()
        body = QVBoxLayout(body_w)
        body.setContentsMargins(14, 12, 14, 12)
        body.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        hdr_ic = QToolButton()
        hdr_ic.setEnabled(False)
        hdr_ic.setFixedSize(20, 20)
        hdr_ic.setStyleSheet("background: transparent; border: none;")
        if _TI is not None:
            try:
                icon_map = {
                    "live":    "tabler_circle_check.svg",
                    "syncing": "tabler_refresh.svg",
                    "pending": "tabler_clock.svg",
                    "failed":  "tabler_alert_triangle.svg",
                }
                hdr_ic.setIcon(_TI(icon_map.get(state, "tabler_circle_check.svg"))
                                 .icon(color=QColor(fg)))
                hdr_ic.setIconSize(QSize(18, 18))
            except Exception:
                pass
        title = QLabel({
            "live":    "Synced successfully",
            "syncing": "Sync in progress",
            "pending": "Sync queued",
            "failed":  "Sync failed",
        }.get(state, "Sync status"))
        title.setStyleSheet(
            "color: #E6EDF3; font-size: 13px; font-weight: 700;"
        )
        close_btn = QToolButton()
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedSize(26, 26)
        close_btn.setIconSize(QSize(16, 16))
        close_btn.setStyleSheet(
            "QToolButton { background: transparent; border: none;"
            "  border-radius: 13px; }"
            "QToolButton:hover { background: rgba(255,255,255,0.06); }"
        )
        if _TI is not None:
            try:
                close_btn.setIcon(_TI("tabler_x.svg").icon(color=QColor("#8B949E")))
            except Exception:
                pass
        def _close_and_reset():
            pop.close()
            self._detail_popover = None
            self._set_chev_icon(direction="up")
        close_btn.clicked.connect(_close_and_reset)
        hdr.addWidget(hdr_ic, 0, Qt.AlignVCenter)
        hdr.addWidget(title, 1)
        hdr.addWidget(close_btn, 0, Qt.AlignVCenter)
        body.addLayout(hdr)

        # Build row helper
        def _row(icon_svg, label, value, value_color="#3FB950"):
            r = QHBoxLayout()
            r.setSpacing(8)
            ic = QToolButton()
            ic.setEnabled(False)
            ic.setFixedSize(18, 18)
            ic.setIconSize(QSize(14, 14))
            ic.setStyleSheet("background: transparent; border: none;")
            if _TI is not None and icon_svg:
                try:
                    ic.setIcon(_TI(icon_svg).icon(color=QColor("#8B949E")))
                except Exception:
                    pass
            r.addWidget(ic, 0, Qt.AlignVCenter)
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #C9D1D9; font-size: 11px;")
            r.addWidget(lbl, 1)
            val = QLabel(value or "—")
            val.setStyleSheet(
                f"color: {value_color}; font-size: 11px; font-weight: 700;"
                " font-family: 'Consolas','Menlo',monospace;"
            )
            r.addWidget(val, 0, Qt.AlignRight)
            return r

        d = self._details
        if state == "failed":
            err = d.get("error") or self.property("sync_error") or "Unknown error"
            err_lbl = QLabel(str(err))
            err_lbl.setWordWrap(True)
            err_lbl.setStyleSheet(
                "color: #F85149; font-size: 11px;"
                " font-family: 'Consolas','Menlo',monospace;"
            )
            body.addWidget(err_lbl)
        else:
            body.addLayout(_row("tabler_clock.svg", "Last sync",
                                 d.get("last_sync") or self._timestamp,
                                 value_color="#C9D1D9"))
            if d.get("report_file"):
                body.addLayout(_row("tabler_file.svg", "Report saved",
                                     d["report_file"], fg))
            if d.get("summary_file"):
                body.addLayout(_row("tabler_file_analytics.svg",
                                     "Summary updated",
                                     d["summary_file"], fg))
            if d.get("dashboard_file"):
                body.addLayout(_row("tabler_file_analytics.svg",
                                     "Dashboard rebuilt",
                                     d["dashboard_file"], fg))

            # Footer cloud line.
            footer_row = QHBoxLayout()
            footer_row.setSpacing(8)
            cl = QToolButton()
            cl.setEnabled(False)
            cl.setFixedSize(18, 18)
            cl.setIconSize(QSize(14, 14))
            cl.setStyleSheet("background: transparent; border: none;")
            if _TI is not None:
                try:
                    cl.setIcon(_TI("tabler_cloud_upload.svg").icon(color=QColor(fg)))
                except Exception:
                    pass
            footer_row.addWidget(cl, 0, Qt.AlignVCenter)
            dest = d.get("destination") or "OneDrive synced to SharePoint"
            f_lbl = QLabel(dest)
            f_lbl.setStyleSheet(
                f"color: {fg}; font-size: 11px; font-weight: 700;"
            )
            footer_row.addWidget(f_lbl, 1)
            body.addLayout(footer_row)

        root.addWidget(body_w)
        pop.setMinimumWidth(320)
        pop.adjustSize()

        # Anchor above the pill, extending to the right so the popover
        # doesn't get pushed off-screen by the statusbar's left edge.
        gpos = self.mapToGlobal(self.rect().topLeft())
        pop.move(gpos.x(), gpos.y() - pop.height() - 6)
        pop.show()
        self._detail_popover = pop
        self._set_chev_icon(direction="down")
        # When the popup closes (click outside, etc.), revert the chevron.
        pop.destroyed.connect(lambda: self._set_chev_icon(direction="up"))

    def _set_chev_icon(self, *, direction: str = "up"):
        try:
            from .tabler_icons import TablerIcon as _TI
            svg = ("tabler_chevron_down.svg" if direction == "down"
                   else "tabler_chevron_up.svg")
            self._chev.setIcon(_TI(svg).icon(color=QColor("#8B949E")))
        except Exception:
            pass
