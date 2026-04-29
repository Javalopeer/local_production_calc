import sys
import os
from datetime import datetime, date
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QScrollArea, QCheckBox,
    QPushButton, QMessageBox, QLabel, QLineEdit, QDialog,
    QVBoxLayout, QHBoxLayout, QDialogButtonBox
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QEvent, qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut, QIcon


def _qt_message_filter(mode, context, message):
    """Drop Qt's harmless `QFont::setPointSize: Point size <= 0` chatter.

    Our stylesheets express font sizes in pixels (`font-size: 11px`), so the
    derived QFont has pointSize == -1. Some internal Qt paths still call
    `setPointSize(font.pointSize())` on those fonts and Qt emits a warning
    every time. The widgets render fine — it's pure noise. Pass everything
    else through to stderr so real warnings stay visible.
    """
    if message and "QFont::setPointSize: Point size <= 0" in message:
        return
    sys.stderr.write(message + "\n")


qInstallMessageHandler(_qt_message_filter)
from db.database import init_db, migrate_legacy_db, discover_and_merge_background_dbs
from sync.app_logger import log_event
from tabs.utils import load_units_eq_data
from tabs.breaks_dialog import (
    init_breaks_table, BreaksDialog, get_breaks,
    get_breaks_answered_today, set_break_attendance, _to_minutes,
    get_active_schedule,
)
import qtawesome as qta

try:
    from sync.daily_performance import (
        init_performance_table,
        get_daily_metrics,
        record_daily_snapshot,
        has_pending_justification,
        mark_success_shown,
        was_success_shown,
        save_justification,
        export_justification,
    )
    from tabs.performance_popups import SuccessPopup, JustificationPopup
    _PERF_OK = True
except Exception as _perf_err:
    print(f"[main] Performance module unavailable: {_perf_err}")
    _PERF_OK = False

_JUSTIFICATION_ENABLED = False


def _resource_path(relative: str) -> str:
    """Return absolute path to a bundled resource (works both frozen and in dev)."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)

# ============== VERSION ==============
APP_VERSION = "1.1.4"
DB_SCHEMA_VERSION = 2
# =====================================

from tabs.tab_register import RegisterTab
from tabs.tab_production import ProductionTab
from tabs.tab_history import HistoryTab
from tabs.tab_standards import StandardsTab
from tabs.tab_dashboard import DashboardTab
from tabs.tab_theme_config import ThemeConfigTab, DEFAULT_LIGHT_COLORS
from tabs.tab_sync import SyncTab
from PySide6.QtWidgets import QDialog, QVBoxLayout as _QVBox
from sync.app_config import load_config

_TRANSIENT_SYNC_KEYWORDS = (
    "permissionerror", "locked", "cannot access", "winerror",
    "timed out", "timeout", "network", "connection reset",
    "remote end closed", "odmpath",
)


def _is_transient_sync_error(msg: str) -> bool:
    m = msg.lower()
    return any(k in m for k in _TRANSIENT_SYNC_KEYWORDS)


class _SilentSyncThread(QThread):
    """Run export_to_sharepoint silently in background after each case save.
    Retries up to 3 times on transient network/file errors."""
    done = Signal(bool, str)

    def run(self):
        try:
            from sync.sharepoint_sync import export_to_sharepoint, _OPENPYXL_OK
            from sync.app_config import load_config
            if not _OPENPYXL_OK:
                return
            cfg = load_config()
            if not cfg.get("name_confirmed") or not cfg.get("export_folder"):
                return
            import os as _os
            if not _os.path.isdir(cfg["export_folder"]):
                return
            import time as _t
            last_ok, last_msg = False, ""
            for attempt in range(3):
                try:
                    ok, msg = export_to_sharepoint()
                    if ok or not _is_transient_sync_error(msg) or attempt == 2:
                        self.done.emit(ok, msg)
                        return
                    last_ok, last_msg = ok, msg
                except Exception as e:
                    last_ok, last_msg = False, str(e)
                    if not _is_transient_sync_error(last_msg) or attempt == 2:
                        self.done.emit(last_ok, last_msg)
                        return
                _t.sleep(5 * (attempt + 1))
            self.done.emit(last_ok, last_msg)
        except Exception as e:
            self.done.emit(False, str(e))
class CenteredTabWidget(QTabWidget):
    """QTabWidget whose tab bar is always horizontally centered.

    Qt re-layouts the tab bar to x=0 on resize, tab switch, and other events.
    We install an event filter on the tab bar that catches every Move/Resize
    event Qt fires on it and immediately corrects the position.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        bar = self.tabBar()
        bar.setExpanding(False)
        bar.setUsesScrollButtons(True)
        bar.installEventFilter(self)
        self._centering = False  # re-entry guard

    # ── event filter on the tab bar ───────────────────────────────────────────

    def eventFilter(self, obj, event):
        if obj is self.tabBar() and event.type() in (
            QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show,
        ):
            self._schedule_center()
        return False  # never consume the event

    def _schedule_center(self):
        if not self._centering:
            self._centering = True
            QTimer.singleShot(0, self._do_center)

    def _do_center(self):
        self._centering = False
        self._center_tabs()

    # ── centering logic ───────────────────────────────────────────────────────

    def _center_tabs(self):
        bar = self.tabBar()
        n = bar.count()
        if n == 0:
            return
        total = sum(bar.tabRect(i).width() for i in range(n))
        geo = bar.geometry()
        x = max(0, (self.width() - total) // 2)
        if geo.x() == x:
            return  # already centered — avoid triggering another Move event
        bar.setGeometry(x, geo.y(), self.width() - x, geo.height())

    # ── also re-center on widget resize / show / tab add ─────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._center_tabs()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_center()

    def tabInserted(self, index):
        super().tabInserted(index)
        self._schedule_center()


class MainWindow(QMainWindow):
    themeChanged = Signal(bool)
    def __init__(self, dark_style="", light_style=""):
        super().__init__()
        self._dark_style = dark_style
        self._light_style = light_style
        self._light_style_base = light_style
        self._font_size = 12
        self._is_light = False
        self.setWindowTitle(f"Production Performance Calculator v{APP_VERSION}")
        _ico = _resource_path(os.path.join("data", "app_icon.ico"))
        self.setWindowIcon(QIcon(_ico))

        self.tabs = CenteredTabWidget()

        self.register_tab = RegisterTab()
        self.production_tab = ProductionTab()
        self.history_tab = HistoryTab()
        self.standards_tab = StandardsTab()
        self.dashboard_tab = DashboardTab()
        self._sync_dialog = None         # created lazily
        self._sync_tab_widget = None     # SyncTab instance inside dialog
        self._sync_thread = None         # background sync thread
        self._sync_status_label = None   # statusbar indicator
        self._eod_sync_triggered_date = None  # prevent double EOD trigger

        self._load_and_apply_light_palette()

        def _safe_connect(signal, target, slot_name: str, name: str):
            try:
                slot = getattr(target, slot_name, None)
                if not callable(slot):
                    log_event("main", f"theme signal skipped (missing slot) for {name}", level="WARN")
                    return
                signal.connect(slot)
            except Exception as exc:
                log_event("main", f"theme signal connect failed for {name}: {exc}", level="WARN")

        # Connect a themeChanged signal to tabs so they update their local styles
        _safe_connect(self.themeChanged, self.register_tab,   "update_theme_labels",        "register.update_theme_labels")
        _safe_connect(self.themeChanged, self.register_tab,   "update_progress_bar_style",  "register.update_progress_bar_style")
        _safe_connect(self.themeChanged, self.history_tab,    "update_theme_labels",        "history.update_theme_labels")
        _safe_connect(self.themeChanged, self.production_tab, "update_theme_labels",        "production.update_theme_labels")
        _safe_connect(self.themeChanged, self.standards_tab,  "update_theme_labels",        "standards.update_theme_labels")
        _safe_connect(self.themeChanged, self.dashboard_tab,  "update_theme_labels",        "dashboard.update_theme_labels")

        
        # Connect register tab to production tab for dynamic updates
        self.register_tab.case_saved.connect(self.production_tab.load_data)
        self.register_tab.case_saved.connect(self.history_tab.load_all_cases)
        self.register_tab.case_saved.connect(self.dashboard_tab.refresh)

        # Downtime mutations (add/edit/delete/status) — refresh views that
        # aggregate downtime data so they don't show stale counts.
        self.register_tab.downtime_changed.connect(self.dashboard_tab.refresh)
        self.register_tab.downtime_changed.connect(self.history_tab.load_all_cases)

        # Connect production tab edit/delete to register tab
        self.production_tab.case_updated.connect(self.on_production_case_updated)

        # Register tab in OT mode also refreshes OT views
        self.register_tab.ot_saved.connect(self.register_tab._load_ot_day_cases)
        self.register_tab.ot_saved.connect(self.production_tab.load_data)
        self.register_tab.ot_saved.connect(self.history_tab.load_all_cases)
        self.register_tab.ot_saved.connect(self.dashboard_tab.refresh)
        self.register_tab.ot_saved.connect(self._silent_sync)
        
        # Connect standards tab to refresh app data when standards change
        self.standards_tab.standards_updated.connect(self.on_standards_updated)

        # Auto-sync silently after every case save
        self.register_tab.case_saved.connect(self._silent_sync)

        self._justification_blocking = False
        if _PERF_OK and _JUSTIFICATION_ENABLED:
            self.register_tab.case_saved.connect(self._check_performance_after_save)
            self._start_eod_timer()

        # Break reminder timer — asks "going on break?" ~10 min before each break
        self._break_reminder_shown = set()  # (fecha, break_id) already asked today
        self._start_break_reminder_timer()

        # EOD auto-sync at 4:55 PM on weekdays
        self._start_eod_sync_timer()
        
        self._tab_icons = [
            'fa5s.edit', 'fa5s.chart-bar',
            'fa5s.history', 'fa5s.cog', 'fa5s.tachometer-alt',
        ]
        _ic = "#b8ceb1"
        self.tabs.addTab(self.register_tab,  qta.icon(self._tab_icons[0], color=_ic), "Register")
        self.tabs.addTab(self.production_tab, qta.icon(self._tab_icons[1], color=_ic), "Production")
        self.tabs.addTab(self.history_tab,    qta.icon(self._tab_icons[2], color=_ic), "History")
        self.tabs.addTab(self.standards_tab,  qta.icon(self._tab_icons[3], color=_ic), "Standards")
        self.tabs.addTab(self.dashboard_tab,  qta.icon(self._tab_icons[4], color=_ic), "Dashboard")
        self.setCentralWidget(self.tabs)

        # ── Global clipboard-import shortcut (Ctrl+Shift+I) ─────────────────────
        # After copying a case page (Ctrl+A, Ctrl+C in the browser), press
        # Ctrl+Shift+I here to auto-fill Register.
        import_shortcut = QShortcut(QKeySequence("Ctrl+Shift+I"), self)
        import_shortcut.activated.connect(self._trigger_import_shortcut)

        # Get screen height for maximum window height
        screen = QGuiApplication.primaryScreen()
        screen_height = screen.availableGeometry().height()
        
        # Set size constraints - resizable with min/max
        self.setMinimumSize(660, 550)
        screen_width = screen.availableGeometry().width()
        max_width = min(1128, screen_width)
        self.setMaximumSize(max_width, screen_height)
        self.resize(min(1100, max_width), 700)
        # Load old DB button in status bar
        try:
            btn_load_db = QPushButton()
            btn_load_db.setIcon(qta.icon('fa5s.database', color='#A371F7'))
            btn_load_db.setToolTip("Import cases from an old cases.db file")
            btn_load_db.setFixedSize(28, 20)
            btn_load_db.setStyleSheet("padding: 1px 3px; border-radius: 4px; border: 1px solid #30363D; background: transparent;")
            btn_load_db.clicked.connect(self.register_tab._on_load_db)
            self.statusBar().addPermanentWidget(btn_load_db)
        except Exception as exc:
            log_event("main", f"statusbar load_db button setup failed: {exc}", level="WARN")

        # Breaks configuration button in status bar
        try:
            btn_breaks = QPushButton()
            btn_breaks.setIcon(qta.icon('fa5s.utensils', color='#FFA726'))
            btn_breaks.setToolTip("Configure break times")
            btn_breaks.setFixedSize(28, 20)
            btn_breaks.setStyleSheet("padding: 1px 3px; border-radius: 4px; border: 1px solid #30363D; background: transparent; color: #FFA726;")
            btn_breaks.clicked.connect(self._open_breaks_dialog)
            self.statusBar().addPermanentWidget(btn_breaks)
        except Exception as exc:
            log_event("main", f"statusbar breaks button setup failed: {exc}", level="WARN")

        # Light-theme palette button in status bar
        try:
            btn_palette = QPushButton()
            btn_palette.setIcon(qta.icon('fa5s.palette', color='#58A6FF'))
            btn_palette.setToolTip("Customize Light Mode Colors")
            btn_palette.setFixedSize(28, 20)
            btn_palette.setStyleSheet("padding: 1px 3px; border-radius: 4px; border: 1px solid #30363D; background: transparent;")
            btn_palette.clicked.connect(self._open_theme_config_dialog)
            self.statusBar().addPermanentWidget(btn_palette)
        except Exception as exc:
            log_event("main", f"statusbar palette button setup failed: {exc}", level="WARN")

        # Theme toggle checkbox in status bar
        try:
            light_chk = QCheckBox("Light")
            light_chk.setToolTip("Toggle light mode")
            def on_theme_toggled(checked):
                self._is_light = checked
                self._apply_style()
                # Update tab icons for contrast
                _icon_color = "#242038" if checked else "#b8ceb1"
                for i, name in enumerate(self._tab_icons):
                    self.tabs.setTabIcon(i, qta.icon(name, color=_icon_color))
                # Signal notifies all connected tabs
                try:
                    self.themeChanged.emit(checked)
                except Exception as exc:
                    log_event("main", f"themeChanged emit failed: {exc}", level="WARN")

            light_chk.toggled.connect(on_theme_toggled)
            self.statusBar().addPermanentWidget(light_chk)

            # Font size buttons
            from PySide6.QtWidgets import QPushButton as _QPB
            btn_fup = _QPB("A+")
            btn_fup.setFixedSize(30, 20)
            btn_fup.setToolTip("Increase font size")
            btn_fup.setStyleSheet("font-size: 10px; padding: 1px 4px; font-weight: 600; border: 1px solid #30363D; border-radius: 4px; background: transparent; color: #8B949E;")
            btn_fdn = _QPB("A-")
            btn_fdn.setFixedSize(30, 20)
            btn_fdn.setToolTip("Decrease font size")
            btn_fdn.setStyleSheet("font-size: 10px; padding: 1px 4px; font-weight: 600; border: 1px solid #30363D; border-radius: 4px; background: transparent; color: #8B949E;")
            btn_fup.clicked.connect(lambda: self._change_font_size(1))
            btn_fdn.clicked.connect(lambda: self._change_font_size(-1))
            self.statusBar().addPermanentWidget(btn_fdn)
            self.statusBar().addPermanentWidget(btn_fup)

            # Sync button
            btn_sync = _QPB("⬆ Sync")
            btn_sync.setFixedSize(54, 20)
            btn_sync.setToolTip("Export to SharePoint")
            btn_sync.setStyleSheet("font-size: 10px; padding: 1px 4px; font-weight: 600; border: 1px solid #388BFD; border-radius: 4px; background: transparent; color: #388BFD;")
            btn_sync.clicked.connect(self._open_sync_dialog)
            self.statusBar().addPermanentWidget(btn_sync)

            # Sync status indicator (last sync time)
            self._sync_status_label = QLabel("")
            self._sync_status_label.setStyleSheet("font-size: 10px; color: #8B949E; padding-right: 4px;")
            self.statusBar().addWidget(self._sync_status_label)
        except Exception as exc:
            log_event("main", f"statusbar theme/sync controls setup failed: {exc}", level="WARN")

    def _open_breaks_dialog(self):
        """Open the breaks configuration dialog."""
        dlg = BreaksDialog(self)
        dlg.exec()

    def _open_sync_dialog(self):
        """Open the Sync panel as a floating dialog."""
        if self._sync_dialog is None:
            self._sync_dialog = QDialog(self)
            self._sync_dialog.setWindowTitle("SharePoint Sync")
            self._sync_dialog.setMinimumSize(760, 800)
            self._sync_dialog.resize(820, 820)
            layout = QVBoxLayout(self._sync_dialog)
            layout.setContentsMargins(0, 0, 0, 0)
            self._sync_tab_widget = SyncTab()
            layout.addWidget(self._sync_tab_widget)
        self._sync_dialog.show()
        self._sync_dialog.raise_()
        self._sync_dialog.activateWindow()

    def _open_theme_config_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Light Theme Colors")
        dlg.setMinimumWidth(560)
        dlg.setMinimumHeight(520)
        layout = QVBoxLayout(dlg)
        cfg = ThemeConfigTab()
        cfg.theme_colors_changed.connect(self._on_light_palette_changed)
        layout.addWidget(cfg)
        dlg.exec()
    # ── Break reminder ─────────────────────────────────────────────────────
    def _start_break_reminder_timer(self):
        """Check every 60s if a break starts in ~10 minutes and ask the user."""
        self._break_timer = QTimer(self)
        self._break_timer.setInterval(60_000)  # every 60 seconds
        self._break_timer.timeout.connect(self._check_break_reminder)
        self._break_timer.start()

    def _check_break_reminder(self):
        """If a configured break starts in ≤10 minutes, show a popup asking
        whether the user is going on that break."""
        now = datetime.now()
        today_str = date.today().isoformat()
        now_mins = now.hour * 60 + now.minute

        breaks = get_breaks(get_active_schedule())
        answered = get_breaks_answered_today(today_str)

        for bid, name, b_start_str, _b_end_str in breaks:
            if bid in answered:
                continue  # already answered today
            key = (today_str, bid)
            if key in self._break_reminder_shown:
                continue  # already shown popup this session
            b_start = _to_minutes(b_start_str)
            # Show popup when we are 0–10 minutes before the break starts
            mins_until = b_start - now_mins
            if 0 <= mins_until <= 10:
                self._break_reminder_shown.add(key)
                self._show_break_popup(today_str, bid, name, b_start_str, _b_end_str)

    def _show_break_popup(self, fecha: str, break_id: int, name: str,
                          start: str, end: str):
        """Small popup: 'Are you going on break <name> (HH:mm – HH:mm)?'"""
        result = QMessageBox.question(
            self,
            "Break Reminder",
            f"Are you going on break?\n\n"
            f"{name}  ({start} – {end})\n\n"
            f"If YES, break time will be subtracted from\n"
            f"any case that overlaps with this period.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        took = result == QMessageBox.StandardButton.Yes
        set_break_attendance(fecha, break_id, took)

    # ── EOD auto-sync ─────────────────────────────────────────────────────────

    def _start_eod_sync_timer(self):
        self._eod_sync_timer = QTimer(self)
        self._eod_sync_timer.setInterval(60_000)
        self._eod_sync_timer.timeout.connect(self._check_eod_sync)
        self._eod_sync_timer.start()

    def _check_eod_sync(self):
        today = date.today()
        if today.weekday() >= 5:
            return
        now = datetime.now()
        if not (now.hour == 16 and now.minute == 55):
            return
        if self._eod_sync_triggered_date == today:
            return
        self._eod_sync_triggered_date = today
        log_event("main", "EOD auto-sync triggered at 16:55")
        self._silent_sync()
        if self._sync_status_label:
            self._sync_status_label.setText("↻ EOD sync…")
            self._sync_status_label.setStyleSheet("font-size: 10px; color: #aaa; padding-right: 4px;")

    # ── Daily performance / justification logic ───────────────────────────────

    @staticmethod
    def _is_weekday() -> bool:
        return date.today().weekday() < 5  # 0=Mon, 4=Fri

    def _start_eod_timer(self):
        if not _PERF_OK or not _JUSTIFICATION_ENABLED:
            return
        self._eod_timer = QTimer(self)
        self._eod_timer.setInterval(30_000)
        self._eod_timer.timeout.connect(self._check_eod_trigger)
        self._eod_timer.start()

    def _check_eod_trigger(self):
        if not _JUSTIFICATION_ENABLED or not self._is_weekday():
            return
        now = datetime.now()
        if now.hour < 15 or (now.hour == 15 and now.minute < 15):
            return
        today_str = date.today().isoformat()
        from db.database import get_connection
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT justification_submitted FROM daily_performance WHERE fecha = ?",
                (today_str,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        if row and row[0]:
            return
        metrics = get_daily_metrics(today_str)
        record_daily_snapshot(today_str, metrics)
        if metrics["met_target"]:
            return
        if metrics["production_pct"] == 0 and metrics["equivalent_units"] == 0:
            return
        self._eod_timer.stop()
        self._show_justification_popup(today_str, metrics)

    def _check_performance_after_save(self):
        if not _PERF_OK or not _JUSTIFICATION_ENABLED or not self._is_weekday():
            return
        today_str = date.today().isoformat()
        metrics = get_daily_metrics(today_str)
        record_daily_snapshot(today_str, metrics)
        if metrics["met_target"] and not was_success_shown(today_str):
            mark_success_shown(today_str)
            dlg = SuccessPopup(metrics, today_str, parent=self)
            dlg.exec()

    def _check_pending_justification_on_start(self):
        if not _PERF_OK or not _JUSTIFICATION_ENABLED or not self._is_weekday():
            return
        pending_date = has_pending_justification()
        if not pending_date:
            return
        metrics = get_daily_metrics(pending_date)
        self._show_justification_popup(pending_date, metrics)

    def _show_justification_popup(self, fecha: str, metrics: dict):
        if not _JUSTIFICATION_ENABLED:
            return
        self._justification_blocking = True
        dlg = JustificationPopup(metrics, fecha, parent=self)
        dlg.exec()
        text = dlg.justification_text
        if text:
            save_justification(fecha, text)
            try:
                from sync.app_config import load_config
                cfg = load_config()
                designer = cfg.get("designer_name", "")
                export_justification(designer, fecha, metrics, text)
            except Exception as exc:
                print(f"[main] Justification export failed: {exc}")
        self._justification_blocking = False

    def closeEvent(self, event):
        if _JUSTIFICATION_ENABLED:
            if self._justification_blocking:
                event.ignore()
                return
            if _PERF_OK and self._is_weekday():
                now = datetime.now()
                if now.hour > 15 or (now.hour == 15 and now.minute >= 15):
                    today_str = date.today().isoformat()
                    metrics = get_daily_metrics(today_str)
                    record_daily_snapshot(today_str, metrics)
                    if not metrics["met_target"] and (metrics["production_pct"] > 0 or metrics["equivalent_units"] > 0):
                        from db.database import get_connection
                        conn = get_connection()
                        try:
                            cur = conn.cursor()
                            cur.execute(
                                "SELECT justification_submitted FROM daily_performance WHERE fecha = ?",
                                (today_str,),
                            )
                            row = cur.fetchone()
                        finally:
                            conn.close()
                        if not row or not row[0]:
                            event.ignore()
                            self._show_justification_popup(today_str, metrics)
                            return
        # Warn if a manual sync operation (Sync dialog) is in progress.
        sync_dialog_busy = (
            self._sync_tab_widget is not None
            and self._sync_tab_widget.is_busy()
        )
        if sync_dialog_busy:
            reply = QMessageBox.question(
                self, "Sync In Progress",
                "A SharePoint sync operation is currently running.\n\n"
                "Closing now may leave the upload incomplete.\n\n"
                "Close anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        # Stop child timers explicitly so they can't fire after Qt cleanup.
        try:
            dm = getattr(self.register_tab, "downtime_manager", None)
            if dm is not None and hasattr(dm, "_stop_poll_timer"):
                dm._stop_poll_timer()
        except Exception:
            pass
        event.accept()

    def _check_first_use(self):
        """Show name confirmation dialog if the designer hasn't confirmed their name yet."""
        try:
            from sync.app_config import load_config, save_config, get_windows_display_name
            cfg = load_config()
            if cfg.get("name_confirmed"):
                return
            suggested = cfg.get("designer_name") or get_windows_display_name()

            dlg = QDialog(self)
            dlg.setWindowTitle("Setup — Your Name")
            dlg.setFixedWidth(380)
            dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
            layout = QVBoxLayout(dlg)
            layout.setContentsMargins(20, 18, 20, 18)
            layout.setSpacing(10)

            lbl = QLabel("Your name will appear on all production reports.\n"
                         "Confirm or change it:")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

            name_edit = QLineEdit(suggested)
            name_edit.setPlaceholderText("Your full name")
            layout.addWidget(name_edit)

            btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
            btns.accepted.connect(dlg.accept)
            layout.addWidget(btns)

            if dlg.exec() == QDialog.DialogCode.Accepted:
                name = name_edit.text().strip() or suggested
                cfg["designer_name"] = name
                cfg["name_confirmed"] = True
                save_config(cfg)
        except Exception as exc:
            log_event("main", f"first-use setup failed: {exc}", level="WARN")

    def _silent_sync(self):
        """Run export_to_sharepoint in background after a case is saved. No UI popup on success."""
        if self._sync_thread and self._sync_thread.isRunning():
            return  # skip if already running
        self._sync_thread = _SilentSyncThread()
        self._sync_thread.done.connect(self._on_silent_sync_done)
        self._sync_thread.start()
        if self._sync_status_label:
            self._sync_status_label.setText("↻ syncing…")
            self._sync_status_label.setStyleSheet("font-size: 10px; color: #aaa; padding-right: 4px;")

    def _on_silent_sync_done(self, ok: bool, msg: str):
        if not self._sync_status_label:
            return
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M")
        if ok:
            self._sync_status_label.setText(f"⬆ {ts}")
            self._sync_status_label.setStyleSheet("font-size: 10px; color: #66bb6a; padding-right: 4px;")
            self._sync_status_label.setToolTip(f"Last sync: {ts}\n{msg}")
            self._sync_status_label.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self._sync_status_label.setText(f"\u26a0 sync error")
            self._sync_status_label.setStyleSheet(
                "font-size: 10px; color: #ef9a9a; padding-right: 4px;"
                "text-decoration: underline; cursor: pointer;")
            self._sync_status_label.setToolTip(f"Click to see error detail\n\n{msg}")
            self._sync_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
            # Store msg so mousePressEvent can show it
            self._sync_status_label.setProperty("sync_error", msg)
            # Connect click only once
            try:
                self._sync_status_label.mousePressEvent = lambda e, m=msg: QMessageBox.warning(
                    self, "Sync Error", m)
            except Exception as exc:
                log_event("main", f"sync error click handler setup failed: {exc}", level="WARN")
    def on_standards_updated(self):
        """Reload standards and units_eq in Register and Production tabs when standards are modified."""
        load_units_eq_data(force=True)  # Invalidate shared cache so all tabs pick up new values
        self.register_tab.load_standards()
        self.register_tab.load_units_eq()
        self.register_tab.update_case_types()
        self.production_tab.load_units_eq()
        self.dashboard_tab._load_metadata()
        self.dashboard_tab.refresh()

    def on_production_case_updated(self):
        """Handle case update/delete from production tab"""
        # Check if production_tab has an editing_case_id (edit action)
        if hasattr(self.production_tab, 'editing_case_id') and self.production_tab.editing_case_id:
            # Route edit to Register depending on what was selected in ProductionTab
            editing_mode = getattr(self.production_tab, 'editing_mode', 'reg')
            db_id = self.production_tab.editing_case_id
            try:
                if editing_mode == 'ot':
                    self.register_tab.load_ot_case_for_edit(db_id)
                else:
                    self.register_tab.load_case_for_edit(db_id)
                self.tabs.setCurrentIndex(0)  # Always switch to Register tab
            finally:
                # clear editing marker on production tab
                self.production_tab.editing_case_id = None
        else:
            # Delete action — refresh whichever tab the deletion came from
            mode = getattr(self.production_tab, 'current_mode', 'reg')
            if mode == 'ot':
                self.register_tab._load_ot_day_cases()
                self.history_tab.load_all_cases()
                self.dashboard_tab.refresh()
            else:
                self.register_tab.load_daily_production()
                self.history_tab.load_all_cases()
                self.dashboard_tab.refresh()
        
        # Refresh history tab
        self.history_tab.load_all_cases()

    def _apply_style(self):
        """Re-apply the current stylesheet with the active font size."""
        base = self._light_style if self._is_light else self._dark_style
        styled = base.replace("font-size: 12px", f"font-size: {self._font_size}px")
        QApplication.instance().setStyleSheet(styled)

    def _apply_light_palette(self, colors: dict):
        mapping = {
            "#F6F8FA": colors.get("base_bg", DEFAULT_LIGHT_COLORS["base_bg"]),
            "#FFFFFF": colors.get("surface_bg", DEFAULT_LIGHT_COLORS["surface_bg"]),
            "#1F2328": colors.get("text_primary", DEFAULT_LIGHT_COLORS["text_primary"]),
            "#656D76": colors.get("text_muted", DEFAULT_LIGHT_COLORS["text_muted"]),
            "#D0D7DE": colors.get("border", DEFAULT_LIGHT_COLORS["border"]),
            "#0969DA": colors.get("accent", DEFAULT_LIGHT_COLORS["accent"]),
            "#DDF4FF": colors.get("selection_bg", DEFAULT_LIGHT_COLORS["selection_bg"]),
            "#EAEEF2": colors.get("button_bg", DEFAULT_LIGHT_COLORS["button_bg"]),
        }
        styled = self._light_style_base
        for old, new in mapping.items():
            if isinstance(new, str) and new.strip():
                styled = styled.replace(old, new.strip().upper())
        self._light_style = styled

    def _load_and_apply_light_palette(self):
        cfg = load_config()
        colors = cfg.get("light_theme_colors", {}) if isinstance(cfg, dict) else {}
        if not isinstance(colors, dict):
            colors = {}
        merged = dict(DEFAULT_LIGHT_COLORS)
        merged.update({k: v for k, v in colors.items() if k in DEFAULT_LIGHT_COLORS})
        self._apply_light_palette(merged)

    def _on_light_palette_changed(self, colors: dict):
        self._apply_light_palette(colors or {})
        if self._is_light:
            self._apply_style()
            try:
                self.themeChanged.emit(True)
            except Exception as exc:
                log_event("main", f"themeChanged emit after palette update failed: {exc}", level="WARN")

    def _change_font_size(self, delta: int):
        """Increment or decrement font size within [9, 18] range and re-apply style."""
        self._font_size = max(9, min(18, self._font_size + delta))
        self._apply_style()

    # ── Clipboard import shortcut ─────────────────────────────────────────────

    def _trigger_import_shortcut(self):
        """Ctrl+Shift+I — runs clipboard import on the currently visible tab."""
        current_widget = self.tabs.currentWidget()
        # Walk up the widget tree in case the tab is wrapped in a QScrollArea
        if hasattr(current_widget, 'widget'):
            current_widget = current_widget.widget()
        if hasattr(current_widget, '_on_import_case'):
            current_widget._on_import_case()
        else:
            self.statusBar().showMessage(
                "Clipboard import is only available in the Register tab.", 4000
            )

if __name__ == "__main__":
    # ── Self-installer: runs before Qt so no QApplication is needed yet ─────
    from self_installer import check_and_install, was_just_installed
    if check_and_install():
        sys.exit(0)

    # ── One-time legacy DB migration (pre-OneDrive path → OneDrive path) ────
    # Must run BEFORE init_db() so the data is in place before any schema work.
    _migration_msg = migrate_legacy_db()

    init_db()
    init_breaks_table()
    if _PERF_OK:
        init_performance_table()
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(_resource_path(os.path.join("data", "app_icon.ico"))))

    DARK_STYLE = """
    /* ── Base ──────────────────────────────────────────────── */
    QWidget {
        background-color: #0D1117;
        color: #E6EDF3;
        font-family: "Segoe UI";
        font-size: 12px;
    }
    QLabel { background: transparent; color: #E6EDF3; }
    QFrame { background: transparent; }
    QScrollArea { border: none; background: transparent; }

    /* ── Inputs ─────────────────────────────────────────────── */
    QLineEdit, QComboBox, QDateEdit, QTimeEdit,
    QTextEdit, QSpinBox, QDoubleSpinBox {
        background-color: #161B22;
        border: 1px solid #30363D;
        border-radius: 6px;
        padding: 5px 8px;
        color: #E6EDF3;
    }
    QComboBox { padding-right: 26px; }
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus,
    QTimeEdit:focus, QTextEdit:focus,
    QSpinBox:focus, QDoubleSpinBox:focus {
        border-color: #388BFD;
    }
    QLineEdit::placeholder, QTextEdit::placeholder { color: #6E7681; }

    QTimeEdit::up-button, QTimeEdit::down-button,
    QDateEdit::up-button, QDateEdit::down-button { width: 0; border: none; }
    QTimeEdit, QDateEdit { padding-right: 6px; }

    QComboBox::drop-down, QDateEdit::drop-down {
        border: none;
        width: 20px;
        border-left: 1px solid #30363D;
    }
    QComboBox::down-arrow, QDateEdit::down-arrow {}
    QComboBox QAbstractItemView {
        background-color: #161B22;
        color: #E6EDF3;
        border: 1px solid #30363D;
        selection-background-color: #1C2D4F;
        outline: none;
    }

    /* ── Buttons (neutral default — specific buttons override inline) ── */
    QPushButton {
        background-color: #21262D;
        border: 1px solid #30363D;
        border-radius: 6px;
        padding: 6px 14px;
        color: #E6EDF3;
        font-weight: 600;
    }
    QPushButton:hover {
        background-color: #30363D;
        border-color: #8B949E;
    }
    QPushButton:pressed { background-color: #161B22; }
    QPushButton:disabled { color: #6E7681; border-color: #21262D; }

    /* ── Tab bar (underline style) ──────────────────────────── */
    QTabWidget::pane {
        border-top: 1px solid #21262D;
        background: #0D1117;
    }
    QTabBar { background: #0D1117; border-bottom: 1px solid #21262D; }
    QTabBar::tab {
        background: transparent;
        color: #8B949E;
        padding: 8px 14px;
        margin-right: 1px;
        border: none;
        border-bottom: 2px solid transparent;
        font-weight: 500;
        font-size: 12px;
        min-width: 52px;
    }
    QTabBar::tab:hover { color: #C9D1D9; border-bottom-color: #30363D; }
    QTabBar::tab:selected {
        color: #E6EDF3;
        font-weight: 700;
        border-bottom: 2px solid #388BFD;
    }

    /* ── Cards (QGroupBox) ──────────────────────────────────── */
    QGroupBox {
        border: 1px solid #21262D;
        border-radius: 8px;
        margin-top: 18px;
        padding: 10px 12px 12px 12px;
        background-color: transparent;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 10px;
        padding: 2px 6px;
        color: #8B949E;
        font-size: 10px;
        font-weight: 700;
        background: #0D1117;
    }

    /* ── Progress bars ──────────────────────────────────────── */
    QProgressBar {
        background-color: #21262D;
        border: none;
        border-radius: 6px;
        text-align: center;
        min-height: 24px;
        color: #E6EDF3;
        font-weight: 700;
        font-size: 11px;
    }
    QProgressBar::chunk { background-color: #388BFD; border-radius: 6px; }

    /* ── Tables ─────────────────────────────────────────────── */
    QTableWidget {
        background-color: #0D1117;
        gridline-color: #21262D;
        selection-background-color: #1C2D4F;
        selection-color: #E6EDF3;
        border: none;
        border-radius: 6px;
    }
    QTableWidget::item { padding: 6px 8px; border: none; }
    QTableWidget::item:selected { background-color: #1C2D4F; }
    QHeaderView { background-color: #0D1117; }
    QHeaderView::section {
        background-color: #161B22;
        color: #8B949E;
        padding: 6px 8px;
        border: none;
        border-bottom: 1px solid #30363D;
        font-weight: 700;
        font-size: 10px;
    }

    /* ── Scrollbars ─────────────────────────────────────────── */
    QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
    QScrollBar::handle:vertical { background: #30363D; border-radius: 3px; min-height: 20px; }
    QScrollBar::handle:vertical:hover { background: #444C56; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
    QScrollBar:horizontal { background: transparent; height: 6px; margin: 0; }
    QScrollBar::handle:horizontal { background: #30363D; border-radius: 3px; min-width: 20px; }
    QScrollBar::handle:horizontal:hover { background: #444C56; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

    /* ── Status bar ─────────────────────────────────────────── */
    QStatusBar {
        background-color: #161B22;
        border-top: 1px solid #21262D;
        color: #8B949E;
        font-size: 11px;
    }

    /* ── Misc ───────────────────────────────────────────────── */
    QToolTip {
        background-color: #161B22;
        color: #E6EDF3;
        border: 1px solid #30363D;
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 11px;
    }
    QCheckBox { color: #8B949E; spacing: 5px; }
    QCheckBox::indicator {
        width: 14px; height: 14px;
        border: 1px solid #30363D; border-radius: 3px;
        background: #161B22;
    }
    QCheckBox::indicator:checked { background-color: #388BFD; border-color: #388BFD; }
    QDialog { background-color: #0D1117; }
    QMessageBox { background-color: #161B22; }
    """

    LIGHT_STYLE = """
    /* ── Base ──────────────────────────────────────────────── */
    QWidget {
        background-color: #F6F8FA;
        color: #1F2328;
        font-family: "Segoe UI";
        font-size: 12px;
    }
    QLabel { background: transparent; color: #1F2328; }
    QFrame { background: transparent; }
    QScrollArea { border: none; background: transparent; }

    /* ── Inputs ─────────────────────────────────────────────── */
    QLineEdit, QComboBox, QDateEdit, QTimeEdit,
    QTextEdit, QSpinBox, QDoubleSpinBox {
        background-color: #FFFFFF;
        border: 1px solid #D0D7DE;
        border-radius: 6px;
        padding: 5px 8px;
        color: #1F2328;
    }
    QComboBox { padding-right: 26px; }
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus,
    QTimeEdit:focus, QTextEdit:focus,
    QSpinBox:focus, QDoubleSpinBox:focus {
        border-color: #0969DA;
    }

    QTimeEdit::up-button, QTimeEdit::down-button,
    QDateEdit::up-button, QDateEdit::down-button { width: 0; border: none; }
    QTimeEdit, QDateEdit { padding-right: 6px; }

    QComboBox::drop-down, QDateEdit::drop-down {
        border: none;
        width: 20px;
        border-left: 1px solid #D0D7DE;
    }
    QComboBox::down-arrow, QDateEdit::down-arrow {}
    QComboBox QAbstractItemView {
        background-color: #FFFFFF;
        color: #1F2328;
        border: 1px solid #D0D7DE;
        selection-background-color: #DDF4FF;
        selection-color: #0969DA;
        outline: none;
    }

    /* ── Buttons ─────────────────────────────────────────────── */
    QPushButton {
        background-color: #EAEEF2;
        border: 1px solid #D0D7DE;
        border-radius: 6px;
        padding: 6px 14px;
        color: #1F2328;
        font-weight: 600;
    }
    QPushButton:hover { background-color: #DEE4EA; border-color: #B3BAC3; }
    QPushButton:pressed { background-color: #D0D7DE; }
    QPushButton:disabled { color: #8C959F; }

    /* ── Tab bar ─────────────────────────────────────────────── */
    QTabWidget::pane { border-top: 1px solid #D8DEE4; background: #F6F8FA; }
    QTabBar { background: #F6F8FA; border-bottom: 1px solid #D8DEE4; }
    QTabBar::tab {
        background: transparent;
        color: #656D76;
        padding: 8px 14px;
        margin-right: 1px;
        border: none;
        border-bottom: 2px solid transparent;
        font-weight: 500;
        font-size: 12px;
        min-width: 52px;
    }
    QTabBar::tab:hover { color: #1F2328; border-bottom-color: #D0D7DE; }
    QTabBar::tab:selected {
        color: #0969DA;
        font-weight: 700;
        border-bottom: 2px solid #0969DA;
    }

    /* ── Cards ───────────────────────────────────────────────── */
    QGroupBox {
        border: 1px solid #D0D7DE;
        border-radius: 8px;
        margin-top: 18px;
        padding: 10px 12px 12px 12px;
        background-color: #FFFFFF;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 10px;
        padding: 2px 6px;
        color: #656D76;
        font-size: 10px;
        font-weight: 700;
        background: #F6F8FA;
    }

    /* ── Progress bars ───────────────────────────────────────── */
    QProgressBar {
        background-color: #EAEEF2;
        border: none;
        border-radius: 6px;
        text-align: center;
        min-height: 24px;
        color: #1F2328;
        font-weight: 700;
        font-size: 11px;
    }
    QProgressBar::chunk { background-color: #0969DA; border-radius: 6px; }

    /* ── Tables ──────────────────────────────────────────────── */
    QTableWidget {
        background-color: #FFFFFF;
        gridline-color: #EAEEF2;
        selection-background-color: #DDF4FF;
        selection-color: #0969DA;
        border: 1px solid #D0D7DE;
        border-radius: 6px;
    }
    QTableWidget::item { padding: 6px 8px; }
    QTableWidget::item:selected { background-color: #DDF4FF; color: #0969DA; }
    QHeaderView { background-color: #FFFFFF; }
    QHeaderView::section {
        background-color: #F6F8FA;
        color: #656D76;
        padding: 6px 8px;
        border: none;
        border-bottom: 1px solid #D0D7DE;
        font-weight: 700;
        font-size: 10px;
    }

    /* ── Scrollbars ──────────────────────────────────────────── */
    QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
    QScrollBar::handle:vertical { background: #D0D7DE; border-radius: 3px; min-height: 20px; }
    QScrollBar::handle:vertical:hover { background: #B3BAC3; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
    QScrollBar:horizontal { background: transparent; height: 6px; }
    QScrollBar::handle:horizontal { background: #D0D7DE; border-radius: 3px; min-width: 20px; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

    /* ── Status bar ──────────────────────────────────────────── */
    QStatusBar {
        background-color: #FFFFFF;
        border-top: 1px solid #D0D7DE;
        color: #656D76;
        font-size: 11px;
    }

    /* ── Misc ────────────────────────────────────────────────── */
    QToolTip {
        background-color: #1F2328;
        color: #E6EDF3;
        border: 1px solid #30363D;
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 11px;
    }
    QCheckBox { color: #656D76; spacing: 5px; }
    QCheckBox::indicator {
        width: 14px; height: 14px;
        border: 1px solid #D0D7DE; border-radius: 3px;
        background: #FFFFFF;
    }
    QCheckBox::indicator:checked { background-color: #0969DA; border-color: #0969DA; }
    QDialog { background-color: #FFFFFF; }
    QMessageBox { background-color: #FFFFFF; }
    """

    app.setStyleSheet(DARK_STYLE)
    
    window = MainWindow(dark_style=DARK_STYLE, light_style=LIGHT_STYLE)
    window.show()
    QTimer.singleShot(400, window._check_first_use)

    # Cleanup old Excel exports in background (runs once per day, never touches DB)
    def _run_cleanup():
        import threading
        def _bg():
            try:
                from sync.cleanup import run_cleanup
                run_cleanup()
            except Exception as exc:
                print(f"[main] Cleanup error: {exc}")
                log_event("main", f"cleanup error: {exc}", level="WARN")
        threading.Thread(target=_bg, daemon=True).start()
    QTimer.singleShot(3000, _run_cleanup)

    # Startup safety backup (lightweight, background, non-blocking)
    def _run_startup_backup():
        import threading
        def _bg():
            try:
                from sync.safety_backup import run_startup_backups
                stats = run_startup_backups()
                log_event("main", f"startup backups done: {stats}")
            except Exception as exc:
                print(f"[main] Startup backup error: {exc}")
                log_event("main", f"startup backup error: {exc}", level="WARN")
        threading.Thread(target=_bg, daemon=True).start()
    QTimer.singleShot(1500, _run_startup_backup)

    # Background DB discovery/merge across common PC paths (time-bounded)
    def _run_background_db_discovery():
        import threading
        def _bg():
            try:
                cfg = load_config()
                if not bool(cfg.get("auto_discover_dbs", True)):
                    return
                summary = discover_and_merge_background_dbs(max_seconds=35)
                if summary:
                    log_event("main", summary)
                    print(f"[main] {summary}")
            except Exception as exc:
                print(f"[main] Background DB discovery error: {exc}")
                log_event("main", f"background DB discovery error: {exc}", level="WARN")
        threading.Thread(target=_bg, daemon=True).start()
    QTimer.singleShot(2500, _run_background_db_discovery)

    # Check for pending justifications from previous days
    if _PERF_OK and _JUSTIFICATION_ENABLED:
        QTimer.singleShot(1000, window._check_pending_justification_on_start)

    # Show a brief notice if the app was just self-installed
    if was_just_installed():
        window.statusBar().showMessage(
            "✓ Production Calc installed — shortcut created on your Desktop.", 8000
        )

    # Notify the user if their data was automatically migrated from the old location
    if _migration_msg:
        def _show_migration_notice():
            QMessageBox.information(
                window,
                "Datos migrados a OneDrive",
                _migration_msg
            )
        QTimer.singleShot(800, _show_migration_notice)

    sys.exit(app.exec())

