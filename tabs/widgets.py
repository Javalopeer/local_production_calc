"""
Shared PySide6 widgets used across multiple tabs.

Centralises widgets that were previously copy-pasted between tab_register.py
and tab_overtime.py so that behaviour stays consistent in both places.
"""
from PySide6.QtWidgets import QTimeEdit, QDateEdit, QGroupBox, QVBoxLayout, QWidget, QLabel
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
        # Strip the red weekend formatting so the calendar matches the app.
        # Theme-aware weekend colour so the calendar reads in light + dark.
        try:
            from PySide6.QtGui import QTextCharFormat, QBrush, QColor
            from qfluentwidgets.common.style_sheet import isDarkTheme
            from .theme_palette import palette as _cal_pal
            _cp = _cal_pal(not isDarkTheme())
            cal = self.calendarWidget()
            if cal is not None:
                neutral = QTextCharFormat()
                neutral.setForeground(QBrush(QColor(_cp["text"])))
                cal.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, neutral)
                cal.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, neutral)
                cal.setVerticalHeaderFormat(cal.VerticalHeaderFormat.NoVerticalHeader)
                cal.setHorizontalHeaderFormat(cal.HorizontalHeaderFormat.SingleLetterDayNames)
                cal.setGridVisible(False)
                cal.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
                # Override the native QCalendarWidget palette so popup bg
                # stops being black in light mode.
                cal.setStyleSheet(
                    f"QCalendarWidget QWidget {{"
                    f"  background-color: {_cp['base']};"
                    f"  color: {_cp['text']}; alternate-background-color: {_cp['surface']}; }}"
                    f"QCalendarWidget QToolButton {{"
                    f"  color: {_cp['text']}; background-color: transparent;"
                    f"  border: none; padding: 6px; }}"
                    f"QCalendarWidget QToolButton:hover {{"
                    f"  background-color: {_cp['raised']}; }}"
                    f"QCalendarWidget QAbstractItemView:enabled {{"
                    f"  color: {_cp['text']};"
                    f"  selection-background-color: {_cp['accent']};"
                    f"  selection-color: #FFFFFF; }}"
                    f"QCalendarWidget QAbstractItemView:disabled {{"
                    f"  color: {_cp['muted_2']}; }}"
                )
        except Exception:
            pass

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


def _icon_url(filename: str) -> str:
    """Return a forward-slash absolute path so Qt QSS can load it.

    Resolves to the bootloader's ``sys._MEIPASS`` tempdir for one-file
    PyInstaller builds, falls back to the exe dir for one-folder builds,
    and to the repo root in dev.
    """
    import os, sys
    candidate = None
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate = os.path.join(meipass, "data", "icons", filename)
            if not os.path.exists(candidate):
                candidate = None
        if candidate is None:
            base = os.path.dirname(sys.executable)
            candidate = os.path.join(base, "data", "icons", filename)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidate = os.path.join(base, "data", "icons", filename)
    return candidate.replace("\\", "/")


def _pro_card_qss(accent: str, is_light: bool) -> str:
    """Build the pro_card QSS for the active theme."""
    try:
        from .theme_palette import palette
        p = palette(is_light)
    except Exception:
        p = {
            "surface": "#161B22", "border": "#21262D",
            "border_strong": "#30363D", "muted_2": "#444C56",
            "accent_2": "#388BFD", "accent": "#1757D4",
        }
    # In light mode, swap dark-theme accents (default blue or white-ish
    # text colours used by call sites) for the user's configured palette
    # accent so titles stay readable on whatever bg the user picked.
    _DARK_ACCENTS = {
        "#1757D4", "#E6EDF3", "#C9D1D9", "#FFFFFF", "WHITE", "#388BFD",
    }
    if is_light and accent.upper() in _DARK_ACCENTS:
        accent = p.get("accent", accent)
    chevron_svg = _icon_url(
        "tabler_chevron_down.svg" if not is_light else "tabler_chevron_down.svg"
    )
    return (
        "#proCard { background: transparent;"
        f"  border: 1px solid {p['border']}; border-radius: 12px; }}"
        "#proCard > QFrame#proCardHeader { background: transparent; }"
        f"#proCard QLabel#proCardTitle {{ color: {accent}; font-size: 11px;"
        " font-weight: 800; letter-spacing: 1.2px; background: transparent;"
        " border: none; }"
        "#proCard QLineEdit, #proCard QComboBox, #proCard QDateEdit,"
        "#proCard QTimeEdit, #proCard QSpinBox, #proCard QDoubleSpinBox {"
        f"  background-color: {p['surface']};"
        f"  border: 1px solid {p['border_strong']}; }}"
        "#proCard QLineEdit:hover, #proCard QComboBox:hover,"
        "#proCard QDateEdit:hover, #proCard QTimeEdit:hover {"
        f"  border-color: {p['muted_2']}; }}"
        "#proCard QLineEdit:focus, #proCard QComboBox:focus,"
        "#proCard QDateEdit:focus, #proCard QTimeEdit:focus {"
        f"  border-bottom: 2px solid {p['accent_2']}; }}"
        "#proCard QComboBox::drop-down { subcontrol-origin: padding;"
        "  subcontrol-position: right center; width: 22px; border: none; }"
        f"#proCard QComboBox::down-arrow {{ image: url({chevron_svg});"
        "  width: 12px; height: 12px; }"
        "#proCard QDateEdit::drop-down { subcontrol-origin: padding;"
        "  subcontrol-position: right center; width: 22px; border: none; }"
        f"#proCard QDateEdit::down-arrow {{ image: url({chevron_svg});"
        "  width: 12px; height: 12px; }"
    )


def pro_card(title: str, body, *, icon=None, accent: str = "#1757D4",
             header_extra=None):
    """Modern card: blue accent bar + icon + UPPERCASE title above the body.

    Parameters
    ----------
    title : str
        Displayed in uppercase, small caps style.
    body : QWidget | QLayout
        The card contents.
    icon : QIcon | FluentIconBase | None
        Optional leading icon next to the title.
    accent : str
        Hex color for the title text and left accent strip.
    """
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton
    from PySide6.QtCore import QSize

    box = QFrame()
    box.setObjectName("proCard")
    box._pro_card_accent = accent  # type: ignore[attr-defined]
    # Detect current theme so first paint matches it; fall back to dark.
    _initial_light = False
    try:
        from qfluentwidgets.common.style_sheet import isDarkTheme
        _initial_light = not isDarkTheme()
    except Exception:
        pass
    box.setStyleSheet(_pro_card_qss(accent, _initial_light))

    def _apply_palette(is_light: bool, _w=box, _a=accent):
        _w.setStyleSheet(_pro_card_qss(_a, is_light))
    box.apply_palette = _apply_palette  # type: ignore[attr-defined]
    outer = QVBoxLayout(box)
    outer.setContentsMargins(20, 14, 20, 16)
    outer.setSpacing(10)

    header = QFrame()
    header.setObjectName("proCardHeader")
    header.setMinimumHeight(34)
    hl = QHBoxLayout(header)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.setSpacing(8)
    hl.setAlignment(Qt.AlignVCenter)

    if icon is not None:
        ic = QToolButton()
        ic.setEnabled(False)
        ic.setStyleSheet("border: none; background: transparent;")
        from PySide6.QtGui import QColor as _QC_ic
        def _apply_icon(is_light: bool, _i=ic, _src=icon, _acc=accent):
            try:
                from .theme_palette import palette
                p = palette(is_light)
                col = p.get("accent_2") if not is_light else p.get("accent")
            except Exception:
                col = _acc
            if hasattr(_src, "icon"):
                _i.setIcon(_src.icon(color=_QC_ic(col)))
            else:
                _i.setIcon(_src)
        ic.apply_palette = _apply_icon
        try:
            from qfluentwidgets.common.style_sheet import isDarkTheme
            _apply_icon(not isDarkTheme())
        except Exception:
            _apply_icon(False)
        ic.setIconSize(QSize(14, 14))
        hl.addWidget(ic)

    title_lbl = QLabel(title.upper())
    title_lbl.setObjectName("proCardTitle")
    hl.addWidget(title_lbl)
    hl.addStretch()
    if header_extra is not None:
        if isinstance(header_extra, QWidget):
            hl.addWidget(header_extra)
        else:
            hl.addLayout(header_extra)
    outer.addWidget(header)

    if isinstance(body, QWidget):
        outer.addWidget(body)
    else:
        outer.addLayout(body)

    return box


def labeled_field(label_text: str, widget) -> QVBoxLayout:
    """Stacked field: small grey label on top, input below."""
    from PySide6.QtCore import Qt
    lay = QVBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lbl = QLabel(label_text)
    lbl.setStyleSheet("color: #8B949E; font-size: 10px; font-weight: 600;"
                      " letter-spacing: 0.5px; background: transparent;")
    lay.addWidget(lbl)
    lay.addWidget(widget)
    return lay
