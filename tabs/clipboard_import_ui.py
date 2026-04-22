"""
Shared clipboard import UI helpers for Register and OT tabs.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton
from sync.clipboard_import import parse_clipboard


def get_clipboard_case_data(standards: dict) -> dict:
    """Parse clipboard and return detected case fields."""
    return parse_clipboard(standards)


def has_detected_case_fields(data: dict) -> bool:
    """Return True if at least one core case field was detected."""
    return any(data.get(k) for k in ("case_id", "region", "tipo", "doctor"))


def show_import_confirmation(parent, data: dict) -> bool:
    """Show import confirmation dialog. Returns True when user confirms."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Import from Clipboard")
    dlg.setMinimumWidth(300)
    layout = QVBoxLayout(dlg)
    layout.setSpacing(10)

    header = QLabel("Import this case?")
    header.setStyleSheet("font-weight: bold; font-size: 13px;")
    layout.addWidget(header)

    rows = [
        ("Case ID", data.get("case_id", "-")),
        ("Region", data.get("region", "-")),
        ("Type", data.get("tipo", "-")),
        ("Doctor", data.get("doctor", "-")),
    ]
    for label_text, value in rows:
        row_lbl = QLabel(f"<b>{label_text}:</b>  {value}")
        row_lbl.setWordWrap(True)
        layout.addWidget(row_lbl)

    btn_layout = QHBoxLayout()
    btn_layout.addStretch()
    btn_cancel = QPushButton("Cancel")
    btn_import = QPushButton("Import")
    btn_import.setDefault(True)
    btn_import.setStyleSheet(
        "background-color: #1a5c2a; color: #7ec890; font-weight: bold;"
    )
    btn_layout.addWidget(btn_cancel)
    btn_layout.addWidget(btn_import)
    layout.addLayout(btn_layout)

    btn_cancel.clicked.connect(dlg.reject)
    btn_import.clicked.connect(dlg.accept)

    return dlg.exec() == QDialog.DialogCode.Accepted


def build_import_summary(imported_case_id: str | None, imported_region: str | None, imported_type: str | None) -> str:
    """Build concise import summary text."""
    summary_parts = [p for p in (imported_case_id, imported_region, imported_type) if p]
    return " | ".join(summary_parts) if summary_parts else "Case imported"


def get_import_not_detected_message(module_name: str) -> str:
    """Return module-specific 'not detected' feedback text."""
    mod = (module_name or "").strip().lower()
    if mod == "ot":
        return (
            "Nothing detected in clipboard.\n"
            "On the case page: press Ctrl+A then Ctrl+C, then try again."
        )
    return "Nothing detected in clipboard.\nPress Ctrl+A, Ctrl+C on the case page, then retry."


def get_import_success_message(summary: str, module_name: str) -> str:
    """Return module-specific success feedback text."""
    mod = (module_name or "").strip().lower()
    if mod == "ot":
        return f"Imported: {summary}\nClick Calculate."
    return f"Imported: {summary} - Click Calculate."


def get_import_reminder_message() -> str:
    """Reminder shown after clipboard import."""
    return (
        "Verify if the case is Stage RX or Bite Sync.\n"
        "Import currently does not auto-detect this."
    )


def apply_imported_case_data(
    data: dict,
    *,
    case_id_widget,
    region_widget,
    type_widget,
    doctor_widget,
    refresh_case_types_fn,
) -> tuple[str | None, str | None, str | None]:
    """
    Apply parsed clipboard data to form widgets.

    Returns (imported_case_id, imported_region, imported_type).
    """
    imported_case_id = None
    imported_region = None
    imported_type = None

    if data.get("case_id"):
        case_id_widget.setText(data["case_id"])
        imported_case_id = data["case_id"]

    if data.get("region"):
        idx = region_widget.findText(data["region"])
        if idx >= 0:
            region_widget.blockSignals(True)
            region_widget.setCurrentIndex(idx)
            region_widget.blockSignals(False)
            refresh_case_types_fn()
            imported_region = data["region"]

    if data.get("tipo"):
        idx = type_widget.findText(data["tipo"])
        if idx >= 0:
            type_widget.setCurrentIndex(idx)
            imported_type = data["tipo"]

    if data.get("doctor"):
        doctor_widget.setText(data["doctor"])

    return imported_case_id, imported_region, imported_type
