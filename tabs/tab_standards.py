import json
import os
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QLabel,
    QTreeWidget, QTreeWidgetItem, QFileDialog, QMessageBox, QLineEdit,
    QHeaderView, QDialog, QFormLayout, QDialogButtonBox, QComboBox,
    QTableWidget, QTableWidgetItem, QDoubleSpinBox, QCheckBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from .utils import (
    get_resource_path,
    get_writable_path,
    load_units_eq_data,
    DAILY_BASE_MINUTES,
    DAILY_TARGET_EQ_UNITS,
)


def card(title, widget):
    """Helper function to create styled card/groupbox"""
    box = QGroupBox(title)
    layout = QVBoxLayout()
    layout.addWidget(widget) if isinstance(widget, QWidget) else layout.addLayout(widget)
    box.setLayout(layout)
    return box


def case_type_sort_key(case_type: str):
    """Sort case types in the business-required order for UI display/editing."""
    order = {
        "primary": 0,
        "secondary": 1,
        "cr": 2,
        "stage rx primary": 3,
        "stage rx secondary": 4,
        "stage rx cr": 5,
        "bite sync primary": 6,
        "bite sync secondary": 7,
        "bite sync cr": 8,
    }
    normalized = (case_type or "").strip().lower()
    return (order.get(normalized, 999), normalized)


class EditStandardDialog(QDialog):
    """Dialog for editing a standard time and equivalent units value"""
    def __init__(self, region, case_type, current_time, current_ue, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Standard")
        self.setMinimumWidth(320)

        layout = QVBoxLayout()

        info_layout = QFormLayout()
        info_layout.addRow("Region:", QLabel(region))
        info_layout.addRow("Type:", QLabel(case_type))

        self.value_input = QLineEdit(str(current_time))
        self.value_input.setPlaceholderText("Enter time in minutes")
        info_layout.addRow("Std Time (min):", self.value_input)

        self.ue_input = QLineEdit(str(current_ue))
        self.ue_input.setPlaceholderText("Equiv. units per case")
        info_layout.addRow("Equiv. Units:", self.ue_input)

        layout.addLayout(info_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def get_time(self):
        try:
            return float(self.value_input.text())
        except ValueError:
            return None

    def get_ue(self):
        try:
            return float(self.ue_input.text())
        except ValueError:
            return None


class AddTypeDialog(QDialog):
    """Dialog for adding a new case type"""
    def __init__(self, regions, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Case Type")
        self.setMinimumWidth(350)
        
        layout = QVBoxLayout()
        
        form_layout = QFormLayout()
        
        # Region selector
        self.region_combo = QComboBox()
        self.region_combo.addItems(regions)
        form_layout.addRow("Region:", self.region_combo)
        
        # Type name input
        self.type_input = QLineEdit()
        self.type_input.setPlaceholderText("e.g., Stage RX Primary")
        form_layout.addRow("Type Name:", self.type_input)
        
        # Std time input
        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("Time in minutes")
        form_layout.addRow("Standard Time:", self.value_input)

        # UE input
        self.ue_input = QLineEdit()
        self.ue_input.setPlaceholderText("Equiv. units per case")
        form_layout.addRow("Equiv. Units:", self.ue_input)

        layout.addLayout(form_layout)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def get_data(self):
        try:
            value = float(self.value_input.text())
            ue = float(self.ue_input.text()) if self.ue_input.text().strip() else None
            return {
                'region': self.region_combo.currentText(),
                'type': self.type_input.text().strip(),
                'value': value,
                'ue': ue,
            }
        except ValueError:
            return None


class AddRegionDialog(QDialog):
    """Dialog for adding a new region with existing types selection"""
    def __init__(self, existing_regions, all_standards, all_units_eq=None, parent=None):
        super().__init__(parent)
        self.existing_regions = existing_regions
        self.all_standards = all_standards
        self.all_units_eq = all_units_eq or {}
        self.type_rows = []  # List to track type checkboxes and spinboxes
        self.setWindowTitle("Add New Region")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        
        layout = QVBoxLayout()
        
        # Region name input
        region_layout = QHBoxLayout()
        region_layout.addWidget(QLabel("Region Name:"))
        self.region_input = QLineEdit()
        self.region_input.setPlaceholderText("e.g., LATAM, APAC, etc.")
        region_layout.addWidget(self.region_input)
        layout.addLayout(region_layout)
        
        # Existing types section
        types_label = QLabel("Select existing types to include:")
        types_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(types_label)
        
        # Get all unique types from all regions
        self.all_types = self.get_all_unique_types()
        
        # Table for existing types
        self.types_table = QTableWidget()
        self.types_table.setColumnCount(4)
        self.types_table.setHorizontalHeaderLabels(["Include", "Type Name", "Time (min)", "Equiv. Units"])
        self.types_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.types_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.types_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.types_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.types_table.setColumnWidth(0, 60)
        self.types_table.setColumnWidth(2, 90)
        self.types_table.setColumnWidth(3, 90)
        self.types_table.verticalHeader().setVisible(False)

        # Populate with existing types
        self.types_table.setRowCount(len(self.all_types))
        for row, (type_name, (default_time, default_ue)) in enumerate(self.all_types.items()):
            checkbox = QCheckBox()
            checkbox.setStyleSheet("margin-left: 20px;")
            self.types_table.setCellWidget(row, 0, checkbox)

            name_item = QTableWidgetItem(type_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.types_table.setItem(row, 1, name_item)

            spinbox = QDoubleSpinBox()
            spinbox.setRange(0.01, 9999.99)
            spinbox.setDecimals(2)
            spinbox.setValue(default_time)
            self.types_table.setCellWidget(row, 2, spinbox)

            ue_spinbox = QDoubleSpinBox()
            ue_spinbox.setRange(0.001, 999.999)
            ue_spinbox.setDecimals(2)
            ue_spinbox.setValue(default_ue)
            self.types_table.setCellWidget(row, 3, ue_spinbox)

            self.type_rows.append((checkbox, type_name, spinbox, ue_spinbox))
        
        layout.addWidget(self.types_table)
        
        # Custom type section
        custom_label = QLabel("Or add a custom type:")
        custom_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(custom_label)
        
        custom_layout = QHBoxLayout()
        self.custom_type_input = QLineEdit()
        self.custom_type_input.setPlaceholderText("Custom type name")
        custom_layout.addWidget(self.custom_type_input)
        
        self.custom_time_input = QLineEdit()
        self.custom_time_input.setPlaceholderText("Time (min)")
        self.custom_time_input.setFixedWidth(80)
        custom_layout.addWidget(self.custom_time_input)
        layout.addLayout(custom_layout)
        
        # Info label
        info = QLabel("Note: Select at least one type or add a custom type.")
        info.setStyleSheet("color: #888; font-size: 11px; margin-top: 5px;")
        layout.addWidget(info)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def get_all_unique_types(self):
        """Get all unique types across all regions with (time, ue) tuples"""
        types = {}
        for region, data in self.all_standards.items():
            if "Aligners" in data:
                reg_ue = self.all_units_eq.get(region, {})
                for type_name, time_value in data["Aligners"].items():
                    if type_name not in types:
                        ue_val = reg_ue.get(type_name, round((time_value / 408.3) * 14.0, 3))
                        types[type_name] = (time_value, ue_val)
        return dict(sorted(types.items(), key=lambda item: case_type_sort_key(item[0])))
    
    def validate_and_accept(self):
        region = self.region_input.text().strip()
        if not region:
            QMessageBox.warning(self, "Error", "Please enter a region name.")
            return
        if region in self.existing_regions:
            QMessageBox.warning(self, "Error", f"Region '{region}' already exists.")
            return
        
        # Check if at least one type is selected or custom type is provided
        has_selected = any(cb.isChecked() for cb, _, _, _ in self.type_rows)
        has_custom = bool(self.custom_type_input.text().strip())
        
        if not has_selected and not has_custom:
            QMessageBox.warning(self, "Error", "Please select at least one type or add a custom type.")
            return
        
        # Validate custom type if provided
        if has_custom:
            try:
                float(self.custom_time_input.text())
            except ValueError:
                QMessageBox.warning(self, "Error", "Please enter a valid time for the custom type.")
                return
        
        self.accept()
    
    def get_data(self):
        """Return region name and dict of types with times"""
        types = {}
        
        # Get selected existing types
        for checkbox, type_name, spinbox, ue_spinbox in self.type_rows:
            if checkbox.isChecked():
                types[type_name] = (spinbox.value(), ue_spinbox.value())

        # Add custom type if provided
        custom_name = self.custom_type_input.text().strip()
        if custom_name:
            try:
                custom_time = float(self.custom_time_input.text())
                ue_val = round((custom_time / 408.3) * 14.0, 3)
                types[custom_name] = (custom_time, ue_val)
            except ValueError:
                pass

        return {
            'region': self.region_input.text().strip(),
            'types': types,
        }


class StandardsTab(QWidget):
    standards_updated = Signal()  # Signal emitted when standards are modified

    def __init__(self):
        super().__init__()
        self.standards = {}
        self.units_eq = {}
        self.load_standards()
        self.load_units_eq()
        self.init_ui()
    
    @staticmethod
    def _inject_new_impressions(standards: dict):
        """Ensure every region has 'New Impressions' = same value as 'Secondary'.

        Called after loading/importing standards so the type is always present
        even if the JSON doesn't contain it explicitly.
        """
        for region, data in standards.items():
            aligners = data.get("Aligners", {}) if isinstance(data, dict) else {}
            if not isinstance(aligners, dict):
                continue
            sec_val = aligners.get("Secondary")
            if sec_val is not None:
                aligners["New Impressions"] = sec_val

    def load_standards(self):
        """Load standards from JSON file"""
        standards_path = get_resource_path(os.path.join("data", "standards.json"))
        try:
            with open(standards_path, "r", encoding="utf-8-sig") as f:
                self.standards = json.load(f)
        except Exception as e:
            print(f"Error loading standards: {e}")
            self.standards = {}
        self._inject_new_impressions(self.standards)

    def load_units_eq(self):
        """Load equivalent units from JSON file"""
        self.units_eq = load_units_eq_data()

    def recalculate_units_eq_from_standards(self):
        """Rebuild units_eq from current standard times using the shared UE target."""
        recalculated = {}
        for region, data in (self.standards or {}).items():
            aligners = data.get("Aligners", {}) if isinstance(data, dict) else {}
            if not isinstance(aligners, dict):
                continue

            recalculated[region] = {}
            for case_type, time_value in aligners.items():
                try:
                    std_time = float(time_value)
                except (TypeError, ValueError):
                    continue
                ue_value = (std_time / DAILY_BASE_MINUTES) * DAILY_TARGET_EQ_UNITS
                recalculated[region][case_type] = round(ue_value, 3)

        self.units_eq = recalculated

    def save_standards(self):
        """Save standards to JSON file"""
        standards_path = get_writable_path(os.path.join("data", "standards.json"))
        try:
            os.makedirs(os.path.dirname(standards_path), exist_ok=True)
            with open(standards_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(self.standards, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving standards: {e}")
            return False

    def save_units_eq(self):
        """Save equivalent units to JSON file"""
        path = get_writable_path(os.path.join("data", "units_eq.json"))
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(self.units_eq, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving units_eq: {e}")
            return False
    
    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # Title — centered
        title_label = QLabel("Standard Times Configuration")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #4aa3ff;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)

        # Buttons row — right-aligned
        header_layout = QHBoxLayout()
        header_layout.addStretch()

        # Import button
        import_btn = QPushButton("Import JSON")
        import_btn.setMaximumWidth(100)
        import_btn.clicked.connect(self.import_json)
        header_layout.addWidget(import_btn)

        # Export button
        export_btn = QPushButton("Export JSON")
        export_btn.setMaximumWidth(100)
        export_btn.clicked.connect(self.export_json)
        header_layout.addWidget(export_btn)

        # Reload button
        reload_btn = QPushButton("Reload")
        reload_btn.setMaximumWidth(80)
        reload_btn.clicked.connect(self.reload_standards)
        header_layout.addWidget(reload_btn)

        main_layout.addLayout(header_layout)
        
        # Tree widget for displaying standards
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Region / Type", "Std Time (min)", "UE"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)

        # Set column widths
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)
        self.tree.setColumnWidth(1, 130)
        self.tree.setColumnWidth(2, 120)
        
        # Style the tree
        self.tree.setStyleSheet("""
            QTreeWidget {
                background-color: #2b2b2b;
                alternate-background-color: #333338;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
            }
            QTreeWidget::item {
                padding: 4px;
            }
            QTreeWidget::item:selected {
                background-color: #3c3c3c;
            }
            QHeaderView::section {
                background-color: #3c3c3c;
                border: 1px solid #5a5a5a;
                padding: 6px;
                font-weight: bold;
            }
        """)
        
        main_layout.addWidget(self.tree)
        
        # Info label
        info_label = QLabel("Double-click a type to view its details.")
        info_label.setStyleSheet("color: #888; font-size: 11px;")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(info_label)
        
        self.setLayout(main_layout)
        self.populate_tree()

    def update_theme_labels(self, is_light: bool):
        """Update tree widget colors when theme changes."""
        from PySide6.QtGui import QBrush, QColor

        if is_light:
            # Light mode: fondo claro, texto oscuro
            fg_color = QColor(36, 32, 56)   # #242038
            tree_css = """
                QTreeWidget {
                    background-color: #ffffff;
                    alternate-background-color: #f0eef5;
                    border: 1px solid #CAC4CE;
                    border-radius: 6px;
                    color: #242038;
                }
                QTreeWidget::item {
                    padding: 4px;
                    color: #242038;
                }
                QTreeWidget::item:selected {
                    background-color: #8D86C9;
                    color: #ffffff;
                }
                QHeaderView::section {
                    background-color: #8D86C9;
                    color: #ffffff;
                    border: 1px solid #CAC4CE;
                    padding: 6px;
                    font-weight: bold;
                }
            """
        else:
            # Dark mode: fondo oscuro, texto claro
            fg_color = QColor(230, 230, 230)  # #e6e6e6
            tree_css = """
                QTreeWidget {
                    background-color: #2b2b2b;
                    alternate-background-color: #333338;
                    border: 1px solid #3c3c3c;
                    border-radius: 6px;
                }
                QTreeWidget::item {
                    padding: 4px;
                }
                QTreeWidget::item:selected {
                    background-color: #3c3c3c;
                }
                QHeaderView::section {
                    background-color: #3c3c3c;
                    border: 1px solid #5a5a5a;
                    padding: 6px;
                    font-weight: bold;
                }
            """

        self.tree.setStyleSheet(tree_css)

        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                child.setForeground(0, QBrush(fg_color))
                child.setForeground(1, QBrush(fg_color))
                child.setForeground(2, QBrush(fg_color))
                walk(child)

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top.setForeground(0, QBrush(fg_color))
            top.setForeground(1, QBrush(fg_color))
            top.setForeground(2, QBrush(fg_color))
            walk(top)
    
    def populate_tree(self):
        """Populate the tree widget with standards data"""
        self.tree.clear()

        for region, data in sorted(self.standards.items()):
            region_item = QTreeWidgetItem([region, "", ""])
            region_item.setFont(0, QFont("Segoe UI", 11, QFont.Weight.Bold))
            region_item.setExpanded(True)

            if "Aligners" in data:
                for case_type, time_value in sorted(
                    data["Aligners"].items(), key=lambda item: case_type_sort_key(item[0])
                ):
                    ue_per_case = self._resolve_ue_value(region, case_type, time_value)
                    ue_str = f"{ue_per_case:.2f}" if ue_per_case is not None else ""
                    type_item = QTreeWidgetItem([case_type, f"{time_value:.2f}", ue_str])
                    type_item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
                    type_item.setTextAlignment(2, Qt.AlignmentFlag.AlignCenter)
                    region_item.addChild(type_item)

            self.tree.addTopLevelItem(region_item)
    
    def on_item_double_clicked(self, item, column):
        """Handle double-click to view type details (read-only)."""
        if item.parent() is None:
            return  # region row, ignore

        region = item.parent().text(0)
        case_type = item.text(0)
        current_time = self.standards.get(region, {}).get("Aligners", {}).get(case_type, 0)
        current_ue = self._resolve_ue_value(region, case_type, current_time) or 0

        dlg = QDialog(self)
        dlg.setWindowTitle("Standard Details")
        dlg.setFixedWidth(420)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        lbl = QLabel(
            f"<b>Region:</b>  {region}<br>"
            f"<b>Type:</b>  {case_type}<br><br>"
            f"<b>Std Time:</b>  {current_time:.2f} min<br>"
            f"<b>Equiv. Units:</b>  {current_ue:.2f}"
        )
        lbl.setStyleSheet("font-size: 13px;")
        layout.addWidget(lbl)

        ok_btn = QPushButton("OK")
        ok_btn.setFixedWidth(80)
        ok_btn.clicked.connect(dlg.accept)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        dlg.exec()

    def _resolve_ue_value(self, region, case_type, time_value):
        """Return UE value for display/edit, preferring explicit per-case values.

        Priority:
          1) units_eq[region][case_type] (if present)
          2) (std_time / 408.3) * units_eq[region]["100"] (legacy fallback)
        """
        reg_ue = self.units_eq.get(region, {})
        if isinstance(reg_ue, dict):
            explicit = reg_ue.get(case_type)
            if isinstance(explicit, (int, float)):
                return float(explicit)
            if explicit is not None:
                try:
                    return float(explicit)
                except (TypeError, ValueError):
                    pass

            base_rate = reg_ue.get("100", 0.0)
            try:
                base_rate = float(base_rate)
            except (TypeError, ValueError):
                base_rate = 0.0

            if base_rate and time_value:
                return (float(time_value) / DAILY_BASE_MINUTES) * base_rate

        return None
    
    def edit_selected(self):
        """Edit the currently selected item"""
        item = self.tree.currentItem()
        if item and item.parent() is not None:
            self.edit_item(item)
        else:
            QMessageBox.information(self, "Info", "Please select a case type to edit.")
    
    def add_region(self):
        """Add a new region"""
        dialog = AddRegionDialog(list(self.standards.keys()), self.standards, self.units_eq, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if data and data['types']:
                region = data['region']
                # data['types'] is now {type: (time, ue)}
                self.standards[region] = {
                    "Aligners": {t: tv[0] for t, tv in data['types'].items()}
                }
                self.units_eq[region] = {t: tv[1] for t, tv in data['types'].items()}
                self.populate_tree()
    
    def add_type(self):
        """Add a new case type"""
        dialog = AddTypeDialog(list(self.standards.keys()), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if data and data['type'] and data['value'] > 0:
                region = data['region']
                if region in self.standards:
                    if "Aligners" not in self.standards[region]:
                        self.standards[region]["Aligners"] = {}
                    self.standards[region]["Aligners"][data['type']] = data['value']
                    # UE: user-provided or compute from std_time as default
                    ue_val = data.get('ue') or round((data['value'] / 408.3) * 14.0, 3)
                    if region not in self.units_eq:
                        self.units_eq[region] = {}
                    self.units_eq[region][data['type']] = ue_val
                    self.populate_tree()
    
    def delete_selected(self):
        """Delete the currently selected item"""
        item = self.tree.currentItem()
        if not item:
            QMessageBox.information(self, "Info", "Please select an item to delete.")
            return

        if item.parent() is None:
            region = item.text(0)
            reply = QMessageBox.question(
                self, "Confirm Delete",
                f"Delete entire region '{region}' and all its types?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                del self.standards[region]
                self.units_eq.pop(region, None)
                self.populate_tree()
        else:
            region = item.parent().text(0)
            case_type = item.text(0)
            reply = QMessageBox.question(
                self, "Confirm Delete",
                f"Delete type '{case_type}' from '{region}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                del self.standards[region]["Aligners"][case_type]
                self.units_eq.get(region, {}).pop(case_type, None)
                self.populate_tree()
    
    def save_changes(self):
        """Save changes to file and notify other tabs"""
        ok1 = self.save_standards()
        ok2 = self.save_units_eq()
        if ok1 and ok2:
            # Bust module-level caches so every tab reloads fresh values
            load_units_eq_data(force=True)
            from .utils import load_standards_data
            load_standards_data(force=True)
            QMessageBox.information(self, "Success", "Standards saved successfully!")
            self.standards_updated.emit()
        else:
            QMessageBox.warning(self, "Error", "Failed to save one or more files.")
    
    def import_json(self):
        """Import standards from a JSON file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Standards JSON", "", "JSON Files (*.json)"
        )
        if file_path:
            try:
                with open(file_path, "r") as f:
                    new_standards = json.load(f)
                
                # Validate structure
                valid = True
                for region, data in new_standards.items():
                    if not isinstance(data, dict) or "Aligners" not in data:
                        valid = False
                        break
                    if not isinstance(data["Aligners"], dict):
                        valid = False
                        break
                
                if valid:
                    self.standards = new_standards
                    self._inject_new_impressions(self.standards)

                    recalc_reply = QMessageBox.question(
                        self,
                        "Recalculate Equivalent Units?",
                        "Do you want to recalculate UE values from the imported standard times?\n\n"
                        "Formula used: UE = (Std Time / 408.3) * 15",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes,
                    )
                    if recalc_reply == QMessageBox.StandardButton.Yes:
                        self.recalculate_units_eq_from_standards()

                    self.populate_tree()
                    QMessageBox.information(
                        self,
                        "Success",
                        "Standards imported successfully!\n"
                        "Click 'Save Changes' to persist standards and UE files.",
                    )
                else:
                    QMessageBox.warning(self, "Error", "Invalid JSON format. Expected structure:\n{\n  \"Region\": {\n    \"Aligners\": {\n      \"Type\": value\n    }\n  }\n}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to import: {str(e)}")
    
    def export_json(self):
        """Export current standards to a JSON file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Standards JSON", "standards.json", "JSON Files (*.json)"
        )
        if file_path:
            try:
                with open(file_path, "w") as f:
                    json.dump(self.standards, f, indent=4)
                QMessageBox.information(self, "Success", "Standards exported successfully!")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to export: {str(e)}")
    
    def reload_standards(self):
        """Reload standards and units_eq from file"""
        from .utils import load_standards_data
        load_standards_data(force=True)  # bust cache before reloading
        self.load_standards()
        load_units_eq_data(force=True)
        self.load_units_eq()
        self.populate_tree()
        QMessageBox.information(self, "Reloaded", "Standards reloaded from file.")
    
    def get_standards(self):
        """Return current standards dictionary"""
        return self.standards
