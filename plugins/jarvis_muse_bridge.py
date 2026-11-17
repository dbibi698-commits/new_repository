"""plugins/jarvis_muse_bridge.py — 🌉 MUSE BRIDGE: ask Muse as a last resort.

Mark-LVII is powered by Muse. When a job cannot be done locally AND no
connected service can do it either (browser, Drive, GitHub, Render, phone
link — all tried first), this tool queues the job for Muse on the Render
dashboard. Muse reads it there and acts; the result comes back into Mark's
chat. The queue itself lives in core/muse_bridge.py (persisted in the
"muse_bridge" config namespace); the dashboard endpoints and HUD buttons
are a sibling worker's job.

Secret safety: the instruction, tried and context are secret-redacted
before anything is stored — no API key or token ever reaches the queue.
"""
from __future__ import annotations

PLUGIN = {
    "name": "ask_muse",
    "description": (
        "Queue a task for Muse (Mark's own brain) on the Render dashboard — "
        "LAST RESORT ONLY. Use it only when Mark's local tools AND every "
        "connected service (browser, Google Drive, GitHub, Render, phone "
        "link) have already been tried and cannot do the job. NEVER use it "
        "for something Mark can do itself with a local tool or a connected "
        "service. It queues the instruction with full context (what was "
        "already tried, relevant files/state) for Muse to act on, and the "
        "result comes back into this chat. The task appears on the dashboard "
        "for Muse to pick up."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "instruction": {
                "type": "STRING",
                "description": "What Muse should do — the full job, clearly stated.",
            },
            "tried": {
                "type": "STRING",
                "description": "What was already tried locally and via connected services, and why it failed.",
            },
            "context": {
                "type": "STRING",
                "description": "Relevant files, state or error output (short). Never include API keys or tokens.",
            },
        },
        "required": ["instruction"],
    },
}


# Settings schema for the Plugin Settings overlay (core/plugin_loader.py
# passes "widget" through to gui/overlays.py): a "🌉 MUSE LINK" section
# whose live panel is built by PluginSettingsOverlay._build_muse_link_box.
# No fields — the panel is live queue data, not stored settings — but the
# loader requires a "fields" list, so it is an empty one. The overlay also
# builds the same panel on its own when this section is absent (e.g. the
# plugin is disabled), so the panel is always visible either way.
PLUGIN_SETTINGS = {
    "namespace": "muse_bridge",
    "title": "🌉 MUSE LINK — Muse Bridge",
    "fields": [],
    "widget": "muse_link",
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Queue the task for Muse and log the fallback. Never raises."""
    try:
        params = parameters if isinstance(parameters, dict) else {}
        instruction = str(params.get("instruction") or "").strip()
        tried = str(params.get("tried") or "").strip()
        context = str(params.get("context") or "").strip()
        if not instruction:
            return "Muse-ke ki pathabo bujhlam na — instruction ta dao."
        try:
            from core.muse_bridge import create_task, log_fallback
            task_id = create_task(instruction, tried=tried, context=context)
            log_fallback(instruction, tried)
        except Exception:
            return "Muse-ke pathate parlam na — bridge ta ekhon kaaj korche na."
        if not task_id:
            return "Muse-ke pathate parlam na — task ta queue-e boshlo na."
        msg = (f"Muse-ke pathano holo, task {task_id} — dashboard-e dekhbe, "
               "result ekhane asbe.")
        if player:
            try:
                player.write_log(f"JARVIS: {msg}")
            except Exception:
                pass
        return msg
    except Exception:
        return "Muse-ke pathate parlam na — kichu ekta gondogol holo."
