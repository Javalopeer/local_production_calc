import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tabs.tab_standards import (
    _build_combined_export_payload,
    _extract_import_payload,
)


def _sample_standards():
    return {
        "ICON": {
            "Aligners": {
                "Primary": 31.35,
                "Secondary": 24.70,
            }
        }
    }


def _sample_units_eq():
    return {
        "ICON": {
            "Primary": 1.15,
            "Secondary": 0.91,
        }
    }


def test_extract_standards_only():
    std, ue = _extract_import_payload(_sample_standards())
    assert std is not None
    assert ue is None
    assert std["ICON"]["Aligners"]["Primary"] == 31.35


def test_extract_ue_only():
    std, ue = _extract_import_payload(_sample_units_eq())
    assert std is None
    assert ue is not None
    assert ue["ICON"]["Primary"] == 1.15


def test_extract_combined_wrapper():
    payload = {
        "standards": _sample_standards(),
        "units_eq": _sample_units_eq(),
    }
    std, ue = _extract_import_payload(payload)
    assert std is not None
    assert ue is not None
    assert std["ICON"]["Aligners"]["Secondary"] == 24.70
    assert ue["ICON"]["Secondary"] == 0.91


def test_extract_combined_region_level():
    payload = {
        "ICON": {
            "Aligners": {"Primary": 31.35},
            "UE": {"Primary": 1.15},
        }
    }
    std, ue = _extract_import_payload(payload)
    assert std is not None
    assert ue is not None
    assert std["ICON"]["Aligners"]["Primary"] == 31.35
    assert ue["ICON"]["Primary"] == 1.15


def test_extract_enveloped_data_wrapper():
    payload = {
        "data": {
            "standards": _sample_standards(),
            "units_eq": _sample_units_eq(),
        }
    }
    std, ue = _extract_import_payload(payload)
    assert std is not None
    assert ue is not None


def test_build_combined_payload_shape():
    payload = _build_combined_export_payload(_sample_standards(), _sample_units_eq())
    assert payload["format"] == "ppc-standards-combined-v1"
    assert "standards" in payload
    assert "units_eq" in payload
    assert payload["standards"]["ICON"]["Aligners"]["Primary"] == 31.35
    assert payload["units_eq"]["ICON"]["Primary"] == 1.15


def test_round_trip_build_then_extract():
    built = _build_combined_export_payload(_sample_standards(), _sample_units_eq())
    std, ue = _extract_import_payload(built)
    assert std is not None
    assert ue is not None
    assert std["ICON"]["Aligners"]["Primary"] == 31.35
    assert ue["ICON"]["Primary"] == 1.15

