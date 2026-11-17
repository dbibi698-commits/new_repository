#!/usr/bin/env python3
"""data/gen_features_1m.py — generate data/feature_structure.py, the
structure behind the formula-based 13,700,000-feature registry.

Source of truth (imported, never copy-pasted or hand-written):
  ~/workspace/.tmp/gen20000.py       -> CATEGORIES (100 x 10 targets), PATTERNS (20)
  ~/workspace/.tmp/gen1000000.py     -> CONTEXTS (49), targets_for() [Volume 1]
  ~/workspace/.tmp/gen2000000_ext.py -> CONTEXTS2 (100 NEW contexts) [Volume 2]
  ~/workspace/.tmp/vol3_spec.py     -> CONTEXTS3 (50 NEW contexts) [Volume 3]
  ~/workspace/.tmp/vol4_spec.py     -> CONTEXTS4 (35 NEW contexts) [Volume 4]
  ~/workspace/.tmp/vol5_spec.py     -> CONTEXTS5 (100 NEW contexts) [Volume 5]
  ~/workspace/.tmp/vol6_spec.py     -> CONTEXTS6 (350 NEW contexts) [Volume 6]
  core/feature_registry.py           -> _status(), the ported Phase 1 rules

Structure:
  Volume 1 (numbers 1-1,000,000): 100 categories x 500 targets x 20
    patterns = 1,000,000. Targets per category: 10 plain + 10 base x 49
    contexts = 500. Numbering: number = c*10000 + t*20 + p + 1.
  Volume 2 (numbers 1,000,001-3,000,000): 100 categories x 1,000 targets
    x 20 patterns = 2,000,000. Targets per category: 10 base x 100 NEW
    contexts = 1,000 (all contextual, no plain). Numbering:
    e = n - 1,000,001; c = e // 20000; t = (e % 20000) // 20; p = e % 20;
    target = base_targets[c][t // 100] + " for " + CONTEXTS2[t % 100].
  Volume 3 (numbers 3,000,001-4,000,000): 100 categories x 500 targets
    x 20 patterns = 1,000,000. Targets per category: 10 base x 50 NEW
    contexts = 500 (all contextual, no plain). Numbering:
    e = n - 3,000,001; c = e // 10000; t = (e % 10000) // 20; p = e % 20;
    target = base_targets[t // 50] + " for " + CONTEXTS3[t % 50].
  Volume 4 (numbers 4,000,001-4,700,000): 100 categories x 350 targets
    x 20 patterns = 700,000. Targets per category: 10 base x 35 NEW
    contexts = 350 (all contextual, no plain). Numbering:
    e = n - 4,000,001; c = e // 7000; t = (e % 7000) // 20; p = e % 20;
    target = base_targets[t // 35] + " for " + CONTEXTS4[t % 35].
  Volume 5 (numbers 4,700,001-6,700,000): 100 categories x 1,000 targets
    x 20 patterns = 2,000,000. Targets per category: 10 base x 100 NEW
    contexts = 1,000 (all contextual, no plain). Numbering:
    e = n - 4,700,001; c = e // 20000; t = (e % 20000) // 20; p = e % 20;
    target = base_targets[t // 100] + " for " + CONTEXTS5[t % 100].
  Volume 6 (numbers 6,700,001-13,700,000): 100 categories x 3,500 targets
    x 20 patterns = 7,000,000. Targets per category: 10 base x 350 NEW
    contexts = 3,500 (all contextual, no plain). Numbering:
    e = n - 6,700,001; c = e // 70000; t = (e % 70000) // 20; p = e % 20;
    target = base_targets[t // 350] + " for " + CONTEXTS6[t % 350].
  Total: 13,700,000. The first 200 numbers of each category are identical
  to the old 20,000-feature registry.

Output: data/feature_structure.py — CATEGORIES, PATTERNS, CONTEXTS,
CONTEXTS2, CONTEXTS3, CONTEXTS4, CONTEXTS5, CONTEXTS6 as Python literals
plus baked-in coverage COUNTS (and COUNTS_V1 / COUNTS_V2 / COUNTS_V3 /
COUNTS_V4 / COUNTS_V5 / COUNTS_V6 per volume), computed by iterating the
status rule over the formula space. Volume 2/3/4/5/6 counts are computed
analytically: each (category, base target) repeats across 100 (Vol 2) /
50 (Vol 3) / 35 (Vol 4) / 100 (Vol 5) / 350 (Vol 6) contexts x 20 patterns,
so one _status() call per (category, base, pattern) counts 100 / 50 / 35 /
100 / 350 features. No 13.7M-entry list is ever written: a stored
13,700,000-record JSON would be ~2 GB. core/feature_registry.py resolves
every feature from its number instead.

Run:  python3 data/gen_features_1m.py        (from ~/workspace/mark-lvii)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/workspace/.tmp"))
import gen20000 as gen  # noqa: E402  (CATEGORIES / PATTERNS)
import gen1000000 as gen1m  # noqa: E402  (CONTEXTS / targets_for)
import gen2000000_ext as gen2m  # noqa: E402  (CONTEXTS2)
import vol3_spec as gen3m  # noqa: E402  (CONTEXTS3)
import vol4_spec as gen4m  # noqa: E402  (CONTEXTS4)
import vol5_spec as gen5m  # noqa: E402  (CONTEXTS5)
import vol6_spec as gen6m  # noqa: E402  (CONTEXTS6)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from core.feature_registry import _status  # noqa: E402  (ported Phase 1 rules)

OUT_PATH = HERE / "feature_structure.py"


def main():
    CATEGORIES = gen.CATEGORIES
    PATTERNS = gen.PATTERNS
    CONTEXTS = gen1m.CONTEXTS
    CONTEXTS2 = gen2m.CONTEXTS2
    CONTEXTS3 = gen3m.CONTEXTS3
    CONTEXTS4 = gen4m.CONTEXTS4
    CONTEXTS5 = gen5m.CONTEXTS5
    CONTEXTS6 = gen6m.CONTEXTS6

    # ---- Assertions (fail loudly rather than writing a bad structure) ----
    assert len(CATEGORIES) == 100, f"categories: {len(CATEGORIES)}"
    assert all(len(t) == 10 for _, t in CATEGORIES), "each category needs 10 plain targets"
    assert len(PATTERNS) == 20, f"patterns: {len(PATTERNS)}"
    assert len(CONTEXTS) == 49, f"contexts: {len(CONTEXTS)}"
    assert len(CONTEXTS2) == 100, f"contexts2: {len(CONTEXTS2)}"
    assert len(CONTEXTS3) == 50, f"contexts3: {len(CONTEXTS3)}"
    assert len(CONTEXTS4) == 35, f"contexts4: {len(CONTEXTS4)}"
    assert len(CONTEXTS5) == 100, f"contexts5: {len(CONTEXTS5)}"
    assert len(CONTEXTS6) == 350, f"contexts6: {len(CONTEXTS6)}"
    assert not set(CONTEXTS2) & set(CONTEXTS), "Volume 2 contexts must be NEW"
    assert not set(CONTEXTS3) & set(CONTEXTS), "Volume 3 contexts must be NEW"
    assert not set(CONTEXTS3) & set(CONTEXTS2), "Volume 3 contexts must be NEW vs Volume 2"
    assert not set(CONTEXTS4) & set(CONTEXTS), "Volume 4 contexts must be NEW"
    assert not set(CONTEXTS4) & set(CONTEXTS2), "Volume 4 contexts must be NEW vs Volume 2"
    assert not set(CONTEXTS4) & set(CONTEXTS3), "Volume 4 contexts must be NEW vs Volume 3"
    assert not set(CONTEXTS5) & set(CONTEXTS), "Volume 5 contexts must be NEW"
    assert not set(CONTEXTS5) & set(CONTEXTS2), "Volume 5 contexts must be NEW vs Volume 2"
    assert not set(CONTEXTS5) & set(CONTEXTS3), "Volume 5 contexts must be NEW vs Volume 3"
    assert not set(CONTEXTS5) & set(CONTEXTS4), "Volume 5 contexts must be NEW vs Volume 4"
    _old_ctx = (set(CONTEXTS) | set(CONTEXTS2) | set(CONTEXTS3)
                | set(CONTEXTS4) | set(CONTEXTS5))
    assert not set(CONTEXTS6) & _old_ctx, "Volume 6 contexts must be NEW"
    for _cat, cat_targets in CATEGORIES:
        assert len(gen1m.targets_for(cat_targets)) == 500
        assert len(gen2m.targets_for(cat_targets)) == 1000
        assert len([f"{b} for {c3}" for b in cat_targets for c3 in CONTEXTS3]) == 500
        assert len([f"{b} for {c4}" for b in cat_targets for c4 in CONTEXTS4]) == 350
        assert len([f"{b} for {c5}" for b in cat_targets for c5 in CONTEXTS5]) == 1000
        assert len([f"{b} for {c6}" for b in cat_targets for c6 in CONTEXTS6]) == 3500
    total_v1 = len(CATEGORIES) * 500 * len(PATTERNS)
    total_v2 = len(CATEGORIES) * 1000 * len(PATTERNS)
    total_v3 = len(CATEGORIES) * 500 * len(PATTERNS)
    total_v4 = len(CATEGORIES) * 350 * len(PATTERNS)
    total_v5 = len(CATEGORIES) * 1000 * len(PATTERNS)
    total_v6 = len(CATEGORIES) * 3500 * len(PATTERNS)
    assert total_v1 == 1_000_000, f"total v1: {total_v1}"
    assert total_v2 == 2_000_000, f"total v2: {total_v2}"
    assert total_v3 == 1_000_000, f"total v3: {total_v3}"
    assert total_v4 == 700_000, f"total v4: {total_v4}"
    assert total_v5 == 2_000_000, f"total v5: {total_v5}"
    assert total_v6 == 7_000_000, f"total v6: {total_v6}"
    assert (total_v1 + total_v2 + total_v3 + total_v4 + total_v5 + total_v6
            == 13_700_000)

    # ---- Coverage counts, Volume 1: iterate the status rule over the
    # formula space. For t >= 10 the BASE target's rule applies
    # (status/tool/args of the base target's feature), exactly as
    # core/feature_registry.resolve() does — so these counts always
    # agree with the resolver.
    counts_v1 = {"WORKING": 0, "NEEDS-KEY": 0, "NEEDS-DEVICE": 0, "PLANNED": 0}
    for ci, (_cat, cat_targets) in enumerate(CATEGORIES, start=1):
        targets = gen1m.targets_for(cat_targets)
        bases = list(cat_targets) + [
            cat_targets[(t - 10) // len(CONTEXTS)] for t in range(10, 500)]
        assert len(targets) == 500 and len(bases) == 500
        for t in range(500):
            base = bases[t]
            for name_tpl, _desc_tpl in PATTERNS:
                status, _tool, _args, _req = _status(ci, base, name_tpl)
                counts_v1[status] += 1
        print(f"  v1 category {ci:3d} done ({_cat})", flush=True)
    counts_v1["total"] = sum(counts_v1.values())
    assert counts_v1["total"] == 1_000_000, counts_v1

    # ---- Coverage counts, Volume 2: analytic. Every target is
    # "<base> for <context2>" and the status rule depends only on
    # (category, base target, pattern) — so each (category, base,
    # pattern) triple covers exactly 100 features (one per context).
    counts_v2 = {"WORKING": 0, "NEEDS-KEY": 0, "NEEDS-DEVICE": 0, "PLANNED": 0}
    for ci, (_cat, cat_targets) in enumerate(CATEGORIES, start=1):
        for base in cat_targets:
            for name_tpl, _desc_tpl in PATTERNS:
                status, _tool, _args, _req = _status(ci, base, name_tpl)
                counts_v2[status] += 100
        print(f"  v2 category {ci:3d} done ({_cat})", flush=True)
    counts_v2["total"] = sum(counts_v2.values())
    assert counts_v2["total"] == 2_000_000, counts_v2

    # ---- Coverage counts, Volume 3: analytic, same as Volume 2.
    # Every target is "<base> for <context3>" and the status rule depends
    # only on (category, base target, pattern) — so each (category, base,
    # pattern) triple covers exactly 50 features (one per context).
    counts_v3 = {"WORKING": 0, "NEEDS-KEY": 0, "NEEDS-DEVICE": 0, "PLANNED": 0}
    for ci, (_cat, cat_targets) in enumerate(CATEGORIES, start=1):
        for base in cat_targets:
            for name_tpl, _desc_tpl in PATTERNS:
                status, _tool, _args, _req = _status(ci, base, name_tpl)
                counts_v3[status] += 50
        print(f"  v3 category {ci:3d} done ({_cat})", flush=True)
    counts_v3["total"] = sum(counts_v3.values())
    assert counts_v3["total"] == 1_000_000, counts_v3

    # ---- Coverage counts, Volume 4: analytic, same as Volume 2/3.
    # Every target is "<base> for <context4>" and the status rule depends
    # only on (category, base target, pattern) — so each (category, base,
    # pattern) triple covers exactly 35 features (one per context).
    counts_v4 = {"WORKING": 0, "NEEDS-KEY": 0, "NEEDS-DEVICE": 0, "PLANNED": 0}
    for ci, (_cat, cat_targets) in enumerate(CATEGORIES, start=1):
        for base in cat_targets:
            for name_tpl, _desc_tpl in PATTERNS:
                status, _tool, _args, _req = _status(ci, base, name_tpl)
                counts_v4[status] += 35
        print(f"  v4 category {ci:3d} done ({_cat})", flush=True)
    counts_v4["total"] = sum(counts_v4.values())
    assert counts_v4["total"] == 700_000, counts_v4

    # ---- Coverage counts, Volume 5: analytic, same as Volume 2/3/4.
    # Every target is "<base> for <context5>" and the status rule depends
    # only on (category, base target, pattern) — so each (category, base,
    # pattern) triple covers exactly 100 features (one per context).
    counts_v5 = {"WORKING": 0, "NEEDS-KEY": 0, "NEEDS-DEVICE": 0, "PLANNED": 0}
    for ci, (_cat, cat_targets) in enumerate(CATEGORIES, start=1):
        for base in cat_targets:
            for name_tpl, _desc_tpl in PATTERNS:
                status, _tool, _args, _req = _status(ci, base, name_tpl)
                counts_v5[status] += 100
        print(f"  v5 category {ci:3d} done ({_cat})", flush=True)
    counts_v5["total"] = sum(counts_v5.values())
    assert counts_v5["total"] == 2_000_000, counts_v5

    # ---- Coverage counts, Volume 6: analytic, same as Volume 2/3/4/5.
    # Every target is "<base> for <context6>" and the status rule depends
    # only on (category, base target, pattern) — so each (category, base,
    # pattern) triple covers exactly 350 features (one per context).
    counts_v6 = {"WORKING": 0, "NEEDS-KEY": 0, "NEEDS-DEVICE": 0, "PLANNED": 0}
    for ci, (_cat, cat_targets) in enumerate(CATEGORIES, start=1):
        for base in cat_targets:
            for name_tpl, _desc_tpl in PATTERNS:
                status, _tool, _args, _req = _status(ci, base, name_tpl)
                counts_v6[status] += 350
        print(f"  v6 category {ci:3d} done ({_cat})", flush=True)
    counts_v6["total"] = sum(counts_v6.values())
    assert counts_v6["total"] == 7_000_000, counts_v6

    counts = {s: counts_v1[s] + counts_v2[s] + counts_v3[s]
              + counts_v4[s] + counts_v5[s] + counts_v6[s]
              for s in ("WORKING", "NEEDS-KEY", "NEEDS-DEVICE", "PLANNED")}
    counts["total"] = (counts_v1["total"] + counts_v2["total"]
                       + counts_v3["total"] + counts_v4["total"]
                       + counts_v5["total"] + counts_v6["total"])
    assert counts["total"] == 13_700_000, counts
    assert all(s in counts for s in ("WORKING", "NEEDS-KEY", "NEEDS-DEVICE", "PLANNED"))

    header = (
        '"""data/feature_structure.py — GENERATED, do not hand-edit.\n'
        '\n'
        'Structure behind the formula-based 13,700,000-feature registry\n'
        '(core/feature_registry.py resolves every feature from its number).\n'
        'Regenerate with:  python3 data/gen_features_1m.py\n'
        '\n'
        'Source of truth: ~/workspace/.tmp/gen20000.py (CATEGORIES, PATTERNS),\n'
        '~/workspace/.tmp/gen1000000.py (CONTEXTS, Volume 1),\n'
        '~/workspace/.tmp/gen2000000_ext.py (CONTEXTS2, Volume 2),\n'
        '~/workspace/.tmp/vol3_spec.py (CONTEXTS3, Volume 3),\n'
        '~/workspace/.tmp/vol4_spec.py (CONTEXTS4, Volume 4),\n'
        '~/workspace/.tmp/vol5_spec.py (CONTEXTS5, Volume 5) and\n'
        '~/workspace/.tmp/vol6_spec.py (CONTEXTS6, Volume 6). COUNTS\n'
        'was computed by iterating the ported Phase 1 status rule over the\n'
        'whole formula space (Volume 1: 100 categories x 500 targets x 20\n'
        'patterns; Volume 2: 100 categories x 1,000 targets x 20 patterns;\n'
        'Volume 3: 100 categories x 500 targets x 20 patterns;\n'
        'Volume 4: 100 categories x 350 targets x 20 patterns;\n'
        'Volume 5: 100 categories x 1,000 targets x 20 patterns;\n'
        'Volume 6: 100 categories x 3,500 targets x 20 patterns).\n'
        '"""\n\n'
    )
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(f"CATEGORIES = {CATEGORIES!r}\n\n")
        f.write(f"PATTERNS = {PATTERNS!r}\n\n")
        f.write(f"CONTEXTS = {CONTEXTS!r}\n\n")
        f.write(f"CONTEXTS2 = {CONTEXTS2!r}\n\n")
        f.write(f"CONTEXTS3 = {CONTEXTS3!r}\n\n")
        f.write(f"CONTEXTS4 = {CONTEXTS4!r}\n\n")
        f.write(f"CONTEXTS5 = {CONTEXTS5!r}\n\n")
        f.write(f"CONTEXTS6 = {CONTEXTS6!r}\n\n")
        f.write(f"COUNTS = {counts!r}\n\n")
        f.write(f"COUNTS_V1 = {counts_v1!r}\n\n")
        f.write(f"COUNTS_V2 = {counts_v2!r}\n\n")
        f.write(f"COUNTS_V3 = {counts_v3!r}\n\n")
        f.write(f"COUNTS_V4 = {counts_v4!r}\n\n")
        f.write(f"COUNTS_V5 = {counts_v5!r}\n\n")
        f.write(f"COUNTS_V6 = {counts_v6!r}\n")

    print(f"categories: {len(CATEGORIES)}  patterns: {len(PATTERNS)}  "
          f"contexts: {len(CONTEXTS)}  contexts2: {len(CONTEXTS2)}  "
          f"contexts3: {len(CONTEXTS3)}  contexts4: {len(CONTEXTS4)}  "
          f"contexts5: {len(CONTEXTS5)}  contexts6: {len(CONTEXTS6)}  "
          f"total: {counts['total']}")
    print("status counts (v1 + v2 + v3 + v4 + v5 + v6 = total):")
    for s in ("WORKING", "NEEDS-KEY", "NEEDS-DEVICE", "PLANNED"):
        print(f"  {s}: {counts_v1[s]} + {counts_v2[s]} + {counts_v3[s]} "
              f"+ {counts_v4[s]} + {counts_v5[s]} + {counts_v6[s]} "
              f"= {counts[s]}")
    print(f"written: {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
