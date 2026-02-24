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
        Font, PatternFill, Alignment, Border, Side, numbers
    )
    from openpyxl.utils import get_column_letter
    _OPENPYXL_OK = True
except Exception as _e:
    _OPENPYXL_OK = False
    _OPENPYXL_ERROR = str(_e)

from db.database import DB_PATH
from sync.app_config import load_config

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
    for col_cells in ws.columns:
        length = max((len(str(c.value)) if c.value else 0) for c in col_cells)
        ws.column_dimensions[get_column_letter(col_cells[0].column)].width = length + extra

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


def _update_team_summary(productions_dir: str, designer: str, target_date: str,
                         total_cases_pct: float, total_downtime_min: float,
                         n_cases: int, n_ot_cases: int):
    """
    Update (or create) Productions/_TeamProduction.xlsx.
    Each designer owns exactly one sheet named after them.
    Rows are one-per-day — if the date already exists it gets overwritten.
    Since every designer only touches their own sheet, concurrent writes are safe.
    """
    team_file  = os.path.join(productions_dir, "_TeamProduction.xlsx")
    sheet_name = _safe_sheet_name(designer)

    d        = date.fromisoformat(target_date)
    week_num = d.isocalendar()[1]
    dt_pct   = (total_downtime_min / DAILY_BASE_MINUTES) * 100
    total_pct = total_cases_pct + dt_pct

    # Load existing or create fresh workbook
    if os.path.exists(team_file):
        try:
            wb = openpyxl.load_workbook(team_file)
        except Exception:
            wb = openpyxl.Workbook()
            # Remove default blank sheet
            for s in list(wb.sheetnames):
                del wb[s]
    else:
        wb = openpyxl.Workbook()
        for s in list(wb.sheetnames):
            del wb[s]

    # Find or create designer sheet
    if sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
    else:
        ws = wb.create_sheet(sheet_name)
        ws.sheet_view.showGridLines = False
        # Header row
        headers = ["Date", "Week", "Cases (%)", "Downtime (%)",
                   "Total (%)", "Cases", "OT Cases"]
        for ci, h in enumerate(headers, 1):
            _hdr(ws.cell(1, ci), h)
        ws.freeze_panes = "A2"

    # Check if this date row already exists (update) or append
    found_row = None
    for row_cells in ws.iter_rows(min_row=2):
        if row_cells[0].value == target_date:
            found_row = row_cells[0].row
            break

    write_row = found_row if found_row else (ws.max_row + 1)
    row_idx   = write_row - 2   # for alternating bg
    bg = _GREY_ROW if row_idx % 2 == 0 else "FFFFFF"

    _cell(ws.cell(write_row, 1), target_date,             align="center", bg=bg)
    _cell(ws.cell(write_row, 2), f"W{week_num:02d}",      align="center", bg=bg)
    _cell(ws.cell(write_row, 3), f"{total_cases_pct:.2f}%", align="right", bg=bg)
    _cell(ws.cell(write_row, 4), f"{dt_pct:.2f}%",        align="right", bg=bg)
    _cell(ws.cell(write_row, 5), f"{total_pct:.2f}%",     bold=True,
          bg=_production_color(total_pct), color=_HEADER_FG, align="center")
    _cell(ws.cell(write_row, 6), n_cases,    align="center", bg=bg)
    _cell(ws.cell(write_row, 7), n_ot_cases, align="center", bg=bg)

    _autowidth(ws)
    wb.save(team_file)


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
        wb.save(out_path)
    except Exception as e:
        return False, f"Could not save daily file:\n{e}"

    # ── Update shared team summary ────────────────────────────────────────────
    team_err = ""
    try:
        _update_team_summary(
            productions_dir, designer, target_date,
            total_cases_pct, total_downtime_min,
            len(cases), len(ot_cases)
        )
    except Exception as e:
        team_err = f"\n\n⚠ Team summary could not be updated: {e}"

    return True, (
        f"Report saved:\n{out_path}"
        f"\n\nTeam summary updated:\n{productions_dir}\\_TeamProduction.xlsx"
        f"\n\nOneDrive will sync to SharePoint automatically."
        + team_err
    )
