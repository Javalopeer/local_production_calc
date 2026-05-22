"""Global font-scale helper.

Stylesheet base is 12px. QFont calls in widgets use pointSize. Both scale by
ratio `current / 12`. MainWindow updates `_current_px` on user font change;
tabs call `scale_pt` when constructing QFonts so they follow.
"""
from __future__ import annotations

BASE_PX = 12
_MIN_PT = 6
_current_px = BASE_PX


def set_current_px(px: int) -> None:
    global _current_px
    _current_px = max(6, int(px))


def get_current_px() -> int:
    return _current_px


def ratio() -> float:
    return _current_px / float(BASE_PX)


def scale_pt(base_pt: int) -> int:
    """Scale a base point size by current ratio. Floor at 6pt to stay readable."""
    return max(_MIN_PT, round(base_pt * ratio()))


def scale_px(base_px: int) -> int:
    return max(_MIN_PT, round(base_px * ratio()))
