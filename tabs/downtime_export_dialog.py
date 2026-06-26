# -*- coding: utf-8 -*-
"""Plan B downtime export — clipboard-assisted hand-off to the Power Apps form.

When the designer marks a DT as Approved locally, this dialog shows each field
of the downtime with a per-row Copy button so the user can paste it field by
field into the HC Control / DownTimes Power App. Also opens the Power App URL
in the default browser with one click.

This is a stop-gap until proper backend integration (SharePoint Graph /
Dataverse Web API) is available. See plan A in the conversation history.
"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QLineEdit, QPlainTextEdit, QSizePolicy,
)


DEFAULT_POWERAPP_URL = (
    "https://apps.powerapps.com/play/e/default-137b3b98-f315-4025-ae27-3d17e9bf0d66/"
    "a/cdd30f1b-bad8-404c-9d5f-437db51cf0d6"
    "?tenantId=137b3b98-f315-4025-ae27-3d17e9bf0d66"
    "&source=portal"
)


class DowntimeExportDialog(QDialog):
    """Per-field copy helper to ferry an approved DT into the Power App form."""

    def __init__(self, fields: list[tuple[str, str]],
                 powerapp_url: str | None = None,
                 parent=None):
        """`fields` is an ordered list of (label, value) pairs displayed in
        the same order as the Power App form. `powerapp_url` overrides the
        default Power App link."""
        super().__init__(parent)
        self.setWindowTitle("Push approved Downtime → Power App")
        self.setMinimumWidth(520)
        self._url = powerapp_url or DEFAULT_POWERAPP_URL

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        intro = QLabel(
            "This downtime was approved locally. Open the Power App and "
            "click <b>Copy</b> next to each field to paste it into the form."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size: 11px;")
        layout.addWidget(intro)

        open_btn = QPushButton("Open Power App in browser")
        open_btn.setStyleSheet(
            "QPushButton { background: #388BFD; color: white; font-weight: 600; "
            "padding: 6px 12px; border-radius: 4px; border: none; }"
            "QPushButton:hover { background: #1757D4; }"
        )
        open_btn.clicked.connect(self._open_url)
        layout.addWidget(open_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #30363D;")
        layout.addWidget(sep)

        # One row per field — label, read-only input, Copy button
        self._field_widgets: dict[str, QLineEdit | QPlainTextEdit] = {}
        for label, value in fields:
            row = QHBoxLayout()
            row.setSpacing(8)

            lbl = QLabel(label)
            lbl.setFixedWidth(120)
            lbl.setStyleSheet("font-weight: 600; font-size: 11px;")
            row.addWidget(lbl)

            multiline = ("description" in label.lower() or len(value) > 80)
            if multiline:
                edit: QLineEdit | QPlainTextEdit = QPlainTextEdit()
                edit.setPlainText(value)
                edit.setMaximumHeight(70)
                edit.setSizePolicy(QSizePolicy.Policy.Expanding,
                                   QSizePolicy.Policy.Preferred)
            else:
                edit = QLineEdit(value)
            edit.setReadOnly(False)  # allow tweaks before copying
            row.addWidget(edit, 1)

            copy_btn = QPushButton("Copy")
            copy_btn.setFixedWidth(60)
            copy_btn.setStyleSheet(
                "QPushButton { padding: 3px 8px; border-radius: 3px; "
                "border: 1px solid #30363D; }"
                "QPushButton:hover { background: #21262D; color: #E6EDF3; }"
            )
            copy_btn.clicked.connect(
                lambda _checked=False, e=edit, b=copy_btn: self._copy(e, b)
            )
            row.addWidget(copy_btn)

            layout.addLayout(row)
            self._field_widgets[label] = edit

        # Bottom actions
        bottom = QHBoxLayout()
        bottom.addStretch()
        copy_all_btn = QPushButton("Copy all (TAB-separated)")
        copy_all_btn.setToolTip(
            "Copies all fields separated by TAB. Useful if you can paste them "
            "in sequence using the keyboard."
        )
        copy_all_btn.clicked.connect(self._copy_all_tab)
        bottom.addWidget(copy_all_btn)
        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

    # ── handlers ───────────────────────────────────────────────────────────
    def _open_url(self):
        try:
            webbrowser.open(self._url, new=2)
        except Exception:
            pass

    def _copy(self, edit, btn):
        text = (edit.toPlainText() if isinstance(edit, QPlainTextEdit)
                else edit.text())
        QGuiApplication.clipboard().setText(text)
        btn.setText("Copied")
        btn.setStyleSheet(
            "QPushButton { padding: 3px 8px; border-radius: 3px; "
            "border: 1px solid #238636; background: #1F6F2C; color: white; }"
        )
        # revert visual after a beat
        from PySide6.QtCore import QTimer
        QTimer.singleShot(900, lambda: self._reset_btn(btn))

    @staticmethod
    def _reset_btn(btn):
        btn.setText("Copy")
        btn.setStyleSheet(
            "QPushButton { padding: 3px 8px; border-radius: 3px; "
            "border: 1px solid #30363D; }"
            "QPushButton:hover { background: #21262D; color: #E6EDF3; }"
        )

    def _copy_all_tab(self):
        values: list[str] = []
        for w in self._field_widgets.values():
            v = w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text()
            values.append(v)
        QGuiApplication.clipboard().setText("\t".join(values))


def build_fields_from_dt(designer: str, fecha: str, reason: str,
                         start: str, end: str,
                         detalle: str = "",
                         supervisor: str = "",
                         event: str = "") -> list[tuple[str, str]]:
    """Build the ordered field list shown in the Power App export dialog.

    Employee, Supervisor and Reason are intentionally omitted — the user
    fills those inside the Power App itself. The local `reason` value
    feeds the Event field.
    """
    return [
        ("Day impacted", fecha),
        ("Event", event or reason),
        ("Start Time", start),
        ("End Time", end),
        ("Event Description", detalle),
    ]
