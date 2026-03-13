"""
Professional Excel report generation for Akamai traffic data.
Uses openpyxl only — no FastMCP dependency.
"""
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    GradientFill,
    PatternFill,
    Side,
)
from openpyxl.utils import get_column_letter

# Brand colours
HEADER_BG = "1F3864"      # dark navy
HEADER_FG = "FFFFFF"      # white
ALT_ROW_BG = "D9E1F2"    # light blue
ACCENT_BG = "4472C4"      # medium blue (cover sheet title)
COVER_BG = "1F3864"       # cover background strip
SUMMARY_BG = "BDD7EE"     # light blue for summary row

THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)

MEDIUM_BOTTOM = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="medium"),
)


def _header_fill() -> PatternFill:
    return PatternFill(start_color=HEADER_BG, end_color=HEADER_BG, fill_type="solid")


def _alt_fill() -> PatternFill:
    return PatternFill(start_color=ALT_ROW_BG, end_color=ALT_ROW_BG, fill_type="solid")


def _summary_fill() -> PatternFill:
    return PatternFill(start_color=SUMMARY_BG, end_color=SUMMARY_BG, fill_type="solid")


def _bytes_to_human(value: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(value) < 1024.0:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} EB"


def _is_bytes_col(col_name: str) -> bool:
    lower = col_name.lower()
    return "bytes" in lower and "percentage" not in lower


def _is_pct_col(col_name: str) -> bool:
    return "percentage" in col_name.lower()


def _auto_col_width(ws, min_width: int = 12, max_width: int = 50) -> None:
    for col_cells in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col_cells[0].column)
        for cell in col_cells:
            if cell.value is not None:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = max(min_width, min(max_len + 2, max_width))


def _write_cover_sheet(wb: Workbook, account_name: str, start: str, end: str) -> None:
    ws = wb.active
    ws.title = "Summary"
    ws.sheet_view.showGridLines = False

    # ── Title block ─────────────────────────────────────────
    ws.merge_cells("B2:G2")
    title_cell = ws["B2"]
    title_cell.value = "Akamai Traffic Report"
    title_cell.font = Font(name="Calibri", bold=True, size=22, color=HEADER_FG)
    title_cell.fill = PatternFill(start_color=COVER_BG, end_color=COVER_BG, fill_type="solid")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 40

    # ── Meta rows ────────────────────────────────────────────
    meta = [
        ("Account", account_name),
        ("Report Period", f"{start}  →  {end}"),
        ("Generated", datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
    ]
    for i, (label, value) in enumerate(meta, start=4):
        label_cell = ws.cell(row=i, column=2, value=label)
        label_cell.font = Font(name="Calibri", bold=True, size=12, color=HEADER_BG)

        value_cell = ws.cell(row=i, column=3, value=value)
        value_cell.font = Font(name="Calibri", size=12)
        ws.row_dimensions[i].height = 20

    # ── Sheet index ──────────────────────────────────────────
    ws.cell(row=8, column=2, value="Sheets in this report:").font = Font(
        name="Calibri", bold=True, size=11, color=HEADER_BG
    )
    sheets = ["By Hostname", "By CP Code", "HTTP Status", "Offload"]
    for j, name in enumerate(sheets, start=9):
        ws.cell(row=j, column=3, value=f"• {name}").font = Font(name="Calibri", size=11)

    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 40


def _write_data_sheet(
    wb: Workbook,
    sheet_name: str,
    rows: list[dict],
    account_name: str,
    start: str,
    end: str,
) -> None:
    ws = wb.create_sheet(title=sheet_name)
    ws.sheet_view.showGridLines = False

    if not rows:
        ws["A1"] = "No data returned for this report."
        return

    columns = list(rows[0].keys())

    # ── Metadata rows (1-2) ──────────────────────────────────
    ws.merge_cells(f"A1:{get_column_letter(len(columns))}1")
    meta_cell = ws["A1"]
    meta_cell.value = (
        f"Account: {account_name}  |  Period: {start} → {end}  |  "
        f"Report: {sheet_name}  |  Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )
    meta_cell.font = Font(name="Calibri", italic=True, size=10, color="595959")
    meta_cell.alignment = Alignment(horizontal="left")
    ws.row_dimensions[1].height = 18

    # ── Header row (3) ───────────────────────────────────────
    HEADER_ROW = 3
    for col_idx, col_name in enumerate(columns, start=1):
        cell = ws.cell(row=HEADER_ROW, column=col_idx, value=col_name)
        cell.font = Font(name="Calibri", bold=True, size=11, color=HEADER_FG)
        cell.fill = _header_fill()
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = MEDIUM_BOTTOM
    ws.row_dimensions[HEADER_ROW].height = 22
    ws.freeze_panes = ws.cell(row=HEADER_ROW + 1, column=1)

    # ── Data rows ────────────────────────────────────────────
    numeric_totals: dict[str, float] = {c: 0.0 for c in columns if c != columns[0]}

    for row_idx, row_data in enumerate(rows, start=HEADER_ROW + 1):
        fill = _alt_fill() if row_idx % 2 == 0 else None
        for col_idx, col_name in enumerate(columns, start=1):
            raw = row_data.get(col_name)
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = THIN_BORDER
            cell.alignment = Alignment(horizontal="right" if isinstance(raw, (int, float)) else "left")
            if fill:
                cell.fill = fill

            if isinstance(raw, (int, float)):
                if _is_bytes_col(col_name):
                    cell.value = _bytes_to_human(float(raw))
                    cell.alignment = Alignment(horizontal="right")
                    numeric_totals[col_name] = numeric_totals.get(col_name, 0.0) + float(raw)
                elif _is_pct_col(col_name):
                    cell.value = round(float(raw), 4)
                    cell.number_format = "0.00%"
                    cell.alignment = Alignment(horizontal="right")
                else:
                    cell.value = raw
                    cell.number_format = "#,##0"
                    numeric_totals[col_name] = numeric_totals.get(col_name, 0.0) + float(raw)
            else:
                cell.value = raw
            cell.font = Font(name="Calibri", size=10)

    # ── Summary / totals row ─────────────────────────────────
    summary_row = HEADER_ROW + len(rows) + 1
    ws.row_dimensions[summary_row].height = 18
    for col_idx, col_name in enumerate(columns, start=1):
        cell = ws.cell(row=summary_row, column=col_idx)
        cell.fill = _summary_fill()
        cell.border = THIN_BORDER
        cell.font = Font(name="Calibri", bold=True, size=10)
        if col_idx == 1:
            cell.value = "TOTAL / AVG"
            cell.alignment = Alignment(horizontal="left")
        elif col_name in numeric_totals:
            if _is_bytes_col(col_name):
                cell.value = _bytes_to_human(numeric_totals[col_name])
                cell.alignment = Alignment(horizontal="right")
            elif _is_pct_col(col_name):
                avg = numeric_totals[col_name] / len(rows) if rows else 0
                cell.value = round(avg, 4)
                cell.number_format = "0.00%"
                cell.alignment = Alignment(horizontal="right")
            else:
                cell.value = numeric_totals[col_name]
                cell.number_format = "#,##0"
                cell.alignment = Alignment(horizontal="right")

    _auto_col_width(ws)


def write_traffic_report(
    results: dict[str, list[dict]],
    output_path: str,
    account_name: str,
    start: str,
    end: str,
) -> str:
    """
    Write a professional multi-sheet .xlsx report.

    Args:
        results: Mapping of sheet name to list of row dicts, e.g.
                 {"By Hostname": [...], "By CP Code": [...], ...}
        output_path: Destination file path (will be created/overwritten).
        account_name: Human-readable account label shown in the report.
        start: ISO-8601 start of the report period.
        end:   ISO-8601 end of the report period.

    Returns:
        Absolute path of the written file.
    """
    wb = Workbook()

    _write_cover_sheet(wb, account_name, start, end)

    for sheet_name, rows in results.items():
        _write_data_sheet(wb, sheet_name, rows, account_name, start, end)

    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return str(path)
