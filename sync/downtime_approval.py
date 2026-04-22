# -*- coding: utf-8 -*-
"""
Downtime Approval Workflow — per-designer files + consolidated view.

Architecture (scales to 30+ designers without conflicts):
  1. Designer adds a downtime → status = 'pending' in local DB.
  2. App writes ONLY this designer's rows to their own file:
       Downtime/designers_dt/_DT_<DesignerName>.xlsx
     No other designer ever touches this file → zero write conflicts.
  3. App reads ALL designers_dt/_DT_*.xlsx files and builds a consolidated file:
       Downtime/_Downtime_Approvals.xlsx
     If this write fails (locked by supervisor), it silently skips — next
     cycle will rebuild it.  The supervisor's edits are never overwritten
     because the consolidated file is rebuilt from scratch each time.
  4. Supervisor opens _Downtime_Approvals.xlsx, changes Status to
     'approved' or 'rejected', then saves.
  5. Each designer's app polls _Downtime_Approvals.xlsx every 15 s,
     reads only their own rows, and applies changes to local DB.
"""

import glob
import json
import os
import time
from datetime import datetime

from db.database import get_connection
from sync import get_local_app_dir
from sync.app_config import load_config, get_excel_sheet_password
from sync.app_logger import log_event

STATUS_PENDING  = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

_DT_WRITE_JITTER   = (1.0, 4.0)  # random backoff (s) on individual designer file write retry
_DT_CONSOL_JITTER  = (0.5, 2.0)  # random backoff (s) on consolidated file write retry

CONSOLIDATED_FILE = "_Downtime_Approvals.xlsx"

# Cache: track the latest mtime of _DT_*.xlsx files to skip unnecessary rebuilds
_last_rebuild_max_mtime: float = 0.0

# Poll cache: remember last consolidated-file mtime so we only load the
# workbook when it actually changed. Falls back to a full read every
# `_POLL_FORCE_EVERY` cycles in case Power Automate updates via Excel
# Online don't bump the filesystem mtime on OneDrive sync.
_last_polled_consolidated_mtime: float = 0.0
_poll_skip_count: int = 0
_POLL_FORCE_EVERY = 5

# Track failed exports so they can be retried on next poll cycle
_pending_retry_designer: str = ""

# Track already-processed Teams response files to avoid re-processing.
# Persisted locally so each machine tracks independently without
# renaming/deleting files from the shared folder.
_LOCAL_PROCESSED_FILE = get_local_app_dir("processed_responses.json")

def _load_processed_responses() -> set:
    """Load the set of already-processed response file basenames from local disk."""
    try:
        with open(_LOCAL_PROCESSED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception as exc:
        log_event("downtime_approval", f"load processed responses failed: {exc}", level="WARN")
        return set()

def _save_processed_responses(processed: set) -> None:
    """Persist the set of processed response basenames to local disk."""
    os.makedirs(os.path.dirname(_LOCAL_PROCESSED_FILE), exist_ok=True)
    try:
        with open(_LOCAL_PROCESSED_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(processed), f)
    except Exception as exc:
        log_event("downtime_approval", f"save processed responses failed: {exc}", level="WARN")

_processed_response_files: set = _load_processed_responses()

_OPENPYXL_OK = False
try:
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side, Protection
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.worksheet.table import Table as XlTable, TableStyleInfo
    _OPENPYXL_OK = True
except ImportError:
    log_event("downtime_approval", "openpyxl not installed; approval excel features disabled", level="WARN")

_SHEET_PASSWORD = get_excel_sheet_password()


# ── helpers ──────────────────────────────────────────────────────────────────

def _thin():
    s = Side(style="thin", color="CCCCCC")
    return Border(left=s, right=s, top=s, bottom=s)


_README_TEXT = (
    "Downtime folder\n"
    "================\n\n"
    "For approval history, open:\n"
    "  _Approval_History.xlsx\n\n"
    "It shows every downtime request with the responder name and timestamp.\n\n"
    "Do NOT edit:\n"
    "  _Downtime_Approvals.xlsx    — managed by Power Automate / the app.\n"
    "  designers_dt\\_DT_<name>.xlsx — individual designer files.\n"
    "  responses\\response_*.json   — Teams adaptive card responses.\n\n"
    "Manual edits to those files will be overwritten by the next rebuild.\n"
)


def _ensure_downtime_readme(downtime_dir: str) -> None:
    """Write README.txt once so leads know which file is for them."""
    readme_path = os.path.join(downtime_dir, "README.txt")
    if os.path.exists(readme_path):
        return
    try:
        with open(readme_path, "w", encoding="utf-8") as fh:
            fh.write(_README_TEXT)
    except OSError as exc:
        log_event("downtime_approval", f"could not write README.txt: {exc}", level="WARN")


def _get_downtime_dir() -> str | None:
    """Return the Downtime/ folder path, creating it if needed."""
    cfg = load_config()
    folder = cfg.get("export_folder", "").strip()
    if not folder:
        return None
    if not os.path.isdir(folder):
        return None
    downtime_dir = os.path.join(folder, "Downtime")
    try:
        os.makedirs(downtime_dir, exist_ok=True)
    except OSError:
        return None
    _ensure_downtime_readme(downtime_dir)
    return downtime_dir


def get_approval_path() -> str | None:
    """Return the full path to the consolidated approval file."""
    d = _get_downtime_dir()
    return os.path.join(d, CONSOLIDATED_FILE) if d else None


def _designer_file_path(designer_name: str) -> str | None:
    """Return the path for this designer's individual file inside designers_dt/."""
    d = _get_downtime_dir()
    if not d:
        return None
    designers_dir = os.path.join(d, "designers_dt")
    try:
        os.makedirs(designers_dir, exist_ok=True)
    except OSError:
        return None
    safe_name = "".join(c for c in designer_name.strip() if c.isalnum() or c in " _-").strip()
    if not safe_name:
        safe_name = "Unknown"
    return os.path.join(designers_dir, f"_DT_{safe_name}.xlsx")


def _force_onedrive_refresh(path: str) -> None:
    """Hint OneDrive to check for updates."""
    if not os.path.exists(path):
        return
    try:
        parent = os.path.dirname(path)
        os.listdir(parent)
        os.stat(path)
    except Exception as exc:
        log_event("downtime_approval", f"onedrive refresh hint failed for {os.path.basename(path)}: {exc}", level="WARN")


def _save_workbook(wb, path: str, retries: int = 6) -> bool:
    """Save a workbook with retries + random jitter for OneDrive locks."""
    import random
    for attempt in range(retries):
        try:
            wb.save(path)
            return True
        except PermissionError:
            if attempt < retries - 1:
                time.sleep(random.uniform(*_DT_WRITE_JITTER))
        except Exception as exc:
            log_event("downtime_approval", f"save failed: {exc}", level="WARN")
            return False
    log_event("downtime_approval", f"file locked after {retries} attempts: {os.path.basename(path)}", level="WARN")
    return False


def _save_consolidated_verified(wb, path: str, verify_delay: float = 5.0,
                                retries: int = 2) -> bool:
    """Save the consolidated approvals file, then verify its content didn't
    get mutated by OneDrive or another writer. Re-saves up to `retries`
    times. Always re-reads any fresh supervisor_edits (Power Automate status
    changes) before the re-save so we never clobber them.
    """
    import hashlib

    def _sha(p: str):
        try:
            with open(p, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        except Exception:
            return None

    if not _save_workbook(wb, path):
        return False
    original = _sha(path)
    if original is None:
        return True

    for attempt in range(retries):
        time.sleep(verify_delay)
        current = _sha(path)
        if current == original:
            return True
        log_event("downtime_approval",
                  f"consolidated mutated after save (hash mismatch), re-saving attempt {attempt + 1}",
                  level="WARN")
        # Re-read supervisor edits (e.g. Power Automate Status changes) from
        # the current file so the re-save preserves them.
        try:
            _wb_cur = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws_cur = _wb_cur.active
            edits = {}
            for r in ws_cur.iter_rows(min_row=2, values_only=True):
                if not r or r[0] is None:
                    continue
                row_designer = str(r[0] or "").strip()
                if row_designer.startswith("("):
                    continue
                try:
                    rid = int(r[1])
                    st = str(r[7] or "").strip().lower()
                except (TypeError, ValueError):
                    continue
                if st in (STATUS_APPROVED, STATUS_REJECTED):
                    edits[(row_designer.lower(), rid)] = st
            _wb_cur.close()
            # Apply preserved edits into the in-memory workbook
            if edits:
                ws_mem = wb.active
                for rr in ws_mem.iter_rows(min_row=2):
                    if not rr or rr[0].value is None:
                        continue
                    try:
                        rid = int(rr[1].value)
                    except (TypeError, ValueError):
                        continue
                    key = (str(rr[0].value).strip().lower(), rid)
                    if key in edits:
                        rr[7].value = edits[key]
        except Exception as exc:
            log_event("downtime_approval",
                      f"consolidated verify read-back failed: {exc}", level="WARN")

        if not _save_workbook(wb, path):
            return False
        original = _sha(path)
        if original is None:
            return True
    return True


def _read_workbook(path: str, retries: int = 4):
    """Read a workbook with retries. Returns workbook or None."""
    import random
    for attempt in range(retries):
        try:
            return openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:
            if attempt == retries - 1:
                log_event("downtime_approval", f"read workbook failed for {os.path.basename(path)} after {retries} tries: {exc}", level="WARN")
            if attempt < retries - 1:
                time.sleep(random.uniform(*_DT_CONSOL_JITTER))
    return None


# ── export (per-designer file) ───────────────────────────────────────────────

def export_pending_downtimes(designer_name: str) -> bool:
    """Write this designer's downtimes to their own _DT_<name>.xlsx file,
    then rebuild the consolidated file.

    Returns True on success.  On failure, sets _pending_retry_designer so
    the next poll cycle will retry automatically.
    """
    global _pending_retry_designer
    if not _OPENPYXL_OK:
        return False

    designer_path = _designer_file_path(designer_name)
    if not designer_path:
        return False

    # ── Before exporting, absorb any approvals from the consolidated file ────
    _absorb_from_consolidated(designer_name)

    # ── Fetch data from DB ───────────────────────────────────────────────────
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, fecha, hora_inicio, hora_fin, duracion, razon, status,
               responded_by, responded_at
        FROM downtimes
        ORDER BY fecha DESC, hora_inicio DESC
    """)
    all_rows = cur.fetchall()
    conn.close()

    pending = [r for r in all_rows if r[6] == STATUS_PENDING]

    # ── Build designer workbook ──────────────────────────────────────────────
    wb = openpyxl.Workbook()

    # -- Pending sheet --
    ws = wb.active
    ws.title = "Pending"
    headers = ["Designer", "ID", "Date", "Start", "End", "Duration (min)", "Reason", "Status",
               "Responded By", "Responded At"]
    _write_header(ws, headers, PatternFill("solid", fgColor="2D89EF"))

    pend_fill = PatternFill("solid", fgColor="FFF9C4")
    row_idx = 2
    for db_row in pending:
        _write_data_row(ws, row_idx, designer_name, db_row, pend_fill)
        row_idx += 1
    if row_idx == 2:
        ws.cell(2, 1, "(no pending requests)")
        ws.merge_cells("A2:J2")
        ws.cell(2, 1).alignment = Alignment(horizontal="center")

    _set_column_widths(ws)

    # -- History sheet --
    ws_hist = wb.create_sheet("History")
    _write_header(ws_hist, headers, PatternFill("solid", fgColor="4CAF50"))

    status_fills = {
        STATUS_APPROVED: PatternFill("solid", fgColor="E8F5E9"),
        STATUS_REJECTED: PatternFill("solid", fgColor="FFEBEE"),
        STATUS_PENDING:  PatternFill("solid", fgColor="FFF9C4"),
    }
    hist_row = 2
    for db_row in all_rows:
        row_status = str(db_row[6] or STATUS_PENDING).lower()
        fill = status_fills.get(row_status, PatternFill("solid", fgColor="F8F8F8"))
        _write_data_row(ws_hist, hist_row, designer_name, db_row, fill)
        hist_row += 1
    if hist_row == 2:
        ws_hist.cell(2, 1, "(no downtime history)")
        ws_hist.merge_cells("A2:J2")
        ws_hist.cell(2, 1).alignment = Alignment(horizontal="center")

    _set_column_widths(ws_hist)

    # ── Save designer file (only this designer writes here → no conflicts) ──
    if not _save_workbook(wb, designer_path):
        _pending_retry_designer = designer_name
        print(f"[downtime_approval] Export failed, will retry on next poll cycle.")
        return False
    print(f"[downtime_approval] Designer file saved: {os.path.basename(designer_path)}")

    # ── Rebuild consolidated file ────────────────────────────────────────────
    _rebuild_consolidated(force=True)

    _pending_retry_designer = ""
    return True


def _absorb_from_consolidated(designer_name: str) -> int:
    """Read the consolidated file and apply any approvals/rejections
    that the supervisor made for this designer. Returns count absorbed."""
    consolidated_path = get_approval_path()
    if not consolidated_path or not os.path.exists(consolidated_path):
        return 0

    _force_onedrive_refresh(consolidated_path)
    wb = _read_workbook(consolidated_path)
    if wb is None:
        return 0

    absorbed = 0
    try:
        ws = wb.active
        for r in ws.iter_rows(min_row=2, values_only=True):
            if not r or r[0] is None:
                continue
            row_designer = str(r[0] or "").strip()
            if row_designer.startswith("("):
                continue
            if row_designer.lower() != designer_name.strip().lower():
                continue
            try:
                row_id = int(r[1])
                status = str(r[7] or "").strip().lower()
            except (TypeError, ValueError):
                continue
            if status in (STATUS_APPROVED, STATUS_REJECTED):
                conn = get_connection()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE downtimes SET status = ? WHERE id = ? AND status = 'pending'",
                    (status, row_id),
                )
                if cur.rowcount > 0:
                    absorbed += 1
                    print(f"[downtime_approval] Absorbed {status} for ID {row_id}")
                conn.commit()
                conn.close()
        wb.close()
    except Exception as exc:
        print(f"[downtime_approval] Error absorbing from consolidated: {exc}")

    return absorbed


# ── consolidated file rebuild ────────────────────────────────────────────────

def _rebuild_consolidated(force: bool = False) -> bool:
    """Read all _DT_*.xlsx files and build _Downtime_Approvals.xlsx.

    Skips the rebuild if no _DT_*.xlsx file has changed since the last
    rebuild (based on file mtimes), unless force=True.
    """
    global _last_rebuild_max_mtime

    downtime_dir = _get_downtime_dir()
    if not downtime_dir:
        return False

    consolidated_path = os.path.join(downtime_dir, CONSOLIDATED_FILE)

    # ── Check if any designer file changed since last rebuild ────────────────
    designers_dir = os.path.join(downtime_dir, "designers_dt")
    os.makedirs(designers_dir, exist_ok=True)
    pattern = os.path.join(designers_dir, "_DT_*.xlsx")
    dt_files = [f for f in glob.glob(pattern) if os.path.basename(f) != CONSOLIDATED_FILE]

    if not force and dt_files:
        max_mtime = max(os.path.getmtime(f) for f in dt_files)
        if max_mtime <= _last_rebuild_max_mtime and os.path.exists(consolidated_path):
            print("[downtime_approval] No designer files changed, skipping rebuild.")
            return True

    # ── First, read any existing supervisor edits from the consolidated file ─
    #    so we can preserve their approved/rejected status changes
    supervisor_edits = {}  # (designer_lower, id) → status
    if os.path.exists(consolidated_path):
        wb_old = _read_workbook(consolidated_path)
        if wb_old is not None:
            try:
                ws_old = wb_old.active
                for r in ws_old.iter_rows(min_row=2, values_only=True):
                    if not r or r[0] is None:
                        continue
                    row_designer = str(r[0] or "").strip()
                    if row_designer.startswith("("):
                        continue
                    try:
                        row_id = int(r[1])
                        status = str(r[7] or "").strip().lower()
                    except (TypeError, ValueError):
                        continue
                    if status in (STATUS_APPROVED, STATUS_REJECTED):
                        supervisor_edits[(row_designer.lower(), row_id)] = status
                wb_old.close()
            except Exception as exc:
                log_event("downtime_approval", f"failed reading existing consolidated edits: {exc}", level="WARN")

    # ── Collect pending rows from all designer files ─────────────────────────
    all_pending = []  # list of 10-tuples (designer, id, date, start, end, dur, reason, status, responded_by, responded_at)
    all_history = []

    def _pad10(r):
        tup = list(r[:10])
        while len(tup) < 10:
            tup.append("")
        return tuple(tup)

    for dt_file in dt_files:
        wb = _read_workbook(dt_file, retries=2)
        if wb is None:
            continue
        try:
            # Read Pending sheet
            ws = wb.active
            for r in ws.iter_rows(min_row=2, values_only=True):
                if not r or r[0] is None:
                    continue
                row_designer = str(r[0] or "").strip()
                if row_designer.startswith("("):
                    continue
                row_tuple = _pad10(r)
                # Check if supervisor already changed status in consolidated
                try:
                    row_id = int(r[1])
                    key = (row_designer.lower(), row_id)
                    if key in supervisor_edits:
                        # Preserve supervisor's edit
                        row_list = list(row_tuple)
                        row_list[7] = supervisor_edits[key]
                        row_tuple = tuple(row_list)
                except (TypeError, ValueError):
                    pass
                all_pending.append(row_tuple)

            # Read History sheet
            if "History" in wb.sheetnames:
                ws_hist = wb["History"]
                for r in ws_hist.iter_rows(min_row=2, values_only=True):
                    if not r or r[0] is None:
                        continue
                    row_designer = str(r[0] or "").strip()
                    if row_designer.startswith("("):
                        continue
                    all_history.append(_pad10(r))

            wb.close()
        except Exception as exc:
            print(f"[downtime_approval] Error reading {os.path.basename(dt_file)}: {exc}")

    # ── Build consolidated workbook ──────────────────────────────────────────
    wb = openpyxl.Workbook()

    # -- Pending Approvals sheet --
    ws = wb.active
    ws.title = "Downtime Approvals"
    ws.sheet_view.showGridLines = False
    headers = ["Designer", "ID", "Date", "Start", "End", "Duration (min)", "Reason", "Status",
               "Responded By", "Responded At"]
    _write_header(ws, headers, PatternFill("solid", fgColor="2D89EF"))

    note = ws.cell(1, 12, "► Managed by Power Automate. Responses tracked per designer.")
    note.font = Font(italic=True, color="555555")

    _locked   = Protection(locked=True)
    _unlocked = Protection(locked=False)

    pend_fill  = PatternFill("solid", fgColor="FFF9C4")
    other_fill = PatternFill("solid", fgColor="F8F8F8")

    row_idx = 2
    for r in all_pending:
        for c_idx, val in enumerate(r, 1):
            cell = ws.cell(row_idx, c_idx, val)
            cell.alignment = Alignment(
                horizontal="left" if c_idx in (1, 7) else "center",
                vertical="center"
            )
            cell.fill   = pend_fill
            cell.border = _thin()
            cell.protection = _unlocked if c_idx == 8 else _locked
        row_idx += 1

    if row_idx == 2:
        # Add a placeholder row so the Excel Table always exists
        placeholder = ["—", 0, "—", "—", "—", 0, "(no pending requests)", "—", "", ""]
        for c_idx, val in enumerate(placeholder, 1):
            cell = ws.cell(2, c_idx, val)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.fill   = other_fill
            cell.border = _thin()
        row_idx = 3

    # Dropdown validation on Status column
    dv = DataValidation(
        type="list",
        formula1='"pending,approved,rejected"',
        allow_blank=False,
        showDropDown=False,
        showErrorMessage=True,
        errorTitle="Invalid value",
        error="Please select: pending, approved, or rejected.",
    )
    ws.add_data_validation(dv)
    dv.sqref = f"H2:H{row_idx - 1}"

    _set_column_widths(ws)
    ws.freeze_panes = "A2"

    # Column filter dropdowns so leads can filter by Date / Reason / Status /
    # Designer before bulk-approving a time window.
    ws.auto_filter.ref = f"A1:J{row_idx - 1}"

    # Add Excel Table so Power Automate can find and update rows by ID.
    # Ref extended to J so Responded By / Responded At are inside the table
    # (non-breaking: PA updates Status by column name, not by index).
    tab = XlTable(
        displayName="DowntimeApprovals",
        ref=f"A1:J{row_idx - 1}",
    )
    tab.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showRowStripes=True,
    )
    ws.add_table(tab)

    # -- History sheet --
    ws_hist = wb.create_sheet("History")
    ws_hist.sheet_view.showGridLines = False
    _write_header(ws_hist, headers, PatternFill("solid", fgColor="4CAF50"))

    status_fills = {
        STATUS_APPROVED: PatternFill("solid", fgColor="E8F5E9"),
        STATUS_REJECTED: PatternFill("solid", fgColor="FFEBEE"),
        STATUS_PENDING:  PatternFill("solid", fgColor="FFF9C4"),
    }
    hist_row = 2
    for r in all_history:
        row_status = str(r[7] if len(r) > 7 else STATUS_PENDING).lower()
        fill = status_fills.get(row_status, other_fill)
        for c_idx, val in enumerate(r, 1):
            cell = ws_hist.cell(hist_row, c_idx, val)
            cell.alignment = Alignment(
                horizontal="left" if c_idx in (1, 7) else "center",
                vertical="center"
            )
            cell.fill   = fill
            cell.border = _thin()
            cell.protection = _locked
        hist_row += 1

    if hist_row == 2:
        ws_hist.cell(2, 1, "(no downtime history)")
        ws_hist.merge_cells("A2:J2")
        ws_hist.cell(2, 1).alignment = Alignment(horizontal="center")

    ws_hist.protection.sheet    = True
    ws_hist.protection.password = _SHEET_PASSWORD
    ws_hist.protection.autoFilter = False  # allow leads to use the dropdowns
    ws_hist.protection.sort       = False
    ws_hist.protection.enable()
    _set_column_widths(ws_hist)
    ws_hist.freeze_panes = "A2"
    if hist_row > 2:
        ws_hist.auto_filter.ref = f"A1:J{hist_row - 1}"

    # ── Save consolidated — if it fails, no problem, next cycle rebuilds ─────
    if _save_consolidated_verified(wb, consolidated_path):
        # Update mtime cache so next call skips rebuild if nothing changed
        if dt_files:
            _last_rebuild_max_mtime = max(os.path.getmtime(f) for f in dt_files if os.path.exists(f))
        print(f"[downtime_approval] Consolidated file rebuilt with {row_idx - 2} pending row(s).")
        return True
    else:
        print("[downtime_approval] Could not update consolidated file (supervisor may have it open). Will retry next cycle.")
        return False


# ── shared formatting helpers ────────────────────────────────────────────────

def _write_header(ws, headers: list, fill: PatternFill):
    hdr_font = Font(color="FFFFFF", bold=True)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(1, col, h)
        cell.fill      = fill
        cell.font      = hdr_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border    = _thin()


def _write_data_row(ws, row_idx: int, designer: str, db_row, fill: PatternFill):
    # db_row may have 7 (legacy) or 9 (with responded_by/at) fields;
    # pad to 9 so the sheet always has the two extra columns.
    row_vals = list(db_row)
    while len(row_vals) < 9:
        row_vals.append("")
    vals = [designer] + row_vals[:9]
    for c_idx, val in enumerate(vals, 1):
        cell = ws.cell(row_idx, c_idx, val)
        cell.alignment = Alignment(
            horizontal="left" if c_idx in (1, 7) else "center",
            vertical="center"
        )
        cell.fill   = fill
        cell.border = _thin()


def _set_column_widths(ws):
    widths = {"A": 22, "B": 8, "C": 14, "D": 10, "E": 10, "F": 16, "G": 38, "H": 14,
              "I": 22, "J": 20}
    for col_letter, width in widths.items():
        ws.column_dimensions[col_letter].width = width
    ws.row_dimensions[1].height = 22


# ── poll ─────────────────────────────────────────────────────────────────────

def _poll_teams_responses(designer_name: str = "") -> int:
    """Read response_*.json files from Downtime/responses/ and apply decisions.

    Each file is created by Power Automate when a supervisor clicks
    Approve or Reject on the Teams Adaptive Card.

    Expected JSON format:
        {"dt_id": 91, "decision": "approved", "designer": "Name",
         "responded_by": "Name", "responded_at": "..."}

    Only processes files whose "designer" field matches *designer_name*
    (case-insensitive).  Files without a designer field are accepted for
    backwards compatibility but matched only by dt_id.

    Returns the number of downtimes updated.
    """
    downtime_dir = _get_downtime_dir()
    if not downtime_dir:
        return 0

    responses_dir = os.path.join(downtime_dir, "responses")
    if not os.path.isdir(responses_dir):
        return 0

    # Read both .json and .json.done (old builds renamed files in shared folder)
    files = glob.glob(os.path.join(responses_dir, "response_*.json"))
    files += glob.glob(os.path.join(responses_dir, "response_*.json.done"))
    if not files:
        return 0

    updated = 0
    conn = get_connection()
    cur = conn.cursor()

    for fpath in files:
        basename = os.path.basename(fpath)
        already = basename in _processed_response_files
        print(f"[DEBUG] Found file: {basename}, processed={already}")
        if already:
            continue

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            print(f"[downtime_approval] Bad response file {os.path.basename(fpath)}: {exc}")
            continue

        dt_id = data.get("dt_id")
        raw_decision = str(data.get("decision", "")).strip().lower()

        # Normalize: Power Automate may return "✅ Approve" or "approved"
        if "approve" in raw_decision:
            decision = STATUS_APPROVED
        elif "reject" in raw_decision:
            decision = STATUS_REJECTED
        else:
            print(f"[downtime_approval] Skipping invalid response: {data}")
            continue

        if not dt_id:
            print(f"[downtime_approval] Skipping response without dt_id: {data}")
            continue

        # Filter by designer so each machine only processes its own DTs
        file_designer = str(data.get("designer", "")).strip().lower()
        if file_designer and designer_name and file_designer != designer_name.strip().lower():
            continue  # Not ours — leave the file for the right machine

        responded_by = str(data.get("responded_by", "")).strip()
        responded_at = str(data.get("responded_at", "")).strip()

        cur.execute(
            "UPDATE downtimes SET status = ?, responded_by = ?, responded_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (decision, responded_by, responded_at, int(dt_id)),
        )
        print(f"[DEBUG] UPDATE rowcount={cur.rowcount} for dt_id={dt_id}")
        if cur.rowcount > 0:
            updated += 1
            print(f"[downtime_approval] Teams response: {decision} for DT #{dt_id} "
                  f"(by {responded_by or '?'})")
            # Track locally — never rename/delete from the shared folder
            # so other machines can still read the same file.
            _processed_response_files.add(basename)
            _save_processed_responses(_processed_response_files)

    conn.commit()
    conn.close()
    return updated


def poll_and_process_responses(designer_name: str) -> int:
    """Read the consolidated approval file and process supervisor responses
    for this designer.  Returns the number of rows updated.

    Also checks for Teams Adaptive Card responses (response_*.json files)
    and retries any previously failed export automatically.
    """
    global _pending_retry_designer
    if not _OPENPYXL_OK:
        return 0

    # ── Check Teams Adaptive Card responses first ─────────────────────────
    teams_updated = _poll_teams_responses(designer_name)

    # ── Retry failed export from a previous cycle ─────────────────────────
    if _pending_retry_designer:
        print("[downtime_approval] Retrying previously failed export...")
        export_pending_downtimes(_pending_retry_designer)

    path = get_approval_path()
    if not path or not os.path.exists(path):
        # Still return teams_updated even if no consolidated file
        if teams_updated > 0:
            export_pending_downtimes(designer_name)
        return teams_updated

    _force_onedrive_refresh(path)

    # ── mtime skip: only read full workbook if file changed since last poll.
    # Force full read every _POLL_FORCE_EVERY cycles as a safety net in case
    # Power Automate updates via Excel Online don't bump the filesystem
    # mtime on OneDrive sync. ──────────────────────────────────────────────
    global _last_polled_consolidated_mtime, _poll_skip_count
    try:
        current_mtime = os.path.getmtime(path)
    except OSError:
        current_mtime = 0.0

    if (current_mtime == _last_polled_consolidated_mtime
            and _poll_skip_count < _POLL_FORCE_EVERY):
        _poll_skip_count += 1
        # IMPORTANT: even when we skip the consolidated read, we must still
        # re-export the designer file + history if Teams responses just
        # updated the DB, otherwise the shared Excel files stay showing
        # 'pending' while the local DB already has approved/rejected.
        if teams_updated > 0:
            export_pending_downtimes(designer_name)
            export_approval_history()
        return teams_updated

    _poll_skip_count = 0
    _last_polled_consolidated_mtime = current_mtime

    wb = _read_workbook(path)
    if wb is None:
        return 0

    processed = 0
    try:
        ws = wb.active
        excel_rows = list(ws.iter_rows(min_row=2, values_only=True))
        wb.close()
    except Exception as exc:
        print(f"[downtime_approval] Could not read consolidated file: {exc}")
        return 0

    conn = get_connection()
    cur = conn.cursor()

    for row in excel_rows:
        if not row or row[0] is None:
            continue
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

    total = processed + teams_updated

    # Re-export to update the designer file (removes processed rows from pending)
    if total > 0:
        export_pending_downtimes(designer_name)
        export_approval_history()

    # Periodic maintenance: clean old response files
    _cleanup_old_responses()

    return total


# ── Approval history Excel ──────────────────────────────────────────────────

APPROVAL_HISTORY_FILE = "_Approval_History.xlsx"


def export_approval_history() -> bool:
    """Export all approval responses from the DB to a shared Excel file.

    Creates/overwrites Downtime/_Approval_History.xlsx with all downtimes
    that have been approved or rejected, including who responded and when.
    """
    if not _OPENPYXL_OK:
        return False

    downtime_dir = _get_downtime_dir()
    if not downtime_dir:
        return False

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, fecha, hora_inicio, hora_fin, duracion, razon, status,
               detalle, responded_by, responded_at
        FROM downtimes
        WHERE status IN ('approved', 'rejected')
        ORDER BY fecha DESC, hora_inicio DESC
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return True

    # Get designer name for the export
    cfg = load_config()
    designer = cfg.get("designer_name", "")

    path = os.path.join(downtime_dir, APPROVAL_HISTORY_FILE)

    # Read existing rows from other designers
    existing_rows = []
    if os.path.exists(path):
        wb_old = _read_workbook(path)
        if wb_old is not None:
            try:
                ws_old = wb_old.active
                for r in ws_old.iter_rows(min_row=2, values_only=True):
                    if r and r[0] is not None:
                        row_designer = str(r[0] or "").strip().lower()
                        if row_designer != designer.strip().lower():
                            existing_rows.append(r)
                wb_old.close()
            except Exception as exc:
                log_event("downtime_approval", f"failed reading existing approval history rows: {exc}", level="WARN")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Approval History"
    ws.sheet_view.showGridLines = False

    headers = [
        "Designer", "ID", "Date", "Start", "End", "Duration (min)",
        "Reason", "Detail", "Status", "Responded By", "Responded At",
    ]
    hdr_fill = PatternFill("solid", fgColor="1565C0")
    _write_header(ws, headers, hdr_fill)

    _locked = Protection(locked=True)
    row_idx = 2

    # Write other designers' rows
    for r in existing_rows:
        for c, val in enumerate(r, 1):
            cell = ws.cell(row_idx, c, val)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = _thin()
            cell.protection = _locked
        row_idx += 1

    # Write this designer's rows
    status_fills = {
        STATUS_APPROVED: PatternFill("solid", fgColor="E8F5E9"),
        STATUS_REJECTED: PatternFill("solid", fgColor="FFEBEE"),
    }
    for db_row in rows:
        dt_id, fecha, h_ini, h_fin, dur, razon, status, detalle, resp_by, resp_at = db_row
        vals = [designer, dt_id, fecha, h_ini, h_fin, dur, razon,
                detalle or "", status, resp_by or "", resp_at or ""]
        fill = status_fills.get(status, PatternFill("solid", fgColor="F8F8F8"))
        for c, val in enumerate(vals, 1):
            cell = ws.cell(row_idx, c, val)
            cell.alignment = Alignment(
                horizontal="left" if c in (1, 7, 8) else "center",
                vertical="center",
            )
            cell.fill = fill
            cell.border = _thin()
            cell.protection = _locked
        row_idx += 1

    # Column widths
    widths = {"A": 22, "B": 8, "C": 14, "D": 10, "E": 10, "F": 14,
              "G": 30, "H": 30, "I": 12, "J": 22, "K": 20}
    for col_letter, width in widths.items():
        ws.column_dimensions[col_letter].width = width
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:K{row_idx - 1}"

    ws.protection.sheet = True
    ws.protection.password = _SHEET_PASSWORD
    ws.protection.autoFilter = False
    ws.protection.sort = False
    ws.protection.enable()

    return _save_workbook(wb, path)


# ── Cleanup old response files ──────────────────────────────────────────────

def _cleanup_old_responses(max_age_days: int = 30, json_max_age_days: int = 60):
    """Delete stale response files from the shared folder.

    Two tiers:
      * `.json.done` files older than max_age_days (default 30).
      * `response_*.json` files older than json_max_age_days (default 60) —
        by then every designer has long since polled and absorbed them into
        the local DB, so they serve no purpose and the folder would grow
        unbounded otherwise (Power Automate keeps appending new ones).
    """
    downtime_dir = _get_downtime_dir()
    if not downtime_dir:
        return

    responses_dir = os.path.join(downtime_dir, "responses")
    if not os.path.isdir(responses_dir):
        return

    now = time.time()
    cutoff_done = now - (max_age_days * 86400)
    cutoff_json = now - (json_max_age_days * 86400)

    removed_done = 0
    removed_json = 0
    for fname in os.listdir(responses_dir):
        fpath = os.path.join(responses_dir, fname)
        try:
            mtime = os.path.getmtime(fpath)
        except OSError:
            continue
        try:
            if fname.endswith(".json.done") and mtime < cutoff_done:
                os.remove(fpath)
                removed_done += 1
            elif fname.startswith("response_") and fname.endswith(".json") and mtime < cutoff_json:
                os.remove(fpath)
                removed_json += 1
                # Drop from local processed set too so it doesn't bloat
                if fname in _processed_response_files:
                    _processed_response_files.discard(fname)
        except OSError as exc:
            log_event("downtime_approval", f"cleanup old response file failed for {fname}: {exc}", level="WARN")

    if removed_done or removed_json:
        log_event("downtime_approval",
                  f"cleanup: removed {removed_done} .json.done, {removed_json} response_*.json",
                  level="INFO")
        if removed_json:
            # Persist the trimmed processed set
            try:
                _save_processed_responses(_processed_response_files)
            except Exception as exc:
                log_event("downtime_approval", f"persist trimmed processed set failed: {exc}", level="WARN")
