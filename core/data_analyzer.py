"""core/data_analyzer.py — 📊 DATA ANALYZER: CSV/Excel file-er summary.

Reads a CSV (stdlib csv) or .xlsx (openpyxl when installed — it is in
requirements.txt; when it is missing the reply says so plainly instead of
faking a result) and returns a real summary: rows, columns, per-column
type + numeric stats (count/mean/min/max) or top values for text columns.
No Qt, no network. Every public function returns a plain value and never
raises.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

_MAX_ROWS = 200_000
_MAX_PREVIEW_COLS = 12


def _is_number(text: str) -> bool:
    try:
        float(str(text).strip())
        return str(text).strip() != ""
    except Exception:
        return False


def analyze_rows(rows: list[dict]) -> dict:
    """Pure summary of parsed rows (list of {column: value}). Never raises."""
    try:
        rows = list(rows or [])
        if not rows:
            return {"ok": False, "rows": 0, "cols": [],
                    "error": "Kono row pelam na — file-ta khali?"}
        cols = list(rows[0].keys())
        summary: dict[str, dict] = {}
        for col in cols[:_MAX_PREVIEW_COLS]:
            vals = [str(r.get(col, "") or "") for r in rows]
            non_empty = [v for v in vals if v.strip()]
            nums = [float(v) for v in non_empty if _is_number(v)]
            if nums and len(nums) >= max(1, len(non_empty) // 2):
                summary[col] = {
                    "type": "number",
                    "count": len(nums),
                    "mean": round(sum(nums) / len(nums), 2),
                    "min": min(nums), "max": max(nums),
                }
            else:
                top: dict[str, int] = {}
                for v in non_empty:
                    top[v] = top.get(v, 0) + 1
                best = sorted(top.items(), key=lambda kv: -kv[1])[:3]
                summary[col] = {
                    "type": "text",
                    "count": len(non_empty),
                    "top": [f"{k} ({n})" for k, n in best],
                }
        return {"ok": True, "rows": len(rows), "cols": cols,
                "summary": summary, "error": ""}
    except Exception as e:
        return {"ok": False, "rows": 0, "cols": [],
                "error": f"Analyze korte parlam na: {e}"}


def analyze_csv_text(text: str) -> dict:
    """Analyze CSV text directly (tests + the plugin's inline mode)."""
    try:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "rows": 0, "cols": [],
                    "error": "CSV text dao — khali analyze korte parbo na."}
        reader = csv.DictReader(io.StringIO(text))
        rows = [dict(r) for r in reader][: _MAX_ROWS]
        return analyze_rows(rows)
    except Exception as e:
        return {"ok": False, "rows": 0, "cols": [],
                "error": f"CSV porte parlam na: {e}"}


def analyze_file(path: str) -> dict:
    """Analyze a .csv / .xlsx file. Returns the analyze_rows dict plus
    {"file": name}. Never raises."""
    try:
        p = Path(str(path or "").strip()).expanduser()
        if not p.is_file():
            return {"ok": False, "rows": 0, "cols": [],
                    "error": f"File-ta pelam na: {path or '(khali)'}"}
        suffix = p.suffix.lower()
        if suffix == ".csv":
            text = p.read_text(encoding="utf-8-sig", errors="replace")
            res = analyze_csv_text(text)
            res["file"] = p.name
            return res
        if suffix == ".xlsx":
            try:
                import openpyxl
            except Exception:
                return {"ok": False, "rows": 0, "cols": [],
                        "error": "Excel porte openpyxl lagbe — "
                                 "`pip install openpyxl` chalao, tarpor abar bolo."}
            wb = openpyxl.load_workbook(str(p), data_only=True, read_only=True)
            ws = wb.active
            rows_iter = ws.iter_rows(values_only=True)
            header = next(rows_iter, None)
            if not header:
                return {"ok": False, "rows": 0, "cols": [],
                        "error": "Excel sheet-ta khali."}
            cols = [str(h) if h is not None else f"col{i+1}"
                    for i, h in enumerate(header)]
            rows = []
            for r in rows_iter:
                if len(rows) >= _MAX_ROWS:
                    break
                rows.append({cols[i]: ("" if v is None else str(v))
                             for i, v in enumerate(r)})
            res = analyze_rows(rows)
            res["file"] = p.name
            return res
        return {"ok": False, "rows": 0, "cols": [],
                "error": f".csv ba .xlsx file dao — '{suffix or '(kono extension nei)'}' "
                         "analyze korte parbo na."}
    except Exception as e:
        return {"ok": False, "rows": 0, "cols": [],
                "error": f"File analyze korte parlam na: {e}"}


def analyze_text(res: dict) -> str:
    """A summary dict -> plain-words string for chat / cards."""
    try:
        if not res.get("ok"):
            return f"📊 Data Analyzer — {res.get('error', 'analyze holo na')}"
        lines = [f"📊 Data Analyzer — {res.get('file', 'data')}: "
                 f"{res.get('rows', 0)} row, {len(res.get('cols', []))} column"]
        for col, s in (res.get("summary") or {}).items():
            if s.get("type") == "number":
                lines.append(f"  • {col} (number): {s['count']} ta — "
                             f"avg {s['mean']}, min {s['min']}, max {s['max']}")
            else:
                top = ", ".join(s.get("top") or []) or "(kono value nei)"
                lines.append(f"  • {col} (text): {s['count']} ta — top: {top}")
        return "\n".join(lines)
    except Exception as e:
        return f"Data Analyzer-er result dekhate parlam na: {e}"
