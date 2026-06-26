# -*- coding: utf-8 -*-
"""Centralised theme palette.

Every Fluent-styled card/component in the app should pull its colours
from :func:`palette` so that toggling dark/light mode (and changing the
light-mode preset in Theme Config) propagates without touching dozens
of stylesheets.

Dark mode is hardcoded to the GitHub-Dark / Fluent-slate values that the
app has been built around. Light mode is read live from the user's
configured palette (Theme Config tab) and falls back to the
``DEFAULT_LIGHT_COLORS`` shipped with the app.

Public surface::

    palette(is_light) -> dict[str, str]   # full token map
    qcolor(token, is_light) -> QColor      # convenience for QPainter code
"""
from __future__ import annotations

from typing import Dict

from PySide6.QtGui import QColor


# ---------------------------------------------------------------------------
# Dark palette — single source of truth for the current Fluent-slate look.
# ---------------------------------------------------------------------------

_DARK: Dict[str, str] = {
    # Surfaces
    "base":       "#0D1117",   # outer card / dashboard bg
    "surface":    "#161B22",   # inner row, table cells, input bg
    "raised":     "#21262D",   # secondary surface (active row, header bg)
    # Borders
    "border":     "#21262D",
    "border_strong": "#30363D",
    # Text
    "text":       "#E6EDF3",   # primary text
    "text_2":     "#C9D1D9",   # secondary text inside cards
    "muted":      "#8B949E",   # captions, sublabels
    "muted_2":    "#6E7681",   # tertiary (chevrons, hints)
    # Accent + status
    "accent":     "#1F6FEB",
    "accent_2":   "#58A6FF",   # accent text/hover
    "good":       "#3FB950",
    "warn":       "#D29922",
    "danger":     "#F85149",
    "info":       "#58A6FF",
    "tip":        "#F0883E",   # orange highlight (OT, hints)
    # Selection
    "selection":  "rgba(56,139,253,0.14)",
}


# ---------------------------------------------------------------------------
# Light palette — text/status colours derived from the user-configured
# values so a custom preset still gets a consistent palette.
# ---------------------------------------------------------------------------

def _build_light(user_cfg: Dict[str, str] | None = None) -> Dict[str, str]:
    """Merge the user's configured light colours with derived tokens.

    ``user_cfg`` keys come from Theme Config:
        base_bg, surface_bg, text_primary, text_muted,
        border, accent, selection_bg, button_bg
    Missing keys fall back to GitHub Light.
    """
    fallback = {
        "base_bg":      "#F6F8FA",
        "surface_bg":   "#FFFFFF",
        "text_primary": "#1F2328",
        "text_muted":   "#656D76",
        "border":       "#D0D7DE",
        "accent":       "#0969DA",
        "selection_bg": "#DDF4FF",
        "button_bg":    "#EAEEF2",
    }
    cfg = dict(fallback)
    if user_cfg:
        for k, v in user_cfg.items():
            if v:
                cfg[k] = v

    return {
        "base":          cfg["base_bg"],
        "surface":       cfg["surface_bg"],
        "raised":        cfg["button_bg"],
        "border":        cfg["border"],
        "border_strong": cfg["border"],
        "text":          cfg["text_primary"],
        "text_2":        cfg["text_primary"],
        "muted":         cfg["text_muted"],
        "muted_2":       cfg["text_muted"],
        "accent":        cfg["accent"],
        "accent_2":      cfg["accent"],
        # Status tier colours stay readable on light bg.
        "good":          "#1A7F37",
        "warn":          "#9A6700",
        "danger":        "#CF222E",
        "info":          cfg["accent"],
        "tip":           "#BC4C00",
        "selection":     cfg["selection_bg"],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def palette(is_light: bool) -> Dict[str, str]:
    """Return the full token map for the active theme."""
    if not is_light:
        return dict(_DARK)
    try:
        from sync.app_config import load_config
        user_cfg = (load_config() or {}).get("light_theme_colors", {}) or {}
    except Exception:
        user_cfg = {}
    return _build_light(user_cfg)


def qcolor(token: str, is_light: bool) -> QColor:
    """Convenience wrapper for QPainter sites — returns a QColor."""
    return QColor(palette(is_light).get(token, "#000000"))


def themed_qss(qss: str) -> str:
    """Translate hardcoded Fluent-dark hex literals in a QSS string to
    the active theme's palette values. Wrap any ``setStyleSheet(qss)``
    call where the QSS still contains dark literals to make it adapt
    to light mode automatically."""
    try:
        from qfluentwidgets.common.style_sheet import isDarkTheme
        is_light = not isDarkTheme()
    except Exception:
        is_light = False
    p = palette(is_light)
    # Map of Fluent-dark literals (case-insensitive) to palette tokens.
    swaps = [
        ("#0D1117", p["base"]), ("#0d1117", p["base"]),
        ("#101824", p["base"]), ("#11161D", p["base"]),
        ("#11161d", p["base"]), ("#0a0e14", p["base"]),
        ("#0A0E14", p["base"]),
        ("#161B22", p["surface"]), ("#161b22", p["surface"]),
        ("#1a1f25", p["surface"]), ("#1A1F25", p["surface"]),
        ("#1C232C", p["surface"]), ("#1c232c", p["surface"]),
        ("#21262D", p["border"]), ("#21262d", p["border"]),
        ("#2D2F36", p["raised"]), ("#2d2f36", p["raised"]),
        ("#2a3a55", p["raised"]), ("#2A3A55", p["raised"]),
        ("#30363D", p["border_strong"]), ("#30363d", p["border_strong"]),
        ("#383B43", p["border_strong"]), ("#383b43", p["border_strong"]),
        ("#444C56", p["muted_2"]), ("#444c56", p["muted_2"]),
        ("#58606A", p["muted_2"]), ("#58606a", p["muted_2"]),
        ("#E6EDF3", p["text"]), ("#e6edf3", p["text"]),
        ("#C9D1D9", p["text_2"]), ("#c9d1d9", p["text_2"]),
        ("#8B949E", p["muted"]), ("#8b949e", p["muted"]),
        ("#6E7681", p["muted_2"]), ("#6e7681", p["muted_2"]),
    ]
    for old, new in swaps:
        if old != new:
            qss = qss.replace(old, new)
    return qss


def apply_fluent_modal_palette(mbb, object_name: str) -> None:
    """Style a qfluentwidgets MessageBoxBase to match the active theme.

    Replaces the hardcoded ``#101824`` dark-card background pattern used
    across every modal in the app with palette-driven colours. Reads the
    current theme via ``isDarkTheme()`` so the modal pops up correctly
    whichever way the user has the global theme set."""
    try:
        from qfluentwidgets.common.style_sheet import isDarkTheme
        is_light = not isDarkTheme()
    except Exception:
        is_light = False
    p = palette(is_light)
    try:
        mbb.widget.setObjectName(object_name)
        mbb.widget.setStyleSheet(
            f"#{object_name} {{ background: {p['base']};"
            f" border: 1px solid {p['border']}; border-radius: 14px; }}"
        )
    except Exception:
        pass
    try:
        # Use !important via wider selector so qfluentwidgets's own
        # buttonGroup theme stylesheet doesn't override us — in light
        # mode the modal would otherwise paint a dark button strip.
        mbb.buttonGroup.setStyleSheet(
            f"QFrame, #buttonGroup {{ background-color: {p['base']};"
            f" border: none; border-top: 1px solid {p['border']}; }}"
        )
        mbb.buttonGroup.setAutoFillBackground(True)
        from PySide6.QtGui import QPalette, QColor as _QC
        _pal = mbb.buttonGroup.palette()
        _pal.setColor(QPalette.ColorRole.Window, _QC(p["base"]))
        mbb.buttonGroup.setPalette(_pal)
    except Exception:
        pass
