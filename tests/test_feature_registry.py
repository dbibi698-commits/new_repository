"""tests/test_feature_registry.py — registry tests for the formula-based
13,700,000-feature registry (core/feature_registry.py).

Run from ~/workspace/mark-lvii:
    python3 tests/test_feature_registry.py
    python3 -m unittest discover -s tests -v

Stdlib only. Covers Volume 1 (1-1,000,000), Volume 2 (1,000,001-3,000,000),
Volume 3 (3,000,001-4,000,000), Volume 4 (4,000,001-4,700,000),
Volume 5 (4,700,001-6,700,000) and Volume 6 (6,700,001-13,700,000):
boundaries, resolve, list/search, counts and the baked-in COUNTS.
Never touches Qt, the network or the user's config — resolve() is pure
formula math over data/feature_structure.py.
"""
from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import feature_registry as fr  # noqa: E402


class TestTotals(unittest.TestCase):
    def test_total_is_13_7m(self):
        self.assertEqual(fr.TOTAL, 13_700_000)

    def test_counts_sum_to_13_7m(self):
        c = fr.counts()
        self.assertEqual(c["total"], 13_700_000)
        self.assertEqual(
            c["WORKING"] + c["NEEDS-KEY"] + c["NEEDS-DEVICE"] + c["PLANNED"],
            13_700_000)

    def test_counts_match_baked_volumes(self):
        from data.feature_structure import (
            COUNTS, COUNTS_V1, COUNTS_V2, COUNTS_V3, COUNTS_V4, COUNTS_V5,
            COUNTS_V6)
        self.assertEqual(COUNTS_V1["total"], 1_000_000)
        self.assertEqual(COUNTS_V2["total"], 2_000_000)
        self.assertEqual(COUNTS_V3["total"], 1_000_000)
        self.assertEqual(COUNTS_V4["total"], 700_000)
        self.assertEqual(COUNTS_V5["total"], 2_000_000)
        self.assertEqual(COUNTS_V6["total"], 7_000_000)
        # Vol 3 distribution matches Vol 1 (same per-base rule, 50
        # instances per base target in both volumes).
        self.assertEqual(COUNTS_V3, COUNTS_V1)
        # Vol 5 distribution is Vol 2's (same per-base rule, 100
        # instances per base target in both volumes).
        self.assertEqual(COUNTS_V5, COUNTS_V2)
        for s in fr.STATUSES:
            self.assertEqual(COUNTS[s],
                             COUNTS_V1[s] + COUNTS_V2[s] + COUNTS_V3[s]
                             + COUNTS_V4[s] + COUNTS_V5[s] + COUNTS_V6[s])
        self.assertEqual(fr.counts(), COUNTS)


class TestVolume3Boundaries(unittest.TestCase):
    def test_first_vol3_feature(self):
        r = fr.resolve(3_000_001)
        self.assertNotIn("error", r)
        self.assertEqual(r["volume"], 3)
        self.assertEqual(r["category"], "Voice & AI Brain")
        self.assertEqual(r["category_index"], 1)
        self.assertEqual(r["target"], "wake-word detection for restaurant")
        self.assertEqual(r["base_target"], "wake-word detection")
        self.assertEqual(r["context"], "restaurant")
        self.assertEqual(r["pattern"], "Auto {t}")
        self.assertEqual(r["pattern_index"], 0)
        self.assertEqual(r["name"], "Auto wake-word detection for restaurant")
        self.assertEqual(r["status"], "PLANNED")

    def test_last_vol3_feature(self):
        r = fr.resolve(4_000_000)
        self.assertNotIn("error", r)
        self.assertEqual(r["volume"], 3)
        self.assertEqual(r["category"], "Ultra AI & Future Lab")
        self.assertEqual(r["category_index"], 100)
        self.assertEqual(r["target"], "idea lab for river")
        self.assertEqual(r["base_target"], "idea lab")
        self.assertEqual(r["context"], "river")
        self.assertEqual(r["pattern"], "Widgets for {t}")
        self.assertEqual(r["pattern_index"], 19)
        self.assertEqual(r["name"], "Widgets for idea lab for river")
        self.assertEqual(r["status"], "PLANNED")

    def test_decompose_spot_checks(self):
        # From ~/workspace/.tmp/vol3_spec.py (verified there).
        self.assertEqual(fr._decompose(3_000_001), (3, 0, 0, 0))
        self.assertEqual(fr._decompose(4_000_000), (3, 99, 499, 19))
        self.assertEqual(fr._decompose(3_500_000), (3, 49, 499, 19))
        self.assertEqual(fr._decompose(3_010_000), (3, 0, 499, 19))

    def test_vol2_end_still_volume_2(self):
        r = fr.resolve(3_000_000)
        self.assertEqual(r["volume"], 2)
        self.assertEqual(r["name"], "Widgets for idea lab for firefighting")

    def test_vol1_and_vol2_starts_unchanged(self):
        self.assertEqual(fr.resolve(1)["volume"], 1)
        self.assertEqual(fr.resolve(1_000_000)["volume"], 1)
        self.assertEqual(fr.resolve(1_000_001)["volume"], 2)

    def test_vol1_first_200_names_unchanged(self):
        # Regression guard: the old 20,000-feature registry's first 200
        # names per category must not move when a volume is added.
        self.assertEqual(fr.resolve(1)["name"], "Auto wake-word detection")
        self.assertEqual(fr.resolve(200)["name"],
                         "Widgets for multi-provider AI")


class TestVolume4Boundaries(unittest.TestCase):
    def test_first_vol4_feature(self):
        r = fr.resolve(4_000_001)
        self.assertNotIn("error", r)
        self.assertEqual(r["volume"], 4)
        self.assertEqual(r["category"], "Voice & AI Brain")
        self.assertEqual(r["category_index"], 1)
        self.assertEqual(r["target"], "wake-word detection for lighthouse")
        self.assertEqual(r["base_target"], "wake-word detection")
        self.assertEqual(r["context"], "lighthouse")
        self.assertEqual(r["pattern"], "Auto {t}")
        self.assertEqual(r["pattern_index"], 0)
        self.assertEqual(r["name"], "Auto wake-word detection for lighthouse")
        self.assertEqual(r["status"], "PLANNED")

    def test_last_vol4_feature(self):
        r = fr.resolve(4_700_000)
        self.assertNotIn("error", r)
        self.assertEqual(r["volume"], 4)
        self.assertEqual(r["category"], "Ultra AI & Future Lab")
        self.assertEqual(r["category_index"], 100)
        self.assertEqual(r["target"], "idea lab for barber")
        self.assertEqual(r["base_target"], "idea lab")
        self.assertEqual(r["context"], "barber")
        self.assertEqual(r["pattern"], "Widgets for {t}")
        self.assertEqual(r["pattern_index"], 19)
        self.assertEqual(r["name"], "Widgets for idea lab for barber")
        self.assertEqual(r["status"], "PLANNED")

    def test_decompose_spot_checks(self):
        # From ~/workspace/.tmp/vol4_spec.py (verified there).
        self.assertEqual(fr._decompose(4_000_001), (4, 0, 0, 0))
        self.assertEqual(fr._decompose(4_700_000), (4, 99, 349, 19))
        self.assertEqual(fr._decompose(4_350_000), (4, 49, 349, 19))
        self.assertEqual(fr._decompose(4_007_000), (4, 0, 349, 19))

    def test_vol3_end_still_volume_3(self):
        r = fr.resolve(4_000_000)
        self.assertEqual(r["volume"], 3)
        self.assertEqual(r["name"], "Widgets for idea lab for river")


class TestVolume5Boundaries(unittest.TestCase):
    def test_first_vol5_feature(self):
        r = fr.resolve(4_700_001)
        self.assertNotIn("error", r)
        self.assertEqual(r["volume"], 5)
        self.assertEqual(r["category"], "Voice & AI Brain")
        self.assertEqual(r["category_index"], 1)
        self.assertEqual(r["target"], "wake-word detection for farmer")
        self.assertEqual(r["base_target"], "wake-word detection")
        self.assertEqual(r["context"], "farmer")
        self.assertEqual(r["pattern"], "Auto {t}")
        self.assertEqual(r["pattern_index"], 0)
        self.assertEqual(r["name"], "Auto wake-word detection for farmer")
        self.assertEqual(r["status"], "PLANNED")

    def test_last_vol5_feature(self):
        r = fr.resolve(6_700_000)
        self.assertNotIn("error", r)
        self.assertEqual(r["volume"], 5)
        self.assertEqual(r["category"], "Ultra AI & Future Lab")
        self.assertEqual(r["category_index"], 100)
        self.assertEqual(r["target"], "idea lab for earthquake")
        self.assertEqual(r["base_target"], "idea lab")
        self.assertEqual(r["context"], "earthquake")
        self.assertEqual(r["pattern"], "Widgets for {t}")
        self.assertEqual(r["pattern_index"], 19)
        self.assertEqual(r["name"], "Widgets for idea lab for earthquake")
        self.assertEqual(r["status"], "PLANNED")

    def test_decompose_spot_checks(self):
        # From ~/workspace/.tmp/vol5_spec.py (verified there).
        self.assertEqual(fr._decompose(4_700_001), (5, 0, 0, 0))
        self.assertEqual(fr._decompose(6_700_000), (5, 99, 999, 19))
        self.assertEqual(fr._decompose(5_700_000), (5, 49, 999, 19))
        self.assertEqual(fr._decompose(4_720_000), (5, 0, 999, 19))

    def test_vol4_end_still_volume_4(self):
        r = fr.resolve(4_700_000)
        self.assertEqual(r["volume"], 4)
        self.assertEqual(r["name"], "Widgets for idea lab for barber")


class TestVolume6Boundaries(unittest.TestCase):
    def test_first_vol6_feature(self):
        r = fr.resolve(6_700_001)
        self.assertNotIn("error", r)
        self.assertEqual(r["volume"], 6)
        self.assertEqual(r["category"], "Voice & AI Brain")
        self.assertEqual(r["category_index"], 1)
        self.assertEqual(r["target"], "wake-word detection for asteroid")
        self.assertEqual(r["base_target"], "wake-word detection")
        self.assertEqual(r["context"], "asteroid")
        self.assertEqual(r["pattern"], "Auto {t}")
        self.assertEqual(r["pattern_index"], 0)
        self.assertEqual(r["name"], "Auto wake-word detection for asteroid")
        self.assertEqual(r["status"], "PLANNED")

    def test_last_vol6_feature(self):
        r = fr.resolve(13_700_000)
        self.assertNotIn("error", r)
        self.assertEqual(r["volume"], 6)
        self.assertEqual(r["category"], "Ultra AI & Future Lab")
        self.assertEqual(r["category_index"], 100)
        self.assertEqual(r["target"], "idea lab for yeti")
        self.assertEqual(r["base_target"], "idea lab")
        self.assertEqual(r["context"], "yeti")
        self.assertEqual(r["pattern"], "Widgets for {t}")
        self.assertEqual(r["pattern_index"], 19)
        self.assertEqual(r["name"], "Widgets for idea lab for yeti")
        self.assertEqual(r["status"], "PLANNED")

    def test_decompose_spot_checks(self):
        # From ~/workspace/.tmp/vol6_spec.py (verified there).
        self.assertEqual(fr._decompose(6_700_001), (6, 0, 0, 0))
        self.assertEqual(fr._decompose(13_700_000), (6, 99, 3499, 19))
        self.assertEqual(fr._decompose(10_000_000), (6, 47, 499, 19))

    def test_vol6_mid_feature_matches_mobile_spec(self):
        # vol6_spec.py resolve_name: #10000000 is Sales & CRM,
        # "Widgets for deal pipeline for cat".
        r = fr.resolve(10_000_000)
        self.assertEqual(r["volume"], 6)
        self.assertEqual(r["category"], "Sales & CRM")
        self.assertEqual(r["category_index"], 48)
        self.assertEqual(r["target"], "deal pipeline for cat")
        self.assertEqual(r["base_target"], "deal pipeline")
        self.assertEqual(r["context"], "cat")
        self.assertEqual(r["name"], "Widgets for deal pipeline for cat")

    def test_vol5_end_still_volume_5(self):
        r = fr.resolve(6_700_000)
        self.assertEqual(r["volume"], 5)
        self.assertEqual(r["name"], "Widgets for idea lab for earthquake")

    def test_invalid_numbers(self):
        for bad in (0, -1, 13_700_001, 99_999_999, "abc", None, True):
            r = fr.resolve(bad)
            self.assertIn("error", r, bad)


class TestVolume4And5ContextsAreNew(unittest.TestCase):
    def test_contexts4_disjoint_from_vol1_vol2_vol3(self):
        from data.feature_structure import (
            CONTEXTS, CONTEXTS2, CONTEXTS3, CONTEXTS4)
        self.assertEqual(len(CONTEXTS4), 35)
        self.assertEqual(len(set(CONTEXTS4)), 35)
        self.assertFalse(set(CONTEXTS4) & set(CONTEXTS))
        self.assertFalse(set(CONTEXTS4) & set(CONTEXTS2))
        self.assertFalse(set(CONTEXTS4) & set(CONTEXTS3))

    def test_contexts5_disjoint_from_vol1_vol2_vol3_vol4(self):
        from data.feature_structure import (
            CONTEXTS, CONTEXTS2, CONTEXTS3, CONTEXTS4, CONTEXTS5)
        self.assertEqual(len(CONTEXTS5), 100)
        self.assertEqual(len(set(CONTEXTS5)), 100)
        self.assertFalse(set(CONTEXTS5) & set(CONTEXTS))
        self.assertFalse(set(CONTEXTS5) & set(CONTEXTS2))
        self.assertFalse(set(CONTEXTS5) & set(CONTEXTS3))
        self.assertFalse(set(CONTEXTS5) & set(CONTEXTS4))

    def test_vol4_names_carry_a_vol4_context(self):
        from data.feature_structure import CONTEXTS4
        rnd = random.Random(20261117)
        for _ in range(200):
            n = rnd.randint(4_000_001, 4_700_000)
            r = fr.resolve(n)
            self.assertEqual(r["volume"], 4)
            self.assertIn(r["context"], CONTEXTS4)
            self.assertIn(f" for {r['context']}", r["target"])

    def test_vol5_names_carry_a_vol5_context(self):
        from data.feature_structure import CONTEXTS5
        rnd = random.Random(20261117)
        for _ in range(200):
            n = rnd.randint(4_700_001, 6_700_000)
            r = fr.resolve(n)
            self.assertEqual(r["volume"], 5)
            self.assertIn(r["context"], CONTEXTS5)
            self.assertIn(f" for {r['context']}", r["target"])


class TestVolume6ContextsAreNew(unittest.TestCase):
    def test_contexts6_disjoint_from_vol1_to_vol5(self):
        from data.feature_structure import (
            CONTEXTS, CONTEXTS2, CONTEXTS3, CONTEXTS4, CONTEXTS5, CONTEXTS6)
        self.assertEqual(len(CONTEXTS6), 350)
        self.assertEqual(len(set(CONTEXTS6)), 350)
        for old in (CONTEXTS, CONTEXTS2, CONTEXTS3, CONTEXTS4, CONTEXTS5):
            self.assertFalse(set(CONTEXTS6) & set(old))

    def test_vol6_names_carry_a_vol6_context(self):
        from data.feature_structure import CONTEXTS6
        rnd = random.Random(20261117)
        for _ in range(200):
            n = rnd.randint(6_700_001, 13_700_000)
            r = fr.resolve(n)
            self.assertEqual(r["volume"], 6)
            self.assertIn(r["context"], CONTEXTS6)
            self.assertIn(f" for {r['context']}", r["target"])


class TestListAndCategory(unittest.TestCase):
    def test_list_categories_vol3_ranges(self):
        cats = fr.list_categories()
        self.assertEqual(len(cats), 100)
        self.assertEqual(cats[0]["vol3_start"], 3_000_001)
        self.assertEqual(cats[0]["vol3_end"], 3_010_000)
        self.assertEqual(cats[99]["vol3_start"], 3_990_001)
        self.assertEqual(cats[99]["vol3_end"], 4_000_000)
        # Ranges are contiguous and cover the whole space.
        self.assertEqual(cats[0]["start"], 1)
        self.assertEqual(cats[99]["end"], 10_000 * 100)
        self.assertEqual(cats[0]["vol2_start"], 1_000_001)
        self.assertEqual(cats[99]["vol2_end"], 3_000_000)

    def test_list_categories_vol4_vol5_ranges(self):
        cats = fr.list_categories()
        self.assertEqual(cats[0]["vol4_start"], 4_000_001)
        self.assertEqual(cats[0]["vol4_end"], 4_007_000)
        self.assertEqual(cats[99]["vol4_start"], 4_693_001)
        self.assertEqual(cats[99]["vol4_end"], 4_700_000)
        self.assertEqual(cats[0]["vol5_start"], 4_700_001)
        self.assertEqual(cats[0]["vol5_end"], 4_720_000)
        self.assertEqual(cats[99]["vol5_start"], 6_680_001)
        self.assertEqual(cats[99]["vol5_end"], 6_700_000)

    def test_list_categories_vol6_ranges(self):
        cats = fr.list_categories()
        self.assertEqual(cats[0]["vol6_start"], 6_700_001)
        self.assertEqual(cats[0]["vol6_end"], 6_770_000)
        self.assertEqual(cats[99]["vol6_start"], 13_630_001)
        self.assertEqual(cats[99]["vol6_end"], 13_700_000)

    def test_list_category_vol3_offsets(self):
        recs = fr.list_category(1, 30000, 3)
        self.assertEqual([r["number"] for r in recs],
                         [3_000_001, 3_000_002, 3_000_003])
        self.assertTrue(all(r["volume"] == 3 for r in recs))
        # Offsets 39990..40009 cross the Vol 3 -> Vol 4 boundary:
        # last 10 of category 100's Vol 3 range, then its first 10 Vol 4.
        tail = fr.list_category(100, 39990, 20)
        self.assertEqual([r["number"] for r in tail],
                         list(range(3_999_991, 4_000_001))
                         + list(range(4_693_001, 4_693_011)))

    def test_list_category_vol4_vol5_offsets(self):
        recs = fr.list_category(1, 40000, 3)
        self.assertEqual([r["number"] for r in recs],
                         [4_000_001, 4_000_002, 4_000_003])
        self.assertTrue(all(r["volume"] == 4 for r in recs))
        recs = fr.list_category(1, 47000, 3)
        self.assertEqual([r["number"] for r in recs],
                         [4_700_001, 4_700_002, 4_700_003])
        self.assertTrue(all(r["volume"] == 5 for r in recs))
        # Offsets 66990..67009 cross the Vol 5 -> Vol 6 boundary:
        # last 10 of category 100's Vol 5 range, then its first 10 Vol 6.
        tail = fr.list_category(100, 66990, 20)
        self.assertEqual([r["number"] for r in tail],
                         list(range(6_699_991, 6_700_001))
                         + list(range(13_630_001, 13_630_011)))
        self.assertEqual(fr.list_category(1, 66999, 5),
                         [fr.resolve(4_720_000),
                          fr.resolve(6_700_001), fr.resolve(6_700_002),
                          fr.resolve(6_700_003), fr.resolve(6_700_004)])

    def test_list_category_vol6_offsets(self):
        recs = fr.list_category(1, 67000, 3)
        self.assertEqual([r["number"] for r in recs],
                         [6_700_001, 6_700_002, 6_700_003])
        self.assertTrue(all(r["volume"] == 6 for r in recs))
        tail = fr.list_category(100, 136990, 20)
        self.assertEqual([r["number"] for r in tail],
                         list(range(13_699_991, 13_700_001)))
        self.assertEqual(fr.list_category(1, 137000), [])
        self.assertEqual(fr.list_category(1, 136999, 5),
                         [fr.resolve(6_770_000)])

    def test_category_status_counts_sum_to_137k(self):
        for cidx in (1, 10, 50, 100):
            counts = fr.category_status_counts(cidx)
            self.assertEqual(sum(counts.values()), 137_000, cidx)
            self.assertTrue(all(v >= 0 for v in counts.values()))


class TestSearch(unittest.TestCase):
    def test_search_vol3_context(self):
        # "restaurant" scores on one pair (cat 22 "restaurant finder"):
        # that pair alone yields 1000 V1 + 2000 V2 + 1000 V3 + 700 V4 +
        # 2000 V5 records, so a limit of 5000 stops inside Volume 4.
        hits = fr.search("restaurant", limit=5000)
        vols = {h["volume"] for h in hits}
        self.assertIn(3, vols)
        self.assertIn(4, vols)
        self.assertTrue(all("error" not in h for h in hits))

    def test_search_vol3_only_context(self):
        # "aquarium" is a Volume 3 context only (and a substring of no
        # base target, category or pattern) — every hit must be Vol 3.
        hits = fr.search("aquarium", limit=5)
        self.assertTrue(hits)
        self.assertTrue(all(h["volume"] == 3 for h in hits))
        self.assertTrue(all(h["context"] == "aquarium" for h in hits))

    def test_search_vol4_only_context(self):
        # "lighthouse" is a Volume 4 context only — every hit must be
        # Vol 4.
        hits = fr.search("lighthouse", limit=5)
        self.assertTrue(hits)
        self.assertTrue(all(h["volume"] == 4 for h in hits))
        self.assertTrue(all(h["context"] == "lighthouse" for h in hits))

    def test_search_vol5_only_context(self):
        # "farmer" is a Volume 5 context only — every hit must be Vol 5.
        hits = fr.search("farmer", limit=5)
        self.assertTrue(hits)
        self.assertTrue(all(h["volume"] == 5 for h in hits))
        self.assertTrue(all(h["context"] == "farmer" for h in hits))

    def test_search_total_vol3_context(self):
        # "aquarium": no pair/pattern/context hits in Vol 1/2/4/5/6; 1 Vol 3
        # context x 1000 (category, base) pairs x 20 patterns.
        self.assertEqual(fr.search_total("aquarium"), 20_000)
        # "river" is also a Vol 3 context, but it is a substring of the
        # base target "driver chat" (cat 68) — that scoring pair adds
        # 13,700 (1000 + 2000 + 1000 + 700 + 2000 + 7000: per base, Vol 6
        # is 350 contexts x 20 patterns) — and of the Vol 5 context
        # "driver" — the other 999 pairs add 20 (Vol 3 "river") + 20
        # (Vol 5 "driver") each.
        self.assertEqual(fr.search_total("river"), 53_660)

    def test_search_total_vol4_context(self):
        # "lighthouse": no pair/pattern/context hits in Vol 1/2/3/5/6; 1
        # Vol 4 context x 1000 (category, base) pairs x 20 patterns.
        self.assertEqual(fr.search_total("lighthouse"), 20_000)

    def test_search_total_vol5_context(self):
        # "farmer": no pair/pattern/context hits in Vol 1/2/3/4/6; 1 Vol 5
        # context x 1000 (category, base) pairs x 20 patterns.
        self.assertEqual(fr.search_total("farmer"), 20_000)

    def test_search_vol6_only_context(self):
        # "asteroid" is a Volume 6 context only — every hit must be
        # Vol 6.
        hits = fr.search("asteroid", limit=5)
        self.assertTrue(hits)
        self.assertTrue(all(h["volume"] == 6 for h in hits))
        self.assertTrue(all(h["context"] == "asteroid" for h in hits))

    def test_search_total_vol6_context(self):
        # "asteroid": no pair/pattern/context hits in Vol 1-5; 1 Vol 6
        # context x 1000 (category, base) pairs x 20 patterns.
        self.assertEqual(fr.search_total("asteroid"), 20_000)

    def test_search_total_restaurant(self):
        # Verified by hand: 1 scoring pair (cat 22 "restaurant finder")
        # x 13,700 + 999 pairs x 1 Vol 3 context ("restaurant") x 20.
        self.assertEqual(fr.search_total("restaurant"), 33_680)

    def test_search_no_match(self):
        # "quokka" is a substring of no category, base target, pattern
        # or context in any volume ("zebra" used to be safe, but Vol 6
        # added it as a context).
        self.assertEqual(fr.search("quokka"), [])
        self.assertEqual(fr.search_total("quokka"), 0)
        self.assertEqual(fr.search(""), [])

    def test_roundtrip_sample(self):
        # resolve() then re-derive the number from its decomposition.
        rnd = random.Random(7)
        for _ in range(500):
            n = rnd.randint(1, 13_700_000)
            vol, c, t, p = fr._decompose(n)
            if vol == 1:
                back = c * 10_000 + t * 20 + p + 1
            elif vol == 2:
                back = 1_000_001 + c * 20_000 + t * 20 + p
            elif vol == 3:
                back = 3_000_001 + c * 10_000 + t * 20 + p
            elif vol == 4:
                back = 4_000_001 + c * 7_000 + t * 20 + p
            elif vol == 5:
                back = 4_700_001 + c * 20_000 + t * 20 + p
            else:
                back = 6_700_001 + c * 70_000 + t * 20 + p
            self.assertEqual(back, n)
            self.assertEqual(fr.resolve(n)["number"], n)


if __name__ == "__main__":
    unittest.main(verbosity=2)
