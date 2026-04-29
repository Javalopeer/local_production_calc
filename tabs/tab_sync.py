import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QDateEdit, QFileDialog, QGroupBox,
    QFormLayout, QTextEdit, QMessageBox, QDialog, QDialogButtonBox,
)
from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QSizePolicy

_TRANSIENT_KEYWORDS = (
    "permissionerror", "locked", "cannot access", "winerror",
    "timed out", "timeout", "network", "connection reset",
    "remote end closed", "odmpath", "onedrive",
)


def _is_transient_error(msg: str) -> bool:
    m = msg.lower()
    return any(k in m for k in _TRANSIENT_KEYWORDS)

try:
    from sync.app_config import load_config, save_config
    from sync.sharepoint_sync import (
        export_to_sharepoint,
        export_all_missing_to_sharepoint,
        audit_dashboard_vs_summaries,
        rebuild_historical_dashboards,
    )
    _SYNC_AVAILABLE = True
except Exception as _e:
    _SYNC_AVAILABLE = False
    _SYNC_ERROR = str(_e)


class _ExportThread(QThread):
    """Run export_to_sharepoint in background with up to 3 retries on transient errors."""
    done = Signal(bool, str)
    status = Signal(str)

    def __init__(self, target_date: str):
        super().__init__()
        self._date = target_date

    def run(self):
        last_ok, last_msg = False, ""
        for attempt in range(3):
            try:
                ok, msg = export_to_sharepoint(self._date)
                if ok or not _is_transient_error(msg) or attempt == 2:
                    self.done.emit(ok, msg)
                    return
                last_ok, last_msg = ok, msg
            except Exception as e:
                last_ok, last_msg = False, str(e)
                if not _is_transient_error(last_msg) or attempt == 2:
                    self.done.emit(last_ok, last_msg)
                    return
            delay = 5 * (attempt + 1)
            self.status.emit(f"Transient error — retrying in {delay}s… (attempt {attempt + 2}/3)")
            time.sleep(delay)
        self.done.emit(last_ok, last_msg)


class _BulkHistoryThread(QThread):
    """Run export_all_missing_to_sharepoint in background with progress updates."""
    progress = Signal(int, int, str)
    done = Signal(bool, str)

    def run(self):
        def _cb(idx, total, message):
            self.progress.emit(idx, total, message)
        try:
            ok, msg = export_all_missing_to_sharepoint(progress_cb=_cb)
            self.done.emit(ok, msg)
        except Exception as e:
            self.done.emit(False, str(e))


class _AuditThread(QThread):
    """Run audit_dashboard_vs_summaries in background."""
    done = Signal(bool, str, dict)

    def run(self):
        try:
            issues, report = audit_dashboard_vs_summaries()
            self.done.emit(len(issues) == 0, report, issues)
        except Exception as e:
            self.done.emit(False, str(e), {})


class _HistoricalRebuildThread(QThread):
    """Run rebuild_historical_dashboards in background."""
    progress = Signal(int, int, str)
    done = Signal(bool, str)

    def __init__(self, dates=None):
        super().__init__()
        self._dates = dates

    def run(self):
        def _cb(idx, total, message):
            self.progress.emit(idx, total, message)
        try:
            ok, msg = rebuild_historical_dashboards(
                dates=self._dates, progress_cb=_cb,
            )
            self.done.emit(ok, msg)
        except Exception as e:
            self.done.emit(False, str(e))


class SyncTab(QWidget):
    def __init__(self):
        super().__init__()
        self._thread = None
        self._busy = False
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
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.designer_name = QLineEdit()
        self.designer_name.setPlaceholderText("Your name as it will appear on reports")
        self.designer_name.setMinimumWidth(420)
        self.designer_name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form.addRow("Designer name:", self.designer_name)

        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.setSpacing(8)
        self.export_folder = QLineEdit()
        self.export_folder.setPlaceholderText("Path to Teams/SharePoint synced folder…")
        self.export_folder.setReadOnly(True)
        self.export_folder.setMinimumWidth(420)
        self.export_folder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.export_folder)
        folder_row.addWidget(browse_btn)
        form.addRow("Export folder:", folder_row)

        self.folder_hint = QLabel("")
        self.folder_hint.setStyleSheet("color: #66bb6a; font-size: 10px;")
        form.addRow("", self.folder_hint)

        save_btn = QPushButton("Save Settings")
        save_btn.setFixedWidth(130)
        save_btn.setFixedHeight(30)
        save_btn.clicked.connect(self._save_settings)
        save_btn.setStyleSheet("QPushButton { border-radius: 4px; padding: 4px 12px; }")
        save_row = QHBoxLayout()
        save_row.setContentsMargins(0, 0, 0, 0)
        save_row.setSpacing(0)
        save_row.addWidget(save_btn)
        save_row.addStretch()
        save_row_widget = QWidget()
        save_row_widget.setLayout(save_row)
        save_row_widget.setMinimumHeight(34)
        form.addRow("", save_row_widget)

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

        self.bulk_btn = QPushButton("  Upload Missing History")
        self.bulk_btn.setFixedHeight(32)
        self.bulk_btn.setToolTip(
            "Uploads daily files for every day in your local database that is missing\n"
            "or corrupt in the shared folder. Valid files are never overwritten."
        )
        self.bulk_btn.setStyleSheet(
            "QPushButton { background: #5E6A75; color: white; font-weight: bold; border-radius: 5px; font-size: 12px; }"
            "QPushButton:hover { background: #485159; }"
            "QPushButton:disabled { background: #555; color: #999; }"
        )
        self.bulk_btn.clicked.connect(self._do_bulk_history)
        exp_layout.addWidget(self.bulk_btn)

        admin_row = QHBoxLayout()
        admin_row.setSpacing(8)

        self.audit_btn = QPushButton("Audit Dashboard History")
        self.audit_btn.setFixedHeight(30)
        self.audit_btn.setToolTip(
            "Compare each dated dashboard snapshot against the per-designer\n"
            "summary files. Reports missing designers, stale values."
        )
        self.audit_btn.setStyleSheet(
            "QPushButton { background: #3A4048; color: #ddd; border-radius: 4px; font-size: 11px; padding: 4px 10px; }"
            "QPushButton:hover { background: #2E343B; }"
            "QPushButton:disabled { background: #444; color: #888; }"
        )
        self.audit_btn.clicked.connect(self._do_audit)
        admin_row.addWidget(self.audit_btn)

        self.rebuild_btn = QPushButton("Rebuild Historical Dashboards")
        self.rebuild_btn.setFixedHeight(30)
        self.rebuild_btn.setToolTip(
            "Regenerate every _Dashboard_YYYY-MM-DD.xlsx snapshot from the per-\n"
            "designer summary files. Live _Dashboard.xlsx is not touched.\n"
            "Recommended: each designer runs 'Upload Missing History' first."
        )
        self.rebuild_btn.setStyleSheet(
            "QPushButton { background: #3A4048; color: #ddd; border-radius: 4px; font-size: 11px; padding: 4px 10px; }"
            "QPushButton:hover { background: #2E343B; }"
            "QPushButton:disabled { background: #444; color: #888; }"
        )
        self.rebuild_btn.clicked.connect(self._do_rebuild_history)
        admin_row.addWidget(self.rebuild_btn)

        admin_row.addStretch()
        exp_layout.addLayout(admin_row)

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
            self.bulk_btn.setEnabled(False)
            self.audit_btn.setEnabled(False)
            self.rebuild_btn.setEnabled(False)
            self._log(f"⚠ Sync module unavailable: {_SYNC_ERROR}", error=True)

        root.addStretch()

    # ── Busy state ────────────────────────────────────────────────────────────

    def is_busy(self) -> bool:
        return self._busy

    def _set_busy(self, busy: bool):
        self._busy = busy
        enabled = not busy and _SYNC_AVAILABLE
        self.export_btn.setEnabled(enabled)
        self.bulk_btn.setEnabled(enabled)
        self.audit_btn.setEnabled(enabled)
        self.rebuild_btn.setEnabled(enabled)

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self):
        if not _SYNC_AVAILABLE:
            return
        try:
            cfg = load_config()
            self.designer_name.setText(cfg.get("designer_name", ""))
            folder = cfg.get("export_folder", "")
            self.export_folder.setText(folder)
            if folder:
                self.folder_hint.setText(f"Folder found: {folder}" if __import__('os').path.isdir(folder)
                                         else "Folder not found — please re-select")
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
            save_config(cfg)
            self._log("Settings saved.")
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
        if not _SYNC_AVAILABLE or self._busy:
            return
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
        self._set_busy(True)
        self.export_btn.setText("  Exporting…")
        self._thread = _ExportThread(target_date)
        self._thread.done.connect(self._on_export_done)
        self._thread.status.connect(self._log)
        self._thread.start()

    def _on_export_done(self, ok: bool, msg: str):
        self._set_busy(False)
        self.export_btn.setText("  Export to SharePoint")
        if ok:
            self._log(f"✓ {msg}")
        else:
            self._log(f"✗ {msg}", error=True)
            QMessageBox.critical(self, "Export Error", msg)

    # ── Bulk history upload ───────────────────────────────────────────────────

    def _do_bulk_history(self):
        if not _SYNC_AVAILABLE or self._busy:
            return
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
        resp = QMessageBox.question(
            self, "Upload Missing History",
            "This will scan every day in your local database and upload a daily\n"
            "file for any day that is missing or corrupt in the shared folder.\n\n"
            "Existing valid files will NOT be overwritten.\n\n"
            "The Dashboard will be rebuilt once at the end. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        self._log("Starting bulk history upload…")
        self._set_busy(True)
        self.bulk_btn.setText("  Uploading…")
        self._bulk_thread = _BulkHistoryThread()
        self._bulk_thread.progress.connect(self._on_bulk_progress)
        self._bulk_thread.done.connect(self._on_bulk_done)
        self._bulk_thread.start()

    def _on_bulk_progress(self, idx: int, total: int, message: str):
        self._log(f"[{idx}/{total}] {message}")

    def _on_bulk_done(self, ok: bool, msg: str):
        self._set_busy(False)
        self.bulk_btn.setText("  Upload Missing History")
        if ok:
            self._log("✓ Bulk history upload complete.")
        else:
            self._log("✗ Bulk history upload finished with errors.", error=True)
        self._log(msg)
        self._show_scrollable_report("Upload Missing History", msg)

    # ── Audit / rebuild historical snapshots ─────────────────────────────────

    def _do_audit(self):
        if not _SYNC_AVAILABLE or self._busy:
            return
        self._log("Running audit…")
        self._set_busy(True)
        self.audit_btn.setText("Auditing…")
        self._audit_thread = _AuditThread()
        self._audit_thread.done.connect(self._on_audit_done)
        self._audit_thread.start()

    def _on_audit_done(self, clean: bool, report: str, issues: dict):
        self._set_busy(False)
        self.audit_btn.setText("Audit Dashboard History")
        self._log(report)
        self._last_audit_issues = issues
        self._show_scrollable_report("Audit", report)

    def _show_scrollable_report(self, title: str, text: str):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(720, 560)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text)
        view.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        layout.addWidget(view, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        layout.addWidget(btns)
        dlg.exec()

    def _do_rebuild_history(self):
        if not _SYNC_AVAILABLE:
            return
        self._save_settings()

        folder = self.export_folder.text().strip()
        import os
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Folder not set",
                                "Export folder must be set in Settings first.")
            return

        resp = QMessageBox.question(
            self, "Rebuild Historical Dashboards",
            "This will regenerate every _Dashboard_YYYY-MM-DD.xlsx snapshot in\n"
            "the Dashboards folder from the per-designer summary files.\n\n"
            "Live _Dashboard.xlsx is NOT touched.\n"
            "Existing snapshots are overwritten.\n\n"
            "Recommended: have each designer run 'Upload Missing History'\n"
            "on their own machine first so their summaries are complete.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        self._log("Starting historical dashboard rebuild…")
        self._set_busy(True)
        self.rebuild_btn.setText("Rebuilding…")

        self._hist_thread = _HistoricalRebuildThread(dates=None)
        self._hist_thread.progress.connect(self._on_hist_progress)
        self._hist_thread.done.connect(self._on_hist_done)
        self._hist_thread.start()

    def _on_hist_progress(self, idx: int, total: int, message: str):
        self._log(f"[{idx}/{total}] {message}")

    def _on_hist_done(self, ok: bool, msg: str):
        self._set_busy(False)
        self.rebuild_btn.setText("Rebuild Historical Dashboards")
        if ok:
            self._log("✓ Historical dashboards rebuilt.")
        else:
            self._log("✗ Historical rebuild finished with errors.", error=True)
        self._log(msg)
        self._show_scrollable_report("Rebuild Historical Dashboards", msg)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log(self, msg: str, error: bool = False):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        color = "#ef9a9a" if error else "#b8f0b8"
        self.log.append(f'<span style="color:#888">[{ts}]</span> '
                        f'<span style="color:{color}">{msg}</span>')
