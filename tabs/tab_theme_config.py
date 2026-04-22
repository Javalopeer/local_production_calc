from __future__ import annotations

import random

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QColorDialog, QMessageBox, QCheckBox, QComboBox, QHBoxLayout,
)

from sync.app_config import load_config, save_config
from db.database import discover_and_merge_background_dbs


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


# Curated light-mode palettes. Each preset is a full color set — text kept dark
# enough for readable contrast on the chosen background.
PALETTE_PRESETS: dict[str, dict[str, str]] = {
    "GitHub Light": dict(DEFAULT_LIGHT_COLORS),
    "Warm Cream": {
        "base_bg": "#FBF7EF", "surface_bg": "#FFFDF7",
        "text_primary": "#2A241A", "text_muted": "#6B5E4A",
        "border": "#E3D9C4", "accent": "#B45309",
        "selection_bg": "#FBE8C4", "button_bg": "#F1E8D3",
    },
    "Mint Fresh": {
        "base_bg": "#EFFBF5", "surface_bg": "#FFFFFF",
        "text_primary": "#0B2A20", "text_muted": "#4B6B5E",
        "border": "#C2E6D6", "accent": "#0F766E",
        "selection_bg": "#C9F0E0", "button_bg": "#DEEFE6",
    },
    "Soft Lavender": {
        "base_bg": "#F4F1FB", "surface_bg": "#FFFFFF",
        "text_primary": "#22163E", "text_muted": "#5E557A",
        "border": "#D7CEEC", "accent": "#7C3AED",
        "selection_bg": "#E3D6FB", "button_bg": "#E8E2F4",
    },
    "Rose Blush": {
        "base_bg": "#FDF2F6", "surface_bg": "#FFFFFF",
        "text_primary": "#2D0E1F", "text_muted": "#775061",
        "border": "#F0CFDC", "accent": "#BE185D",
        "selection_bg": "#FBD9E7", "button_bg": "#F4DDE5",
    },
    "Ocean Breeze": {
        "base_bg": "#EEF6FB", "surface_bg": "#FFFFFF",
        "text_primary": "#0E2636", "text_muted": "#4A6A7C",
        "border": "#C7DEEC", "accent": "#0284C7",
        "selection_bg": "#CDE8F7", "button_bg": "#DCEAF2",
    },
    "Forest Sage": {
        "base_bg": "#F1F6EE", "surface_bg": "#FFFFFF",
        "text_primary": "#1B2A14", "text_muted": "#55664A",
        "border": "#CFDCC1", "accent": "#2F855A",
        "selection_bg": "#D9EAC7", "button_bg": "#E1EAD6",
    },
    "Slate Steel": {
        "base_bg": "#EFF2F6", "surface_bg": "#FFFFFF",
        "text_primary": "#1A2330", "text_muted": "#5B6572",
        "border": "#CBD3DD", "accent": "#475569",
        "selection_bg": "#D8DFE8", "button_bg": "#E2E7ED",
    },
    "Peach Sorbet": {
        "base_bg": "#FFF3EB", "surface_bg": "#FFFFFF",
        "text_primary": "#2E180A", "text_muted": "#7A5640",
        "border": "#F3D3BA", "accent": "#EA580C",
        "selection_bg": "#FCDBBE", "button_bg": "#F5DFC9",
    },
    "Honey Gold": {
        "base_bg": "#FAF5E6", "surface_bg": "#FFFDF5",
        "text_primary": "#2A2108", "text_muted": "#6B5F33",
        "border": "#EAD79A", "accent": "#CA8A04",
        "selection_bg": "#F5E7B0", "button_bg": "#EEE3B8",
    },
    "Arctic": {
        "base_bg": "#F2F8FA", "surface_bg": "#FFFFFF",
        "text_primary": "#0D2430", "text_muted": "#4A6976",
        "border": "#CCDDE4", "accent": "#0891B2",
        "selection_bg": "#D5EEF5", "button_bg": "#DDE9EE",
    },
    "Dusty Rose": {
        "base_bg": "#F6EEEF", "surface_bg": "#FFFFFF",
        "text_primary": "#2A1617", "text_muted": "#6F5052",
        "border": "#E6CFD2", "accent": "#9F1239",
        "selection_bg": "#F2D6DB", "button_bg": "#ECD8DA",
    },
    "Graphite Paper": {
        "base_bg": "#F3F4F6", "surface_bg": "#FCFCFD",
        "text_primary": "#111827", "text_muted": "#4B5563",
        "border": "#D1D5DB", "accent": "#111827",
        "selection_bg": "#E5E7EB", "button_bg": "#E5E7EB",
    },
    "Iris Indigo": {
        "base_bg": "#F0F2FB", "surface_bg": "#FFFFFF",
        "text_primary": "#101438", "text_muted": "#4B5280",
        "border": "#CED3F0", "accent": "#4338CA",
        "selection_bg": "#DCE0FB", "button_bg": "#E0E3F3",
    },
    "Lemon Zest": {
        "base_bg": "#FFFBE6", "surface_bg": "#FFFEF5",
        "text_primary": "#2A2600", "text_muted": "#6B6428",
        "border": "#EFE48E", "accent": "#A16207",
        "selection_bg": "#F8EFA8", "button_bg": "#F2EBB3",
    },
}


class _DbScanThread(QThread):
    done = Signal(bool, str)

    def run(self):
        try:
            msg = discover_and_merge_background_dbs(max_seconds=20)
            self.done.emit(True, msg or "No new DB data found to merge.")
        except Exception as exc:
            self.done.emit(False, str(exc))


class ThemeConfigTab(QWidget):
    theme_colors_changed = Signal(dict)

    _LABELS = {
        "base_bg": "App Background",
        "surface_bg": "Cards & Panels",
        "text_primary": "Main Text",
        "text_muted": "Secondary Text",
        "border": "Lines & Borders",
        "accent": "Primary Action Color",
        "selection_bg": "Selection Highlight",
        "button_bg": "Secondary Buttons",
    }

    def __init__(self):
        super().__init__()
        self._colors = dict(DEFAULT_LIGHT_COLORS)
        self._auto_discover_dbs = True
        self._swatches: dict[str, QFrame] = {}
        self._value_labels: dict[str, QLabel] = {}
        self._scan_thread: _DbScanThread | None = None
        self._load_from_config()
        self._init_ui()
        self._refresh_swatches()

    def _load_from_config(self):
        cfg = load_config()
        incoming = cfg.get("light_theme_colors", {}) or {}
        if isinstance(incoming, dict):
            for key, val in incoming.items():
                if key in self._colors and isinstance(val, str) and val.strip():
                    self._colors[key] = val.strip().upper()
        self._auto_discover_dbs = bool(cfg.get("auto_discover_dbs", True))

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        title = QLabel("Light Theme Colors")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #4aa3ff;")
        root.addWidget(title)

        subtitle = QLabel("Pick a preset, generate a palette, or edit colors manually. Save applies globally.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(subtitle)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        preset_row.addWidget(QLabel("Preset:"))
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItems(list(PALETTE_PRESETS.keys()))
        self.cmb_preset.setMinimumWidth(180)
        preset_row.addWidget(self.cmb_preset, 1)
        btn_apply_preset = QPushButton("Load Preset")
        btn_apply_preset.setFixedWidth(100)
        btn_apply_preset.clicked.connect(self._apply_preset)
        preset_row.addWidget(btn_apply_preset)
        root.addLayout(preset_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        for row, key in enumerate(DEFAULT_LIGHT_COLORS.keys()):
            lbl = QLabel(self._LABELS.get(key, key))
            swatch = QFrame()
            swatch.setFixedSize(36, 18)
            swatch.setFrameShape(QFrame.Shape.Box)
            val_lbl = QLabel("")
            val_lbl.setMinimumWidth(84)
            btn = QPushButton("Pick")
            btn.setFixedWidth(58)
            btn.clicked.connect(lambda _=False, k=key: self._pick_color(k))

            grid.addWidget(lbl, row, 0)
            grid.addWidget(swatch, row, 1)
            grid.addWidget(val_lbl, row, 2)
            grid.addWidget(btn, row, 3)

            self._swatches[key] = swatch
            self._value_labels[key] = val_lbl

        root.addLayout(grid)

        btn_row = QGridLayout()
        btn_row.setHorizontalSpacing(8)

        btn_reset = QPushButton("Reset Defaults")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_row.addWidget(btn_reset, 0, 0)

        btn_generate = QPushButton("Generate Palette")
        btn_generate.clicked.connect(self._generate_palette)
        btn_row.addWidget(btn_generate, 0, 1)

        btn_save = QPushButton("Save & Apply")
        btn_save.clicked.connect(self._save_and_apply)
        btn_row.addWidget(btn_save, 0, 2)

        btn_row.setColumnStretch(3, 1)
        root.addLayout(btn_row)

        db_title = QLabel("Data Discovery")
        db_title.setStyleSheet("font-size: 12px; font-weight: 700; color: #8B949E;")
        root.addWidget(db_title)

        self.chk_auto_discover = QCheckBox("Auto-discover and merge DB files on app startup")
        self.chk_auto_discover.setChecked(self._auto_discover_dbs)
        root.addWidget(self.chk_auto_discover)

        db_row = QGridLayout()
        db_row.setHorizontalSpacing(8)
        btn_scan_now = QPushButton("Scan Now")
        btn_scan_now.clicked.connect(self._scan_now)
        db_row.addWidget(btn_scan_now, 0, 0)
        self.lbl_scan_status = QLabel("")
        self.lbl_scan_status.setStyleSheet("color: #8B949E; font-size: 11px;")
        db_row.addWidget(self.lbl_scan_status, 0, 1)
        db_row.setColumnStretch(2, 1)
        root.addLayout(db_row)
        root.addStretch()

    def _refresh_swatches(self):
        for key, color in self._colors.items():
            sw = self._swatches.get(key)
            lbl = self._value_labels.get(key)
            if sw:
                sw.setStyleSheet(f"background-color: {color}; border: 1px solid #30363D;")
            if lbl:
                lbl.setText(color.upper())

    def _pick_color(self, key: str):
        current = QColor(self._colors.get(key, "#FFFFFF"))
        picked = QColorDialog.getColor(current, self, f"Choose {self._LABELS.get(key, key)}")
        if not picked.isValid():
            return
        self._colors[key] = picked.name().upper()
        self._refresh_swatches()

    def _reset_defaults(self):
        self._colors = dict(DEFAULT_LIGHT_COLORS)
        self._refresh_swatches()

    def _apply_preset(self):
        name = self.cmb_preset.currentText()
        preset = PALETTE_PRESETS.get(name)
        if not preset:
            return
        self._colors = {k: v.upper() for k, v in preset.items()}
        self._refresh_swatches()

    @staticmethod
    def _mix(c1: str, c2: str, t: float) -> str:
        """Linear color blend c1 -> c2 with factor t (0..1)."""
        a = QColor(c1)
        b = QColor(c2)
        r = int(a.red() + (b.red() - a.red()) * t)
        g = int(a.green() + (b.green() - a.green()) * t)
        bl = int(a.blue() + (b.blue() - a.blue()) * t)
        return QColor(r, g, bl).name().upper()

    def _generate_palette(self):
        """Generate a coherent light palette around a curated accent color."""
        accents = [
            "#0969DA",  # blue
            "#0EA5A5",  # teal
            "#2F855A",  # green
            "#B45309",  # amber
            "#7C3AED",  # violet
            "#BE185D",  # rose
            "#2563EB",  # indigo
            "#0F766E",  # emerald-teal
        ]
        accent = random.choice(accents)

        self._colors = {
            "accent": accent,
            "surface_bg": "#FFFFFF",
            "text_primary": "#1F2328",
            "text_muted": "#656D76",
            "base_bg": self._mix(accent, "#FFFFFF", 0.94),
            "border": self._mix(accent, "#D0D7DE", 0.86),
            "selection_bg": self._mix(accent, "#FFFFFF", 0.80),
            "button_bg": self._mix(accent, "#EAEEF2", 0.86),
        }
        self._refresh_swatches()

    def _save_and_apply(self):
        cfg = load_config()
        cfg["light_theme_colors"] = dict(self._colors)
        cfg["auto_discover_dbs"] = bool(self.chk_auto_discover.isChecked())
        save_config(cfg)
        self.theme_colors_changed.emit(dict(self._colors))
        QMessageBox.information(self, "Saved", "Light mode colors saved and applied.")

    def _scan_now(self):
        if self._scan_thread and self._scan_thread.isRunning():
            return
        self.lbl_scan_status.setText("Scanning...")
        self._scan_thread = _DbScanThread()
        self._scan_thread.done.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self, ok: bool, message: str):
        if ok:
            self.lbl_scan_status.setText(message)
            QMessageBox.information(self, "Scan Complete", message)
        else:
            self.lbl_scan_status.setText("Scan failed.")
            QMessageBox.warning(self, "Scan Error", message)
