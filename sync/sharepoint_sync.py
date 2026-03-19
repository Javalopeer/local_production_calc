# -*- coding: utf-8 -*-
"""
SharePoint / OneDrive Excel export.

Generates an .xlsx file with:
  Sheet 1 – Daily Summary    (today's production overview)
  Sheet 2 – Cases Today      (all cases recorded today)
  Sheet 3 – Monthly Summary  (daily totals for the current month)

The file is saved to the configured export_folder so OneDrive
automatically syncs it to SharePoint.

Filename pattern:
  <DesignerName>_Production_<YYYY-MM-DD>.xlsx
"""
import os
import sqlite3
from datetime import datetime, date

_OPENPYXL_ERROR = ""
try:
    import openpyxl
    from openpyxl.styles import (
        Font, PatternFill, Alignment, Border, Side
    )
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.worksheet.filters import FilterColumn, Filters
    _OPENPYXL_OK = True
except Exception as _e:
    _OPENPYXL_OK = False
    _OPENPYXL_ERROR = str(_e)

from db.database import DB_PATH
from sync.app_config import load_config
from tabs.utils import calculate_downtime_equivalent_units

# ── Colour palette ──────────────────────────────────────────────────────────
_BLUE       = "2D89EF"
_BLUE_LIGHT = "D6E8FF"
_GREEN      = "4CAF50"
_YELLOW     = "FFC107"
_RED        = "F44336"
_HEADER_FG  = "FFFFFF"
_GREY_ROW   = "F5F5F5"
_TITLE_GREY = "3C3C3C"

DAILY_BASE_MINUTES = 408.3


# ── Helpers ─────────────────────────────────────────────────────────────────

def _db():
    return sqlite3.connect(DB_PATH)

def _thin_border():
    s = Side(style="thin", color="CCCCCC")
    return Border(left=s, right=s, top=s, bottom=s)

def _header_fill(hex_color=_BLUE):
    return PatternFill("solid", fgColor=hex_color)

def _row_fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def _hdr(cell, text, bold=True, color=_HEADER_FG, bg=_BLUE, size=11, wrap=False):
    cell.value = text
    cell.font = Font(bold=bold, color=color, size=size)
    cell.fill = _header_fill(bg)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=wrap)
    cell.border = _thin_border()

def _cell(cell, value, bold=False, color="000000", align="left", bg=None, num_fmt=None):
    cell.value = value
    cell.font = Font(bold=bold, color=color)
    cell.alignment = Alignment(horizontal=align, vertical="center")
    cell.border = _thin_border()
    if bg:
        cell.fill = PatternFill("solid", fgColor=bg)
    if num_fmt:
        cell.number_format = num_fmt

def _autowidth(ws, extra=4):
    max_col = ws.max_column or 1
    for ci in range(1, max_col + 1):
        length = 0
        for row in ws.iter_rows(min_col=ci, max_col=ci):
            for cell in row:
                try:
                    if cell.value:
                        length = max(length, len(str(cell.value)))
                except Exception:
                    pass
        ws.column_dimensions[get_column_letter(ci)].width = max(length, 8) + extra

def _production_color(pct):
    if pct >= 100:  return _GREEN
    if pct >= 95:   return _YELLOW
    return _RED


# ── Data queries ─────────────────────────────────────────────────────────────

def _get_daily_data(target_date: str):
    conn = _db()
    cur  = conn.cursor()

    # Cases
    cur.execute("""
        SELECT case_id, region, tipo_caso, doctor, hora_inicio, hora_fin,
               std_time, tiempo_real, efficiency, estado, case_value, count_production, comments
        FROM cases WHERE fecha = ? ORDER BY hora_inicio
    """, (target_date,))
    cases = cur.fetchall()

    # OT Cases
    cur.execute("""
        SELECT case_id, region, tipo_caso, doctor, hora_inicio, hora_fin,
               std_time, tiempo_real, efficiency, estado, case_value, count_production, comments
        FROM ot_cases WHERE fecha = ? ORDER BY hora_inicio
    """, (target_date,))
    ot_cases = cur.fetchall()

    # Downtime
    cur.execute("""
        SELECT hora_inicio, hora_fin, duracion, razon
        FROM downtimes WHERE fecha = ? ORDER BY hora_inicio
    """, (target_date,))
    downtimes = cur.fetchall()

    # Totals (only count_production = 1)
    cur.execute("""
        SELECT SUM(case_value) FROM cases
        WHERE fecha = ? AND (count_production = 1 OR count_production IS NULL)
    """, (target_date,))
    total_cases_pct = cur.fetchone()[0] or 0.0

    cur.execute("SELECT SUM(duracion) FROM downtimes WHERE fecha = ?", (target_date,))
    total_downtime_min = cur.fetchone()[0] or 0.0

    conn.close()
    return cases, ot_cases, downtimes, total_cases_pct, total_downtime_min


def _get_monthly_data(year: int, month: int):
    conn = _db()
    cur  = conn.cursor()
    prefix = f"{year:04d}-{month:02d}-%"

    cur.execute("""
        SELECT fecha, SUM(case_value), COUNT(*)
        FROM cases
        WHERE fecha LIKE ? AND (count_production = 1 OR count_production IS NULL)
        GROUP BY fecha ORDER BY fecha
    """, (prefix,))
    monthly_cases = {r[0]: (r[1] or 0.0, r[2]) for r in cur.fetchall()}

    cur.execute("""
        SELECT fecha, SUM(duracion)
        FROM downtimes WHERE fecha LIKE ?
        GROUP BY fecha ORDER BY fecha
    """, (prefix,))
    monthly_dt = {r[0]: r[1] or 0.0 for r in cur.fetchall()}

    conn.close()

    # Merge all dates
    all_dates = sorted(set(list(monthly_cases.keys()) + list(monthly_dt.keys())))
    rows = []
    for d in all_dates:
        cases_pct, n_cases = monthly_cases.get(d, (0.0, 0))
        dt_min   = monthly_dt.get(d, 0.0)
        dt_pct   = (dt_min / DAILY_BASE_MINUTES) * 100
        total    = cases_pct + dt_pct
        rows.append((d, n_cases, cases_pct, dt_min, dt_pct, total))
    return rows


# Fixed case types shown as individual columns in the Dashboard
FIXED_CASE_TYPES = ["Primary", "Secondary", "CR"]

# Full explicit type list for dashboard/history exports (REG + OT)
CASE_TYPE_COLUMNS = [
    "Primary",
    "Secondary",
    "CR",
    "Stage RX Primary",
    "Stage RX Secondary",
    "Stage RX CR",
    "Bite Sync Primary",
    "Bite Sync Secondary",
    "Bite Sync CR",
]


def _bucket_case_types(type_counts: dict) -> dict:
    """Expand raw case-type counts into explicit dashboard columns.

    Returns (counts_by_case_type, other_count) where counts_by_case_type has
    one entry for each value in CASE_TYPE_COLUMNS.
    """
    counts = {name: 0 for name in CASE_TYPE_COLUMNS}
    other_count = 0

    alias_map = {
        "bitesync2": "Bite Sync Secondary",
        "bite sync2": "Bite Sync Secondary",
        "bitesync3": "Bite Sync CR",
        "bite sync3": "Bite Sync CR",
    }

    for raw_type, count in (type_counts or {}).items():
        n = int(count or 0)
        t_raw = (raw_type or "").strip()
        t = t_raw.lower()

        if not t:
            other_count += n
            continue

        canonical = None
        if t_raw in counts:
            canonical = t_raw
        elif t in alias_map:
            canonical = alias_map[t]
        elif "stage rx" in t:
            if "primary" in t:
                canonical = "Stage RX Primary"
            elif "secondary" in t:
                canonical = "Stage RX Secondary"
            elif t.endswith("cr") or " cr" in t:
                canonical = "Stage RX CR"
        elif "bite sync" in t:
            if "primary" in t:
                canonical = "Bite Sync Primary"
            elif "secondary" in t:
                canonical = "Bite Sync Secondary"
            elif t.endswith("cr") or " cr" in t:
                canonical = "Bite Sync CR"
        elif t == "primary":
            canonical = "Primary"
        elif t == "secondary":
            canonical = "Secondary"
        elif t == "cr":
            canonical = "CR"

        if canonical and canonical in counts:
            counts[canonical] += n
        else:
            other_count += n

    return counts, other_count


def _get_ue_and_types(target_date: str):
    """
    Returns (ue_total, reg_type_counts, ot_type_counts) for target_date.
    reg_type_counts / ot_type_counts are dicts  {tipo_caso: count}.
        UE supports both models:
            - per-type UE (units_eq[region][tipo])
            - legacy base-rate UE (units_eq[region]['100'])
    """
    import json as _json
    try:
        _ueq_path = os.path.join(os.path.dirname(__file__),
                                  "..", "data", "units_eq.json")
        units_eq = _json.load(open(_ueq_path, encoding="utf-8-sig"))
    except Exception:
        units_eq = {}

    conn = _db()
    cur  = conn.cursor()

    # UE and reg type counts
    cur.execute("""
        SELECT region, tipo_caso, case_value, count_production
        FROM cases WHERE fecha = ?
    """, (target_date,))
    reg_rows = cur.fetchall()

    # OT type counts
    cur.execute("""
        SELECT tipo_caso FROM ot_cases WHERE fecha = ?
    """, (target_date,))
    ot_rows = cur.fetchall()

    # Downtime total for UE conversion
    cur.execute("SELECT SUM(duracion) FROM downtimes WHERE fecha = ?", (target_date,))
    downtime_total_min = cur.fetchone()[0] or 0.0
    conn.close()

    ue_total = 0.0
    reg_type_counts: dict = {}
    for region, tipo, case_value, count_prod in reg_rows:
        if count_prod in (1, None):
            reg_map = units_eq.get(region, {}) if isinstance(units_eq.get(region, {}), dict) else {}
            if tipo in reg_map:
                try:
                    ue_total += float(reg_map.get(tipo) or 0.0)
                except (TypeError, ValueError):
                    pass
            else:
                try:
                    rate = float(reg_map.get("100") or 0.0)
                except (TypeError, ValueError):
                    rate = 0.0
                ue_total += (case_value or 0) * rate / 100.0
        reg_type_counts[tipo] = reg_type_counts.get(tipo, 0) + 1

    ot_type_counts: dict = {}
    for (tipo,) in ot_rows:
        ot_type_counts[tipo] = ot_type_counts.get(tipo, 0) + 1

    ue_total += calculate_downtime_equivalent_units(downtime_total_min)

    return ue_total, reg_type_counts, ot_type_counts


# ── Sheet builders ───────────────────────────────────────────────────────────

def _build_daily_summary(wb, target_date: str, designer: str,
                         cases, ot_cases, downtimes,
                         total_cases_pct, total_downtime_min):
    ws = wb.active
    ws.title = "Daily Summary"
    ws.sheet_view.showGridLines = False

    dt_pct   = (total_downtime_min / DAILY_BASE_MINUTES) * 100
    total_pct = total_cases_pct + dt_pct
    pct_color = _production_color(total_pct)

    # ── Title block ─────────────────────────────────────────────────
    ws.merge_cells("A1:F1")
    t = ws["A1"]
    t.value = "Production Performance Report"
    t.font  = Font(bold=True, size=15, color=_HEADER_FG)
    t.fill  = _header_fill(_TITLE_GREY)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:F2")
    s = ws["A2"]
    s.value = f"Designer: {designer}     Date: {target_date}"
    s.font  = Font(size=11, color="555555")
    s.alignment = Alignment(horizontal="center")
    ws.row_dimensions[2].height = 20
    ws["A3"].value = ""

    # ── KPI row ─────────────────────────────────────────────────────
    row = 4
    ws.row_dimensions[row].height = 22
    for col, label in enumerate(["Cases Production", "Downtime", "Total Production",
                                  "Reg Cases", "OT Cases", "Downtime Events"], 1):
        _hdr(ws.cell(row, col), label, bg=_BLUE)

    row = 5
    ws.row_dimensions[row].height = 22
    _cell(ws.cell(row, 1), f"{total_cases_pct:.2f}%", bold=True, align="center", bg="DCEEFB")
    _cell(ws.cell(row, 2), f"{total_downtime_min:.0f} min  ({dt_pct:.2f}%)", align="center", bg="DCEEFB")
    _cell(ws.cell(row, 3), f"{total_pct:.2f}%", bold=True, align="center",
          bg=pct_color, color=_HEADER_FG)
    _cell(ws.cell(row, 4), len(cases),    align="center", bg="DCEEFB")
    _cell(ws.cell(row, 5), len(ot_cases), align="center", bg="DCEEFB")
    _cell(ws.cell(row, 6), len(downtimes),align="center", bg="DCEEFB")

    ws["A6"].value = ""

    # ── Cases table ─────────────────────────────────────────────────
    row = 7
    ws.merge_cells(f"A{row}:F{row}")
    t2 = ws.cell(row, 1)
    t2.value = "Regular Cases"
    t2.font  = Font(bold=True, size=11, color=_HEADER_FG)
    t2.fill  = _header_fill("1565C0")
    t2.alignment = Alignment(horizontal="left")

    row = 8
    cols_c = ["Case ID", "Region", "Type", "Start", "End", "Value (%)"]
    for ci, label in enumerate(cols_c, 1):
        _hdr(ws.cell(row, ci), label, bg=_BLUE_LIGHT, color="000000")

    for i, c in enumerate(cases):
        row += 1
        bg = _GREY_ROW if i % 2 == 0 else "FFFFFF"
        _cell(ws.cell(row, 1), c[0],  bg=bg)
        _cell(ws.cell(row, 2), c[1],  bg=bg)
        _cell(ws.cell(row, 3), c[2],  bg=bg)
        _cell(ws.cell(row, 4), c[4],  bg=bg, align="center")
        _cell(ws.cell(row, 5), c[5],  bg=bg, align="center")
        _cell(ws.cell(row, 6), f"{c[10]:.3f}%" if c[10] else "—",
              bg=bg, align="right")

    if not cases:
        row += 1
        ws.merge_cells(f"A{row}:F{row}")
        ws.cell(row, 1).value = "No regular cases for this date."

    row += 1; ws.cell(row, 1).value = ""

    # ── OT cases table ──────────────────────────────────────────────
    row += 1
    ws.merge_cells(f"A{row}:F{row}")
    t3 = ws.cell(row, 1)
    t3.value = "Overtime Cases"
    t3.font  = Font(bold=True, size=11, color=_HEADER_FG)
    t3.fill  = _header_fill("6A1B9A")
    t3.alignment = Alignment(horizontal="left")

    row += 1
    for ci, label in enumerate(cols_c, 1):
        _hdr(ws.cell(row, ci), label, bg="F3E5F5", color="000000")

    for i, c in enumerate(ot_cases):
        row += 1
        bg = _GREY_ROW if i % 2 == 0 else "FFFFFF"
        _cell(ws.cell(row, 1), c[0], bg=bg)
        _cell(ws.cell(row, 2), c[1], bg=bg)
        _cell(ws.cell(row, 3), c[2], bg=bg)
        _cell(ws.cell(row, 4), c[4], bg=bg, align="center")
        _cell(ws.cell(row, 5), c[5], bg=bg, align="center")
        _cell(ws.cell(row, 6), f"{c[10]:.3f}%" if c[10] else "—",
              bg=bg, align="right")

    if not ot_cases:
        row += 1
        ws.merge_cells(f"A{row}:F{row}")
        ws.cell(row, 1).value = "No OT cases for this date."

    row += 1; ws.cell(row, 1).value = ""

    # ── Downtime table ──────────────────────────────────────────────
    row += 1
    ws.merge_cells(f"A{row}:F{row}")
    t4 = ws.cell(row, 1)
    t4.value = "Downtime"
    t4.font  = Font(bold=True, size=11, color=_HEADER_FG)
    t4.fill  = _header_fill("E65100")
    t4.alignment = Alignment(horizontal="left")

    row += 1
    for ci, label in enumerate(["Start", "End", "Duration (min)", "Reason", "", ""], 1):
        _hdr(ws.cell(row, ci), label, bg="FBE9E7", color="000000")

    for i, d in enumerate(downtimes):
        row += 1
        bg = _GREY_ROW if i % 2 == 0 else "FFFFFF"
        _cell(ws.cell(row, 1), d[0], bg=bg, align="center")
        _cell(ws.cell(row, 2), d[1], bg=bg, align="center")
        _cell(ws.cell(row, 3), d[2], bg=bg, align="center")
        _cell(ws.cell(row, 4), d[3], bg=bg)

    if not downtimes:
        row += 1
        ws.merge_cells(f"A{row}:F{row}")
        ws.cell(row, 1).value = "No downtime recorded."

    # ── Timestamp footer ────────────────────────────────────────────
    row += 2
    ws.merge_cells(f"A{row}:F{row}")
    ws.cell(row, 1).value = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    ws.cell(row, 1).font  = Font(italic=True, color="999999", size=9)

    _autowidth(ws)


def _build_monthly_summary(wb, year: int, month: int, designer: str, monthly_rows):
    ws = wb.create_sheet("Monthly Summary")
    ws.sheet_view.showGridLines = False

    # Title
    ws.merge_cells("A1:G1")
    t = ws["A1"]
    t.value = f"Monthly Summary — {designer} — {year:04d}-{month:02d}"
    t.font  = Font(bold=True, size=13, color=_HEADER_FG)
    t.fill  = _header_fill(_TITLE_GREY)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26

    row = 3
    headers = ["Date", "Reg Cases", "Cases (%)", "Downtime (min)", "Downtime (%)", "Total (%)", "Status"]
    for ci, h in enumerate(headers, 1):
        _hdr(ws.cell(row, ci), h)

    total_production_sum = 0.0
    for i, (d, n_cases, cases_pct, dt_min, dt_pct, total) in enumerate(monthly_rows):
        row += 1
        bg = _GREY_ROW if i % 2 == 0 else "FFFFFF"
        status = "✓ OK" if total >= 100 else ("▲ WARN" if total >= 95 else "✗ LOW")
        s_color = _GREEN if total >= 100 else (_YELLOW if total >= 95 else _RED)

        _cell(ws.cell(row, 1), d,                 bg=bg, align="center")
        _cell(ws.cell(row, 2), n_cases,            bg=bg, align="center")
        _cell(ws.cell(row, 3), f"{cases_pct:.2f}%",bg=bg, align="right")
        _cell(ws.cell(row, 4), f"{dt_min:.0f}",    bg=bg, align="center")
        _cell(ws.cell(row, 5), f"{dt_pct:.2f}%",   bg=bg, align="right")
        _cell(ws.cell(row, 6), f"{total:.2f}%",    bold=True, bg=_production_color(total),
              color=_HEADER_FG, align="center")
        _cell(ws.cell(row, 7), status, bg=s_color, color=_HEADER_FG, align="center")
        total_production_sum += total

    if monthly_rows:
        row += 1
        avg = total_production_sum / len(monthly_rows)
        ws.merge_cells(f"A{row}:E{row}")
        _cell(ws.cell(row, 1), "Monthly Average", bold=True, align="right", bg="EEEEEE")
        _cell(ws.cell(row, 6), f"{avg:.2f}%", bold=True,
              bg=_production_color(avg), color=_HEADER_FG, align="center")
        _cell(ws.cell(row, 7), "", bg="EEEEEE")

    _autowidth(ws)


# ── Team summary helpers ─────────────────────────────────────────────────────

def _safe_sheet_name(name: str) -> str:
    """Excel sheet names: max 31 chars, no []:*?/\\ characters."""
    for ch in '[]:*?/\\':
        name = name.replace(ch, '-')
    return name[:31]


_DASH_SHEET = "Dashboard"


def _rebuild_dashboard(wb, today_str: str):
    """
    Rebuild (or create) the 'Dashboard' sheet as the first sheet.
    Shows one row per designer with today's data, a traffic-light color on
    Total%, a 'Last Sync' column, and a team-totals row at the bottom.
    Called every time any designer syncs so the supervisor always sees
    up-to-date data without opening individual sheets.
    """
    if _DASH_SHEET in wb.sheetnames:
        del wb[_DASH_SHEET]

    designer_sheets = [s for s in wb.sheetnames if s != _DASH_SHEET]

    ws = wb.create_sheet(_DASH_SHEET, 0)
    ws.sheet_view.showGridLines = False
    ws.sheet_view.showRowColHeaders = True

    refreshed = datetime.now().strftime("%H:%M")
    ws.merge_cells("A1:G1")
    title_cell = ws.cell(1, 1)
    title_cell.value = f"Production Dashboard  —  {today_str}    (refreshed {refreshed})"
    title_cell.font = Font(bold=True, size=13, color="FFFFFF")
    title_cell.fill = PatternFill("solid", fgColor=_TITLE_GREY)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    col_headers = ["Designer", "Cases (%)", "Downtime (%)", "Total (%)", "Cases", "Last Sync", "Status"]
    for ci, h in enumerate(col_headers, 1):
        _hdr(ws.cell(2, ci), h)
    ws.freeze_panes = "A3"

    rows_data = []
    for sname in sorted(designer_sheets):
        src = wb[sname]
        today_row = None
        for row_cells in src.iter_rows(min_row=2):
            if row_cells[0].value == today_str:
                today_row = row_cells
                break

        if today_row is not None:
            def _v(cell):
                val = cell.value
                if isinstance(val, str) and val.endswith("%"):
                    try:
                        return float(val.rstrip("%"))
                    except ValueError:
                        return 0.0
                return val if val is not None else 0

            cases_pct = _v(today_row[2])
            dt_pct = _v(today_row[3])
            total_pct = _v(today_row[4])
            cases = today_row[5].value or 0
            ot_cases = today_row[6].value or 0
            last_sync = today_row[7].value if len(today_row) > 7 else "—"
        else:
            cases_pct = dt_pct = total_pct = cases = ot_cases = 0
            last_sync = "—"

        rows_data.append((sname, cases_pct, dt_pct, total_pct, cases, ot_cases, last_sync))

    for ri, (designer, cases_pct, dt_pct, total_pct, cases, ot_cases, last_sync) in enumerate(rows_data):
        row = ri + 3
        bg = _GREY_ROW if ri % 2 == 0 else "FFFFFF"
        no_data = (cases == 0 and ot_cases == 0 and last_sync == "—")

        total_bg = _production_color(total_pct) if not no_data else "E0E0E0"
        total_fg = _HEADER_FG if not no_data else "888888"
        status_text = "—" if no_data else (
            "🟢 On Track" if total_pct >= 95 else "🟡 At Risk" if total_pct >= 85 else "🔴 Behind"
        )
        status_bg = (
            "E0E0E0" if no_data else
            "C8E6C9" if total_pct >= 95 else
            "FFF9C4" if total_pct >= 85 else "FFCDD2"
        )
        status_fg = "888888" if no_data else "000000"

        _cell(ws.cell(row, 1), designer, bold=True, bg=bg)
        _cell(ws.cell(row, 2), f"{cases_pct:.1f}%" if not no_data else "—", align="right", bg=bg)
        _cell(ws.cell(row, 3), f"{dt_pct:.1f}%" if not no_data else "—", align="right", bg=bg)
        _cell(ws.cell(row, 4), f"{total_pct:.1f}%" if not no_data else "—", bold=True, color=total_fg, bg=total_bg, align="center")
        _cell(ws.cell(row, 5), cases if not no_data else "—", align="center", bg=bg)
        _cell(ws.cell(row, 6), last_sync or "—", align="center", bg=bg)
        _cell(ws.cell(row, 7), status_text, bold=True, color=status_fg, bg=status_bg, align="center")

    active = [r for r in rows_data if not (r[4] == 0 and r[5] == 0 and r[6] == "—")]
    if active:
        total_row = len(rows_data) + 3
        n = len(active)
        avg_cases = sum(r[1] for r in active) / n
        avg_dt = sum(r[2] for r in active) / n
        avg_total = sum(r[3] for r in active) / n
        sum_cases = sum(r[4] for r in active)
        TOTALS_BG = "2D2D2D"

        _hdr(ws.cell(total_row, 1), f"TEAM AVG  ({n} designers)", bg=TOTALS_BG, color=_HEADER_FG)
        _hdr(ws.cell(total_row, 2), f"{avg_cases:.1f}%", bg=TOTALS_BG, color=_HEADER_FG)
        _hdr(ws.cell(total_row, 3), f"{avg_dt:.1f}%", bg=TOTALS_BG, color=_HEADER_FG)
        _hdr(ws.cell(total_row, 4), f"{avg_total:.1f}%", bg=_production_color(avg_total), color=_HEADER_FG)
        _hdr(ws.cell(total_row, 5), sum_cases, bg=TOTALS_BG, color=_HEADER_FG)
        _hdr(ws.cell(total_row, 6), "", bg=TOTALS_BG, color=_HEADER_FG)
        _hdr(ws.cell(total_row, 7), "", bg=TOTALS_BG, color=_HEADER_FG)

    _autowidth(ws, extra=6)


def _rebuild_dashboard_file(productions_dir: str, today_str: str):
    """
        Read ALL _Summary_*.xlsx files and write _Dashboard.xlsx with two sheets:
            - "Dashboard": snapshot for today_str, one row per designer
            - "History": flat table for all dates/designers

        Both sheets show all explicit case types in CASE_TYPE_COLUMNS for REG and OT,
        plus Reg Other / OT Other and status columns.

        Summary compatibility:
            - New schema (29 cols): explicit REG+OT case types
            - Previous schema (21 cols): bucketed Stage RX / Bite Sync
            - Older schema (15 cols): reduced type columns
    """
    import glob as _glob
    from openpyxl.utils import get_column_letter as _gcl

    summary_files = sorted(
        _glob.glob(os.path.join(productions_dir, "_Summary_*.xlsx"))
    )

    def _pct(v):
        if isinstance(v, str) and v.endswith("%"):
            try:
                return float(v.rstrip("%"))
            except ValueError:
                return 0.0
        return float(v) if v is not None else 0.0

    def _num(row, idx, default=0):
        try:
            v = row[idx]
            return int(v) if v is not None else default
        except (IndexError, TypeError, ValueError):
            return default

    def _flt(row, idx, default=0.0):
        try:
            v = row[idx]
            return float(v) if v is not None else default
        except (IndexError, TypeError, ValueError):
            return default

    # ── Load all data from every summary file ────────────────────────────────
    # Entry tuple indices:
    #  0 designer 1 date 2 week 3 cases_pct 4 dt_pct 5 total_pct
    #  6 reg_cases 7 ot_cases 8 ue
    #  9 reg_explicit(dict) 10 reg_other
    #  11 ot_explicit(dict) 12 ot_other
    #  13 last_sync
    all_rows = []
    today_data = {}   # designer → entry tuple for today_str

    def _parse_summary_type_counts(row_values):
        reg_explicit = {name: 0 for name in CASE_TYPE_COLUMNS}
        ot_explicit = {name: 0 for name in CASE_TYPE_COLUMNS}
        reg_other = 0
        ot_other = 0
        last_sync = "—"

        # New explicit schema (29 cols)
        if len(row_values) >= 29:
            for i, case_type in enumerate(CASE_TYPE_COLUMNS):
                reg_explicit[case_type] = _num(row_values, 8 + i)
            reg_other = _num(row_values, 17)
            for i, case_type in enumerate(CASE_TYPE_COLUMNS):
                ot_explicit[case_type] = _num(row_values, 18 + i)
            ot_other = _num(row_values, 27)
            last_sync = row_values[28] if row_values[28] else "—"
            return reg_explicit, reg_other, ot_explicit, ot_other, last_sync

        # Previous bucket schema (21 cols)
        if len(row_values) >= 21:
            reg_explicit["Primary"] = _num(row_values, 8)
            reg_explicit["Secondary"] = _num(row_values, 9)
            reg_explicit["CR"] = _num(row_values, 10)
            reg_other = _num(row_values, 11) + _num(row_values, 12) + _num(row_values, 13)

            ot_explicit["Primary"] = _num(row_values, 14)
            ot_explicit["Secondary"] = _num(row_values, 15)
            ot_explicit["CR"] = _num(row_values, 16)
            ot_other = _num(row_values, 17) + _num(row_values, 18) + _num(row_values, 19)

            last_sync = row_values[20] if row_values[20] else "—"
            return reg_explicit, reg_other, ot_explicit, ot_other, last_sync

        # Old schema (15 cols)
        reg_explicit["Primary"] = _num(row_values, 8)
        reg_explicit["Secondary"] = _num(row_values, 9)
        reg_explicit["CR"] = _num(row_values, 10)
        reg_other = _num(row_values, 11)
        ot_explicit["Primary"] = _num(row_values, 12)
        ot_other = _num(row_values, 13)
        last_sync = row_values[14] if len(row_values) > 14 and row_values[14] else "—"
        return reg_explicit, reg_other, ot_explicit, ot_other, last_sync

    for sf in summary_files:
        try:
            swb = openpyxl.load_workbook(sf, read_only=True, data_only=True)
            sws = swb.active
            base = os.path.basename(sf)
            designer_name = base[len("_Summary_"):-len(".xlsx")].replace("_", " ")
            for row in sws.iter_rows(min_row=2, values_only=True):
                if not row[0]:
                    continue
                d_str      = str(row[0])
                week       = row[1] or ""
                cases_pct  = _pct(row[2])
                dt_pct     = _pct(row[3])
                total_pct  = _pct(row[4])
                reg_cases  = _num(row, 5)
                ot_cases   = _num(row, 6)
                ue         = _flt(row, 7)
                reg_explicit, reg_other, ot_explicit, ot_other, last_sync = _parse_summary_type_counts(row)

                entry = (designer_name, d_str, week, cases_pct, dt_pct,
                         total_pct, reg_cases, ot_cases, ue,
                         reg_explicit, reg_other,
                         ot_explicit, ot_other,
                         last_sync)
                all_rows.append(entry)
                if d_str == today_str:
                    today_data[designer_name] = entry
            swb.close()
        except Exception:
            continue

    # Build snapshot: include all known designers (blank row if no data today)
    all_designers = sorted({r[0] for r in all_rows})
    _blank = lambda d: (d, today_str, "", 0.0, 0.0, 0.0,
                        0, 0, 0.0,
                        {name: 0 for name in CASE_TYPE_COLUMNS}, 0,
                        {name: 0 for name in CASE_TYPE_COLUMNS}, 0,
                        "—")
    today_rows = [today_data.get(d) or _blank(d) for d in all_designers]

    wb = openpyxl.Workbook()

    # ════════════════════════════════════════════════════════════════════════
    # SHEET 1 — Dashboard (today_str snapshot)
    # ════════════════════════════════════════════════════════════════════════
    # Columns: Designer | Cases% | DT% | Total% | UE | Reg |
    #          Reg <all CASE_TYPE_COLUMNS> | Reg Other |
    #          Last Sync | Status
    dash_headers = [
        "Designer", "Cases (%)", "Downtime (%)", "Total (%)",
        "UE", "Reg Cases",
    ] + [f"Reg {name}" for name in CASE_TYPE_COLUMNS] + [
        "Reg Other", "Last Sync", "Status"
    ]
    DASH_COLS = len(dash_headers)
    ws_dash = wb.active
    ws_dash.title = "Dashboard"
    ws_dash.sheet_view.showGridLines = False

    refreshed = datetime.now().strftime("%H:%M")
    ws_dash.merge_cells(f"A1:{_gcl(DASH_COLS)}1")
    tc = ws_dash.cell(1, 1)
    tc.value = (f"Production Dashboard  —  {today_str}"
                f"    (refreshed {refreshed})")
    tc.font      = Font(bold=True, size=13, color="FFFFFF")
    tc.fill      = PatternFill("solid", fgColor=_TITLE_GREY)
    tc.alignment = Alignment(horizontal="center", vertical="center")
    ws_dash.row_dimensions[1].height = 28

    for ci, h in enumerate(dash_headers, 1):
        _hdr(ws_dash.cell(2, ci), h)
    ws_dash.freeze_panes = "A3"

    for ri, entry in enumerate(today_rows):
        (
            designer_name,
            _d,
            _w,
            cases_pct,
            dt_pct,
            total_pct,
            reg_cases,
            ot_cases,
            ue,
            reg_explicit,
            reg_other,
            ot_explicit,
            ot_other,
            last_sync,
        ) = entry
        row = ri + 3
        bg = _GREY_ROW if ri % 2 == 0 else "FFFFFF"
        no_data = (reg_cases == 0 and ot_cases == 0 and last_sync == "—")

        total_bg = _production_color(total_pct) if not no_data else "E0E0E0"
        total_fg = _HEADER_FG if not no_data else "888888"
        status_text = (
            "—" if no_data else
            "On Track" if total_pct >= 95 else
            "At Risk" if total_pct >= 85 else "Behind"
        )
        status_bg = (
            "E0E0E0" if no_data else
            "C8E6C9" if total_pct >= 95 else
            "FFF9C4" if total_pct >= 85 else "FFCDD2"
        )
        status_fg = "888888" if no_data else "000000"
        dash = "—"

        _cell(ws_dash.cell(row, 1), designer_name, bold=True, bg=bg)
        _cell(ws_dash.cell(row, 2), f"{cases_pct:.1f}%" if not no_data else dash, align="right", bg=bg)
        _cell(ws_dash.cell(row, 3), f"{dt_pct:.1f}%" if not no_data else dash, align="right", bg=bg)
        _cell(
            ws_dash.cell(row, 4),
            f"{total_pct:.1f}%" if not no_data else dash,
            bold=True,
            color=total_fg,
            bg=total_bg,
            align="center",
        )
        _cell(ws_dash.cell(row, 5), f"{ue:.2f}" if not no_data else dash, align="right", bg=bg)
        _cell(ws_dash.cell(row, 6), reg_cases if not no_data else dash, align="center", bg=bg)

        write_col = 7
        for case_type in CASE_TYPE_COLUMNS:
            _cell(
                ws_dash.cell(row, write_col),
                reg_explicit.get(case_type, 0) if not no_data else dash,
                align="center",
                bg=bg,
            )
            write_col += 1

        _cell(ws_dash.cell(row, write_col), reg_other if not no_data else dash, align="center", bg=bg)
        write_col += 1
        _cell(ws_dash.cell(row, write_col), last_sync or dash, align="center", bg=bg)
        write_col += 1
        _cell(ws_dash.cell(row, write_col), status_text, bold=True, color=status_fg, bg=status_bg, align="center")

    # Team averages row
    active_today = [e for e in today_rows if not (e[6] == 0 and e[7] == 0 and e[13] == "—")]
    if active_today:
        tr = len(today_rows) + 3
        n  = len(active_today)
        TOTALS_BG = "2D2D2D"
        _hdr(ws_dash.cell(tr,  1), f"TEAM AVG  ({n} designers)",
             bg=TOTALS_BG, color=_HEADER_FG)
        _hdr(ws_dash.cell(tr,  2),
             f"{sum(e[3] for e in active_today)/n:.1f}%",
             bg=TOTALS_BG, color=_HEADER_FG)
        _hdr(ws_dash.cell(tr,  3),
             f"{sum(e[4] for e in active_today)/n:.1f}%",
             bg=TOTALS_BG, color=_HEADER_FG)
        avg_total = sum(e[5] for e in active_today) / n
        _hdr(ws_dash.cell(tr,  4), f"{avg_total:.1f}%",
             bg=_production_color(avg_total), color=_HEADER_FG)
        _hdr(ws_dash.cell(tr,  5),
             f"{sum(e[8]  for e in active_today):.2f}",
             bg=TOTALS_BG, color=_HEADER_FG)
        _hdr(ws_dash.cell(tr,  6), sum(e[6]  for e in active_today),
             bg=TOTALS_BG, color=_HEADER_FG)
        write_col = 7
        for case_type in CASE_TYPE_COLUMNS:
            _hdr(ws_dash.cell(tr, write_col),
                 sum(e[9].get(case_type, 0) for e in active_today),
                 bg=TOTALS_BG, color=_HEADER_FG)
            write_col += 1
        _hdr(ws_dash.cell(tr, write_col), sum(e[10] for e in active_today),
             bg=TOTALS_BG, color=_HEADER_FG)
        write_col += 1
        _hdr(ws_dash.cell(tr, write_col), "", bg=TOTALS_BG, color=_HEADER_FG)
        write_col += 1
        _hdr(ws_dash.cell(tr, write_col), "", bg=TOTALS_BG, color=_HEADER_FG)

    _autowidth(ws_dash, extra=1)
    for ci in range(1, DASH_COLS + 1):
        col = _gcl(ci)
        if ci == 1:
            ws_dash.column_dimensions[col].width = 18
        elif ci in (2, 3, 4):
            ws_dash.column_dimensions[col].width = 11
        elif ci == 5:
            ws_dash.column_dimensions[col].width = 8
        elif ci == 6:
            ws_dash.column_dimensions[col].width = 9
        elif ci in (DASH_COLS - 1, DASH_COLS):
            ws_dash.column_dimensions[col].width = 10
        else:
            ws_dash.column_dimensions[col].width = min(ws_dash.column_dimensions[col].width, 12)

    # ════════════════════════════════════════════════════════════════════════
    # SHEET 2 — History (all dates × all designers, filterable table)
    # Layout:
    #   Row 1  — date-picker header  (label | date input cell | instruction)
    #   Row 2  — thin spacer
    #   Row 3  — table column headers
    #   Row 4+ — data rows
    # ════════════════════════════════════════════════════════════════════════
    import datetime as _dt

    hist_headers = [
        "Date", "Designer", "Total (%)", "UE",
        "Reg Cases",
    ] + [f"Reg {name}" for name in CASE_TYPE_COLUMNS] + [
        "Reg Other", "Status"
    ]
    HIST_COLS = len(hist_headers)
    HDR_ROW   = 3   # table header row
    DATA_ROW  = 4   # first data row

    ws_hist = wb.create_sheet("History")
    ws_hist.sheet_view.showGridLines = False

    # ── Row 1: date-picker ───────────────────────────────────────────────
    try:
        _filter_date = _dt.datetime.strptime(today_str, "%Y-%m-%d").date()
    except Exception:
        _filter_date = _dt.date.today()

    # A1 — label
    lbl = ws_hist.cell(1, 1)
    lbl.value     = "View date:"
    lbl.font      = Font(bold=True, color="FFFFFF", size=11)
    lbl.fill      = PatternFill("solid", fgColor="2E75B6")
    lbl.alignment = Alignment(horizontal="right", vertical="center")

    # B1 — date input cell (actual date value so Excel treats it as a date)
    dc = ws_hist.cell(1, 2)
    dc.value         = _filter_date
    dc.number_format = "YYYY-MM-DD"
    dc.font          = Font(bold=True, size=12, color="1F3864")
    dc.fill          = PatternFill("solid", fgColor="D9E1F2")
    dc.alignment     = Alignment(horizontal="center", vertical="center")
    _med = Side(style="medium", color="2E75B6")
    dc.border = Border(left=_med, right=_med, top=_med, bottom=_med)

    # DataValidation: accept any date (serial > 0)
    dv = DataValidation(
        type="date", operator="greaterThan", formula1="0",
        showErrorMessage=False, showInputMessage=True,
        promptTitle="Date filter",
        prompt="Edit this date, then use the Date ▼ dropdown on the table to filter"
    )
    ws_hist.add_data_validation(dv)
    dv.add(dc)

    # C1:L1 — instruction text
    ws_hist.merge_cells(f"C1:{_gcl(HIST_COLS)}1")
    inst = ws_hist.cell(1, 3)
    inst.value     = ("← Edit this date, then click the  Date ▼  "
                      "dropdown on the table header to filter")
    inst.font      = Font(italic=True, color="888888", size=10)
    inst.fill      = PatternFill("solid", fgColor="F2F2F2")
    inst.alignment = Alignment(horizontal="left", vertical="center")
    ws_hist.row_dimensions[1].height = 26

    # ── Row 2: thin spacer ───────────────────────────────────────────────
    for ci in range(1, HIST_COLS + 1):
        ws_hist.cell(2, ci).fill = PatternFill("solid", fgColor="E8EEF7")
    ws_hist.row_dimensions[2].height = 4

    # ── Row 3: column headers ────────────────────────────────────────────
    for ci, h in enumerate(hist_headers, 1):
        _hdr(ws_hist.cell(HDR_ROW, ci), h)
    ws_hist.freeze_panes = f"A{DATA_ROW}"

    # ── Rows 4+: data ────────────────────────────────────────────────────
    # Sort: date desc, then designer asc
    sorted_rows = sorted(all_rows, key=lambda r: (r[1], r[0]))
    sorted_rows.sort(key=lambda r: r[1], reverse=True)

    for ri, entry in enumerate(sorted_rows):
        (designer_name, d_str, _w, cases_pct, dt_pct, total_pct,
         reg_cases, ot_cases, ue,
         reg_explicit, reg_other,
         ot_explicit, ot_other,
         last_sync) = entry
        row      = ri + DATA_ROW
        bg       = _GREY_ROW if ri % 2 == 0 else "FFFFFF"
        total_bg = _production_color(total_pct)
        status_text = ("On Track" if total_pct >= 95 else
                       "At Risk"  if total_pct >= 85 else "Behind")
        status_bg   = ("C8E6C9" if total_pct >= 95 else
                       "FFF9C4" if total_pct >= 85 else "FFCDD2")

        _cell(ws_hist.cell(row,  1), d_str,              align="center", bg=bg)
        _cell(ws_hist.cell(row,  2), designer_name,       bold=True,     bg=bg)
        _cell(ws_hist.cell(row,  3), f"{total_pct:.1f}%",
              bold=True, color=_HEADER_FG, bg=total_bg, align="center")
        _cell(ws_hist.cell(row,  4), f"{ue:.2f}",         align="right", bg=bg)
        _cell(ws_hist.cell(row,  5), reg_cases, align="center", bg=bg)

        write_col = 6
        for case_type in CASE_TYPE_COLUMNS:
            _cell(
                ws_hist.cell(row, write_col),
                reg_explicit.get(case_type, 0),
                align="center",
                bg=bg,
            )
            write_col += 1

        _cell(ws_hist.cell(row, write_col), reg_other, align="center", bg=bg)
        write_col += 1
        _cell(ws_hist.cell(row, write_col), status_text, bold=True, bg=status_bg, align="center")

    # ── Excel Table + pre-applied date filter ────────────────────────────
    if sorted_rows:
        last_row = len(sorted_rows) + HDR_ROW
        ref = f"A{HDR_ROW}:{_gcl(HIST_COLS)}{last_row}"
        tbl = Table(displayName="HistoryTable", ref=ref)
        tbl.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium9",
            showFirstColumn=False, showLastColumn=False,
            showRowStripes=True,   showColumnStripes=False)
        ws_hist.add_table(tbl)

        # Pre-apply filter on Date column (colId=0) to today_str
        # so the file opens already showing only the relevant day.
        ws_hist.auto_filter.ref = ref
        fc = FilterColumn(colId=0)
        fc.filters = Filters(filter=[today_str])
        ws_hist.auto_filter.filterColumn = [fc]

    _autowidth(ws_hist, extra=1)
    for ci in range(1, HIST_COLS + 1):
        col = _gcl(ci)
        if ci in (1, 2):
            ws_hist.column_dimensions[col].width = 13
        elif ci in (3,):
            ws_hist.column_dimensions[col].width = 10
        elif ci in (4, 5):
            ws_hist.column_dimensions[col].width = 9
        elif ci == HIST_COLS:
            ws_hist.column_dimensions[col].width = 10
        else:
            ws_hist.column_dimensions[col].width = min(ws_hist.column_dimensions[col].width, 12)

    dashboard_path = os.path.join(productions_dir, "_Dashboard.xlsx")
    try:
        try:
            os.remove(dashboard_path)
        except FileNotFoundError:
            pass
        _save_atomic(wb, dashboard_path)
    except PermissionError:
        # If dashboard is open/locked (Excel, preview, etc.), skip silently.
        # Daily and summary files were already saved.
        return

    # Save a dated snapshot so each day keeps its own dashboard file.
    # If snapshot is locked, skip silently as well.
    snapshots_dir = os.path.join(productions_dir, "Dashboards")
    os.makedirs(snapshots_dir, exist_ok=True)
    snapshot_path = os.path.join(snapshots_dir, f"_Dashboard_{today_str}.xlsx")
    try:
        _save_atomic(wb, snapshot_path)
    except PermissionError:
        return


def _update_team_summary(productions_dir: str, designer: str, target_date: str,
                         total_cases_pct: float, total_downtime_min: float,
                         n_cases: int, n_ot_cases: int,
                         ue_total: float = 0.0,
                         reg_type_counts: dict | None = None,
                         ot_type_counts:  dict | None = None):
    """
    NEW ARCHITECTURE — no shared-file lock problem:

    Step 1: Write _Summary_<DesignerName>.xlsx  (only THIS designer ever writes it)
            → no conflicts possible, always succeeds even if Dashboard is open.

    Step 2: Rebuild _Dashboard.xlsx by reading ALL _Summary_*.xlsx files.
            → if Excel has _Dashboard.xlsx open (locked), skip silently;
              it will be rebuilt on the next sync.
    """
    if reg_type_counts is None:
        reg_type_counts = {}
    if ot_type_counts is None:
        ot_type_counts = {}
    safe_name = designer.replace(" ", "_").replace("/", "-")
    summary_file = os.path.join(productions_dir, f"_Summary_{safe_name}.xlsx")

    d         = date.fromisoformat(target_date)
    week_num  = d.isocalendar()[1]
    dt_pct    = (total_downtime_min / DAILY_BASE_MINUTES) * 100
    total_pct = total_cases_pct + dt_pct

    os.makedirs(productions_dir, exist_ok=True)

    # ── Step 1: Read existing historical rows into memory (skip today) ────────
    # We read first, then delete, then write fresh — no in-place overwrite
    # so there is no file-lock issue.
    history_rows = []   # list of raw value tuples, date != target_date
    if os.path.exists(summary_file):
        try:
            old_wb = openpyxl.load_workbook(summary_file, read_only=True,
                                            data_only=True)
            old_ws = old_wb.active
            for row in old_ws.iter_rows(min_row=2, values_only=True):
                if row[0] and row[0] != target_date:
                    history_rows.append(row)
            old_wb.close()
        except Exception as _read_exc:
            # SAFETY: if we cannot read the existing file (locked by OneDrive,
            # open in Excel, or corrupt) we must NOT delete it — that would
            # permanently erase all historical rows.  Surface the error so the
            # caller knows the sync did not complete.
            raise PermissionError(
                f"Cannot read the existing summary file — it may be open in "
                f"Excel or locked by OneDrive.\n\n"
                f"File: {summary_file}\n\n"
                f"Close the file (and wait for OneDrive to finish syncing), "
                f"then try again.\n\nDetail: {_read_exc}"
            ) from _read_exc
        # Read succeeded — safe to delete and rewrite
        try:
            os.remove(summary_file)
        except Exception:
            pass

    # ── Step 2: Build fresh workbook with all rows ────────────────────────────
    # Column layout (1-indexed):
    # 1:Date 2:Week 3:Cases% 4:DT% 5:Total% 6:RegCases 7:OTCases 8:UE
    # 9..17: Reg explicit CASE_TYPE_COLUMNS
    # 18:Reg Other
    # 19..27: OT explicit CASE_TYPE_COLUMNS
    # 28:OT Other
    # 29:LastSync
    NCOLS = 29
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = safe_name
    ws.sheet_view.showGridLines = False
    col_headers = [
        "Date", "Week", "Cases (%)", "Downtime (%)", "Total (%)",
        "Reg Cases", "OT Cases", "UE",
    ] + [f"Reg {name}" for name in CASE_TYPE_COLUMNS] + [
        "Reg Other",
    ] + [f"OT {name}" for name in CASE_TYPE_COLUMNS] + [
        "OT Other", "Last Sync"
    ]
    for ci, h in enumerate(col_headers, 1):
        _hdr(ws.cell(1, ci), h)
    ws.freeze_panes = "A2"

    # Re-write history rows sorted oldest first (pad/trim to NCOLS if needed)
    history_rows.sort(key=lambda r: r[0])
    for ri, hrow in enumerate(history_rows):
        row_i = ri + 2
        bg = _GREY_ROW if ri % 2 == 0 else "FFFFFF"
        padded = list(hrow) + [None] * NCOLS
        for ci in range(1, NCOLS + 1):
            _cell(ws.cell(row_i, ci), padded[ci - 1],
                  align="center" if ci in (1, 2, 6, 7, 15) else "right",
                  bg=bg)

    # Compute today's explicit type counts (REG + OT)
    reg_explicit, reg_other = _bucket_case_types(reg_type_counts)
    ot_explicit, ot_other = _bucket_case_types(ot_type_counts)

    # Write today's fresh data
    today_ri  = len(history_rows)
    write_row = today_ri + 2
    bg = _GREY_ROW if today_ri % 2 == 0 else "FFFFFF"

    _cell(ws.cell(write_row,  1), target_date,               align="center", bg=bg)
    _cell(ws.cell(write_row,  2), f"W{week_num:02d}",        align="center", bg=bg)
    _cell(ws.cell(write_row,  3), f"{total_cases_pct:.2f}%", align="right",  bg=bg)
    _cell(ws.cell(write_row,  4), f"{dt_pct:.2f}%",          align="right",  bg=bg)
    _cell(ws.cell(write_row,  5), f"{total_pct:.2f}%",       bold=True,
          bg=_production_color(total_pct), color=_HEADER_FG, align="center")
    _cell(ws.cell(write_row,  6), n_cases,                   align="center", bg=bg)
    _cell(ws.cell(write_row,  7), n_ot_cases,                align="center", bg=bg)
    _cell(ws.cell(write_row,  8), round(ue_total, 2),        align="right",  bg=bg)
    write_col = 9
    for case_type in CASE_TYPE_COLUMNS:
        _cell(ws.cell(write_row, write_col), reg_explicit.get(case_type, 0), align="center", bg=bg)
        write_col += 1
    _cell(ws.cell(write_row, write_col), reg_other, align="center", bg=bg)
    write_col += 1
    for case_type in CASE_TYPE_COLUMNS:
        _cell(ws.cell(write_row, write_col), ot_explicit.get(case_type, 0), align="center", bg=bg)
        write_col += 1
    _cell(ws.cell(write_row, write_col), ot_other, align="center", bg=bg)
    write_col += 1
    _cell(ws.cell(write_row, write_col), datetime.now().strftime("%H:%M"), align="center", bg=bg)

    _autowidth(ws)
    wb.save(summary_file)   # fresh file, no lock possible

    # ── Step 2: Rebuild _Dashboard.xlsx from all _Summary_*.xlsx ─────────────
    _rebuild_dashboard_file(productions_dir, target_date)


def _save_atomic(wb, final_path: str, retries: int = 8):
    """Save workbook directly to final_path, retrying with random jitter if
    OneDrive or another user holds a lock.

    Random delay between retries prevents 25 designers from all hammering the
    file at the same millisecond after a failed attempt.

    We do NOT use a temp-file + os.replace() because that swaps the file inode,
    which OneDrive interprets as two conflicting versions of the same file.
    Instead we overwrite in-place with retries so the inode stays the same and
    OneDrive just sees an updated file with no conflict.
    """
    import time, random
    os.makedirs(os.path.dirname(final_path) or ".", exist_ok=True)
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(max(1, retries)):
        try:
            wb.save(final_path)
            return                      # success
        except PermissionError as exc:
            last_exc = exc
            if attempt < retries - 1:
                # Random jitter 1–6 s so each designer backs off independently
                time.sleep(random.uniform(1.0, 6.0))
        except Exception:
            raise
    raise last_exc


# ── Public entry point ───────────────────────────────────────────────────────

def export_to_sharepoint(target_date: str | None = None) -> tuple[bool, str]:
    """
    Generate the Excel report and save to the configured export folder.

    Returns (success: bool, message: str)
    """
    if not _OPENPYXL_OK:
        return False, f"openpyxl load error: {_OPENPYXL_ERROR}"

    cfg = load_config()
    designer     = cfg.get("designer_name", "Designer").strip() or "Designer"
    export_folder = cfg.get("export_folder", "").strip()

    if not export_folder:
        return False, "Export folder not configured. Please set it in Settings."
    if not os.path.isdir(export_folder):
        return False, f"Export folder not found:\n{export_folder}"

    if target_date is None:
        target_date = date.today().isoformat()

    # Gather data
    cases, ot_cases, downtimes, total_cases_pct, total_downtime_min = \
        _get_daily_data(target_date)
    year  = int(target_date[:4])
    month = int(target_date[5:7])
    monthly_rows = _get_monthly_data(year, month)

    # ── Build structured folder path ─────────────────────────────────────────
    # Productions/
    #   2026-02/
    #     Week-08/
    #       2026-02-23/
    #         Gerardo_Production_2026-02-23.xlsx
    d         = date.fromisoformat(target_date)
    week_num  = d.isocalendar()[1]
    month_str = d.strftime("%Y-%m")          # "2026-02"
    week_str  = f"Week-{week_num:02d}"        # "Week-08"

    productions_dir = os.path.join(export_folder, "Productions")
    day_dir = os.path.join(productions_dir, month_str, week_str, target_date)
    os.makedirs(day_dir, exist_ok=True)

    # Build workbook
    wb = openpyxl.Workbook()
    _build_daily_summary(wb, target_date, designer,
                         cases, ot_cases, downtimes,
                         total_cases_pct, total_downtime_min)
    _build_monthly_summary(wb, year, month, designer, monthly_rows)

    # Save individual daily file
    safe_name = designer.replace(" ", "_").replace("/", "-")
    filename  = f"{safe_name}_Production_{target_date}.xlsx"
    out_path  = os.path.join(day_dir, filename)

    try:
        _save_atomic(wb, out_path)
    except Exception as e:
        return False, f"Could not save daily file:\n{e}"

    # ── Update shared team summary ────────────────────────────────────────────
    ue_total, reg_type_counts, ot_type_counts = _get_ue_and_types(target_date)
    try:
        _update_team_summary(
            productions_dir, designer, target_date,
            total_cases_pct, total_downtime_min,
            len(cases), len(ot_cases),
            ue_total, reg_type_counts, ot_type_counts
        )
    except Exception as e:
        # Return False so the caller knows something went wrong
        return False, f"Daily report saved but team summary failed:\n{e}"

    safe_name = designer.replace(" ", "_").replace("/", "-")
    return True, (
        f"Report saved:\n{out_path}"
        f"\n\nSummary updated:\n{productions_dir}\\_Summary_{safe_name}.xlsx"
        f"\n\nDashboard rebuilt:\n{productions_dir}\\_Dashboard.xlsx"
        f"\n\nOneDrive will sync to SharePoint automatically."
    )
