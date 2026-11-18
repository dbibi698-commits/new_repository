"""plugins/utility_convert.py — 🔁 CONVERT tools: Unit Converter,
Currency Converter, Code Formatter, JSON Viewer, Regex Tester. Thin
voice wrapper over core/utility_tools.py. Never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "utility_convert",
    "description": (
        "Convert tools — unit converter (length/weight/volume/temperature), "
        "currency converter (live rate, free API), code formatter (Python / "
        "JSON), JSON viewer (validate + pretty-print), regex tester. Call "
        "when the user says: convert koro, currency, code format koro, "
        "JSON dekhao, regex test koro."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "unit | currency | code_format | json | regex"},
            "value": {"type": "NUMBER",
                      "description": "Number to convert (unit)."},
            "from_unit": {"type": "STRING",
                          "description": "From unit, e.g. km, kg, ml, C."},
            "to_unit": {"type": "STRING",
                        "description": "To unit, e.g. mile, lb, l, F."},
            "amount": {"type": "NUMBER",
                       "description": "Amount for currency."},
            "from_cur": {"type": "STRING",
                         "description": "From currency, e.g. USD."},
            "to_cur": {"type": "STRING",
                       "description": "To currency, e.g. INR."},
            "code": {"type": "STRING",
                     "description": "Code / JSON text to format or view."},
            "lang": {"type": "STRING",
                     "description": "python | json."},
            "pattern": {"type": "STRING",
                        "description": "Regex pattern."},
            "text": {"type": "STRING",
                     "description": "Text to test the regex against."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        p = parameters or {}
        action = str(p.get("action") or "").strip().lower()
        from core import utility_tools as u
        if action == "unit":
            return u.unit_convert(float(p.get("value") or 0),
                                  str(p.get("from_unit") or ""),
                                  str(p.get("to_unit") or ""))
        if action == "currency":
            return u.currency_convert(float(p.get("amount") or 0),
                                      str(p.get("from_cur") or "USD"),
                                      str(p.get("to_cur") or "INR"))
        if action == "code_format":
            return u.code_format(str(p.get("code") or ""),
                                 str(p.get("lang") or "python"))
        if action == "json":
            return u.json_view(str(p.get("code") or ""))
        if action == "regex":
            return u.regex_test(str(p.get("pattern") or ""),
                                str(p.get("text") or ""))
        return ("Ki convert korbo — unit, currency, code_format, json, "
                "regex-er ekta bolo.")
    except Exception as e:
        return f"Convert korte parlam na: {e}"
