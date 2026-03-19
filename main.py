import sys
import os
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QScrollArea, QCheckBox,
    QPushButton, QMessageBox, QLabel, QLineEdit, QDialog,
    QVBoxLayout, QHBoxLayout, QDialogButtonBox
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut, QIcon
from db.database import init_db, migrate_legacy_db
from tabs.utils import load_units_eq_data
import qtawesome as qta


def _resource_path(relative: str) -> str:
    """Return absolute path to a bundled resource (works both frozen and in dev)."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)

# ============== VERSION ==============
APP_VERSION = "1.1.4"
DB_SCHEMA_VERSION = 1
# =====================================

from tabs.tab_register import RegisterTab
from tabs.tab_production import ProductionTab
from tabs.tab_history import HistoryTab
from tabs.tab_overtime import OvertimeTab
from tabs.tab_standards import StandardsTab
from tabs.tab_dashboard import DashboardTab
from tabs.tab_sync import SyncTab
from PySide6.QtWidgets import QDialog, QVBoxLayout as _QVBox

class _SilentSyncThread(QThread):
    """Run export_to_sharepoint silently in background after each case save."""
    done = Signal(bool, str)

    def run(self):
        try:
            from sync.sharepoint_sync import export_to_sharepoint, _OPENPYXL_OK
            from sync.app_config import load_config
            if not _OPENPYXL_OK:
                return
            cfg = load_config()
            if not cfg.get("name_confirmed") or not cfg.get("export_folder"):
                return  # silent skip if not configured yet
            import os as _os
            if not _os.path.isdir(cfg["export_folder"]):
                return
            ok, msg = export_to_sharepoint()
            self.done.emit(ok, msg)
        except Exception as e:
            self.done.emit(False, str(e))
class MainWindow(QMainWindow):
    themeChanged = Signal(bool)
    def __init__(self, dark_style="", light_style=""):
        super().__init__()
        self._dark_style = dark_style
        self._light_style = light_style
        self._font_size = 12
        self._is_light = False
        self.setWindowTitle(f"Production Performance Calculator v{APP_VERSION}")
        _ico = _resource_path(os.path.join("data", "app_icon.ico"))
        self.setWindowIcon(QIcon(_ico))

        self.tabs = QTabWidget()
        
        self.register_tab = RegisterTab()
        self.production_tab = ProductionTab()
        self.history_tab = HistoryTab()
        self.overtime_tab = OvertimeTab()
        self.standards_tab = StandardsTab()
        self.dashboard_tab = DashboardTab()
        self._sync_dialog = None  # created lazily
        self._sync_thread = None   # background sync thread
        self._sync_status_label = None  # statusbar indicator

        # Connect a themeChanged signal to tabs so they update their local styles
        try:
            self.themeChanged.connect(self.register_tab.update_theme_labels)
        except Exception:
            pass
        try:
            self.themeChanged.connect(self.overtime_tab.update_theme_labels)
        except Exception:
            pass
        try:
            self.themeChanged.connect(self.history_tab.update_theme_labels)
        except Exception:
            pass
        try:
            self.themeChanged.connect(self.production_tab.update_theme_labels)
        except Exception:
            pass
        try:
            self.themeChanged.connect(self.register_tab.update_progress_bar_style)
        except Exception:
            pass
        try:
            self.themeChanged.connect(self.overtime_tab.update_progress_bar_style)
        except Exception:
            pass
        try:
            self.themeChanged.connect(self.production_tab.update_theme_labels)
        except Exception:
            pass
        try:
            self.themeChanged.connect(self.dashboard_tab.update_theme_labels)
        except Exception:
            pass

        
        # Connect register tab to production tab for dynamic updates
        self.register_tab.case_saved.connect(self.production_tab.load_data)
        self.register_tab.case_saved.connect(self.history_tab.load_all_cases)
        self.register_tab.case_saved.connect(self.dashboard_tab.refresh)

        # Connect production tab edit/delete to register tab
        self.production_tab.case_updated.connect(self.on_production_case_updated)

        # Connect OT tab to refresh when cases change
        self.overtime_tab.ot_saved.connect(self.overtime_tab.load_ot_cases)
        self.overtime_tab.ot_saved.connect(self.overtime_tab.load_daily_ot_production)
        self.overtime_tab.ot_saved.connect(self.production_tab.load_data)
        self.overtime_tab.ot_saved.connect(self.history_tab.load_all_cases)
        self.overtime_tab.ot_saved.connect(self.dashboard_tab.refresh)
        
        # Connect standards tab to refresh Register and OT when standards change
        self.standards_tab.standards_updated.connect(self.on_standards_updated)

        # Auto-sync silently after every case save
        self.register_tab.case_saved.connect(self._silent_sync)
        self.overtime_tab.ot_saved.connect(self._silent_sync)
        
        self.tabs.addTab(self.register_tab,  qta.icon('fa5s.edit',            color="#b8ceb1"), "Register")
        self.tabs.addTab(self.overtime_tab,   qta.icon('fa5s.clock',           color='#b8ceb1'), "OT")
        self.tabs.addTab(self.production_tab, qta.icon('fa5s.chart-bar',       color='#b8ceb1'), "Production")
        self.tabs.addTab(self.history_tab,    qta.icon('fa5s.history',         color='#b8ceb1'), "History")
        self.tabs.addTab(self.standards_tab,  qta.icon('fa5s.cog',             color='#b8ceb1'), "Standards")
        self.tabs.addTab(self.dashboard_tab,  qta.icon('fa5s.tachometer-alt',  color='#b8ceb1'), "Dashboard")
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setUsesScrollButtons(True)

        self.setCentralWidget(self.tabs)

        # ── Global clipboard-import shortcut (Ctrl+Shift+I) ─────────────────────
        # After copying a case page (Ctrl+A, Ctrl+C in the browser), press
        # Ctrl+Shift+I here to auto-fill the Register or OT tab.
        import_shortcut = QShortcut(QKeySequence("Ctrl+Shift+I"), self)
        import_shortcut.activated.connect(self._trigger_import_shortcut)

        # Get screen height for maximum window height
        screen = QGuiApplication.primaryScreen()
        screen_height = screen.availableGeometry().height()
        
        # Set size constraints - resizable with min/max
        self.setMinimumSize(640, 550)  # Minimum width 640px
        self.setMaximumSize(900, screen_height)  # Maximum height = monitor height
        self.resize(900, 700)  # Default size 900x700
        # Theme toggle checkbox in status bar
        try:
            light_chk = QCheckBox("Light")
            light_chk.setToolTip("Toggle light mode")
            def on_theme_toggled(checked):
                self._is_light = checked
                self._apply_style()
                # Emit a single signal so tabs update themselves (clean approach)
                try:
                    self.themeChanged.emit(checked)
                except Exception:
                    # Fallback: call known updaters directly if emit fails
                    try:
                        self.register_tab.update_progress_bar_style(checked)
                    except Exception:
                        pass
                    try:
                        self.overtime_tab.update_progress_bar_style(checked)
                    except Exception:
                        pass
                    try:
                        self.production_tab.update_theme_labels(checked)
                    except Exception:
                        pass
                    try:
                        self.register_tab.update_theme_labels(checked)
                    except Exception:
                        pass
                    try:
                        self.overtime_tab.update_theme_labels(checked)
                    except Exception:
                        pass

            light_chk.toggled.connect(on_theme_toggled)
            self.statusBar().addPermanentWidget(light_chk)

            # Font size buttons
            from PySide6.QtWidgets import QPushButton as _QPB
            btn_fup = _QPB("A+")
            btn_fup.setFixedSize(30, 20)
            btn_fup.setToolTip("Increase font size")
            btn_fup.setStyleSheet("font-size: 10px; padding: 1px 3px; font-weight: bold;")
            btn_fdn = _QPB("A-")
            btn_fdn.setFixedSize(30, 20)
            btn_fdn.setToolTip("Decrease font size")
            btn_fdn.setStyleSheet("font-size: 10px; padding: 1px 3px; font-weight: bold;")
            btn_fup.clicked.connect(lambda: self._change_font_size(1))
            btn_fdn.clicked.connect(lambda: self._change_font_size(-1))
            self.statusBar().addPermanentWidget(btn_fdn)
            self.statusBar().addPermanentWidget(btn_fup)

            # Sync button
            btn_sync = _QPB("⬆ Sync")
            btn_sync.setFixedSize(54, 20)
            btn_sync.setToolTip("Export to SharePoint")
            btn_sync.setStyleSheet("font-size: 10px; padding: 1px 3px; font-weight: bold; background:#2E75B6; color:white; border-radius:3px;")
            btn_sync.clicked.connect(self._open_sync_dialog)
            self.statusBar().addPermanentWidget(btn_sync)

            # Sync status indicator (last sync time)
            self._sync_status_label = QLabel("")
            self._sync_status_label.setStyleSheet("font-size: 10px; color: #888; padding-right: 4px;")
            self.statusBar().addWidget(self._sync_status_label)
        except Exception:
            pass

    def _open_sync_dialog(self):
        """Open the Sync panel as a floating dialog."""
        if self._sync_dialog is None:
            self._sync_dialog = QDialog(self)
            self._sync_dialog.setWindowTitle("SharePoint Sync")
            self._sync_dialog.setMinimumSize(520, 480)
            layout = QVBoxLayout(self._sync_dialog)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(SyncTab())
        self._sync_dialog.show()
        self._sync_dialog.raise_()
        self._sync_dialog.activateWindow()
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
        except Exception:
            pass

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
            except Exception:
                pass
    def on_standards_updated(self):
        """Reload standards and units_eq in Register, OT and Production tabs when standards are modified"""
        load_units_eq_data(force=True)  # Invalidate shared cache so all tabs pick up new values
        self.register_tab.load_standards()
        self.register_tab.load_units_eq()
        self.register_tab.update_case_types()
        self.overtime_tab.load_standards()
        self.overtime_tab.load_units_eq()
        self.overtime_tab.update_case_types()
        self.production_tab.load_units_eq()
        self.dashboard_tab._load_metadata()
        self.dashboard_tab.refresh()

    def on_production_case_updated(self):
        """Handle case update/delete from production tab"""
        # Check if production_tab has an editing_case_id (edit action)
        if hasattr(self.production_tab, 'editing_case_id') and self.production_tab.editing_case_id:
            # Route edit to Register or OT depending on what was selected in ProductionTab
            editing_mode = getattr(self.production_tab, 'editing_mode', 'reg')
            db_id = self.production_tab.editing_case_id
            try:
                if editing_mode == 'ot':
                    # Load into OT tab form
                    try:
                        self.overtime_tab.load_case_for_edit(db_id)
                    except Exception:
                        # fallback if method missing
                        self.overtime_tab.editing_ot_id = db_id
                    # Switch to OT tab (index 1)
                    self.tabs.setCurrentIndex(1)
                else:
                    # Default: load into Register tab
                    self.register_tab.load_case_for_edit(db_id)
                    self.tabs.setCurrentIndex(0)
            finally:
                # clear editing marker on production tab
                self.production_tab.editing_case_id = None
        else:
            # Delete action — refresh whichever tab the deletion came from
            mode = getattr(self.production_tab, 'current_mode', 'reg')
            if mode == 'ot':
                self.overtime_tab.load_ot_cases()
                self.overtime_tab.load_daily_ot_production()
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
                "Clipboard import is only available in the Register and OT tabs.", 4000
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
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(_resource_path(os.path.join("data", "app_icon.ico"))))

    DARK_STYLE = """
    QWidget {
        background-color: #1e1e1e;
        color: #e6e6e6;
        font-family: Segoe UI;
        font-size: 12px;
    }

    QLabel {
        color: #e6e6e6;
    }

    QLineEdit, QComboBox, QDateEdit, QTimeEdit {
        background-color: #2b2b2b;
        border: 1px solid #3c3c3c;
        border-radius: 6px;
        padding: 6px;
        color: #e6e6e6;
    }

    QTimeEdit::up-button, QTimeEdit::down-button,
    QDateEdit::up-button, QDateEdit::down-button {
        width: 0px;
        border: none;
    }

    QTimeEdit, QDateEdit {
        padding-right: 6px;
    }

    QComboBox {
        background-color: #2b2b2b;
        border: 1px solid #3c3c3c;
        border-radius: 6px;
        padding: 6px;
    }

    QComboBox QAbstractItemView {
        background-color: #2b2b2b;
        color: #e6e6e6;
        selection-background-color: #2d89ef;
        border: 1px solid #3c3c3c;
        outline: none;
    }

    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus {
        border: 1px solid #4aa3ff;
    }

    QPushButton {
        background-color: #2d89ef;
        border: none;
        border-radius: 6px;
        padding: 8px 14px;
        color: white;
        font-weight: bold;
    }

    QPushButton:hover {
        background-color: #1e6fd9;
    }

    QPushButton:pressed {
        background-color: #165ab8;
    }

    QPushButton:disabled {
        background-color: #555;
    }

    QTabWidget::pane {
        border: 1px solid #3c3c3c;
        margin-top: 5px;
    }

    QTabBar::tab {
        background: #2b2b2b;
        padding: 4px 6px;
        border-radius: 6px;
        margin-left: 3px;
        margin-right: 1px;
        margin-top: 8px;
        margin-bottom: 4px;
        border: 1px solid #3c3c3c;
        color: #999;
        font-weight: 500;
        font-size: 11px;
        min-width: 40px;
    }

    QTabBar::tab:hover {
        background: #333;
        color: #e6e6e6;
    }

    QTabBar::tab:selected {
        background: #2d89ef;
        color: white;
        border: 1px solid #2d89ef;
    }

    QGroupBox {
        border: 1px solid #3c3c3c;
        border-radius: 8px;
        margin-top: 10px;
        padding: 10px;
        color: #e6e6e6;
    }

    QGroupBox:title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 6px;
        color: #4aa3ff;
        font-weight: bold;
    }

    QProgressBar {
        border: 1px solid #3c3c3c;
        border-radius: 8px;
        text-align: center;
        height: 24px;
        background-color: #2b2b2b;
        color: #ffffff;
    }

    QProgressBar::chunk {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #2d89ef, stop:0.5 #4CAF50, stop:1 #2d89ef);
        border-radius: 6px;
    }

    QTableWidget {
        gridline-color: #3c3c3c;
        selection-background-color: #2d89ef;
    }

    QTableWidget::item {
        padding: 6px;
    }

    QHeaderView::section {
        background-color: #2d89ef;
        color: white;
        padding: 6px;
        border: none;
        font-weight: bold;
    }
    """

    LIGHT_STYLE = """
    QWidget {
        background-color: #F7ECE1; /* main background */
        color: #242038; /* primary text */
        font-family: Segoe UI;
        font-size: 12px;
    }

    QLabel {
        color: #242038;
    }

    QLineEdit, QComboBox, QDateEdit, QTimeEdit {
        background-color: #ffffff;
        border: 1px solid #CAC4CE;
        border-radius: 6px;
        padding: 6px;
        color: #242038;
    }

    QTimeEdit::up-button, QTimeEdit::down-button,
    QDateEdit::up-button, QDateEdit::down-button {
        width: 0px;
        border: none;
    }

    QTimeEdit, QDateEdit {
        padding-right: 6px;
    }

    QComboBox {
        background-color: #ffffff;
        border: 1px solid #CAC4CE;
        border-radius: 6px;
        padding: 6px;
    }

    QComboBox QAbstractItemView {
        background-color: #ffffff;
        color: #242038;
        selection-background-color: #8D86C9;
        border: 1px solid #CAC4CE;
        outline: none;
    }

    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus {
        border: 1px solid #725AC1;
    }

    QPushButton {
        background-color: #725AC1; /* primary action */
        border: none;
        border-radius: 6px;
        padding: 8px 14px;
        color: white;
        font-weight: bold;
    }

    QPushButton:hover {
        background-color: #8D86C9; /* hover */
    }

    QPushButton:pressed {
        background-color: #5e489f;
    }

    QPushButton:disabled {
        background-color: #CAC4CE;
    }

    QTabWidget::pane {
        border: 1px solid #CAC4CE;
        margin-top: 5px;
    }

    QTabBar::tab {
        background: #8D86C9;
        padding: 6px 10px;
        border-radius: 6px;
        margin-left: 6px;
        margin-right: 2px;
        margin-top: 8px;
        margin-bottom: 4px;
        border: 1px solid #8D86C9;
        color: white;
        font-weight: 500;
        min-width: 64px;
    }

    QTabBar::tab:hover {
        background: #9b94d1;
        color: white;
    }

    QTabBar::tab:selected {
        background: #8D86C9;
        color: white;
        border: 1px solid #8D86C9;
    }

    QGroupBox {
        border: 1px solid #CAC4CE;
        border-radius: 8px;
        margin-top: 10px;
        padding: 10px;
        color: #242038;
    }

    QGroupBox:title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 6px;
        color: #725AC1;
        font-weight: bold;
    }

    QProgressBar {
        border: 1px solid #8D86C9;
        border-radius: 8px;
        text-align: center;
        height: 24px;
        background-color: #8D86C9; /* production bar background */
        color: #ffffff;
    }

    QProgressBar::chunk {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #2b2b2b, stop:0.5 #1e1e1e, stop:1 #2b2b2b);
        border-radius: 6px;
    }

    QTableWidget {
        gridline-color: #CAC4CE;
        selection-background-color: #8D86C9;
    }

    QTableWidget::item {
        padding: 6px;
    }

    QHeaderView::section {
        background-color: #8D86C9;
        color: white;
        padding: 6px;
        border: none;
        font-weight: bold;
    }
    """

    app.setStyleSheet(DARK_STYLE)
    
    window = MainWindow(dark_style=DARK_STYLE, light_style=LIGHT_STYLE)
    window.show()
    QTimer.singleShot(400, window._check_first_use)

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

