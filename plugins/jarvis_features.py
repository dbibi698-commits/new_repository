"""plugins/jarvis_features.py — 📋 13,700,000 FEATURES: the feature registry.

The registry is formula-based (core/feature_registry.py over
data/feature_structure.py): Volume 1 (100 categories x 500 targets x
20 patterns = 1,000,000 features, numbered 1-1000000) + Volume 2
(100 categories x 1,000 targets x 20 patterns = 2,000,000 features,
numbered 1000001-3000000) + Volume 3 (100 categories x 500 targets x
20 patterns = 1,000,000 features, numbered 3000001-4000000) +
Volume 4 (100 categories x 350 targets x 20 patterns = 700,000
features, numbered 4000001-4700000) + Volume 5 (100 categories x
1,000 targets x 20 patterns = 2,000,000 features, numbered
4700001-6700000) + Volume 6 (100 categories x 3,500 targets x
20 patterns = 7,000,000 features, numbered 6700001-13700000) —
13,700,000 total, no list is stored anywhere
(a stored 13.7M-record JSON would be ~2 GB). Each feature has a status:
WORKING (built and verified in Mark-LVII), NEEDS-KEY (tool exists, needs
the user's own account/API key in Settings), NEEDS-DEVICE (needs hardware
Mark cannot conjure) or PLANNED (a real idea, not built yet).

Targets per category, Volume 1: 10 plain + 10 base x 49 contexts = 500,
so e.g. "YouTube upload" also exists as "YouTube upload for home",
"... for travel", and so on. Volume 2: 10 base x 100 NEW contexts =
1,000 (all contextual, e.g. "YouTube upload for winter"). Volume 3:
10 base x 50 NEW contexts = 500. Volume 4: 10 base x 35 NEW contexts
= 350. Volume 5: 10 base x 100 NEW contexts = 1,000. Volume 6:
10 base x 350 NEW contexts = 3,500. The first
200 numbers of each category are identical to the old 20,000-feature
registry. Resolve by number, never by name: near-duplicate names across
categories carry no suffix here (the PDFs may add " Plus" / " Ultra").

Actions:
  search — text query over category / target / pattern / context, top 10 hits
  list   — one category (by name or index), 20 per page; no category (or
           "all") lists the 100 categories with their number ranges
  get    — full record for one feature number
  run    — run one feature by number. Dispatches to the owning tool ONLY
           when the feature is WORKING or NEEDS-KEY and the tool can run
           from here (player.run_tool, else the automation engine's
           runner); a NEEDS-KEY tool reports its own missing key honestly.
           PLANNED / NEEDS-DEVICE features are never dispatched — the
           answer says what the feature would do and what is missing
           instead of faking it. Disabled features refuse outright.
  stats  — status counts and WORKING per category (categories 1-10)

The resolver loads lazily and is cached; run() returns short strings and
never raises. No Qt here — tools run on worker threads; anything shown
on screen goes through player.
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN = {
    "name": "features",
    "description": (
        "Search, list, show and run features from Mark's 13,700,000-feature "
        "registry (100 categories, numbered 1-13700000, each WORKING, "
        "NEEDS-KEY, NEEDS-DEVICE or PLANNED). Use it when the user asks "
        "about a feature by number or name, wants to browse a category, "
        "or wants to run/add a feature. Actions: 'search' (query text, "
        "top 10 with numbers), 'list' (category name or index, 20 per "
        "page; no category lists all 100 categories), 'get' (full record "
        "for a feature number), 'run' (run a feature by number — only "
        "WORKING or NEEDS-KEY features dispatch to their tool; PLANNED "
        "and NEEDS-DEVICE features honestly report what is missing), "
        "'stats' (status counts). A feature number is 1-13700000."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "search | list | get | run | stats",
            },
            "query": {
                "type": "STRING",
                "description": "Search text for the search action.",
            },
            "category": {
                "type": "STRING",
                "description": (
                    "Category name (or part of it) or index 1-100 for the "
                    "list action. Empty or 'all' lists all 100 categories."
                ),
            },
            "number": {
                "type": "STRING",
                "description": "Feature number 1-13700000 for get / run.",
            },
            "page": {
                "type": "STRING",
                "description": "Page number for list (20 features per page).",
            },
        },
        "required": ["action"],
    },
    "tier": "extra",
    "brief": "Search, list, show and run features from the 13,700,000-feature registry.",
}

_REGISTRY = None  # cached core.feature_registry module (or False if missing)
_PAGE_SIZE = 20
_TOTAL = 13_700_000


def _registry():
    """Lazily import core.feature_registry; None when it cannot load.
    Never raises."""
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY or None
    try:
        from core import feature_registry
        _REGISTRY = feature_registry
    except Exception:
        _REGISTRY = False
    return _REGISTRY or None


def _registry_missing():
    return ("Feature registry-ta ekhono build kora hoy ni — "
            "core/feature_registry.py ba data/feature_structure.py pelam na. "
            "data/gen_features_1m.py chalale 13,700,000 feature-er registry "
            "toiri hobe.")


def _parse_number(value):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= _TOTAL else None


def _parse_page(value):
    try:
        p = int(str(value).strip())
    except (TypeError, ValueError):
        return 1
    return p if p >= 1 else 1


def _one_line(rec):
    return f"#{rec['number']} {rec['name']} [{rec['status']}]"


def _full(rec):
    tool = rec.get("tool") or "—"
    req = rec.get("requires") or "—"
    enabled = "" if rec.get("enabled", True) else " | DISABLED"
    return (
        f"#{rec['number']} — {rec['name']}\n"
        f"Category: {rec['category']} ({rec['category_index']}) | "
        f"Target: {rec['target']} | Pattern: {rec['pattern']}\n"
        f"{rec['description']}\n"
        f"Status: {rec['status']}{enabled} | Tool: {tool} | Needs: {req}"
    )


def _do_search(params, reg):
    query = str(params.get("query") or "").strip()
    if not query:
        return "Search korte query dao — jemon 'YouTube upload' ba 'weather'."
    try:
        hits = reg.search(query, limit=10)
        total = reg.search_total(query)
    except Exception:
        hits, total = [], 0
    if not hits:
        return f"'{query}' diye kono feature pelam na."
    lines = [f"'{query}' — {total} ta mil, prothom {len(hits)} ta:"]
    lines += [_one_line(rec) for rec in hits]
    return "\n".join(lines)


def _find_category(reg, value):
    """Match a category by index or (sub)string of its name. Returns the
    category dict {index, name, start, end} or None."""
    value = str(value or "").strip()
    if not value or value.lower() == "all":
        return None
    cats = {c["index"]: c for c in reg.list_categories()}
    try:
        idx = int(value)
        if idx in cats:
            return cats[idx]
    except ValueError:
        pass
    low = value.lower()
    exact = [i for i, c in cats.items() if c["name"].lower() == low]
    if exact:
        return cats[exact[0]]
    part = [i for i, c in cats.items() if low in c["name"].lower()]
    if len(part) == 1:
        return cats[part[0]]
    if len(part) > 1:
        names = ", ".join(f"{i}. {cats[i]['name']}" for i in part)
        raise ValueError(f"Ekadhik category milche: {names}. Ektar naam ba number dao.")
    return None


def _do_list(params, reg):
    cat_value = str(params.get("category") or "").strip()
    if not cat_value or cat_value.lower() == "all":
        cats = reg.list_categories()
        if not cats:
            return _registry_missing()
        lines = ["100 category (proti-ta-te 30,000 feature: "
                 "10,000 Volume 1 + 20,000 Volume 2):"]
        for c in cats:
            v2 = ""
            if c.get("vol2_start") and c.get("vol2_end"):
                v2 = f" + {c['vol2_start']}-{c['vol2_end']}"
            lines.append(f"{c['index']}. {c['name']} — {c['start']}-{c['end']}{v2}")
        return "\n".join(lines)
    try:
        cat = _find_category(reg, cat_value)
    except ValueError as e:
        return str(e)
    if cat is None:
        return (f"Category '{cat_value}' pelam na. 'list' khali rekhe "
                "100 category-r list dekho.")
    page = _parse_page(params.get("page"))
    pages = (_TOTAL // 100 + _PAGE_SIZE - 1) // _PAGE_SIZE  # 30000/20 = 1500
    page = min(page, pages)
    items = reg.list_category(cat["index"], offset=(page - 1) * _PAGE_SIZE,
                              limit=_PAGE_SIZE)
    if not items:
        return f"{cat['index']}. {cat['name']} — ei page-e kono feature nei."
    lines = [f"{cat['index']}. {cat['name']} — page {page}/{pages} "
             f"(feature {items[0]['number']}-{items[-1]['number']}):"]
    lines += [_one_line(rec) for rec in items]
    return "\n".join(lines)


def _do_get(params, reg):
    n = _parse_number(params.get("number"))
    if n is None:
        return "Feature number dao — 1 theke 13700000-er modhye."
    rec = reg.resolve(n)
    if "error" in rec:
        return f"Feature #{n}: {rec['error']}"
    return _full(rec)


def _do_stats(reg):
    counts = reg.counts()
    lines = [f"Total feature: {counts.get('total', _TOTAL)}",
             f"WORKING: {counts.get('WORKING', 0)} | "
             f"NEEDS-KEY: {counts.get('NEEDS-KEY', 0)} | "
             f"NEEDS-DEVICE: {counts.get('NEEDS-DEVICE', 0)} | "
             f"PLANNED: {counts.get('PLANNED', 0)}"]
    lines.append("WORKING per category (1-10):")
    cats = {c["index"]: c["name"] for c in reg.list_categories()}
    for ci in range(1, 11):
        w = reg.category_status_counts(ci).get("WORKING", 0)
        lines.append(f"  {ci}. {cats.get(ci, '?')}: {w} WORKING")
    return "\n".join(lines)


def _tool_runner(player):
    """Best available tool runner: player.run_tool first, else the
    automation engine's full runner (covers actions+plugins). None when
    neither is wired (tests, phone dashboard). Never raises."""
    try:
        if player is not None:
            fn = getattr(player, "run_tool", None)
            if callable(fn):
                return fn
        from core.automation import ENGINE
        fn = ENGINE.get_tool_runner()
        return fn if callable(fn) else None
    except Exception:
        return None


def _do_run(params, reg, player):
    n = _parse_number(params.get("number"))
    if n is None:
        return "Feature number dao — 1 theke 13700000-er modhye."
    rec = reg.resolve(n)
    if "error" in rec:
        return f"Feature #{n}: {rec['error']}"
    name = rec["name"]
    status = rec["status"]
    desc = rec["description"]

    if not rec.get("enabled", True):
        return (f"⛔ #{n} {name} — DISABLED: ei feature-ta bondho kore "
                "rakha hoyeche, tai chalate parlam na.")

    if status == "PLANNED":
        return (f"⏳ #{n} {name} — PLANNED: {desc} Eta ekhono banano "
                "hoy ni, tai chalate parlam na. Eta banate bolle ami "
                "dev agent diye bananor chesta korbo.")
    if status == "NEEDS-DEVICE":
        need = rec.get("requires") or "matching hardware"
        return (f"🔌 #{n} {name} — NEEDS-DEVICE: {desc} Eta chalate "
                f"{need} lagbe — hardware chara kono app eta korte pare na.")

    # WORKING: try the pattern engine first (core/pattern_engines.py) —
    # it runs the feature through its pattern's real capability
    # (automation, agent routing, dashboard snapshot, queue, ...). When
    # the engine reports it cannot handle the record (None), fall through
    # to the existing direct dispatch below. NEEDS-KEY behaviour is
    # untouched: it still dispatches so the tool reports the missing key.
    if status == "WORKING":
        try:
            from core.pattern_engines import run_pattern
            handled = run_pattern(rec.get("pattern"), rec, player)
        except Exception:
            handled = None
        if isinstance(handled, str) and handled.strip():
            return handled

    # WORKING or NEEDS-KEY: dispatch to the owning tool when possible.
    tool = rec.get("tool")
    if not tool:
        if status == "WORKING":
            return (f"✅ #{n} {name} — WORKING: {desc} Eta Mark-er "
                    "vitorei built-in — alada kore chalate hoy na, emnitei cholche.")
        need = rec.get("requires") or "account / API key"
        return (f"🔑 #{n} {name} — NEEDS-KEY: {desc} Eta chalate "
                f"{need} lagbe — Settings-e key boshan, chat-e key deben na.")
    runner = _tool_runner(player)
    if runner is None:
        if status == "WORKING":
            return (f"✅ #{n} {name} — WORKING (tool: {tool}). Ekhane theke "
                    "tool chalate parlam na — Mark app-e voice/chat diye "
                    f"'{tool}' chalalei hobe.")
        need = rec.get("requires") or "account / API key"
        return (f"🔑 #{n} {name} — NEEDS-KEY: {desc} Eta chalate "
                f"{need} lagbe — Settings-e key boshan.")
    try:
        result = runner(tool, dict(rec.get("args") or {}))
    except Exception as exc:
        return f"#{n} {name} chalate giye problem holo: {exc}"
    if isinstance(result, str) and result.strip():
        return result
    return f"#{n} {name} — {tool} theke kono uttor pelam na."


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Search / list / get / run / stats over the feature registry.
    Never raises."""
    try:
        params = parameters or {}
        action = str(params.get("action") or "").strip().lower()
        reg = _registry()
        if reg is None or not reg.list_categories():
            return _registry_missing()

        if action == "search":
            return _do_search(params, reg)
        if action == "list":
            return _do_list(params, reg)
        if action == "get":
            return _do_get(params, reg)
        if action == "run":
            return _do_run(params, reg, player)
        if action == "stats":
            return _do_stats(reg)
        return ("Action bujhlam na. Use koro: search, list, get, run, stats. "
                "Jemon: search 'YouTube upload', list 'Browser Control', "
                "get 1234, run 1234.")
    except Exception as exc:
        return f"Features tool-ta korte parlam na: {exc}"
