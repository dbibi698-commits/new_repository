"""plugins/utility_vault.py — 🔐 PASSWORD VAULT: credentials stored
AES-256-GCM encrypted (core/utility_tools.py vault_put/vault_get). The
key is derived from this PC — the vault cannot be opened on another
machine, and nothing is ever stored in plain text. Never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "utility_vault",
    "description": (
        "Password vault — save a service login (encrypted with AES-256-GCM, "
        "per-PC key) and get it back later. Call when the user says: vault-e "
        "rakho, password save koro, <service>-er password dao."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "put | get"},
            "service": {"type": "STRING", "description": "Service name, e.g. gmail."},
            "username": {"type": "STRING", "description": "Username (for put)."},
            "password": {"type": "STRING", "description": "Password (for put)."},
        },
        "required": ["action", "service"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        p = parameters or {}
        action = str(p.get("action") or "").strip().lower()
        from core import utility_tools as u
        if action == "put":
            return u.vault_put(str(p.get("service") or ""),
                               str(p.get("username") or ""),
                               str(p.get("password") or ""))
        if action == "get":
            return u.vault_get(str(p.get("service") or ""))
        return ("Vault-e ki korbo — put (save) ba get (dao) bolo.")
    except Exception as e:
        return f"Vault chalate parlam na: {e}"
