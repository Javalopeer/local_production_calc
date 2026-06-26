"""Tabler SVG icons rendered as FluentIconBase so they auto-theme.

Tabler outline icons use `stroke="currentColor"` instead of `fill`, so the
default FluentIconBase.render path (which substitutes `fill` on <path>
elements) doesn't recolor them. This wrapper does a plain string substitution
of `currentColor` for the theme/selection color before handing the SVG to
QSvgRenderer.

Usage:
    icon = TablerIcon("tabler_database.svg")
    button.setIcon(icon.icon())            # for QPushButton etc.
    # or pass `icon` directly anywhere a FluentIconBase is accepted
    # (e.g. NavigationBar.addItem).

All SVGs must live in `data/icons/` so they get bundled by PyInstaller.
"""
from __future__ import annotations

import os
import sys
from PySide6.QtCore import QRectF
from PySide6.QtGui import QIcon, QColor

from qfluentwidgets.common.icon import (
    FluentIconBase, SvgIconEngine, drawSvgIcon, getIconColor,
)
from qfluentwidgets.common.config import Theme


def _icons_dir() -> str:
    """Return the absolute path of data/icons (works frozen and in dev).

    PyInstaller one-file builds unpack bundled data to ``sys._MEIPASS``
    at runtime, not next to the .exe. Check that first; fall back to the
    exe directory (one-folder build) and finally to the repo root.
    """
    if getattr(sys, "frozen", False):
        # 1) one-file: data lives in the bootloader's extraction tempdir.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate = os.path.join(meipass, "data", "icons")
            if os.path.isdir(candidate):
                return candidate
        # 2) one-folder: data sits beside the .exe.
        base = os.path.dirname(sys.executable)
        return os.path.join(base, "data", "icons")
    # 3) dev / source tree.
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "data", "icons")


class TablerIcon(FluentIconBase):
    """A Tabler outline SVG icon that follows the qfluentwidgets theme."""

    def __init__(self, filename: str):
        # Source priority:
        #   1. EMBEDDED_ICONS dict generated at build time — zero filesystem
        #      access, works identically on every machine no matter where
        #      PyInstaller extracts the bundle.
        #   2. Filesystem fallback for dev runs where embedded module is
        #      missing or out-of-date.
        self._abs_path = filename
        self._template = ""
        try:
            from ._embedded_icons import EMBEDDED_ICONS
            self._template = EMBEDDED_ICONS.get(filename, "")
        except Exception:
            pass
        if not self._template:
            # Dev / legacy fallback: read SVG from data/icons on disk.
            try:
                fs_path = os.path.join(_icons_dir(), filename)
                with open(fs_path, "rb") as f:
                    self._template = f.read().decode("utf-8")
                self._abs_path = fs_path
            except OSError:
                self._template = ""

    def path(self, theme=Theme.AUTO) -> str:
        return self._abs_path

    def _colored_svg(self, color: str) -> bytes:
        if not self._template:
            return b""
        return self._template.replace("currentColor", color).encode("utf-8")

    def icon(self, theme=Theme.AUTO, color: QColor = None) -> QIcon:
        c = QColor(color).name() if color else getIconColor(theme)
        svg = self._colored_svg(c).decode("utf-8")
        return QIcon(SvgIconEngine(svg))

    # Render at full rect — visual weight matches FluentIcon family closely
    # when stroke-width sits in the 1.5–2 range. Tune if needed.
    _OPTICAL_SCALE = 1.0

    def render(self, painter, rect, theme=Theme.AUTO, indexes=None, **attributes):
        # _CompactNavButton passes `fill=color.name()` when the item is selected;
        # honour that so the active icon picks up the accent colour. Otherwise
        # fall back to the theme-aware mono colour.
        color = attributes.get("fill") or getIconColor(theme)
        svg = self._colored_svg(color)
        if not svg:
            return
        r = QRectF(rect)
        inset_x = r.width() * (1 - self._OPTICAL_SCALE) / 2
        inset_y = r.height() * (1 - self._OPTICAL_SCALE) / 2
        r.adjust(inset_x, inset_y, -inset_x, -inset_y)
        drawSvgIcon(svg, painter, r)
