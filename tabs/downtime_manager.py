import os
import threading
import uuid

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTimeEdit, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QComboBox, QMessageBox,
    QHeaderView, QDialog, QTextEdit, QDialogButtonBox, QSizePolicy,
    QApplication,
)
from PySide6.QtCore import QTime, QDate, QTimer, Qt, Signal
from PySide6.QtGui import QColor
from db.database import get_connection
from .theme_table_utils import CLR_FG_LIGHT
from sync.app_config import load_config
from sync.app_logger import log_event
from datetime import datetime
try:
    from sync.downtime_approval import (
        export_pending_downtimes,
        poll_and_process_responses,
        get_approval_path,
        export_approval_history,
    )
    _APPROVAL_OK = True
except Exception as _approval_err:
    print(f"[downtime_manager] Approval module unavailable: {_approval_err}")
    _APPROVAL_OK = False

# Local mirror of the pending-status string.
STATUS_PENDING_LOCAL = "pending"
STATUS_APPROVED_LOCAL = "approved"
STATUS_REJECTED_LOCAL = "rejected"


# ── Sync-state helpers ───────────────────────────────────────────────────────
# Flip the per-row sync flags when a destination confirms receipt. Idempotent —
# safe to call from any thread, but keep them tiny (single UPDATE) so the lock
# window stays small under WAL.

def _mark_excel_synced(dt_id: int) -> None:
    if not dt_id:
        return
    try:
        conn = get_connection()
        conn.execute(
            "UPDATE downtimes SET synced_to_excel = 1, last_sync_error = '' "
            "WHERE id = ?",
            (int(dt_id),),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log_event("downtime_manager",
                  f"_mark_excel_synced({dt_id}) failed: {exc}",
                  level="WARN")


def _mark_teams_synced(dt_id: int) -> None:
    if not dt_id:
        return
    try:
        conn = get_connection()
        conn.execute(
            "UPDATE downtimes SET synced_to_teams = 1 WHERE id = ?",
            (int(dt_id),),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log_event("downtime_manager",
                  f"_mark_teams_synced({dt_id}) failed: {exc}",
                  level="WARN")


def _bump_sync_attempt(dt_id: int, err_msg: str = "") -> None:
    """Increment sync_attempts and stash the last error for diagnostics."""
    if not dt_id:
        return
    try:
        conn = get_connection()
        conn.execute(
            "UPDATE downtimes "
            "SET sync_attempts = COALESCE(sync_attempts, 0) + 1, "
            "    last_sync_error = ? "
            "WHERE id = ?",
            (str(err_msg)[:500], int(dt_id)),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log_event("downtime_manager",
                  f"_bump_sync_attempt({dt_id}) failed: {exc}",
                  level="WARN")


class DowntimeManager(QWidget):
    _poll_result_ready = Signal(int)

    def __init__(self, parent=None, on_update_callback=None):
        super().__init__(parent)
        self._poll_result_ready.connect(self._handle_poll_result)
        self.on_update_callback = on_update_callback
        self.delete_mode = False
        self.edit_mode = False
        self.current_edit_row = -1
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        self._retry_in_progress = False
        self.init_ui()
        self.load_downtimes()
        self._start_poll_timer()
        self._start_retry_timer()

    def _start_poll_timer(self):
        """Poll the approval Excel every 15 seconds for supervisor responses."""
        if not _APPROVAL_OK:
            return
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(15_000)  # 15 seconds
        self._poll_timer.timeout.connect(self._poll_approvals)
        self._poll_timer.timeout.connect(self.load_downtimes)
        self._poll_timer.start()
        # Stop the timer if the widget is destroyed so it can't fire on a
        # deleted C++ object (which would crash the app on shutdown).
        self.destroyed.connect(self._stop_poll_timer)

    def _stop_poll_timer(self, *_args):
        """Idempotent timer stop. Called on widget destruction and on close."""
        timer = getattr(self, "_poll_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
            self._poll_timer = None

    # ── Retry worker for unsynced downtimes ─────────────────────────────────
    # Every 60 s, scan for rows where synced_to_excel=0 OR (status=pending AND
    # synced_to_teams=0) and retry the missing destination. Silent — the user
    # only notices via the per-row status icon.
    def _start_retry_timer(self):
        if not _APPROVAL_OK:
            return
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(60_000)  # 60 seconds
        self._retry_timer.timeout.connect(self._retry_unsynced_downtimes)
        self._retry_timer.start()
        self.destroyed.connect(self._stop_retry_timer)
        # Kick once shortly after startup to clear any backlog from prior session
        QTimer.singleShot(5_000, self._retry_unsynced_downtimes)

    def _stop_retry_timer(self, *_args):
        timer = getattr(self, "_retry_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
            self._retry_timer = None

    def _retry_unsynced_downtimes(self):
        """Find pending unsynced downtimes and retry their failed destinations.

        Runs in a background thread so the UI never blocks. Reentrancy-guarded
        with `_retry_in_progress` so back-to-back ticks don't pile up.
        """
        if self._retry_in_progress:
            return
        self._retry_in_progress = True

        def _run():
            try:
                self._do_retry_unsynced()
            except Exception as exc:
                log_event("downtime_manager",
                          f"retry worker crashed: {exc}",
                          level="WARN")
            finally:
                self._retry_in_progress = False

        threading.Thread(target=_run, daemon=True).start()

    def _do_retry_unsynced(self):
        """Retry the Excel export when needed.

        Triggers an export when EITHER:
          - some row has synced_to_excel=0 (insert/edit/status-change failed
            to propagate), OR
          - it has been more than _FORCE_RESYNC_SECONDS since the last export
            (catches deletions that failed to propagate, since a deleted row
            leaves no flag behind to retry from).
        """
        if not _APPROVAL_OK:
            return
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM downtimes WHERE synced_to_excel = 0 LIMIT 1"
            )
            has_unsynced = cur.fetchone() is not None
            conn.close()
        except Exception as exc:
            print(f"[downtime_manager] retry: query failed: {exc}")
            return

        import time as _time
        now = _time.time()
        last = getattr(self, "_last_force_resync_ts", 0.0)
        force_due = (now - last) >= self._FORCE_RESYNC_SECONDS

        if not has_unsynced and not force_due:
            return

        cfg = load_config()
        designer = cfg.get("designer_name", "")
        try:
            ok = export_pending_downtimes(designer)
            if ok:
                self._last_force_resync_ts = now
            else:
                log_event("downtime_manager",
                          "retry export returned False", level="WARN")
        except Exception as exc:
            log_event("downtime_manager",
                      f"retry export crashed: {exc}", level="WARN")
            return

        try:
            QTimer.singleShot(0, self.load_downtimes)
        except Exception:
            pass

    _FORCE_RESYNC_SECONDS = 300  # 5-minute periodic full resync as a safety net

    def closeEvent(self, event):
        self._stop_poll_timer()
        self._stop_retry_timer()
        super().closeEvent(event)

    def _handle_poll_result(self, updated: int):
        """Handle poll results on the main thread (via signal)."""
        if updated > 0:
            self.load_downtimes()
            if self.on_update_callback:
                self.on_update_callback()
            try:
                from sync.sharepoint_sync import export_to_sharepoint
                threading.Thread(target=export_to_sharepoint, daemon=True).start()
            except Exception as exc:
                log_event("downtime_manager", f"post-approval sharepoint export trigger failed: {exc}", level="WARN")

    def _poll_approvals(self, silent: bool = True):
        """Poll the shared approval Excel for supervisor responses."""
        if not _APPROVAL_OK:
            if not silent:
                QMessageBox.warning(self, "Unavailable",
                    "Approval module is not available (openpyxl missing or export folder not configured).")
            return
        cfg = load_config()
        designer = cfg.get("designer_name", "")

        def _bg_poll():
            try:
                return poll_and_process_responses(designer)
            except Exception as exc:
                print(f"[downtime_manager] Poll error: {exc}")
                return 0

        if silent:
            def _run():
                result = _bg_poll()
                if result > 0:
                    self._poll_result_ready.emit(result)
            threading.Thread(target=_run, daemon=True).start()
        else:
            updated = _bg_poll()
            if updated > 0:
                self._handle_poll_result(updated)
                QMessageBox.information(self, "Approvals",
                    f"{updated} downtime(s) updated from the approval file.")
            else:
                details = self._approval_file_info(designer)
                QMessageBox.information(self, "Approvals",
                    f"No new approvals or rejections found.\n\n{details}")

    def _approval_file_info(self, designer: str) -> str:
        """Return a short diagnostic string about the approval file."""
        path = get_approval_path() if _APPROVAL_OK else None
        if not path or not os.path.exists(path):
            return "Approval file not found."
        try:
            mtime = os.path.getmtime(path)
            mod_dt = datetime.fromtimestamp(mtime)
            age = datetime.now() - mod_dt
            mins = int(age.total_seconds() // 60)
            secs = int(age.total_seconds() % 60)
            return (f"File last modified: {mod_dt.strftime('%H:%M:%S')} "
                    f"({mins}m {secs}s ago).\n"
                    "If the supervisor already responded, OneDrive may not have synced yet.")
        except Exception:
            log_event("downtime_manager", "approval file info read failed", level="WARN")
            return ""

    def set_date(self, date_str: str):
        """Called by RegisterTab when the date picker changes."""
        self.current_date = date_str
        self.load_downtimes()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        # Input section
        input_layout = QHBoxLayout()
        input_layout.setSpacing(6)

        input_layout.addWidget(QLabel("Start:"))
        self.downtime_start = QTimeEdit()
        self.downtime_start.setDisplayFormat("HH:mm")
        self.downtime_start.setTime(QTime.currentTime())
        self.downtime_start.setMinimumWidth(90)
        input_layout.addWidget(self.downtime_start)

        input_layout.addWidget(QLabel("End:"))
        self.downtime_end = QTimeEdit()
        self.downtime_end.setDisplayFormat("HH:mm")
        self.downtime_end.setTime(QTime.currentTime())
        self.downtime_end.setMinimumWidth(90)
        # End cannot be earlier than Start (blocks typing + scroll below Start)
        self.downtime_end.setMinimumTime(self.downtime_start.time())
        self.downtime_start.timeChanged.connect(self._on_start_time_changed)
        self.downtime_end.timeChanged.connect(self._on_end_time_changed)
        input_layout.addWidget(self.downtime_end)

        input_layout.addWidget(QLabel("Reason:"))
        self.downtime_reason = QComboBox()
        self.downtime_reason.addItems([
            "Anatomy Reprocess",
            "Breastfeeding Leave",
            "CMS Down",
            "Computer Issues",
            "Consultation",
            "Corporate Event",
            "CSS' Feedback",
            "CSS Revision",
            "Customer Meeting",
            "Evacuation Drill",
            "Extend Check emails allowances",
            "Extend Master Control allowances",
            "Extended Consultation",
            "Extended Weekly Huddle",
            "Gemba & listening Events",
            "Hours of Paid Leave",
            "Low Rate Feedback",
            "Medical and/or legal appointment",
            "MFG Feedbacks",
            "Multitreatment",
            "No_Cases",
            "Non-planned meetings",
            "One on One",
            "Other Meetings",
            "Project",
            "Quality Feedback",
            "Re Training ODB",
            "Regulatory Audit",
            "Relocation (Hardware/Software)",
            "Relocation (Internet/Electricity Issues)",
            "Rev Guidelines",
            "Site (Internet/Electricity Issues)",
            "Software",
            "Spark Town Hall",
            "Survey",
            "Team Meeting",
            "Training",
            "Translation",
            "WorkDay Courses"

        ])
        self.downtime_reason.setMinimumWidth(180)
        self.downtime_reason.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.downtime_reason.setStyleSheet("""
            QComboBox { padding-right: 26px; }
            QComboBox::drop-down {
                width: 22px;
                border-left: 1px solid rgba(130, 130, 130, 0.35);
            }
        """)
        input_layout.addWidget(self.downtime_reason)
        input_layout.setStretch(input_layout.count() - 1, 1)

        add_btn = QPushButton("Add")
        add_btn.setMaximumWidth(75)
        add_btn.setMinimumHeight(23)
        add_btn.clicked.connect(self.add_downtime)
        input_layout.addWidget(add_btn)

        input_layout.addStretch()
        main_layout.addLayout(input_layout)

        # Table
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(False)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Start", "End", "Dur.(min)", "Reason", "Status",
            "Sync", "Actions",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellClicked.connect(self.on_cell_clicked)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setStyleSheet("""
            QTableWidget::item:selected {
                background-color: transparent;
            }
        """)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 52)
        self.table.setColumnWidth(1, 52)
        self.table.setColumnWidth(2, 72)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 44)
        self.table.setColumnWidth(6, 220)
        self.table.setMinimumHeight(180)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(self.table)

        # Buttons layout - centered
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setMaximumWidth(85)
        self.delete_btn.clicked.connect(self.delete_downtime)
        buttons_layout.addWidget(self.delete_btn)
        
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setMaximumWidth(85)
        self.edit_btn.clicked.connect(self.edit_downtime)
        buttons_layout.addWidget(self.edit_btn)

        check_btn = QPushButton("Check Approvals")
        check_btn.setMaximumWidth(120)
        check_btn.setToolTip("Manually check the shared approval file for supervisor responses")
        check_btn.clicked.connect(lambda: self._poll_approvals(silent=False))
        buttons_layout.addWidget(check_btn)

        buttons_layout.addStretch()
        main_layout.addLayout(buttons_layout)

        self.setLayout(main_layout)
        self._apply_table_layout_mode()

    def add_downtime(self):
        start = self.downtime_start.time().toString("HH:mm")
        end = self.downtime_end.time().toString("HH:mm")
        reason = self.downtime_reason.currentText()

        # Calculate duration
        start_mins = self.downtime_start.time().hour() * 60 + self.downtime_start.time().minute()
        end_mins = self.downtime_end.time().hour() * 60 + self.downtime_end.time().minute()
        duration = end_mins - start_mins
        if duration < 0:
            duration += 24 * 60

        err = self._validate_downtime(start_mins, end_mins, reason)
        if err:
            QMessageBox.warning(self, "Invalid downtime", err)
            return

        detalle = self._get_downtime_detail(reason)
        if detalle is None:
            return  # Cancelado por el usuario

        # New flow: every DT starts in pending. The user pastes it to Teams
        # via the Copy button, the supervisor reacts, and the user marks it
        # Approved or Rejected manually inside the app. No auto-approval.
        client_uid = str(uuid.uuid4())
        # synced_to_teams is repurposed as "manually marked by user" (always 1
        # to keep the retry worker out of the Teams loop, which no longer exists).
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO downtimes
                (fecha, hora_inicio, hora_fin, razon, duracion, status, detalle,
                 client_uid, synced_to_excel, synced_to_teams)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
        """, (
            self.current_date, start, end, reason, duration,
            STATUS_PENDING_LOCAL, detalle, client_uid,
        ))
        dt_id = cursor.lastrowid
        conn.commit()
        conn.close()
        self.load_downtimes()
        self.downtime_start.setTime(QTime.currentTime())
        self.downtime_end.setTime(QTime.currentTime())

        # Kick off the Excel export in the background. The retry worker keeps
        # trying every 60 s until synced_to_excel flips to 1, so a transient
        # OneDrive lock here is NOT data loss.
        if _APPROVAL_OK:
            cfg = load_config()
            designer = cfg.get("designer_name", "")
            def _bg_first_sync():
                try:
                    ok = export_pending_downtimes(designer)
                    if not ok:
                        _bump_sync_attempt(dt_id, "first export returned False")
                except Exception as exc:
                    log_event("downtime_manager",
                              f"first sync failed for DT #{dt_id}: {exc}",
                              level="WARN")
                    _bump_sync_attempt(dt_id, str(exc))
            threading.Thread(target=_bg_first_sync, daemon=True).start()

        if self.on_update_callback:
            self.on_update_callback()

    def _get_downtime_detail(self, reason: str) -> str | None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Detalle")
        needs_case_id = reason.strip().lower() == "multitreatment"
        dialog.setMinimumWidth(360)
        dialog.setMinimumHeight(170 if not needs_case_id else 215)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        case_id_input = None
        if needs_case_id:
            case_label = QLabel("Case ID (requerido para Multitreatment):")
            case_label.setStyleSheet("font-size: 11px;")
            layout.addWidget(case_label)
            case_id_input = QLineEdit()
            case_id_input.setPlaceholderText("Ej: 123456789")
            layout.addWidget(case_id_input)
        label = QLabel("Describe el motivo del downtime:")
        label.setStyleSheet("font-size: 11px;")
        layout.addWidget(label)
        text_edit = QTextEdit()
        text_edit.setPlaceholderText("Ej: 'Sistema CMS caído por mantenimiento'")
        text_edit.setMaximumHeight(60)
        layout.addWidget(text_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() == QDialog.Accepted:
            detail = text_edit.toPlainText().strip()
            if needs_case_id:
                case_id = (case_id_input.text().strip() if case_id_input else "")
                if not case_id:
                    QMessageBox.warning(self, "Case ID requerido", "Para Multitreatment debes ingresar Case ID.")
                    return None
                if detail:
                    return f"Case ID: {case_id} | {detail}"
                return f"Case ID: {case_id}"
            return detail
        return None

    def _is_light_mode(self) -> bool:
        """Return last theme state pushed via update_theme_labels.

        Substring matching on `app.styleSheet()` breaks when the user
        customizes the light palette (the default `#F6F8FA` is replaced),
        so we cache the flag instead.
        """
        return bool(getattr(self, "_light_mode_active", False))

    def update_theme_labels(self, is_light: bool):
        """Hook called by parent when theme changes — caches the flag and
        reloads the table so item foregrounds get recomputed."""
        self._light_mode_active = bool(is_light)
        self.load_downtimes()

    # Regular shift window — used to reject downtimes outside working hours.
    _SHIFT_START_MIN = 6 * 60    # 06:00
    _SHIFT_END_MIN = 15 * 60     # 15:00
    _MIN_DURATION_MIN = 1

    def _validate_downtime(self, start_mins: int, end_mins: int,
                            reason: str, exclude_id: int | None = None) -> str | None:
        """Return an error message if the downtime is invalid, else None."""
        if not reason or not reason.strip():
            return "Reason is required."

        if start_mins < self._SHIFT_START_MIN or end_mins > self._SHIFT_END_MIN:
            return ("Downtime must be inside the regular shift "
                    f"(06:00 – 15:00). Got "
                    f"{start_mins // 60:02d}:{start_mins % 60:02d} – "
                    f"{end_mins // 60:02d}:{end_mins % 60:02d}.")

        duration = end_mins - start_mins
        if duration < self._MIN_DURATION_MIN:
            return f"Duration must be at least {self._MIN_DURATION_MIN} minute(s)."

        # Overlap check against existing downtimes for the same date.
        # Two intervals [a,b) and [c,d) overlap iff a < d AND c < b.
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT id, hora_inicio, hora_fin FROM downtimes "
                "WHERE fecha = ? AND COALESCE(status,'') != 'rejected'",
                (self.current_date,),
            )
            rows = cur.fetchall()
            conn.close()
        except Exception as exc:
            return f"Could not validate overlaps: {exc}"

        for row_id, hi, hf in rows:
            if exclude_id is not None and row_id == exclude_id:
                continue
            try:
                hi_t = QTime.fromString(hi, "HH:mm")
                hf_t = QTime.fromString(hf, "HH:mm")
                s = hi_t.hour() * 60 + hi_t.minute()
                e = hf_t.hour() * 60 + hf_t.minute()
            except Exception:
                continue
            if start_mins < e and s < end_mins:
                return (f"Overlaps with existing downtime "
                        f"{hi}–{hf}. Adjust the time range.")
        return None

    def _on_start_time_changed(self, t: QTime):
        """Keep End >= Start. Bump End forward if Start moves past it."""
        self.downtime_end.setMinimumTime(t)
        if self.downtime_end.time() < t:
            self.downtime_end.setTime(t)

    def _on_end_time_changed(self, t: QTime):
        """Safety net — if End somehow drops below Start, snap it back."""
        start = self.downtime_start.time()
        if t < start:
            self.downtime_end.blockSignals(True)
            self.downtime_end.setTime(start)
            self.downtime_end.blockSignals(False)

    def _normalize_status(self, status: str) -> str:
        s = (status or "").strip().lower()
        if s in ("accept", "accepted", "approve"):
            return "approved"
        if s in ("reject",):
            return "rejected"
        if s in ("pending", "approved", "rejected"):
            return s
        return "approved"

    def load_downtimes(self):
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, hora_inicio, hora_fin, duracion, razon, status, detalle,
                       COALESCE(synced_to_excel, 0),
                       COALESCE(last_sync_error, '')
                FROM downtimes
                WHERE fecha = ?
                ORDER BY hora_inicio DESC
            """, (self.current_date,))
            rows = cursor.fetchall()
            conn.close()
        except Exception as exc:
            print(f"[downtime_manager] load_downtimes failed: {exc}")
            return

        # Reset cell widgets from previous load to avoid stale labels stacking.
        # Cols 4 (Status), 5 (Sync), 6 (Actions) all use cell widgets.
        for _r in range(self.table.rowCount()):
            for _c in (4, 5, 6):
                self.table.removeCellWidget(_r, _c)
        self.table.setRowCount(len(rows))
        self.row_ids = []

        _STATUS_COLORS = {
            "pending":  QColor(0, 0, 0, 0),     # transparent background
            "rejected": QColor(0, 0, 0, 0),     # transparent background
            "approved": QColor(0, 0, 0, 0),     # transparent background
        }
        _STATUS_TEXT_COLORS = {
            "pending":  QColor("#F1C40F"),       # yellow text
            "rejected": QColor("#E74C3C"),       # red text
            "approved": QColor("#2ECC71"),       # green text
        }
        _STATUS_LABELS = {
            "pending":  "Pending",
            "approved": "Approved",
            "rejected": "Rejected",
        }

        compact = self.width() < 720  # threshold to switch inline → dropdown

        for idx, row in enumerate(rows):
            (row_id, start, end, duration, reason, status, detalle,
             sync_excel, last_err) = row
            status = self._normalize_status(status)

            values = [start, end, str(duration), reason,
                      _STATUS_LABELS.get(status, status),
                      "", ""]  # cols 5 (sync) and 6 (actions) rendered as widgets

            tooltip = detalle if detalle else reason

            is_light = self._is_light_mode()
            fg_default = QColor("#1F2328") if is_light else CLR_FG_LIGHT
            for col, val in enumerate(values):
                # Cols 4 (status), 5 (sync), 6 (actions) are widgets below;
                # keep underlying items empty so text doesn't bleed through.
                item_text = "" if col in (4, 5, 6) else str(val)
                item = QTableWidgetItem(item_text)
                item.setToolTip(tooltip)
                if self.edit_mode and idx == self.current_edit_row:
                    item.setBackground(QColor(70, 130, 180))
                    item.setForeground(QColor("#FFFFFF"))
                elif col in (4, 5, 6):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                else:
                    item.setForeground(fg_default)
                self.table.setItem(idx, col, item)

                # Status cell (col 4) rendered as label widget for solid bg
                if col == 4:
                    if self.edit_mode and idx == self.current_edit_row:
                        bg_css, fg_css = "#4682B4", "#FFFFFF"
                    else:
                        bg = _STATUS_COLORS.get(status, QColor(128, 128, 128))
                        fg = _STATUS_TEXT_COLORS.get(status, CLR_FG_LIGHT)
                        bg_css = "transparent" if bg.alpha() == 0 else bg.name()
                        fg_css = fg.name()
                    lbl = QLabel(_STATUS_LABELS.get(status, status))
                    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    lbl.setStyleSheet(
                        f"background-color: {bg_css}; color: {fg_css}; padding: 0px;"
                    )
                    self.table.setCellWidget(idx, 4, lbl)

            # ── Sync icon (col 5) ───────────────────────────────────────────
            # Reflects ONLY synced_to_excel now. Status decides ✓/⏳/✗ color.
            #   ✓ green  = excel synced + status approved
            #   ⏳ amber = excel synced + status pending (waiting on user mark)
            #   ✗ red    = excel synced + status rejected
            #   ⚠ red    = NOT synced to excel — retry worker will handle it
            if sync_excel == 0:
                sync_icon, sync_color = "⚠", "#E74C3C"
                sync_tip = "Pending sync to shared Excel"
                if last_err:
                    sync_tip += f"\nLast error: {last_err}"
            elif status == STATUS_PENDING_LOCAL:
                sync_icon, sync_color = "⏳", "#F1C40F"
                sync_tip = "Synced — paste to Teams, then mark Approved/Rejected"
            elif status == STATUS_REJECTED_LOCAL:
                sync_icon, sync_color = "✗", "#E74C3C"
                sync_tip = "Synced — rejected"
            else:
                sync_icon, sync_color = "✓", "#2ECC71"
                sync_tip = "Synced — approved"
            sync_lbl = QLabel(sync_icon)
            sync_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sync_lbl.setStyleSheet(
                f"color: {sync_color}; font-size: 14px; font-weight: bold;"
            )
            sync_lbl.setToolTip(sync_tip)
            self.table.setCellWidget(idx, 5, sync_lbl)

            # ── Actions (col 6) ─────────────────────────────────────────────
            # In wide mode: 3 inline buttons [Copy] [✓] [✗].
            # In compact mode: a single dropdown menu with the same actions.
            actions_widget = self._build_actions_widget(row_id, status, compact)
            self.table.setCellWidget(idx, 6, actions_widget)

            self.row_ids.append(row_id)

        # Fixed columns are set once in init_ui; Reason stretches automatically
        self._apply_table_layout_mode()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_table_layout_mode()

    def _apply_table_layout_mode(self):
        """Adjust table columns for narrow layouts so rows remain visible."""
        compact = self.width() < 720
        self.table.setColumnWidth(0, 56 if compact else 72)   # Start
        self.table.setColumnWidth(1, 56 if compact else 72)   # End
        self.table.setColumnWidth(2, 64 if compact else 86)   # Dur(min)
        self.table.setColumnWidth(4, 70 if compact else 80)   # Status
        self.table.setColumnWidth(5, 36 if compact else 44)   # Sync icon
        self.table.setColumnWidth(6, 96 if compact else 220)  # Actions

    # ── Actions cell (Copy + Approve + Reject) ─────────────────────────────
    def _build_actions_widget(self, dt_id: int, status: str, compact: bool):
        """Build the Actions cell. Inline buttons in wide layout, dropdown in
        compact layout (so labels never get clipped on narrow windows)."""
        from PySide6.QtWidgets import QWidget, QHBoxLayout, QMenu

        if compact:
            # Single dropdown button with all 3 actions
            btn = QPushButton("Actions ▾")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { background-color: #2D2F36; color: #E6EDF3; "
                "border: 1px solid #444; border-radius: 3px; padding: 2px 6px; "
                "font-size: 11px; } "
                "QPushButton:hover { background-color: #383B43; } "
                "QPushButton::menu-indicator { image: none; width: 0; }"
            )
            menu = QMenu(btn)
            menu.addAction("Copy for Teams",
                           lambda _id=dt_id: self._copy_dt_for_teams(_id))
            if status == STATUS_PENDING_LOCAL:
                menu.addSeparator()
                menu.addAction("Mark Approved",
                               lambda _id=dt_id: self._set_dt_status(_id, STATUS_APPROVED_LOCAL))
                menu.addAction("Mark Rejected",
                               lambda _id=dt_id: self._set_dt_status(_id, STATUS_REJECTED_LOCAL))
            else:
                menu.addSeparator()
                menu.addAction("Reset to Pending",
                               lambda _id=dt_id: self._set_dt_status(_id, STATUS_PENDING_LOCAL))
            btn.setMenu(menu)
            return btn

        # Wide layout — 3 inline buttons in a horizontal container
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(4)

        copy_btn = QPushButton("Copy")
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setToolTip("Copy DT details to clipboard, ready to paste in Teams")
        copy_btn.setStyleSheet(
            "QPushButton { background-color: #1F6FEB; color: white; border: none; "
            "border-radius: 3px; padding: 3px 8px; font-size: 11px; font-weight: 600; } "
            "QPushButton:hover { background-color: #388BFD; } "
            "QPushButton:pressed { background-color: #1A5FCF; }"
        )
        copy_btn.clicked.connect(lambda _checked=False, _id=dt_id: self._copy_dt_for_teams(_id))
        layout.addWidget(copy_btn)

        if status == STATUS_PENDING_LOCAL:
            ok_btn = QPushButton("✓")
            ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            ok_btn.setToolTip("Mark this DT as Approved")
            ok_btn.setMaximumWidth(34)
            ok_btn.setStyleSheet(
                "QPushButton { background-color: #2EA043; color: white; border: none; "
                "border-radius: 3px; padding: 3px 0; font-size: 12px; font-weight: 700; } "
                "QPushButton:hover { background-color: #3FB950; }"
            )
            ok_btn.clicked.connect(
                lambda _checked=False, _id=dt_id: self._set_dt_status(_id, STATUS_APPROVED_LOCAL))
            layout.addWidget(ok_btn)

            no_btn = QPushButton("✗")
            no_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            no_btn.setToolTip("Mark this DT as Rejected")
            no_btn.setMaximumWidth(34)
            no_btn.setStyleSheet(
                "QPushButton { background-color: #DA3633; color: white; border: none; "
                "border-radius: 3px; padding: 3px 0; font-size: 12px; font-weight: 700; } "
                "QPushButton:hover { background-color: #F85149; }"
            )
            no_btn.clicked.connect(
                lambda _checked=False, _id=dt_id: self._set_dt_status(_id, STATUS_REJECTED_LOCAL))
            layout.addWidget(no_btn)
        else:
            # Already decided — offer a small "reset to pending" undo
            undo_btn = QPushButton("↺")
            undo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            undo_btn.setToolTip("Reset to Pending")
            undo_btn.setMaximumWidth(34)
            undo_btn.setStyleSheet(
                "QPushButton { background-color: #444C56; color: #C9D1D9; border: none; "
                "border-radius: 3px; padding: 3px 0; font-size: 12px; } "
                "QPushButton:hover { background-color: #545D69; }"
            )
            undo_btn.clicked.connect(
                lambda _checked=False, _id=dt_id: self._set_dt_status(_id, STATUS_PENDING_LOCAL))
            layout.addWidget(undo_btn)

        layout.addStretch()
        return container

    def _copy_dt_for_teams(self, dt_id: int):
        """Build a Teams-ready text block for this DT and put it on the clipboard."""
        if not dt_id:
            return
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT fecha, hora_inicio, hora_fin, duracion, razon, detalle, "
                "       COALESCE(downtime_case_id, '') "
                "FROM downtimes WHERE id = ?",
                (int(dt_id),),
            )
            r = cur.fetchone()
            conn.close()
        except Exception as exc:
            QMessageBox.warning(self, "Copy failed", f"Could not load DT #{dt_id}: {exc}")
            return
        if not r:
            QMessageBox.warning(self, "Copy failed", f"DT #{dt_id} not found.")
            return

        fecha, h_ini, h_fin, dur, razon, detalle, pid = r

        lines = [
            f"Razon: {razon or ''}",
            f"Hora inicio - Hora final: {h_ini or ''} - {h_fin or ''}",
            f"Total: {int(dur or 0)} min",
            f"Descripcion: {detalle or ''}",
        ]
        if pid:
            lines.append(f"PID: {pid}")
        text = "\n".join(lines)

        try:
            QApplication.clipboard().setText(text)
        except Exception as exc:
            QMessageBox.warning(self, "Copy failed", f"Clipboard error: {exc}")
            return

        self._flash_status("Copied — paste it in the Teams chat")

    def _set_dt_status(self, dt_id: int, new_status: str):
        """User marks a DT as approved/rejected/pending after Teams reaction."""
        if not dt_id or new_status not in (
                STATUS_PENDING_LOCAL, STATUS_APPROVED_LOCAL, STATUS_REJECTED_LOCAL):
            return
        try:
            conn = get_connection()
            cur = conn.cursor()
            # When the user changes the decision, mark the row as needing
            # re-export so the shared Excel reflects the new status.
            cur.execute(
                "UPDATE downtimes "
                "SET status = ?, synced_to_excel = 0, "
                "    responded_by = COALESCE(NULLIF(?, ''), responded_by), "
                "    responded_at = ? "
                "WHERE id = ?",
                (
                    new_status,
                    self._current_designer_name(),
                    datetime.now().isoformat(timespec="seconds")
                        if new_status != STATUS_PENDING_LOCAL else "",
                    int(dt_id),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            QMessageBox.warning(self, "Status update failed",
                                f"Could not update DT #{dt_id}: {exc}")
            return

        self.load_downtimes()
        if self.on_update_callback:
            self.on_update_callback()

        # Push the new status to the shared Excel in the background
        if _APPROVAL_OK:
            designer = self._current_designer_name()
            threading.Thread(
                target=lambda: export_pending_downtimes(designer),
                daemon=True,
            ).start()

    def _current_designer_name(self) -> str:
        try:
            cfg = load_config()
            return cfg.get("designer_name", "") or ""
        except Exception:
            return ""

    def _flash_status(self, msg: str, ms: int = 1800):
        """Temporary toast shown in the parent window's status bar, if present.
        Falls back to a tooltip near the table on the next paint cycle."""
        try:
            wnd = self.window()
            sb = getattr(wnd, "statusBar", None)
            if callable(sb):
                wnd.statusBar().showMessage(msg, ms)
                return
        except Exception:
            pass
        # Fallback: brief QMessageBox-less hint via window title flicker
        try:
            wnd = self.window()
            old_title = wnd.windowTitle()
            wnd.setWindowTitle(f"{msg}   —   {old_title}")
            QTimer.singleShot(ms, lambda: wnd.setWindowTitle(old_title))
        except Exception:
            pass

    def on_cell_clicked(self, row, column):
        """Handle cell click - delete if in delete mode"""
        if self.delete_mode:
            # If in delete mode, delete with confirmation
            self.delete_downtime_at_row(row)
        
        if self.edit_mode:
            # If in edit mode, load data into edit fields
            self.load_edit_data(row)


    def load_edit_data(self, row):
        """Load downtime data into edit fields"""
        start_text = self.table.item(row, 0).text()
        end_text = self.table.item(row, 1).text()
        reason_text = self.table.item(row, 3).text()
        
        self.downtime_start.setTime(QTime.fromString(start_text, "HH:mm"))
        self.downtime_end.setTime(QTime.fromString(end_text, "HH:mm"))
        
        index = self.downtime_reason.findText(reason_text)
        if index >= 0:
            self.downtime_reason.setCurrentIndex(index)
        
        self.current_edit_row = row
        self.update_button_colors()

    def save_edited_downtime(self):
        """Save edited downtime back to database"""
        if self.current_edit_row < 0 or self.current_edit_row >= len(self.row_ids):
            QMessageBox.warning(self, "Error", "No downtime selected for editing.")
            return
        
        # Get the new values
        start = self.downtime_start.time().toString("HH:mm")
        end = self.downtime_end.time().toString("HH:mm")
        reason = self.downtime_reason.currentText()
        
        # Calculate duration
        start_mins = self.downtime_start.time().hour() * 60 + self.downtime_start.time().minute()
        end_mins = self.downtime_end.time().hour() * 60 + self.downtime_end.time().minute()
        duration = end_mins - start_mins
        if duration < 0:
            duration += 24 * 60

        # Editing a DT resets it to pending and clears the synced flag so the
        # retry worker re-uploads the modified data to the shared Excel.
        row_id = self.row_ids[self.current_edit_row]

        err = self._validate_downtime(start_mins, end_mins, reason, exclude_id=row_id)
        if err:
            QMessageBox.warning(self, "Invalid downtime", err)
            return
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE downtimes
            SET hora_inicio = ?, hora_fin = ?, razon = ?, duracion = ?,
                status = 'pending', synced_to_excel = 0,
                responded_by = '', responded_at = ''
            WHERE id = ?
        """, (start, end, reason, duration, row_id))
        
        conn.commit()
        conn.close()
        
        # Reload and clear
        self.load_downtimes()
        self.downtime_start.setTime(QTime.currentTime())
        self.downtime_end.setTime(QTime.currentTime())
        self.downtime_reason.setCurrentIndex(0)
        self.current_edit_row = -1

        # Re-export pending entries in background (now includes this edited row)
        if _APPROVAL_OK:
            cfg = load_config()
            _designer = cfg.get("designer_name", "")
            threading.Thread(target=export_pending_downtimes, args=(_designer,), daemon=True).start()

        # Trigger callback to update production
        if self.on_update_callback:
            self.on_update_callback()

        QMessageBox.information(self, "Success", "Downtime updated successfully!")

    def edit_downtime(self):
        """Toggle edit mode / Save edited downtime"""
        if self.edit_mode:
            # Exiting edit mode - save if a row was selected
            if self.current_edit_row >= 0:
                self.save_edited_downtime()
            self.edit_mode = False
        else:
            # Entering edit mode
            if self.table.currentRow() < 0:
                QMessageBox.information(self, "Info", "Please select a downtime to edit.")
                return
            self.edit_mode = True
            self.load_edit_data(self.table.currentRow())
            # Deactivate delete mode
            self.delete_mode = False
        
        self.update_button_colors()

    # def load_edit_data(self, row):
    #     """Load downtime data into edit fields"""
    #     start_text = self.table.item(row, 0).text()
    #     end_text = self.table.item(row, 1).text()
    #     reason_text = self.table.item(row, 3).text()
        
    #     self.downtime_start.setTime(QTime.fromString(start_text, "HH:mm"))
    #     self.downtime_end.setTime(QTime.fromString(end_text, "HH:mm"))
        
    #     index = self.downtime_reason.findText(reason_text)
    #     if index >= 0:
    #         self.downtime_reason.setCurrentIndex(index)
        
    #     self.current_edit_row = row
    #     self.update_button_colors()

    # def edit_downtime(self):
    #     """Toggle edit mode"""
    #     self.edit_mode = not self.edit_mode
        
    #     if self.edit_mode:
    #         # Entering edit mode - deactivate delete mode
    #         self.delete_mode = False
        
    #     self.update_button_colors()
        
    #     if not self.edit_mode:
    #         # If exiting edit mode, clear fields
    #         self.downtime_start.setTime(QTime.currentTime())
    #         self.downtime_end.setTime(QTime.currentTime())
    #         self.downtime_reason.setCurrentIndex(0)
    #         self.current_edit_row = -1

    def update_button_colors(self):
        """Update button colors based on mode"""
        if self.delete_mode:
            # Delete mode active - red delete button, default edit button
            self.delete_btn.setStyleSheet("""
                QPushButton {
                    background-color: #B71C1C;
                    border-radius: 6px;
                    color: white;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #C62828;
                }
            """)
            self.edit_btn.setStyleSheet("")
        elif self.edit_mode:
            # Edit mode active - green save button, default delete button
            self.edit_btn.setText("Save")
            self.edit_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    border: none;
                    border-radius: 6px;
                    color: white;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #388E3C;
                }
            """)
            self.delete_btn.setStyleSheet("")
        else:
            # Normal mode - use global theme styles
            self.edit_btn.setText("Edit")
            self.delete_btn.setStyleSheet("")
            self.edit_btn.setStyleSheet("")

    def delete_downtime_at_row(self, row):
        """Delete downtime at specific row with confirmation"""
        if row >= len(self.row_ids):
            return
        
        # Exit delete mode first
        self.delete_mode = False
        self.update_button_colors()
        
        # Show confirmation dialog
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            "Are you sure you want to delete this downtime?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        row_id = self.row_ids[row]
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM downtimes WHERE id = ?", (row_id,))
        conn.commit()
        conn.close()

        self.load_downtimes()

        if self.on_update_callback:
            self.on_update_callback()

        # Re-export this designer's xlsx so the deletion propagates to the
        # shared folder. export_pending_downtimes reads the full local table
        # and rewrites _DT_<designer>.xlsx from scratch, so a deleted row
        # simply disappears. The consolidated file picks the change up on
        # its next rebuild (also kicked off by export_pending_downtimes).
        if _APPROVAL_OK:
            designer = self._current_designer_name()
            threading.Thread(
                target=lambda: export_pending_downtimes(designer),
                daemon=True,
            ).start()

    def delete_downtime(self):
        """Toggle delete mode"""
        self.delete_mode = not self.delete_mode
        self.update_button_colors()
