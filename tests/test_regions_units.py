import os
import sys
import json
import pytest

from PySide6.QtWidgets import QApplication

# Ensure package path
ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tabs.tab_production import ProductionTab


def setup_module():
    """Create a QApplication for widget instantiation."""
    global app
    app = QApplication.instance() or QApplication([])


def load_standards():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    standards_path = os.path.join(base, "data", "standards.json")
    with open(standards_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_all_regions_have_units_at_100():
    pt = ProductionTab()
    standards = load_standards()

    missing = []
    for region in standards.keys():
        units = pt.get_units_at_100(region)
        if not units or units == 0:
            missing.append(region)

    assert not missing, f"Regions without units_at_100: {missing}"


@pytest.mark.parametrize("pct", [0, 50, 100, 150, 200])
def test_calculate_units_eq_linear_for_various_percentages(pct):
    """For each region, calculate units eq for several % values and verify linear scaling."""
    pt = ProductionTab()
    standards = load_standards()

    for region in standards.keys():
        units100 = pt.get_units_at_100(region)
        calc = pt.calculate_units_eq(region, pct)
        expected = (pct / 100.0) * units100
        # allow small float tolerance
        assert abs(calc - expected) < 1e-6, f"Region {region} pct {pct}: got {calc}, expected {expected}"
