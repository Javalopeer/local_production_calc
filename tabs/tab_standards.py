import json
import os
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QLabel,
    QTreeWidget, QTreeWidgetItem, QFileDialog, QMessageBox, QLineEdit,
    QHeaderView, QDialog, QFormLayout, QDialogButtonBox, QComboBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


def get_resource_path(relative_path):
    """Get absolute path to resource - works for dev and PyInstaller"""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        exe_path = os.path.join(exe_dir, relative_path)
        if os.path.exists(exe_path):
            return exe_path
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, relative_path)


def get_writable_path(relative_path):
    """Get writable path for saving files"""
    if getattr(sys, 'frozen', False):
        # When running as exe, save in exe directory
        exe_dir = os.path.dirname(sys.executable)
        return os.path.join(exe_dir, relative_path)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, relative_path)


def card(title, widget):
    """Helper function to create styled card/groupbox"""
    box = QGroupBox(title)
    layout = QVBoxLayout()
    layout.addWidget(widget) if isinstance(widget, QWidget) else layout.addLayout(widget)
    box.setLayout(layout)
    return box


class EditStandardDialog(QDialog):
    """Dialog for editing a standard time value"""
    def __init__(self, region, case_type, current_value, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Standard Time")
        self.setMinimumWidth(300)
        
        layout = QVBoxLayout()
        
        # Info labels
        info_layout = QFormLayout()
        info_layout.addRow("Region:", QLabel(region))
        info_layout.addRow("Type:", QLabel(case_type))
        
        # Value input
        self.value_input = QLineEdit(str(current_value))
        self.value_input.setPlaceholderText("Enter time in minutes")
        info_layout.addRow("Time (min):", self.value_input)
        
        layout.addLayout(info_layout)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def get_value(self):
        try:
            return float(self.value_input.text())
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
        
        # Value input
        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("Time in minutes")
        form_layout.addRow("Standard Time:", self.value_input)
        
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
            return {
                'region': self.region_combo.currentText(),
                'type': self.type_input.text().strip(),
                'value': value
            }
        except ValueError:
            return None


class StandardsTab(QWidget):
    standards_updated = Signal()  # Signal emitted when standards are modified
    
    def __init__(self):
        super().__init__()
        self.standards = {}
        self.load_standards()
        self.init_ui()
    
    def load_standards(self):
        """Load standards from JSON file"""
        standards_path = get_resource_path(os.path.join("data", "standards.json"))
        try:
            with open(standards_path, "r") as f:
                self.standards = json.load(f)
        except Exception as e:
            print(f"Error loading standards: {e}")
            self.standards = {}
    
    def save_standards(self):
        """Save standards to JSON file"""
        standards_path = get_writable_path(os.path.join("data", "standards.json"))
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(standards_path), exist_ok=True)
            with open(standards_path, "w") as f:
                json.dump(self.standards, f, indent=4)
            return True
        except Exception as e:
            print(f"Error saving standards: {e}")
            return False
    
    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # Header with buttons
        header_layout = QHBoxLayout()
        
        title_label = QLabel("Standard Times Configuration")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #4aa3ff;")
        header_layout.addWidget(title_label)
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
        self.tree.setHeaderLabels(["Region / Type", "Standard Time (min)"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        # Set column widths
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 150)
        
        # Style the tree
        self.tree.setStyleSheet("""
            QTreeWidget {
                background-color: #2b2b2b;
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
        
        # Action buttons
        action_layout = QHBoxLayout()
        action_layout.addStretch()
        
        add_type_btn = QPushButton("Add Type")
        add_type_btn.setMaximumWidth(100)
        add_type_btn.clicked.connect(self.add_type)
        action_layout.addWidget(add_type_btn)
        
        edit_btn = QPushButton("Edit Selected")
        edit_btn.setMaximumWidth(100)
        edit_btn.clicked.connect(self.edit_selected)
        action_layout.addWidget(edit_btn)
        
        delete_btn = QPushButton("Delete Selected")
        delete_btn.setMaximumWidth(110)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
            }
            QPushButton:hover {
                background-color: #D32F2F;
            }
        """)
        delete_btn.clicked.connect(self.delete_selected)
        action_layout.addWidget(delete_btn)
        
        save_btn = QPushButton("Save Changes")
        save_btn.setMaximumWidth(110)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
            }
            QPushButton:hover {
                background-color: #388E3C;
            }
        """)
        save_btn.clicked.connect(self.save_changes)
        action_layout.addWidget(save_btn)
        
        action_layout.addStretch()
        main_layout.addLayout(action_layout)
        
        # Info label
        info_label = QLabel("Double-click a type to edit its value. Changes are applied to Register and OT tabs after saving.")
        info_label.setStyleSheet("color: #888; font-size: 11px;")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(info_label)
        
        self.setLayout(main_layout)
        self.populate_tree()
    
    def populate_tree(self):
        """Populate the tree widget with standards data"""
        self.tree.clear()
        
        for region, data in sorted(self.standards.items()):
            region_item = QTreeWidgetItem([region, ""])
            region_item.setFont(0, QFont("Segoe UI", 11, QFont.Weight.Bold))
            region_item.setExpanded(True)
            
            if "Aligners" in data:
                for case_type, time_value in sorted(data["Aligners"].items()):
                    type_item = QTreeWidgetItem([case_type, f"{time_value:.2f}"])
                    type_item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
                    region_item.addChild(type_item)
            
            self.tree.addTopLevelItem(region_item)
    
    def on_item_double_clicked(self, item, column):
        """Handle double-click to edit a type"""
        if item.parent() is not None:  # It's a type item, not a region
            self.edit_item(item)
    
    def edit_item(self, item):
        """Edit a standard time value"""
        if item.parent() is None:
            return  # Can't edit region headers
        
        region = item.parent().text(0)
        case_type = item.text(0)
        current_value = self.standards.get(region, {}).get("Aligners", {}).get(case_type, 0)
        
        dialog = EditStandardDialog(region, case_type, current_value, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_value = dialog.get_value()
            if new_value is not None and new_value > 0:
                self.standards[region]["Aligners"][case_type] = new_value
                item.setText(1, f"{new_value:.2f}")
    
    def edit_selected(self):
        """Edit the currently selected item"""
        item = self.tree.currentItem()
        if item and item.parent() is not None:
            self.edit_item(item)
        else:
            QMessageBox.information(self, "Info", "Please select a case type to edit.")
    
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
                    self.populate_tree()
    
    def delete_selected(self):
        """Delete the currently selected item"""
        item = self.tree.currentItem()
        if not item:
            QMessageBox.information(self, "Info", "Please select an item to delete.")
            return
        
        if item.parent() is None:
            # Deleting a region
            region = item.text(0)
            reply = QMessageBox.question(
                self, "Confirm Delete",
                f"Delete entire region '{region}' and all its types?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                del self.standards[region]
                self.populate_tree()
        else:
            # Deleting a type
            region = item.parent().text(0)
            case_type = item.text(0)
            reply = QMessageBox.question(
                self, "Confirm Delete",
                f"Delete type '{case_type}' from '{region}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                del self.standards[region]["Aligners"][case_type]
                self.populate_tree()
    
    def save_changes(self):
        """Save changes to file and notify other tabs"""
        if self.save_standards():
            QMessageBox.information(self, "Success", "Standard times saved successfully!")
            self.standards_updated.emit()
        else:
            QMessageBox.warning(self, "Error", "Failed to save standard times.")
    
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
                    self.populate_tree()
                    QMessageBox.information(self, "Success", "Standards imported successfully!")
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
        """Reload standards from file"""
        self.load_standards()
        self.populate_tree()
        QMessageBox.information(self, "Reloaded", "Standards reloaded from file.")
    
    def get_standards(self):
        """Return current standards dictionary"""
        return self.standards
