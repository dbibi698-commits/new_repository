"""plugins/utility_system.py — 🖥️ SYSTEM tools: System Info, Process
Manager, Startup Manager, Network Speed Test, WiFi Networks, Bluetooth
Devices, VPN Status, Battery Monitor, Screen Recorder. Thin voice
wrapper over core/utility_tools.py. Never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "utility_system",
    "description": (
        "System tools — system info (OS/CPU/RAM/disk/battery), process "
        "manager (top processes, kill by PID with confirm), startup "
        "manager, network speed test, WiFi networks, Bluetooth devices, "
        "VPN status, battery monitor (PC + phone), screen recorder "
        "(ffmpeg). Call when the user says: system info, process dekhao, "
        "startup dekhao, speed test, wifi dekhao, bluetooth dekhao, vpn, "
        "battery, screen record koro."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "info | processes | startup | speed | wifi | bluetooth | vpn | battery | record_start | record_stop | record_status"},
            "pid": {"type": "NUMBER",
                    "description": "Process id to kill (with confirmed=true)."},
            "confirmed": {"type": "BOOLEAN",
                          "description": "True to really kill the process."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        p = parameters or {}
        action = str(p.get("action") or "").strip().lower()
        from core import utility_tools as u
        if action == "info":
            return u.system_info()
        if action == "processes":
            return u.process_list()
        if action == "startup":
            return u.startup_list()
        if action == "speed":
            return u.network_speed_test()
        if action == "wifi":
            return u.wifi_networks()
        if action == "bluetooth":
            return u.bluetooth_devices()
        if action == "vpn":
            return u.vpn_status()
        if action == "battery":
            return u.battery_monitor()
        if action == "record_start":
            return u.screen_record("start")
        if action == "record_stop":
            return u.screen_record("stop")
        if action == "record_status":
            return u.screen_record("status")
        if action == "kill":
            return u.process_kill(int(p.get("pid") or 0),
                                  bool(p.get("confirmed")))
        return u.system_info()
    except Exception as e:
        return f"System tool chalate parlam na: {e}"
