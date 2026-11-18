"""plugins/utility_phone.py — 📱 PHONE tools (via relay): SMS Sender,
Call Log, Step Counter. Thin voice wrapper over core/utility_tools.py.
The phone must be paired; when it is not, the reply says so plainly.
Never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "utility_phone",
    "description": (
        "Phone tools via the relay — SMS sender (phone sends the SMS), "
        "call log (phone's recent calls), step counter (today's steps "
        "from the phone). Call when the user says: SMS pathao, call log "
        "dao, koto step hetechhi. Needs the phone paired."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "sms | call_log | steps"},
            "phone": {"type": "STRING", "description": "Phone number for SMS."},
            "message": {"type": "STRING", "description": "SMS text."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        p = parameters or {}
        action = str(p.get("action") or "").strip().lower()
        from core import utility_tools as u
        if action == "sms":
            return u.sms_send(str(p.get("phone") or ""),
                              str(p.get("message") or ""))
        if action == "call_log":
            return u.call_log()
        if action == "steps":
            return u.step_counter()
        return ("Ki korbo — sms, call_log, steps-er ekta bolo.")
    except Exception as e:
        return f"Phone tool chalate parlam na: {e}"
