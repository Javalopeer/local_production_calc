from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QDateEdit, QFileDialog, QGroupBox,
    QFormLayout, QTextEdit, QMessageBox
)
from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtGui import QFont

try:
    from sync.app_config import load_config, save_config, save_shared_config
    from sync.sharepoint_sync import export_to_sharepoint
    _SYNC_AVAILABLE = True
except Exception as _e:
    _SYNC_AVAILABLE = False
    _SYNC_ERROR = str(_e)


class _ExportThread(QThread):
    """Run export_to_sharepoint in a background thread so the UI doesn't freeze."""
    done = Signal(bool, str)

    def __init__(self, target_date: str):
        super().__init__()
        self._date = target_date

    def run(self):
        try:
            ok, msg = export_to_sharepoint(self._date)
            self.done.emit(ok, msg)
        except Exception as e:
            self.done.emit(False, str(e))


class SyncTab(QWidget):
    def __init__(self):
        super().__init__()
        self._thread = None
        self._init_ui()
        self._load_config()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(18)

        # Title
        title = QLabel("SharePoint Sync")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #4aa3ff;")
        root.addWidget(title)

        subtitle = QLabel("Export daily production reports to the shared Teams/SharePoint folder.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(subtitle)

        # ── Settings box ────────────────────────────────────────────────────
        settings_box = QGroupBox("Settings")
        settings_box.setStyleSheet("QGroupBox { font-weight: bold; }")
        form = QFormLayout(settings_box)
        form.setContentsMargins(16, 14, 16, 14)
        form.setSpacing(10)

        self.designer_name = QLineEdit()
        self.designer_name.setPlaceholderText("Your name as it will appear on reports")
        form.addRow("Designer name:", self.designer_name)

        folder_row = QHBoxLayout()
        self.export_folder = QLineEdit()
        self.export_folder.setPlaceholderText("Path to Teams/SharePoint synced folder…")
        self.export_folder.setReadOnly(True)
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.export_folder)
        folder_row.addWidget(browse_btn)
        form.addRow("Export folder:", folder_row)

        self.folder_hint = QLabel("")
        self.folder_hint.setStyleSheet("color: #66bb6a; font-size: 10px;")
        form.addRow("", self.folder_hint)

        # Teams Webhook for downtime notifications
        self.webhook_url = QLineEdit()
        self.webhook_url.setPlaceholderText("https://... (Teams Incoming Webhook URL for downtime alerts)")
        form.addRow("Teams Webhook:", self.webhook_url)

        webhook_hint = QLabel("Optional — notifies supervisors in Teams when a downtime is submitted.")
        webhook_hint.setStyleSheet("color: #888; font-size: 10px;")
        form.addRow("", webhook_hint)

        save_btn = QPushButton("Save Settings")
        save_btn.setFixedWidth(130)
        save_btn.clicked.connect(self._save_settings)
        save_btn.setStyleSheet("QPushButton { border-radius: 4px; padding: 4px 12px; }")
        form.addRow("", save_btn)

        root.addWidget(settings_box)

        # ── Export box ──────────────────────────────────────────────────────
        export_box = QGroupBox("Export Report")
        export_box.setStyleSheet("QGroupBox { font-weight: bold; }")
        exp_layout = QVBoxLayout(export_box)
        exp_layout.setContentsMargins(16, 14, 16, 14)
        exp_layout.setSpacing(10)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Export date:"))
        self.export_date = QDateEdit(QDate.currentDate())
        self.export_date.setCalendarPopup(True)
        self.export_date.setDisplayFormat("yyyy-MM-dd")
        self.export_date.setFixedWidth(130)
        date_row.addWidget(self.export_date)

        self.today_btn = QPushButton("Today")
        self.today_btn.setFixedWidth(60)
        self.today_btn.clicked.connect(lambda: self.export_date.setDate(QDate.currentDate()))
        date_row.addWidget(self.today_btn)
        date_row.addStretch()
        exp_layout.addLayout(date_row)

        self.export_btn = QPushButton("  Export to SharePoint")
        self.export_btn.setFixedHeight(36)
        self.export_btn.setStyleSheet(
            "QPushButton { background: #2E75B6; color: white; font-weight: bold; border-radius: 5px; font-size: 13px; }"
            "QPushButton:hover { background: #1F5C9E; }"
            "QPushButton:disabled { background: #555; color: #999; }"
        )
        self.export_btn.clicked.connect(self._do_export)
        exp_layout.addWidget(self.export_btn)

        root.addWidget(export_box)

        # ── Log box ─────────────────────────────────────────────────────────
        log_box = QGroupBox("Status")
        log_box.setStyleSheet("QGroupBox { font-weight: bold; }")
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(12, 10, 12, 10)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(140)
        self.log.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        log_layout.addWidget(self.log)

        root.addWidget(log_box)

        if not _SYNC_AVAILABLE:
            self.export_btn.setEnabled(False)
            self._log(f"⚠ Sync module unavailable: {_SYNC_ERROR}", error=True)

        root.addStretch()

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self):
        if not _SYNC_AVAILABLE:
            return
        try:
            cfg = load_config()
            self.designer_name.setText(cfg.get("designer_name", ""))
            self.webhook_url.setText(cfg.get("teams_webhook", ""))
            folder = cfg.get("export_folder", "")
            self.export_folder.setText(folder)
            if folder:
                self.folder_hint.setText(f"✓ Folder found: {folder}" if __import__('os').path.isdir(folder)
                                         else "⚠ Folder not found — please re-select")
                self.folder_hint.setStyleSheet(
                    "color: #66bb6a; font-size: 10px;" if __import__('os').path.isdir(folder)
                    else "color: #ef9a9a; font-size: 10px;"
                )
        except Exception as e:
            self._log(f"Could not load config: {e}", error=True)

    def _save_settings(self):
        if not _SYNC_AVAILABLE:
            return
        try:
            cfg = load_config()
            cfg["designer_name"] = self.designer_name.text().strip()
            cfg["export_folder"] = self.export_folder.text().strip()
            cfg["teams_webhook"] = self.webhook_url.text().strip()
            save_config(cfg)
            # Also save webhook to shared folder so all team members get it
            if cfg.get("teams_webhook") and cfg.get("export_folder"):
                shared = {"teams_webhook": cfg["teams_webhook"]}
                if save_shared_config(shared):
                    self._log("✓ Settings saved (webhook shared with team).")
                else:
                    self._log("✓ Settings saved (shared config could not be updated).")
            else:
                self._log("✓ Settings saved.")
        except Exception as e:
            self._log(f"Error saving settings: {e}", error=True)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Teams/SharePoint export folder")
        if folder:
            import os
            self.export_folder.setText(folder)
            self.folder_hint.setText(f"✓ {folder}")
            self.folder_hint.setStyleSheet("color: #66bb6a; font-size: 10px;")

    # ── Export ────────────────────────────────────────────────────────────────

    def _do_export(self):
        if not _SYNC_AVAILABLE:
            return

        # Auto-save settings first
        self._save_settings()

        folder = self.export_folder.text().strip()
        if not folder:
            QMessageBox.warning(self, "No folder set",
                                "Please set the export folder in Settings first.")
            return

        import os
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Folder not found",
                                f"The export folder does not exist:\n{folder}")
            return

        target_date = self.export_date.date().toString("yyyy-MM-dd")
        self._log(f"Exporting {target_date}…")
        self.export_btn.setEnabled(False)
        self.export_btn.setText("  Exporting…")

        self._thread = _ExportThread(target_date)
        self._thread.done.connect(self._on_export_done)
        self._thread.start()

    def _on_export_done(self, ok: bool, msg: str):
        self.export_btn.setEnabled(True)
        self.export_btn.setText("  Export to SharePoint")
        if ok:
            self._log(f"✓ {msg}")
        else:
            self._log(f"✗ {msg}", error=True)
            QMessageBox.critical(self, "Export Error", msg)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log(self, msg: str, error: bool = False):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        color = "#ef9a9a" if error else "#b8f0b8"
        self.log.append(f'<span style="color:#888">[{ts}]</span> '
                        f'<span style="color:{color}">{msg}</span>')
