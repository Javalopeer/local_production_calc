# -*- coding: utf-8 -*-
"""
Downtime Approval Workflow via a shared Excel file.

Flow:
  1. Designer adds a downtime → status = 'pending' in DB.
  2. App writes their pending rows into a SHARED file:
       <export_folder>/Productions/_Downtime_Approvals.xlsx
     Each row contains a 'Designer' column, so every designer's requests
     appear side-by-side — same pattern as _Dashboard.xlsx.
  3. The file syncs to SharePoint automatically via OneDrive/Teams.
  4. Supervisor opens the file, changes the 'Status' column to
     'approved' or 'rejected' for the relevant rows, then saves.
  5. Each designer's app polls the file every 15 s.  It only processes rows
     belonging to that designer.  Approved/rejected entries are applied to the
     local DB and removed from the shared file on the next export.
"""

import os
import subprocess
import time

from db.database import get_connection
from sync.app_config import load_config

STATUS_PENDING  = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

# Shared file — lives in the same Productions/ folder as _Dashboard.xlsx
SHARED_APPROVAL_FILE = "_Downtime_Approvals.xlsx"

_OPENPYXL_OK = False
try:
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side, Protection
    from openpyxl.worksheet.datavalidation import DataValidation
    _OPENPYXL_OK = True
except ImportError:
    pass

# Password required to unprotect sheets (delete rows, edit locked cells, etc.)
_SHEET_PASSWORD = "spark2026"


# ── helpers ──────────────────────────────────────────────────────────────────

def _thin():
    s = Side(style="thin", color="CCCCCC")
    return Border(left=s, right=s, top=s, bottom=s)


def get_approval_path() -> str | None:
    """Return the full path to the shared approval Excel, creating the
    Downtime/ folder if needed.  Returns None if the export folder is
    not configured or unreachable."""
    cfg = load_config()
    folder = cfg.get("export_folder", "").strip()
    if not folder:
        print("[downtime_approval] Export folder not configured.")
        return None
    if not os.path.isdir(folder):
        print(f"[downtime_approval] Export folder not found: {folder}")
        return None
    downtime_dir = os.path.join(folder, "Downtime")
    try:
        os.makedirs(downtime_dir, exist_ok=True)
    except OSError as e:
        print(f"[downtime_approval] Cannot create Downtime folder: {e}")
        return None
    return os.path.join(downtime_dir, SHARED_APPROVAL_FILE)


def _force_onedrive_refresh(path: str) -> None:
    """Force OneDrive to download the latest cloud version of a file.

    Strategy: rename the local copy to a backup, which makes OneDrive
    re-download the file from the cloud.  If the new file appears within
    a few seconds, we use it.  Otherwise, restore the backup so nothing
    is lost.
    """
    if not os.path.exists(path):
        return
    bak = path + ".bak_sync"
    try:
        old_mtime = os.path.getmtime(path)
        # Move local copy out of the way — OneDrive will recreate from cloud
        os.rename(path, bak)

        # Wait for OneDrive to re-download (up to ~4 seconds)
        for _ in range(8):
            time.sleep(0.5)
            if os.path.exists(path):
                break

        if os.path.exists(path):
            # OneDrive re-created it — remove backup
            new_mtime = os.path.getmtime(path)
            try:
                os.remove(bak)
            except OSError:
                pass
            if new_mtime != old_mtime:
                print("[downtime_approval] OneDrive delivered fresh file.")
            else:
                print("[downtime_approval] OneDrive re-synced (same content).")
        else:
            # OneDrive didn't recreate — restore backup
            os.rename(bak, path)
            print("[downtime_approval] OneDrive didn't re-sync, restored local copy.")
    except Exception as exc:
        # Restore backup if something went wrong
        print(f"[downtime_approval] OneDrive refresh failed: {exc}")
        if not os.path.exists(path):
            try:
                if os.path.exists(bak):
                    os.rename(bak, path)
            except OSError:
                pass


# ── export ────────────────────────────────────────────────────────────────────

def export_pending_downtimes(designer_name: str) -> bool:
    """Merge this designer's pending downtimes into the shared approval file.

    Strategy (safe for multi-designer use):
      1. Load the existing file (if any) and retain rows from *other* designers.
      2. Replace all rows for *this* designer with the current pending set from DB.
      3. Save.  Retry once if the file is momentarily locked.

    Returns True on success.
    """
    if not _OPENPYXL_OK:
        return False

    path = get_approval_path()
    if not path:
        return False

    # ── fetch this designer's pending rows from DB ───────────────────────────
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, fecha, hora_inicio, hora_fin, duracion, razon, status
        FROM downtimes
        WHERE status = 'pending'
        ORDER BY fecha DESC, hora_inicio DESC
    """)
    my_pending = cur.fetchall()
    conn.close()

    # ── fetch ALL this designer's downtimes for the history sheet ────────────
    conn2 = get_connection()
    cur2  = conn2.cursor()
    cur2.execute("""
        SELECT id, fecha, hora_inicio, hora_fin, duracion, razon, status
        FROM downtimes
        ORDER BY fecha DESC, hora_inicio DESC
    """)
    all_my_downtimes = cur2.fetchall()
    conn2.close()

    # ── load existing file and keep other designers' rows ────────────────────
    other_rows         = []   # pending sheet: (designer, id, date, start, end, dur, reason, status)
    other_history_rows = []   # history sheet: same shape
    if os.path.exists(path):
        try:
            wb_old = openpyxl.load_workbook(path, read_only=True, data_only=True)
            # ── approval sheet ────────────────────────────────────────────────
            ws_old = wb_old.active
            for r in ws_old.iter_rows(min_row=2, values_only=True):
                if not r or r[0] is None:
                    continue
                row_designer = str(r[0] or "").strip()
                # Skip placeholder rows
                if row_designer.startswith("("):
                    continue
                if row_designer.lower() != designer_name.strip().lower():
                    other_rows.append(r)
            # ── history sheet ─────────────────────────────────────────────────
            if "History" in wb_old.sheetnames:
                ws_hist_old = wb_old["History"]
                for r in ws_hist_old.iter_rows(min_row=2, values_only=True):
                    if not r or r[0] is None:
                        continue
                    row_designer = str(r[0] or "").strip()
                    if row_designer.startswith("("):
                        continue
                    if row_designer.lower() != designer_name.strip().lower():
                        other_history_rows.append(r)
            wb_old.close()
        except Exception as exc:
            print(f"[downtime_approval] Could not read existing file (will overwrite): {exc}")

    # ── build workbook ───────────────────────────────────────────────────────
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Downtime Approvals"
    ws.sheet_view.showGridLines = False

    headers = ["Designer", "ID", "Date", "Start", "End", "Duration (min)", "Reason", "Status"]
    hdr_fill = PatternFill("solid", fgColor="2D89EF")
    hdr_font = Font(color="FFFFFF", bold=True)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(1, col, h)
        cell.fill      = hdr_fill
        cell.font      = hdr_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border    = _thin()

    # Instruction note in column J
    note = ws.cell(1, 10, "► Change Status to 'approved' or 'rejected', then save.")
    note.font = Font(italic=True, color="555555")

    pend_fill = PatternFill("solid", fgColor="FFF9C4")
    other_fill = PatternFill("solid", fgColor="F8F8F8")

    _locked   = Protection(locked=True)
    _unlocked = Protection(locked=False)

    def _write_row(ws_ref, row_idx, designer, data_tuple, fill, unlock_status=False):
        vals = [designer] + list(data_tuple)
        for c_idx, val in enumerate(vals, 1):
            cell = ws_ref.cell(row_idx, c_idx, val)
            cell.alignment = Alignment(
                horizontal="left" if c_idx in (1, 7) else "center",
                vertical="center"
            )
            cell.fill   = fill
            cell.border = _thin()
            # Only the Status column (H = col 8) is editable
            cell.protection = _unlocked if (unlock_status and c_idx == 8) else _locked

    row_idx = 2
    # Write this designer's pending rows first
    for db_row in my_pending:
        _write_row(ws, row_idx, designer_name, db_row, pend_fill, unlock_status=True)
        row_idx += 1

    # Then all other designers' rows
    for r in other_rows:
        for c_idx, val in enumerate(r, 1):
            cell = ws.cell(row_idx, c_idx, val)
            cell.alignment = Alignment(
                horizontal="left" if c_idx in (1, 7) else "center",
                vertical="center"
            )
            cell.fill   = other_fill
            cell.border = _thin()
            # Unlock only Status column
            cell.protection = _unlocked if c_idx == 8 else _locked
        row_idx += 1

    if row_idx == 2:
        # Nothing at all — placeholder
        ws.cell(2, 1, "(no pending downtime requests)")
        ws.merge_cells("A2:H2")
        ws.cell(2, 1).alignment = Alignment(horizontal="center")

    # ── dropdown validation on Status column (H) ─────────────────────────────
    dv = DataValidation(
        type="list",
        formula1='"pending,approved,rejected"',
        allow_blank=False,
        showDropDown=False,   # False = show the arrow in Excel
        showErrorMessage=True,
        errorTitle="Invalid value",
        error="Please select: pending, approved, or rejected.",
    )
    ws.add_data_validation(dv)
    if row_idx > 2:           # only if there are actual data rows
        dv.sqref = f"H2:H{row_idx - 1}"

    # ── lock header cells ─────────────────────────────────────────────────
    for col in range(1, 9):
        ws.cell(1, col).protection = _locked

    # ── protect approval sheet ───────────────────────────────────────────────
    ws.protection.sheet     = True
    ws.protection.password  = _SHEET_PASSWORD
    ws.protection.enable()
    # Explicitly disable destructive actions
    ws.protection.deleteRows    = False
    ws.protection.deleteColumns = False
    ws.protection.insertRows    = False
    ws.protection.insertColumns = False
    ws.protection.formatCells   = False
    ws.protection.formatColumns = False
    ws.protection.formatRows    = False
    ws.protection.sort          = False
    ws.protection.autoFilter    = False

    # Column widths
    widths = {"A": 22, "B": 8, "C": 14, "D": 10, "E": 10, "F": 16, "G": 38, "H": 14}
    for col_letter, width in widths.items():
        ws.column_dimensions[col_letter].width = width
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"

    # ── build History sheet ───────────────────────────────────────────────────
    ws_hist = wb.create_sheet("History")
    ws_hist.sheet_view.showGridLines = False

    hist_hdr_fill = PatternFill("solid", fgColor="4CAF50")
    for col, h in enumerate(headers, 1):
        cell = ws_hist.cell(1, col, h)
        cell.fill      = hist_hdr_fill
        cell.font      = hdr_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border    = _thin()

    status_fills = {
        STATUS_APPROVED: PatternFill("solid", fgColor="E8F5E9"),
        STATUS_REJECTED: PatternFill("solid", fgColor="FFEBEE"),
        STATUS_PENDING:  PatternFill("solid", fgColor="FFF9C4"),
    }

    hist_row = 2
    for db_row in all_my_downtimes:
        row_status = str(db_row[6] or STATUS_PENDING).lower()
        row_fill   = status_fills.get(row_status, other_fill)
        vals = [designer_name] + list(db_row)
        for c_idx, val in enumerate(vals, 1):
            cell = ws_hist.cell(hist_row, c_idx, val)
            cell.alignment = Alignment(
                horizontal="left" if c_idx in (1, 7) else "center",
                vertical="center"
            )
            cell.fill   = row_fill
            cell.border = _thin()
        hist_row += 1

    for r in other_history_rows:
        row_status = str(r[7] if len(r) > 7 else STATUS_APPROVED).lower()
        row_fill   = status_fills.get(row_status, other_fill)
        for c_idx, val in enumerate(r, 1):
            cell = ws_hist.cell(hist_row, c_idx, val)
            cell.alignment = Alignment(
                horizontal="left" if c_idx in (1, 7) else "center",
                vertical="center"
            )
            cell.fill   = row_fill
            cell.border = _thin()
        hist_row += 1

    if hist_row == 2:
        ws_hist.cell(2, 1, "(no downtime history yet)")
        ws_hist.merge_cells("A2:H2")
        ws_hist.cell(2, 1).alignment = Alignment(horizontal="center")

    # ── lock all history cells ────────────────────────────────────────────────
    for r in ws_hist.iter_rows(min_row=1, max_row=max(hist_row - 1, 1), max_col=8):
        for cell in r:
            cell.protection = _locked

    # ── protect history sheet (fully read-only) ──────────────────────────────
    ws_hist.protection.sheet    = True
    ws_hist.protection.password = _SHEET_PASSWORD
    ws_hist.protection.enable()

    for col_letter, width in widths.items():
        ws_hist.column_dimensions[col_letter].width = width
    ws_hist.row_dimensions[1].height = 22
    ws_hist.freeze_panes = "A2"

    # ── save with retry on lock ───────────────────────────────────────────────
    for attempt in range(3):
        try:
            wb.save(path)
            print(f"[downtime_approval] Saved: {path}")
            return True
        except PermissionError:
            if attempt < 2:
                time.sleep(1)
            else:
                print(f"[downtime_approval] File locked after retries: {path}")
                return False
        except Exception as exc:
            print(f"[downtime_approval] Export failed: {exc}")
            return False
    return False


# ── poll ──────────────────────────────────────────────────────────────────────

def poll_and_process_responses(designer_name: str) -> int:
    """Read the shared approval Excel and process responses for this designer.

    Columns: Designer(0) ID(1) Date(2) Start(3) End(4) Duration(5) Reason(6) Status(7)

    Only rows belonging to this designer and whose Status is 'approved' or
    'rejected' are processed.  Updates the local DB accordingly.
    Returns the number of rows updated.
    """
    if not _OPENPYXL_OK:
        return 0

    path = get_approval_path()
    if not path or not os.path.exists(path):
        return 0

    # Force OneDrive to download the latest version before reading
    _force_onedrive_refresh(path)

    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        excel_rows = list(ws.iter_rows(min_row=2, values_only=True))
        wb.close()
    except Exception as exc:
        print(f"[downtime_approval] Could not read approval file: {exc}")
        return 0

    processed = 0
    conn = get_connection()
    cur  = conn.cursor()

    for row in excel_rows:
        if not row or row[0] is None:
            continue
        # col 0 = Designer, col 1 = ID, col 7 = Status
        row_designer = str(row[0] or "").strip().lower()
        if row_designer != designer_name.strip().lower():
            continue
        try:
            row_id = int(row[1])
        except (TypeError, ValueError):
            continue
        status = str(row[7] or "").strip().lower()
        if status in (STATUS_APPROVED, STATUS_REJECTED):
            cur.execute(
                "UPDATE downtimes SET status = ? WHERE id = ? AND status = 'pending'",
                (status, row_id),
            )
            if cur.rowcount > 0:
                processed += 1

    conn.commit()
    conn.close()

    # If anything changed, re-export to remove processed rows from the file
    if processed > 0:
        export_pending_downtimes(designer_name)

    return processed
