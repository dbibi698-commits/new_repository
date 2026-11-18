"""core/commander.py — 🎖️ COMMANDER: Mark nijei Commander.

The user tells the Commander (Mark, the main agent), the Commander
PLANS the order, DELEGATES each step to a worker agent, TRACKS what each
worker is doing right now, and REPORTS the final result back to the user.
The existing tool functions are the workers' hands — the Commander never
does a worker's job itself, it commands.

WORKERS (the 7 in core/agents.py, via REGISTRY):
    builder  — software_build, python_run, apk_build, render_deploy,
               firebase_connect, hosting_autofix
    browser  — browser_control
    desktop / media / social / research / phone — routed orders (agents.route)
               that carry no Commander intent; the step is logged honestly
               and the worker's own tool runs when one matches, otherwise
               the Commander says plainly that no tool matched.

SMARTER (advanced round):
  * AUTO-PLAN — decompose_order() splits a multi-clause order into one
    step per clause, each with its own intent + worker ("dashboard banao
    and browser-e kholo" -> builder + browser).
  * AUTO-DELEGATE — pick_worker() orders the candidate workers by
    capability match (intent worker first, then the router's scores).
  * RETRY — a step that fails is tried ONCE more with a different worker
    (a general step's retry asks Gemini directly); the panel marks it 🔁.
  * PLAN MEMORY — the last 20 successful orders are remembered in config;
    a repeated order reuses the plan that already worked (panel: 📋 reuse).

COMMAND LOG
    Every order, delegation and result is appended to plugin_config
    ["commander"]["log"] (capped at 50 entries) and the current order is
    kept in plugin_config["commander"]["current"]. The master screen's
    Commander live panel reads status_text() on its 1 s tick — a scrolling
    command log + per-agent status rows — so the user SEES the Commander
    commanding.

PHONE (Commander-to-Commander)
    The phone's Commander sends COMMANDER::{json or text} (or the
    dedicated kinds python_run / software_build / apk_build /
    render_deploy) through the relay; Mark treats each as a Commander
    order, delegates to his workers, and returns the result via the relay.

No Qt, no network except through the workers' own helpers. Every public
function returns a plain value and never raises.
"""
from __future__ import annotations

import json
import re
import time

_NAMESPACE = "commander"
_MAX_LOG = 50

# intent -> (registry agent id, worker label)
INTENT_WORKERS = {
    "python_run": ("builder", "Python Run"),
    "software_build": ("builder", "Software Builder"),
    "apk_build": ("builder", "APK Build"),
    "render_deploy": ("builder", "Render Deploy"),
    "firebase_connect": ("builder", "Firebase Connect"),
    "hosting_autofix": ("builder", "Hosting Auto-Fix"),
    "browser_control": ("browser", "Browser Control"),
    "photo_edit": ("media", "Photo Editor"),
}

_INTENT_KEYWORDS = [
    ("python_run", ["python run", "python code", "python chalao", "code chalao",
                    "snippet chalao", "run python", "python "]),
    ("software_build", ["software banao", "app banao", "dashboard banao",
                        "website banao", "web app banao", "tool banao",
                        "software", "dashboard", "website", "web app"]),
    ("apk_build", ["apk build", "apk banao", "apk baniye"]),
    ("render_deploy", ["render deploy", "deploy koro", "deploy", "render-e"]),
    ("firebase_connect", ["firebase"]),
    ("hosting_autofix", ["hosting fix", "hosting thik", "deploy fail",
                         "hosting auto-fix", "autofix"]),
    ("browser_control", ["browser kholo", "chrome kholo", "website kholo",
                         "browser-e", "chrome-e"]),
    ("photo_edit", ["photo edit", "chobi edit", "6 copy", "a4 kore",
                    "photo-ta", "chobi-ta"]),
]


# ── intent detection ─────────────────────────────────────────────────────────

# Same clause splitter as core/agents.py: "X and Y" / "X, Y" / "X then Y"
# become separate sub-tasks so each clause can go to its own worker.
_CLAUSE_SPLIT_RE = re.compile(r"\s+(?:and|then|tarpor|ar)\s+|,\s*|\s*;\s*",
                              re.IGNORECASE)

# Plan memory: last 20 orders (persisted in config) so a repeated order
# reuses the plan that already worked.
_MAX_HISTORY = 20


def _split_clauses(order: str) -> list[str]:
    """Order -> clauses. Pure. Never raises."""
    try:
        text = str(order or "").strip()
        if not text:
            return []
        parts = [c.strip() for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]
        return parts or [text]
    except Exception:
        return [str(order or "")]


def _norm_order(order: str) -> str:
    """Normalized order for plan-memory matching (lowercase, alnum only)."""
    try:
        return re.sub(r"[^a-z0-9]+", " ", (order or "").lower()).strip()
    except Exception:
        return ""


def _history() -> list[dict]:
    try:
        raw = _read_ns().get("history")
        return [dict(e) for e in raw if isinstance(e, dict)] \
            if isinstance(raw, list) else []
    except Exception:
        return []


def _save_history_entry(order: str, intent: str, plan: list[dict],
                        ok: bool) -> None:
    """Append one order's plan to the history (capped at 20). Never raises."""
    try:
        hist = _history()
        entry = {"order": str(order or "")[:200],
                 "norm": _norm_order(order),
                 "intent": str(intent or ""),
                 "steps": [{"agent_id": s.get("agent_id"),
                            "intent": s.get("intent"),
                            "subtask": s.get("subtask")}
                           for s in plan],
                 "ok": bool(ok), "at": time.strftime("%Y-%m-%d %H:%M")}
        hist = [e for e in hist if e.get("norm") != entry["norm"]]
        hist.append(entry)
        _write_ns({"history": hist[-_MAX_HISTORY:]})
    except Exception:
        pass


def find_similar_plan(order: str) -> list[dict]:
    """A stored plan for the same (or nearly the same) order, with fresh
    'pending' statuses — or [] when nothing matches. Matching: exact
    normalized order, or same intent + same first 3 words. Never raises."""
    try:
        order = (order or "").strip()
        if not order:
            return []
        norm = _norm_order(order)
        intent = detect_intent(order)
        words = norm.split()
        for entry in reversed(_history()):
            if not entry.get("ok"):
                continue
            matched = entry.get("norm") == norm or (
                (entry.get("intent") or "") == intent and words[:3] and
                (entry.get("norm") or "").split()[:3] == words[:3])
            if not matched:
                continue
            # Fresh copies with runtime fields reset — a reused plan must
            # start from "pending" with no tried workers, so the first
            # attempt goes to the original worker again.
            fresh = []
            for s in entry.get("steps") or []:
                step = dict(s)
                step["status"] = "pending"
                step["tried"] = []
                step["retried"] = False
                step["result"] = None
                fresh.append(step)
            return fresh
        return []
    except Exception:
        return []


def pick_worker(intent: str, subtask: str,
                exclude: tuple[str, ...] = ()) -> list[str]:
    """Ordered candidate worker agents for one step: the intent's own
    worker first, then the agents the 7-agent router scores for the
    subtask, then the Commander itself. `exclude` drops agents already
    tried (the retry path). Never raises."""
    try:
        out: list[str] = []
        if intent in INTENT_WORKERS:
            out.append(INTENT_WORKERS[intent][0])
        try:
            from core import agents as _ag
            for r in _ag.route(subtask or ""):
                out.append(str(r["agent_id"]))
        except Exception:
            pass
        out.append("commander")
        seen: list[str] = []
        for aid in out:
            if aid and aid not in seen and aid not in (exclude or ()):
                seen.append(aid)
        return seen
    except Exception:
        return ["commander"]


def detect_intent(order: str, payload: dict | None = None) -> str:
    """'python_run' | 'software_build' | ... | 'general'. Never raises."""
    try:
        if isinstance(payload, dict):
            intent = str(payload.get("intent") or payload.get("kind") or "").strip()
            if intent in INTENT_WORKERS:
                return intent
            if str(payload.get("code") or "").strip():
                return "python_run"
            if str(payload.get("spec") or "").strip():
                return "software_build"
        text = " " + (order or "").lower() + " "
        for intent, keywords in _INTENT_KEYWORDS:
            for kw in keywords:
                if kw.lower() in text:
                    return intent
        return "general"
    except Exception:
        return "general"


def decompose_order(order: str, intent: str = "",
                    payload: dict | None = None) -> list[dict]:
    """AUTO-PLAN: break an order into steps, one per clause, each with its
    own intent + worker (auto-delegate). Consecutive clauses with the same
    intent fold into one step, like the 7-agent router does. Single-clause
    orders give exactly the old one-step plan. Pure planning — runs
    nothing. Never raises."""
    try:
        order = (order or "").strip()
        if not order:
            return []
        clauses = _split_clauses(order)
        steps: list[dict] = []
        for clause in clauses:
            ci = (intent or "").strip() or detect_intent(clause, payload)
            if ci != "general" and ci in INTENT_WORKERS:
                agent_id, _label = INTENT_WORKERS[ci]
                if steps and steps[-1]["intent"] == ci:
                    steps[-1]["subtask"] += " + " + clause
                    continue
                steps.append({"agent_id": agent_id, "intent": ci,
                              "subtask": clause, "status": "pending"})
                continue
            # No Commander intent for this clause — let the 7-agent router
            # split it; unrouted clauses go to the Commander directly.
            try:
                from core import agents as _ag
                routed = _ag.route(clause)
            except Exception:
                routed = []
            if routed:
                for r in routed:
                    aid = str(r["agent_id"])
                    if steps and steps[-1]["agent_id"] == aid \
                            and steps[-1]["intent"] == "general":
                        steps[-1]["subtask"] += " + " + str(r["subtask"])
                        continue
                    steps.append({"agent_id": aid, "intent": "general",
                                  "subtask": str(r["subtask"]),
                                  "status": "pending"})
            else:
                steps.append({"agent_id": "commander", "intent": "general",
                              "subtask": clause, "status": "pending"})
        return steps or [{"agent_id": "commander", "intent": "general",
                          "subtask": order, "status": "pending"}]
    except Exception:
        return [{"agent_id": "commander", "intent": "general",
                 "subtask": str(order or ""), "status": "pending"}]


def plan_order(order: str, intent: str = "",
               payload: dict | None = None) -> list[dict]:
    """Order -> plan steps [{agent_id, intent, subtask, status}].
    Pure planning — runs nothing. Never raises."""
    return decompose_order(order, intent=intent, payload=payload)


# ── command log (persisted in config) ────────────────────────────────────────

def _read_ns() -> dict:
    try:
        from memory.config_manager import get_plugin_config
        return dict(get_plugin_config(_NAMESPACE) or {})
    except Exception:
        return {}


def _write_ns(values: dict) -> None:
    try:
        from memory.config_manager import save_plugin_config
        save_plugin_config(_NAMESPACE, values)
    except Exception:
        pass


def _log(kind: str, text: str) -> None:
    try:
        ns = _read_ns()
        log = ns.get("log")
        log = list(log) if isinstance(log, list) else []
        log.append({"t": time.strftime("%H:%M:%S"), "kind": kind,
                    "text": str(text or "")[:300]})
        _write_ns({"log": log[-_MAX_LOG:]})
    except Exception:
        pass


def command_log(limit: int = 20) -> list[dict]:
    """Most recent log entries, oldest first. Never raises."""
    try:
        log = _read_ns().get("log") or []
        if not isinstance(log, list):
            return []
        return [dict(e) for e in log[-max(1, int(limit or 20)):]]
    except Exception:
        return []


def current_order() -> dict:
    """The order the Commander is working on right now (or {})."""
    try:
        cur = _read_ns().get("current")
        return dict(cur) if isinstance(cur, dict) else {}
    except Exception:
        return {}


# ── worker dispatch (the workers' hands) ─────────────────────────────────────

def _extract_code(text: str) -> str:
    """Pull Python code out of an order like 'python run: print(1)'."""
    try:
        t = str(text or "").strip()
        t = re.sub(r"^```(?:python)?\s*|```$", "", t, flags=re.I).strip()
        for prefix in ("python run:", "run python:", "python chalao:",
                       "code chalao:", "python:", "run:"):
            if t.lower().startswith(prefix):
                t = t[len(prefix):].strip()
                break
        return t
    except Exception:
        return str(text or "")


def _run_step(step: dict, payload: dict | None = None,
              ask_fn=None, retry: bool = False) -> str:
    """Execute ONE plan step through the worker that owns it. The step's
    intent picks the real function; unknown/general steps are reported
    honestly instead of faked. On a RETRY of a general step the Commander
    answers directly through Gemini (a different worker — the model
    itself) instead of repeating the same 'no tool matched' line.
    Never raises."""
    try:
        intent = str(step.get("intent") or "")
        subtask = str(step.get("subtask") or "")
        payload = payload if isinstance(payload, dict) else {}
        if intent == "python_run":
            code = str(payload.get("code") or "") or _extract_code(subtask)
            if not code:
                return "Python code pelam na — code-ta dao."
            from core import python_run as _pr
            if code.strip().startswith("PYTHON_RUN::"):
                return _pr.handle_phone_request(code)
            return _pr.run_snippet_text(code)
        if intent == "software_build":
            spec = str(payload.get("spec") or "") or subtask
            from core import software_builder as _sb
            return _sb.build_and_run_text(
                spec, kind=str(payload.get("kind") or ""),
                deploy=bool(payload.get("deploy")),
                repo=str(payload.get("repo") or ""),
                ask_fn=ask_fn, open_browser=True)
        if intent == "apk_build":
            repo = str(payload.get("repo") or "")
            workflow = str(payload.get("workflow") or "build-apk.yml")
            if not repo:
                m = re.search(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", subtask)
                repo = m.group(1) if m else ""
            if not repo:
                return ("APK build-er jonno repo dao (owner/name) — "
                        "workflow file-er naam-o dao jodi alada hoy.")
            from core import apk_selfheal as _sh
            return _sh.build_apk_selfheal(repo, workflow)
        if intent == "render_deploy":
            from core import render_deploy as _rd
            service_id = str(payload.get("service_id") or "")
            if service_id:
                return _rd.trigger_deploy(service_id)
            return _rd.deploy_status()
        if intent == "firebase_connect":
            from core import firebase_connect as _fb
            from pathlib import Path as _Path
            folder = str(payload.get("folder") or "") or str(
                _Path.home() / "Documents" / "firebase-config")
            _ok, msg = _fb.connect_flow(folder)
            return msg
        if intent == "hosting_autofix":
            from core import hosting_autofix as _hf
            return _hf.autofix(str(payload.get("service_id") or ""))
        if intent == "browser_control":
            url = str(payload.get("url") or "")
            if not url:
                m = re.search(r"https?://\S+", subtask)
                url = m.group(0) if m else ""
            if not url:
                return "Browser-e ki khulbo — URL dao."
            from core import browser_control as _bc
            ok, msg = _bc.drive_url(url)
            return msg if ok else f"Browser-e khulte parlam na: {msg}"
        if intent == "photo_edit":
            from core import photo_editor as _pe
            return _pe.handle_phone_request(subtask, payload=payload)
        # General / Commander-direct step: no worker tool matched.
        if retry:
            # Second worker: the model answers directly.
            try:
                from core import gemini as _gm
                ans = _gm.text(
                    f"Answer briefly in the user's language (Bengali/English "
                    f"as they wrote): {subtask[:400]}", tier=_gm.FAST)
                if ans:
                    return str(ans)[:1000]
            except Exception:
                pass
        agent = str(step.get("agent_id") or "commander")
        return (f"🎖️ Commander order dilo ({agent}): {subtask[:120]} — "
                f"ei order-er jonno kono worker tool mil lo na, "
                f"Commander nije dekhbe.")
    except Exception as e:
        return f"Step-ta chalate parlam na: {e}"


# ── issue an order ───────────────────────────────────────────────────────────

def _execute_step(step: dict, payload: dict | None = None,
                  execute_fn=None, ask_fn=None, registry=None) -> str:
    """Run ONE step, with ONE retry on a different worker when the first
    worker fails. Returns the final output string; the step dict gains
    "tried" (agent ids tried) and "retried" (bool). Never raises."""
    tried: list[str] = []
    out = ""
    try:
        intent = str(step.get("intent") or "")
        subtask = str(step.get("subtask") or "")
        candidates = pick_worker(intent, subtask)
        primary = candidates[0] if candidates else "commander"
        step["agent_id"] = primary
        for attempt, agent_id in enumerate(candidates[:2]):
            tried.append(agent_id)
            step["agent_id"] = agent_id
            step["status"] = "working"
            _log("delegate",
                 f"➡️ {agent_id} ke dilam: {subtask[:150]}"
                 + (" (🔁 retry — ager worker fail koreche)"
                    if attempt else ""))
            if registry is not None and agent_id != "commander":
                try:
                    registry.start(agent_id, subtask)
                except Exception:
                    pass
            try:
                if callable(execute_fn):
                    out = execute_fn(step, payload)
                else:
                    out = _run_step(step, payload=payload, ask_fn=ask_fn,
                                    retry=attempt > 0)
            except Exception as e:
                out = f"Step-ta chalate parlam na: {e}"
            out = str(out or "")
            failed = (not out) or out.startswith(("⚠️", "Step-ta"))
            _log("result", f"{agent_id}: {out[:200]}")
            if registry is not None and agent_id != "commander":
                try:
                    if not failed:
                        registry.done(agent_id, out)
                    else:
                        registry.fail(agent_id, out)
                except Exception:
                    pass
            if not failed:
                break
            if attempt == 0 and len(candidates) > 1:
                _log("retry", f"🔁 {agent_id} fail — "
                     f"{candidates[1]} ke try korchi.")
                continue
            break
        step["tried"] = tried
        step["retried"] = len(tried) > 1
        step["status"] = "done" if out and not out.startswith(
            ("⚠️", "Step-ta")) else "error"
        return out
    except Exception as e:
        step["tried"] = tried
        step["retried"] = len(tried) > 1
        step["status"] = "error"
        return f"Step-ta chalate parlam na: {e}"


def issue_order(order: str, intent: str = "", payload: dict | None = None,
                execute_fn=None, ask_fn=None) -> dict:
    """The Commander takes an order: plan → delegate → track → report.

    Smarter than before: a repeated order REUSES the plan that already
    worked (plan memory), and a step that fails is RETRIED once with a
    different worker before the Commander reports failure.

    Returns {"ok", "order_id", "plan", "results", "result_text"}.
    execute_fn(step, payload) overrides the real worker dispatch (tests
    inject fakes). Never raises."""
    try:
        order = (order or "").strip()
        if not order:
            return {"ok": False, "order_id": "", "plan": [], "results": [],
                    "result_text": "Order dao — ki korte hobe bolo."}
        order_id = f"cmd-{int(time.time())}"
        reused = find_similar_plan(order)
        if reused:
            plan = reused
            _log("order", f"🎖️ Commander order pelo: {order[:200]}")
            _log("plan", "📋 Ager plan reuse korlam — eki order ageo hoyeche.")
        else:
            plan = plan_order(order, intent=intent, payload=payload)
            _log("order", f"🎖️ Commander order pelo: {order[:200]}")
        _write_ns({"current": {"id": order_id, "order": order,
                               "plan": plan, "status": "working",
                               "reused": bool(reused),
                               "started_at": time.strftime("%H:%M:%S")}})
        try:
            from core import agents as _ag
            registry = _ag.REGISTRY
        except Exception:
            registry = None
        results: list[str] = []
        for step in plan:
            out = _execute_step(step, payload=payload, execute_fn=execute_fn,
                                ask_fn=ask_fn, registry=registry)
            results.append(out)
        ok = any(s.get("status") == "done" for s in plan)
        result_text = "\n".join(
            f"[{s.get('agent_id')}] {r}" for s, r in zip(plan, results)) \
            or "Kichu holo na."
        _log("done", f"✅ Order shesh: {order[:120]}")
        _write_ns({"current": {"id": order_id, "order": order,
                               "plan": plan, "status": "done" if ok else "error",
                               "reused": bool(reused),
                               "result": result_text[:1000],
                               "started_at": time.strftime("%H:%M:%S")}})
        _save_history_entry(order,
                            intent or detect_intent(order, payload),
                            plan, ok)
        return {"ok": ok, "order_id": order_id, "plan": plan,
                "results": results, "result_text": result_text}
    except Exception as e:
        return {"ok": False, "order_id": "", "plan": [], "results": [],
                "result_text": f"Commander order nite parlam na: {e}"}


# ── live panel data ──────────────────────────────────────────────────────────

def status_text() -> str:
    """The Commander live panel, as plain text: current order → plan →
    which worker is doing what → each agent's status → final result +
    recent log. Read by the master screen on its 1 s tick. Never raises."""
    try:
        lines = ["🎖️  COMMANDER — live feed"]
        cur = current_order()
        if not cur:
            lines.append("• Kono order ekhono ashe ni — bolo, ki korte hobe.")
        else:
            lines.append(f"📋 Order: {cur.get('order', '')[:150]}")
            if cur.get("reused"):
                lines.append("  📋 Ager plan reuse korlam — eki order ageo hoyeche.")
            for step in cur.get("plan") or []:
                mark = {"pending": "⏳", "working": "🔄",
                        "done": "✅", "error": "❌"}.get(
                            str(step.get("status") or ""), "•")
                retry = " (🔁 retry)" if step.get("retried") else ""
                lines.append(f"  {mark} {step.get('agent_id')}: "
                             f"{str(step.get('subtask') or '')[:100]}{retry}")
            if cur.get("result"):
                lines.append(f"🏁 Result: {str(cur['result'])[:200]}")
        try:
            from core import agents as _ag
            snap = _ag.REGISTRY.snapshot()
            rows = []
            for st in snap:
                if st.get("status") in ("working", "done", "error"):
                    rows.append(f"{st.get('icon', '')} {st.get('name')}: "
                                f"{st.get('status')}"
                                f"{' — ' + st['current_task'] if st.get('current_task') else ''}")
            if rows:
                lines.append("🤖 Workers: " + " | ".join(rows))
        except Exception:
            pass
        log = command_log(8)
        if log:
            lines.append("📜 Log:")
            for e in log:
                lines.append(f"  {e.get('t', '')} {e.get('text', '')[:140]}")
        hist = _history()
        if hist:
            lines.append(f"📋 Mone rakha plan: {len(hist)} ta order")
        return "\n".join(lines)
    except Exception as e:
        return f"Commander panel dekhte parlam na: {e}"


# ── phone relay (Commander-to-Commander) ─────────────────────────────────────

def is_commander_request(text: str) -> bool:
    return str(text or "").strip().startswith("COMMANDER::")


def handle_phone_request(text: str, ask_fn=None) -> str:
    """COMMANDER::{json: {order, intent, ...} | plain order text} — treat
    it as a Commander order, delegate to workers, return the result.
    Never raises."""
    try:
        raw = str(text or "").strip()
        if raw.startswith("COMMANDER::"):
            raw = raw[len("COMMANDER::"):]
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                payload = {"order": raw}
        except Exception:
            payload = {"order": raw}
        order = str(payload.get("order") or payload.get("text") or "").strip()
        if not order:
            return "Commander order dao — ki korte hobe bolo."
        res = issue_order(order, intent=str(payload.get("intent") or ""),
                          payload=payload, ask_fn=ask_fn)
        return res.get("result_text", "")
    except Exception as e:
        return f"Phone-er Commander order korte parlam na: {e}"
