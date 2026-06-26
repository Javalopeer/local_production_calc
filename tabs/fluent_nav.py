"""Drop-in replacement for QTabWidget using qfluentwidgets' sidebar nav.

Exposes the small subset of QTabWidget API that main.py touches:
    addTab(widget, icon, text)
    setCurrentIndex(int)
    currentWidget()
    setTabIcon(index, icon)
    currentChanged (Signal[int])

The rest of the app keeps thinking it's talking to a QTabWidget. statusBar,
closeEvent, themeChanged signal, every QSS rule — all untouched.
"""
from typing import Union

from PySide6.QtCore import Signal, QSize, Qt, QRect, QRectF
from PySide6.QtGui import QIcon, QPainter, QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget, QSizePolicy, QFrame,
)

from qfluentwidgets import NavigationBar, NavigationItemPosition
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets.common.font import setFont
from qfluentwidgets.common.icon import drawIcon, FluentIconBase
from qfluentwidgets.common.style_sheet import isDarkTheme
from qfluentwidgets.common.color import autoFallbackThemeColor
from qfluentwidgets.components.navigation.navigation_bar import NavigationBarPushButton


# Icon-only item — names show via tooltip on hover.
_ITEM_W = 42
_ITEM_H = 38
_ICON_RECT = QRectF(10, 8, 22, 22)    # icon centered in 42x38
_INDICATOR_RECT = QRectF(0, 11, 2, 16)
_FONT_PX = 8


class _CompactNavButton(NavigationBarPushButton):
    """Icon-only variant of NavigationBarPushButton — name shown via tooltip."""

    def __init__(self, icon, text, isSelectable, selectedIcon=None, parent=None):
        super().__init__(icon, text, isSelectable, selectedIcon, parent)
        self.setFixedSize(_ITEM_W, _ITEM_H)
        setFont(self, _FONT_PX)
        # Hover tooltip carries the tab name since labels are hidden.
        self.setToolTip(text)

    def indicatorRect(self):
        """Slide animation rectangle — match the static per-item one."""
        return _INDICATOR_RECT

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform
        )
        painter.setPen(Qt.NoPen)

        # Background pill
        if self.isSelected or self.isAboutSelected:
            painter.setBrush(QColor(255, 255, 255, 42) if isDarkTheme() else Qt.white)
            painter.drawRoundedRect(self.rect(), 5, 5)
            if not self.isAboutSelected:
                painter.setBrush(autoFallbackThemeColor(self.lightSelectedColor, self.darkSelectedColor))
                painter.drawRoundedRect(_INDICATOR_RECT, 2, 2)
        elif self.isPressed or self.isEnter:
            c = 255 if isDarkTheme() else 0
            alpha = 9 if self.isEnter else 6
            painter.setBrush(QColor(c, c, c, alpha))
            painter.drawRoundedRect(self.rect(), 5, 5)

        # Icon — centered, no label
        if (self.isPressed or not self.isEnter) and not (self.isSelected or self.isAboutSelected):
            painter.setOpacity(0.6)
        if not self.isEnabled():
            painter.setOpacity(0.4)

        selectedIcon = self._selectedIcon or self._icon
        if isinstance(selectedIcon, FluentIconBase) and (self.isSelected or self.isAboutSelected):
            color = autoFallbackThemeColor(self.lightSelectedColor, self.darkSelectedColor)
            selectedIcon.render(painter, _ICON_RECT, fill=color.name())
        elif self.isSelected or self.isAboutSelected:
            drawIcon(selectedIcon, painter, _ICON_RECT)
        else:
            drawIcon(self._icon, painter, _ICON_RECT)


class _CompactNavigationBar(NavigationBar):
    """NavigationBar that creates _CompactNavButton items instead of the
    full-size default. We override addItem to swap the widget class while
    keeping every other NavigationBar behaviour intact (indicator, routing,
    selection, theme).
    """

    def addItem(self, routeKey: str, icon, text: str, onClick=None,
                selectable: bool = True, selectedIcon=None,
                position: NavigationItemPosition = NavigationItemPosition.TOP):
        widget = _CompactNavButton(icon, text, selectable, selectedIcon, self)
        widget.setSelectedColor(self.lightSelectedColor, self.darkSelectedColor)
        widget.setSelectedTextVisible(self.isSelectedTextVisible())
        self.insertWidget(-1, routeKey, widget, onClick, position)
        return widget


class FluentNavigation(QWidget):
    """QTabWidget-compatible sidebar nav backed by a compact NavigationBar."""

    currentChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._route_to_index = {}

        self.nav = _CompactNavigationBar(self)
        # Icon-only items: tight width, expand vertical to fill window.
        self.nav.setFixedWidth(_ITEM_W + 8)
        self.nav.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        # Tighten lateral padding inside each navigation layout.
        for _lay in (self.nav.topLayout, self.nav.scrollLayout, self.nav.bottomLayout):
            _lay.setSpacing(20)
            _lay.setContentsMargins(2, 0, 2, 0)

        # Action button column docked at the very bottom of the sidebar.
        self._bottom_actions = QVBoxLayout()
        self._bottom_actions.setSpacing(6)
        self._bottom_actions.setContentsMargins(2, 4, 2, 8)
        self._bottom_actions.setAlignment(Qt.AlignHCenter)

        # Action column anchored to the very TOP of the sidebar (e.g.
        # help button). Stretches keep the main icon cluster centred
        # vertically regardless of how many top actions exist.
        self._top_actions = QVBoxLayout()
        self._top_actions.setSpacing(6)
        self._top_actions.setContentsMargins(2, 8, 2, 4)
        self._top_actions.setAlignment(Qt.AlignHCenter)

        # Vertically center the icon cluster: rebuild the outer vBoxLayout
        # with stretches above and below topLayout, plus the bottom action
        # column. ScrollArea + bottomLayout aren't used (all items in topLayout).
        self.nav.scrollArea.hide()
        _v = self.nav.vBoxLayout
        while _v.count():
            _v.takeAt(0)
        _v.addLayout(self._top_actions)
        _v.addStretch(1)
        _v.addLayout(self.nav.topLayout)
        _v.addStretch(1)
        _v.addLayout(self._bottom_actions)

        # Dedicated full-height vertical separator between sidebar and content.
        self._separator = QFrame(self)
        self._separator.setFixedWidth(1)
        self._separator.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.apply_palette(False)

        self.stack = QStackedWidget(self)
        self.stack.currentChanged.connect(self._on_stack_changed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.nav)
        lay.addWidget(self._separator)
        lay.addWidget(self.stack, 1)

    def apply_palette(self, is_light: bool):
        """Repaint elements that need explicit colours (separator, etc.)
        when the global theme flips between dark and light."""
        try:
            from .theme_palette import palette
            p = palette(is_light)
            self._separator.setStyleSheet(
                f"background-color: {p['border_strong']}; border: none;"
            )
        except Exception:
            self._separator.setStyleSheet(
                "background-color: #30363D; border: none;"
            )

    def add_top_action(self, widget: QWidget):
        """Add a widget (typically an icon-only button) above the main
        nav cluster at the top of the sidebar."""
        self._top_actions.addWidget(widget, 0, Qt.AlignHCenter)

    # ── QTabWidget-compatible API ─────────────────────────────────────────

    def addTab(self, widget: QWidget, icon: Union[QIcon, FluentIconBase], text: str) -> int:
        index = self.stack.count()
        route_key = f"tab_{index}"
        widget.setObjectName(route_key)
        self.stack.addWidget(widget)
        self._items.append((route_key, widget))
        self._route_to_index[route_key] = index

        self.nav.addItem(
            routeKey=route_key,
            icon=icon,
            text=text,
            onClick=lambda checked=False, i=index: self.setCurrentIndex(i),
            selectable=True,
            position=NavigationItemPosition.TOP,
        )
        if index == 0:
            self.nav.setCurrentItem(route_key)
        return index

    def setCurrentIndex(self, index: int) -> None:
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)
            route_key = self._items[index][0]
            self.nav.setCurrentItem(route_key)

    def currentIndex(self) -> int:
        return self.stack.currentIndex()

    def currentWidget(self) -> QWidget:
        return self.stack.currentWidget()

    def widget(self, index: int) -> QWidget:
        return self.stack.widget(index)

    def count(self) -> int:
        return self.stack.count()

    def setTabIcon(self, index: int, icon) -> None:
        if not (0 <= index < len(self._items)):
            return
        route_key = self._items[index][0]
        try:
            item = self.nav.widget(route_key)
        except Exception:
            item = None
        if item is not None and hasattr(item, "setIcon"):
            try:
                item.setIcon(icon)
            except Exception:
                pass

    def setTabText(self, index: int, text: str) -> None:
        if not (0 <= index < len(self._items)):
            return
        route_key = self._items[index][0]
        try:
            item = self.nav.widget(route_key)
        except Exception:
            item = None
        if item is not None and hasattr(item, "setText"):
            try:
                item.setText(text)
            except Exception:
                pass

    # ── Bottom action slot ────────────────────────────────────────────────

    def add_bottom_action(self, widget: QWidget) -> None:
        """Dock an arbitrary widget at the bottom of the sidebar (legacy)."""
        widget.setFixedSize(36, 30)
        widget.setCursor(Qt.PointingHandCursor)
        self._bottom_actions.addWidget(widget, 0, Qt.AlignHCenter)

    def add_bottom_nav_action(self, icon, tooltip: str, on_click) -> QWidget:
        """Dock an action button that visually matches the top nav icons.

        Uses the same _CompactNavButton paint (icon-only, indicator on hover/
        pressed) but with selectable=False, so clicking it just fires the
        callback without changing the current tab.
        """
        btn = _CompactNavButton(icon, tooltip, False, None, self.nav)
        btn.setSelectedColor(self.nav.lightSelectedColor, self.nav.darkSelectedColor)
        btn.setSelectedTextVisible(False)
        btn.setToolTip(tooltip)
        btn.clicked.connect(on_click)
        self._bottom_actions.addWidget(btn, 0, Qt.AlignHCenter)
        return btn

    # ── Internal ───────────────────────────────────────────────────────────

    def _on_stack_changed(self, index: int) -> None:
        self.currentChanged.emit(index)
