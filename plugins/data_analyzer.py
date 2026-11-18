"""plugins/data_analyzer.py — 📊 DATA ANALYZER: CSV/Excel file-er summary.

Reads a CSV (stdlib) or .xlsx (openpyxl) file and returns a real summary:
rows, columns, per-column type + numeric stats (count/mean/min/max) or
top values for text columns. Runs on a worker thread. Returns a short
string, never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "data_analyzer",
    "description": (
        "Analyze a CSV or Excel file: rows, columns, numeric stats "
        "(count/mean/min/max) and top values for text columns. Call when "
        "the user asks: csv analyze koro, excel-er summary dao, data-ta "
        "dekho."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file": {"type": "STRING",
                     "description": "CSV ba .xlsx file-er path."},
            "csv_text": {"type": "STRING",
                         "description": "CSV text directly (file-er bodle)."},
        },
        "required": [],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Analyze a file or CSV text. Short string, never raises."""
    try:
        params = parameters or {}
        from core import data_analyzer as _da
        csv_text = str(params.get("csv_text") or "").strip()
        if csv_text:
            return _da.analyze_text(_da.analyze_csv_text(csv_text))
        path = str(params.get("file") or "").strip()
        if not path:
            return ("📊 Data Analyzer — CSV ba Excel file-er path dao, "
                    "ami summary dibo (row, column, avg/min/max).")
        return _da.analyze_text(_da.analyze_file(path))
    except Exception as e:
        return f"Data analyze korte parlam na: {e}"
