# -*- coding: utf-8 -*-
"""Modal dialog to edit an existing downtime row.

Replaces the previous inline edit mode (which reused the top input row) with
a proper dialog exposing every editable field at once: start, end, reason,
case-id (when applicable), and free-text detail.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QTimeEdit, QComboBox, QLineEdit, QPlainTextEdit, QDialogButtonBox,
)


class DowntimeEditDialog(QDialog):
    """Edit a downtime row. Returns the new values via `result_values()`."""

    def __init__(self, *, start: str, end: str, reason: str,
                 detalle: str, case_id: str,
                 reasons: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Downtime")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        # Start time
        self.start_edit = QTimeEdit()
        self.start_edit.setDisplayFormat("HH:mm")
        self.start_edit.setTime(QTime.fromString(start, "HH:mm"))
        form.addRow("Start:", self.start_edit)

        # End time — guarded against going below start
        self.end_edit = QTimeEdit()
        self.end_edit.setDisplayFormat("HH:mm")
        self.end_edit.setTime(QTime.fromString(end, "HH:mm"))
        self.end_edit.setMinimumTime(self.start_edit.time())
        self.start_edit.timeChanged.connect(self._on_start_changed)
        self.end_edit.timeChanged.connect(self._on_end_changed)
        form.addRow("End:", self.end_edit)

        # Reason
        self.reason_combo = QComboBox()
        self.reason_combo.addItems(reasons)
        idx = self.reason_combo.findText(reason)
        if idx >= 0:
            self.reason_combo.setCurrentIndex(idx)
        self.reason_combo.currentTextChanged.connect(self._on_reason_changed)
        form.addRow("Reason:", self.reason_combo)

        # Case ID — only meaningful for Multitreatment, but keep visible always
        self.case_id_edit = QLineEdit(case_id or "")
        self.case_id_edit.setPlaceholderText("Required for Multitreatment")
        form.addRow("Case ID:", self.case_id_edit)

        # Detail — free text
        self.detail_edit = QPlainTextEdit(detalle or "")
        self.detail_edit.setPlaceholderText("Additional context (optional)")
        self.detail_edit.setMinimumHeight(80)
        form.addRow("Detail:", self.detail_edit)

        layout.addLayout(form)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Initial state for case_id field
        self._on_reason_changed(self.reason_combo.currentText())

    # ── time guards ────────────────────────────────────────────────────────
    def _on_start_changed(self, t: QTime):
        self.end_edit.setMinimumTime(t)
        if self.end_edit.time() < t:
            self.end_edit.setTime(t)

    def _on_end_changed(self, t: QTime):
        start = self.start_edit.time()
        if t < start:
            self.end_edit.blockSignals(True)
            self.end_edit.setTime(start)
            self.end_edit.blockSignals(False)

    def _on_reason_changed(self, reason: str):
        needs_case_id = (reason or "").strip().lower() == "multitreatment"
        self.case_id_edit.setEnabled(needs_case_id)
        if not needs_case_id:
            self.case_id_edit.clear()

    # ── result accessor ────────────────────────────────────────────────────
    def result_values(self) -> dict:
        return {
            "start": self.start_edit.time().toString("HH:mm"),
            "end": self.end_edit.time().toString("HH:mm"),
            "start_mins": (self.start_edit.time().hour() * 60
                           + self.start_edit.time().minute()),
            "end_mins": (self.end_edit.time().hour() * 60
                         + self.end_edit.time().minute()),
            "reason": self.reason_combo.currentText(),
            "case_id": self.case_id_edit.text().strip(),
            "detail": self.detail_edit.toPlainText().strip(),
        }
