import os
import threading

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
    )
    _APPROVAL_OK = True
except Exception as _approval_err:
    print(f"[downtime_manager] Approval module unavailable: {_approval_err}")
    _APPROVAL_OK = False

try:
    from sync.teams_notify import notify_downtime_submitted
    _TEAMS_OK = True
except Exception as _teams_err:
    log_event("downtime_manager", f"teams notify module unavailable: {_teams_err}", level="WARN")
    _TEAMS_OK = False


# Reasons that affect the whole team and do NOT require supervisor approval.
# Downtimes with these reasons are inserted with status='approved' and skip the
# approval export + Teams notification.
AUTO_APPROVED_REASONS = {
    "Corporate Event",
    "Evacuation Drill",
    "Extended Weekly Huddle",
    "Gemba & listening Events",
    "Spark Town Hall",
    "Team Meeting",
}


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
        self.init_ui()
        self.load_downtimes()
        self._start_poll_timer()

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

    def closeEvent(self, event):
        self._stop_poll_timer()
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
        self.downtime_start.setTime(QTime.currentTime())
        self.downtime_start.setMinimumWidth(90)
        input_layout.addWidget(self.downtime_start)

        input_layout.addWidget(QLabel("End:"))
        self.downtime_end = QTimeEdit()
        self.downtime_end.setTime(QTime.currentTime())
        self.downtime_end.setMinimumWidth(90)
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
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Start", "End", "Dur.(min)", "Reason", "Status", "Responded By"])
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
        self.table.setColumnWidth(0, 52)
        self.table.setColumnWidth(1, 52)
        self.table.setColumnWidth(2, 72)
        self.table.setColumnWidth(4, 70)
        self.table.setColumnWidth(5, 120)
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

        detalle = self._get_downtime_detail(reason)
        if detalle is None:
            return  # Cancelado por el usuario

        auto_approve = reason in AUTO_APPROVED_REASONS
        initial_status = "approved" if auto_approve else "pending"

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO downtimes (fecha, hora_inicio, hora_fin, razon, duracion, status, detalle)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            self.current_date,
            start,
            end,
            reason,
            duration,
            initial_status,
            detalle
        ))
        dt_id = cursor.lastrowid
        conn.commit()
        conn.close()
        self.load_downtimes()
        self.downtime_start.setTime(QTime.currentTime())
        self.downtime_end.setTime(QTime.currentTime())

        # Team-wide reasons skip approval workflow entirely
        if auto_approve:
            log_event("downtime_manager",
                      f"auto-approved team downtime: {reason} ({duration} min)",
                      level="INFO")
            if self.on_update_callback:
                self.on_update_callback()
            return

        # Export + Teams notification in background to avoid blocking UI
        if _APPROVAL_OK or _TEAMS_OK:
            cfg = load_config()
            designer = cfg.get("designer_name", "")
            _date = self.current_date
            def _bg_export():
                if _APPROVAL_OK:
                    export_pending_downtimes(designer)
                if _TEAMS_OK:
                    notify_downtime_submitted(
                        designer=designer, fecha=_date,
                        start=start, end=end, duration=duration,
                        reason=reason, detalle=detalle,
                        dt_id=dt_id,
                    )
            threading.Thread(target=_bg_export, daemon=True).start()

        # Trigger callback to update production
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
        app = QApplication.instance()
        if not app:
            return False
        return "background-color: #F6F8FA" in (app.styleSheet() or "")

    def update_theme_labels(self, is_light: bool):
        """Hook called by parent when theme changes — reloads table so item
        foregrounds are recomputed with the new theme."""
        self.load_downtimes()

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
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, hora_inicio, hora_fin, duracion, razon, status, detalle,
                   responded_by, responded_at
            FROM downtimes
            WHERE fecha = ?
            ORDER BY hora_inicio DESC
        """, (self.current_date,))

        rows = cursor.fetchall()
        conn.close()

        # Reset cell widgets from previous load to avoid stale labels stacking
        for _r in range(self.table.rowCount()):
            self.table.removeCellWidget(_r, 4)
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

        for idx, row in enumerate(rows):
            row_id, start, end, duration, reason, status, detalle, resp_by, resp_at = row
            status = self._normalize_status(status)
            resp_by = resp_by or ""
            resp_at = resp_at or ""

            # Format responded_by with timestamp if available
            resp_display = resp_by
            if resp_at and resp_by:
                # Show just the date/time portion if it's a full ISO timestamp
                try:
                    dt = datetime.fromisoformat(resp_at.replace("Z", "+00:00"))
                    resp_display = f"{resp_by} ({dt.strftime('%m/%d %H:%M')})"
                except (ValueError, TypeError):
                    resp_display = f"{resp_by} ({resp_at})"

            values = [start, end, str(duration), reason, _STATUS_LABELS.get(status, status), resp_display]

            tooltip = detalle if detalle else reason
            # Build a detailed tooltip for the Responded By column
            resp_tooltip = ""
            if resp_by:
                resp_tooltip = f"Responded by: {resp_by}"
                if resp_at:
                    resp_tooltip += f"\nDate/Time: {resp_at}"
                resp_tooltip += f"\nDecision: {_STATUS_LABELS.get(status, status)}"

            is_light = self._is_light_mode()
            fg_default = QColor("#1F2328") if is_light else CLR_FG_LIGHT
            for col, val in enumerate(values):
                # Col 4 (Status) is rendered via a QLabel widget below; keep
                # the underlying item empty so text doesn't bleed through.
                item_text = "" if col == 4 else str(val)
                item = QTableWidgetItem(item_text)
                if col == 5 and resp_tooltip:
                    item.setToolTip(resp_tooltip)
                else:
                    item.setToolTip(tooltip)
                # Only colour the Status cell (col 4); highlight entire row when editing
                if self.edit_mode and idx == self.current_edit_row:
                    item.setBackground(QColor(70, 130, 180))
                    item.setForeground(QColor("#FFFFFF"))
                elif col == 4:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                else:
                    item.setForeground(fg_default)
                self.table.setItem(idx, col, item)

                # Status cell: setCellWidget bypasses the global QTableWidget::item
                # stylesheet that otherwise suppresses setBackground() on items.
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

            self.row_ids.append(row_id)

        # Fixed columns are set once in init_ui; Reason stretches automatically
        self._apply_table_layout_mode()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_table_layout_mode()

    def _apply_table_layout_mode(self):
        """Adjust table columns for narrow layouts so rows remain visible."""
        compact = self.width() < 560
        self.table.setColumnWidth(0, 64 if compact else 72)   # Start
        self.table.setColumnWidth(1, 64 if compact else 72)   # End
        self.table.setColumnWidth(2, 74 if compact else 86)   # Dur(min)
        self.table.setColumnWidth(4, 70 if compact else 80)   # Status
        self.table.setColumnWidth(5, 86 if compact else 108)  # Responded By

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
        
        # Update database (team-wide reasons auto-approve on edit too)
        new_status = "approved" if reason in AUTO_APPROVED_REASONS else "pending"
        row_id = self.row_ids[self.current_edit_row]
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE downtimes
            SET hora_inicio = ?, hora_fin = ?, razon = ?, duracion = ?, status = ?
            WHERE id = ?
        """, (start, end, reason, duration, new_status, row_id))
        
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

    def delete_downtime(self):
        """Toggle delete mode"""
        self.delete_mode = not self.delete_mode
        self.update_button_colors()
