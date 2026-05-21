"""
clipboard_import.py
────────────────────
Parses case details from Ormco CMS clipboard text.

Workflow for user:
  1. Open the case detail page in Chrome.
  2. Press Ctrl+A then Ctrl+C.
  3. Click "Import" in the app.

Ormco CMS page structure (data-testid attributes guide the parsing):
  - "Case # XXXXXXX"     → case_id
  - First letter line    → P (Primary), S1/S2... (Secondary/label, overridden by CR logic)
  - "Change Requests #"  → CR count:
        0  → Primary
        ≥1 → CR  (regardless of S label)
  - "Doctor"  label row  → doctor name
  - "POD"     label row  → maps to known regions (e.g. "IBERIA 1" → "POD Iberia")
  - "Region"  label row  → fallback for region matching
"""
from __future__ import annotations
import re
import os
import sys


# ── POD → Region mapping (Ormco CMS POD values to standards.json region names) ─
# Keys are substrings that appear in the POD field (case-insensitive).
# Values are the exact region keys from standards.json.
_POD_REGION_MAP: list[tuple[str, str]] = [
    # ── North America / Canada ───────────────────────────────────────────────
    ("stagerx america",  "Regions NA & Canada"),
    ("stage rx america", "Regions NA & Canada"),
    ("na & canada",      "Regions NA & Canada"),
    ("icon warford",     "ICON Warford"),
    ("icon",             "ICON"),              
    # ── Sanitas ──────────────────────────────────────────────────────────────
    ("pod sanitas",      "POD Sanitas"),
    ("sanitas",          "POD Sanitas"),
    # ── Australia ────────────────────────────────────────────────────────────
    ("pod australia",    "POD Australia"),
    ("australia",        "POD Australia"),
    # ── Iberia ───────────────────────────────────────────────────────────────
    ("pod iberia",       "POD Iberia"),
    ("iberia",           "POD Iberia"),         
    # ── UK / Ireland ─────────────────────────────────────────────────────────
    ("pod ukin",         "POD Ukin"),
    ("ukin",             "Ukin"),
    # ── IDI ──────────────────────────────────────────────────────────────────
    ("pod idi",          "Pod IDI"),
    ("idi",              "Pod IDI"),
    # ── France / Clex ────────────────────────────────────────────────────────
    ("clex france",      "Clex France"),
    ("clex",             "Clex France"),
    ("france 1",         "France 1"),
    ("france",           "France"),
    # ── Benelux ──────────────────────────────────────────────────────────────
    ("benelux",          "Benelux"),
    # ── Portugal ─────────────────────────────────────────────────────────────
    ("portugal",         "Portugal"),
    # ── Italy ────────────────────────────────────────────────────────────────
    ("italy",            "Italy"),
    # ── Mediterranean ────────────────────────────────────────────────────────
    ("mediterranean",    "Mediterranean"),
    # ── Africa ───────────────────────────────────────────────────────────────
    ("africa",           "Africa"),
    # ── Latam ────────────────────────────────────────────────────────────────
    ("latam",            "Latam"),
    ("latin america",    "Latam"),
    # ── Russia / Slavic / Arabic / Dachee ────────────────────────────────────
    ("russia",           "Russia"),
    ("slavic",           "Slavic"),
    ("arabic",           "Arabic"),
    ("dachee",           "Dachee"),
]

# Country / Region field values visible on the CMS page → standards.json keys
_COUNTRY_REGION_MAP: list[tuple[str, str]] = [
    ("united states",   "Regions NA & Canada"),
    ("canada",          "Regions NA & Canada"),
    ("spain",           "POD Iberia"),
    ("australia",       "POD Australia"),
    ("united kingdom",  "Ukin"),
    ("france",          "France 1"),
    ("russia",          "Russia"),
    ("ukraine",         "Slavic"),
    ("saudi",           "Arabic"),
    ("japan",           "Dachee"),
    ("italy",           "Italy"),
    ("portugal",        "Portugal"),
]


def parse_clipboard(standards: dict, clipboard_text: str = "") -> dict:
    """
    Extract case_id, region, tipo, doctor from Ormco CMS clipboard text.

    Returns dict with keys: case_id, region, tipo, doctor (strings, may be '').
    """
    if not clipboard_text:
        clipboard_text = _read_clipboard()

    text = clipboard_text or ""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    flat  = " ".join(lines)

    # ── 1. Case ID ───────────────────────────────────────────────────────────
    # Ormco format: "Case # 1756388"  or  "Case #1756388"
    case_id = ""
    m = re.search(r'Case\s*#\s*(\d{5,10})', flat, re.IGNORECASE)
    if m:
        case_id = m.group(1)

    # ── 2. Type — label + Change Requests # ──────────────────────────────────
    # Rules (in priority order):
    #   1. CR ≥ 1  →  CR  (always, regardless of label)
    #   2. CR = 0  +  label P      →  Primary
    #   2. CR = 0  +  label S1/S2… →  Secondary
    #   3. No CR field found: use label alone  P→Primary, S+number→Secondary
    tipo = ""

    # Extract the case-type label (P, S1, S2, S3 …) from the line right below the case number
    label_match = re.search(r'\bCase\s*#\s*\d+\s+([PS]\d*)\b', flat, re.IGNORECASE)
    label = label_match.group(1).upper() if label_match else ""

    cr_match = re.search(r'Change\s+Requests?\s*#\s*(\d+)', flat, re.IGNORECASE)
    if cr_match:
        cr_count = int(cr_match.group(1))
        if cr_count >= 1:
            tipo = "CR"
        else:
            # CR = 0: label decides Primary vs Secondary
            if label == "P":
                tipo = "Primary"
            elif re.match(r'^S\d*$', label):
                tipo = "Secondary"
            else:
                tipo = "Primary"   # safe default when CR=0
    else:
        # No CR field found — use label only
        if label == "P":
            tipo = "Primary"
        elif re.match(r'^S\d*$', label):
            tipo = "Secondary"

    # ── 3. Doctor ────────────────────────────────────────────────────────────
    # CMS layout: "Doctor   LAST-NAME, FIRST NAME"
    # The word "Doctor" appears as a standalone label followed by the value.
    # Character classes use Unicode ranges so any alphabet survives the
    # regex match: Latin-1 + Latin Extended (Spanish, French, German, Polish,
    # Czech, Hungarian, etc.), Cyrillic (Russian, Ukrainian, Bulgarian),
    # Greek, and CJK (Chinese, Japanese, Korean). Apostrophe included for
    # names like "O'Brien".
    _NAME_CHARS = (
        r"A-Za-z"
        r"À-ɏ"   # Latin-1 Supplement + Latin Extended-A/B
        r"Ḁ-ỿ"   # Latin Extended Additional (Vietnamese)
        r"Ͱ-Ͽ"   # Greek and Coptic
        r"Ѐ-ӿ"   # Cyrillic (Russian, Ukrainian, etc.)
        r"Ԁ-ԯ"   # Cyrillic Supplement
        r"一-鿿"   # CJK Unified Ideographs (Chinese, Japanese kanji)
        r"぀-ゟ"   # Hiragana
        r"゠-ヿ"   # Katakana
        r"가-힯"   # Hangul (Korean)
    )
    _NAME_SEP = r"\s,&.\-'"
    doctor = ""
    doc_match = re.search(
        rf'\bDoctor\b\s+([{_NAME_CHARS}][{_NAME_CHARS}{_NAME_SEP}]{{2,60}}?)'
        r'(?=\s{2,}|\n|POD|Country|Region|Scanner|CBCT|$)',
        flat, re.IGNORECASE
    )
    if doc_match:
        doctor = doc_match.group(1).strip().rstrip(',').strip()

    # ── 4. Region ────────────────────────────────────────────────────────────
    # Priority 1: POD field  (most reliable for design region)
    # Priority 2: direct match against known region names
    # Priority 3: Country field heuristic
    known_regions: list[str] = list(standards.keys())
    region = ""

    # Extract POD value from clipboard
    pod_match = re.search(r'\bPOD\b\s+([^\n]{3,50}?)(?=\s{2,}|\n|Country|Region|$)', flat)
    pod_value = pod_match.group(1).strip() if pod_match else ""

    if pod_value:
        # Try POD → region mapping
        pv_lower = pod_value.lower()
        for keyword, mapped in _POD_REGION_MAP:
            if keyword in pv_lower:
                if mapped in known_regions:
                    region = mapped
                    break
        # Try direct match of POD value against known regions
        if not region:
            for r in sorted(known_regions, key=len, reverse=True):
                if r.lower() in pv_lower or pv_lower in r.lower():
                    region = r
                    break

    # Fallback: direct region name match in full text
    if not region:
        for r in sorted(known_regions, key=len, reverse=True):
            if re.search(r'(?<![A-Za-z])' + re.escape(r) + r'(?![A-Za-z])', flat, re.IGNORECASE):
                region = r
                break

    # Fallback: country-based mapping
    if not region:
        country_match = re.search(r'\bCountry\b\s+([^\n]{3,30}?)(?=\s{2,}|\n|$)', flat)
        if country_match:
            country_val = country_match.group(1).strip().lower()
            for keyword, mapped in _COUNTRY_REGION_MAP:
                if keyword in country_val:
                    if mapped in known_regions:
                        region = mapped
                        break

    return {
        'case_id': case_id,
        'region':  region,
        'tipo':    tipo,
        'doctor':  doctor,
    }


def _read_clipboard() -> str:
    """Read text from system clipboard (Windows)."""
    try:
        # PySide6 clipboard (preferred — already imported by the app)
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            cb = app.clipboard()
            return cb.text() or ""
    except Exception:
        pass

    # Fallback: win32clipboard or ctypes
    try:
        import ctypes
        import ctypes.wintypes as wintypes

        CF_UNICODETEXT = 13
        ctypes.windll.user32.OpenClipboard(0)
        try:
            handle = ctypes.windll.user32.GetClipboardData(CF_UNICODETEXT)
            if handle:
                ptr = ctypes.windll.kernel32.GlobalLock(handle)
                text = ctypes.wstring_at(ptr)
                ctypes.windll.kernel32.GlobalUnlock(handle)
                return text
        finally:
            ctypes.windll.user32.CloseClipboard()
    except Exception:
        pass

    return ""
