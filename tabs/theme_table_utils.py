"""
Shared helpers for table theme updates, plus canonical theme color palette.

Import colors from here instead of hard-coding hex strings in tab files.
"""

from __future__ import annotations

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTableWidget
from sync.app_config import load_config

# ── Semantic palette ──────────────────────────────────────────────────────────
# Foreground
CLR_FG_LIGHT   = QColor(255, 255, 255)   # white text on dark backgrounds
CLR_FG_DARK    = QColor(34, 32, 56)      # dark text on light backgrounds (#242038)

# Status / accent
CLR_ACCENT     = QColor("#4AA3FF")        # primary blue accent
CLR_SUCCESS    = QColor("#3FB950")        # green — met target / approved
CLR_WARNING    = QColor("#D29922")        # amber — at-risk / warning
CLR_ERROR      = QColor("#F85149")        # red — missed / rejected
CLR_ORANGE     = QColor("#F0883E")        # orange — pending / overtime

# Dark-mode surface layers
CLR_DARK_BG    = QColor("#21262D")        # deepest background
CLR_DARK_MID   = QColor("#2B2B2B")        # mid-level panel
CLR_DARK_BORD  = QColor("#3C3C3C")        # border / separator

# Light palette defaults (must match tab_theme_config + main light replacements)
DEFAULT_LIGHT_COLORS = {
    "base_bg": "#F6F8FA",
    "surface_bg": "#FFFFFF",
    "text_primary": "#1F2328",
    "text_muted": "#656D76",
    "border": "#D0D7DE",
    "accent": "#0969DA",
    "selection_bg": "#DDF4FF",
    "button_bg": "#EAEEF2",
}


def get_light_theme_colors() -> dict:
    """Return merged light palette from config + defaults."""
    out = dict(DEFAULT_LIGHT_COLORS)
    try:
        cfg = load_config()
        raw = cfg.get("light_theme_colors", {}) if isinstance(cfg, dict) else {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k in out and isinstance(v, str) and v.strip():
                    out[k] = v.strip().upper()
    except Exception:
        pass
    return out


def mix_hex(c1: str, c2: str, t: float) -> str:
    """Linear color mix c1 -> c2 with t in [0,1]."""
    t = max(0.0, min(1.0, float(t)))
    a = QColor(c1)
    b = QColor(c2)
    r = int(a.red() + (b.red() - a.red()) * t)
    g = int(a.green() + (b.green() - a.green()) * t)
    bl = int(a.blue() + (b.blue() - a.blue()) * t)
    return QColor(r, g, bl).name().upper()


def light_row_bg(index: int, colors: dict | None = None) -> QColor:
    """Subtle zebra bg color in light mode derived from user palette."""
    c = colors or get_light_theme_colors()
    base = c.get("surface_bg", DEFAULT_LIGHT_COLORS["surface_bg"])
    alt = mix_hex(base, c.get("base_bg", DEFAULT_LIGHT_COLORS["base_bg"]), 0.55)
    return QColor(base if (index % 2 == 0) else alt)


def light_header_bg(colors: dict | None = None) -> str:
    c = colors or get_light_theme_colors()
    return mix_hex(c.get("accent", DEFAULT_LIGHT_COLORS["accent"]), "#FFFFFF", 0.68)


def light_header_fg(colors: dict | None = None) -> str:
    c = colors or get_light_theme_colors()
    return c.get("text_primary", DEFAULT_LIGHT_COLORS["text_primary"])


def apply_table_theme(
    container,
    is_light: bool,
    *,
    light_append_css: str = "",
    dark_append_css: str = "",
    default_fg: QColor | None = None,
    adaptive_fg_by_bg: bool = False,
    adaptive_default_fg: QColor | None = None,
) -> None:
    """
    Apply style/foreground updates to all QTableWidget descendants.

    Preserves each table's original style in `_saved_style`.
    """
    for table in container.findChildren(QTableWidget):
        if not hasattr(table, "_saved_style"):
            table._saved_style = table.styleSheet() or ""
        base = table._saved_style
        append_css = light_append_css if is_light else dark_append_css
        try:
            table.setStyleSheet(base + append_css)
        except Exception:
            continue

        if default_fg is None and not adaptive_fg_by_bg:
            continue

        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                item = table.item(r, c)
                if not item:
                    continue
                if adaptive_fg_by_bg:
                    bg = item.background().color() if item.background() else None
                    if bg is None:
                        base_fg = adaptive_default_fg or CLR_FG_LIGHT
                        item.setForeground(QBrush(base_fg))
                    else:
                        fg = CLR_FG_LIGHT if bg.lightness() < 129 else CLR_FG_DARK
                        item.setForeground(QBrush(fg))
                else:
                    item.setForeground(QBrush(default_fg))
