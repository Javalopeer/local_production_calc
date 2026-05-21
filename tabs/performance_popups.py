# -*- coding: utf-8 -*-
"""
End-of-day performance popup dialogs.

Two dialogs:
  1. SuccessPopup    — congratulations + daily summary (can be closed freely)
  2. JustificationPopup — encouragement + daily summary + required text input
                          (cannot be closed until justification is submitted)
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QMessageBox, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


def _summary_text(metrics: dict, fecha: str) -> str:
    """Build a human-readable daily summary from metrics dict."""
    lines = []
    lines.append(f"Date: {fecha}")
    lines.append("")
    lines.append(f"Production:  {metrics['production_pct']:.2f}%")
    if metrics["downtime_pct"] > 0:
        lines.append(f"   Cases:        {metrics['cases_pct']:.2f}%")
        lines.append(f"   Downtime:  {metrics['downtime_pct']:.2f}%")
    target = metrics.get("ue_target")
    target_suffix = f"  (target: {target:.2f})" if target else ""
    lines.append(f"Equivalent Units:  {metrics['equivalent_units']:.2f}{target_suffix}")
    if metrics["downtime_ue"] > 0:
        lines.append(f"   Cases:        {metrics['cases_ue']:.2f}")
        lines.append(f"   Downtime:  {metrics['downtime_ue']:.2f}")
    lines.append(f"Total Cases:  {metrics['total_cases']}")
    if metrics["total_downtime_min"] > 0:
        lines.append(f"Total Downtime:  {metrics['total_downtime_min']:.0f} min")
    return "\n".join(lines)


class SuccessPopup(QDialog):
    """Shown when the designer meets the daily target (production ≥95% or UE ≥ effective target)."""

    def __init__(self, metrics: dict, fecha: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Daily Target Reached!")
        self.setMinimumWidth(420)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Congratulations header
        header = QLabel("🎉  Congratulations!")
        header.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        msg = QLabel("You've reached your daily production target.\nGreat job — keep it up!")
        msg.setFont(QFont("Segoe UI", 11))
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        # Summary frame
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet("""
            QFrame {
                background-color: #1B5E20;
                border-radius: 8px;
                padding: 12px;
            }
            QLabel {
                color: #C8E6C9;
                font-family: Consolas, monospace;
                font-size: 12px;
            }
        """)
        frame_layout = QVBoxLayout(frame)
        summary_lbl = QLabel(_summary_text(metrics, fecha))
        summary_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        frame_layout.addWidget(summary_lbl)
        layout.addWidget(frame)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(120)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #388E3C; }
        """)
        close_btn.clicked.connect(self.accept)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)


class JustificationPopup(QDialog):
    """Shown when the designer does NOT meet the target.
    Cannot be closed until a justification is typed and submitted."""

    def __init__(self, metrics: dict, fecha: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("End of Day — Justification Required")
        self.setMinimumWidth(480)
        self.setMinimumHeight(440)
        self.justification_text = ""
        # Block closing without submitting
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowType.WindowContextHelpButtonHint
            & ~Qt.WindowType.WindowCloseButtonHint
        )
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Encouragement header
        header = QLabel("💪  Great effort today!")
        header.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        msg = QLabel(
            "You didn't quite reach today's target — but that's okay!\n"
            "Stay consistent and you'll get there. Don't lose the rhythm."
        )
        msg.setFont(QFont("Segoe UI", 11))
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        # Summary frame
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet("""
            QFrame {
                background-color: #B71C1C;
                border-radius: 8px;
                padding: 12px;
            }
            QLabel {
                color: #FFCDD2;
                font-family: Consolas, monospace;
                font-size: 12px;
            }
        """)
        frame_layout = QVBoxLayout(frame)
        summary_lbl = QLabel(_summary_text(metrics, fecha))
        summary_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        frame_layout.addWidget(summary_lbl)
        layout.addWidget(frame)

        # Justification input
        input_label = QLabel("Please explain why the target was not met today:")
        input_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        layout.addWidget(input_label)

        self._text_edit = QTextEdit()
        self._text_edit.setPlaceholderText(
            "Write your justification here... (minimum 10 characters)"
        )
        self._text_edit.setMinimumHeight(80)
        layout.addWidget(self._text_edit)

        # Submit button
        self._submit_btn = QPushButton("Submit Justification")
        self._submit_btn.setFixedWidth(200)
        self._submit_btn.setStyleSheet("""
            QPushButton {
                background-color: #E65100;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #BF360C; }
        """)
        self._submit_btn.clicked.connect(self._on_submit)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self._submit_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def _on_submit(self):
        text = self._text_edit.toPlainText().strip()
        if len(text) < 10:
            QMessageBox.warning(
                self, "Too short",
                "Please write at least 10 characters explaining the situation."
            )
            return
        self.justification_text = text
        self.accept()

    def reject(self):
        """Override reject to prevent closing with Escape or X button."""
        # Do nothing — force the user to submit
        pass

    def closeEvent(self, event):
        """Prevent closing the dialog via Alt+F4 or window manager."""
        event.ignore()
