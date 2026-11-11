#!/usr/bin/env python3
"""
Regression tests for the risk engine.

These lock in the behaviour that makes the model defensible, so a future tweak
to a weight cannot silently break it:

    python3 -m unittest tests -v
"""

import unittest

import detect


def ev(t, roll, result="GRANTED", ts=None):
    e = {
        "uid": roll or "DE AD BE EF",
        "roll": roll,
        "name": roll,
        "result": result,
        "attendance": "PRESENT" if result == "GRANTED" else "NOT_RECORDED",
        "t": float(t),
    }
    if ts:
        e["ts"] = ts
    return e


def session(events):
    return detect.add_context(sorted(events, key=lambda e: e["t"]))


class PhysicsRule(unittest.TestCase):
    def test_five_cards_under_half_a_second_is_flagged(self):
        base = detect.Baseline()
        evs = session([ev(0.0, "A"), ev(0.2, "B"), ev(0.4, "C"),
                       ev(0.6, "D"), ev(0.8, "E")])
        incidents = detect.detect(evs, base)
        self.assertTrue(incidents, "a sub-second stack tap must raise an incident")
        self.assertGreaterEqual(incidents[0]["score"], 50)

    def test_impossible_gap_is_the_dominant_signal(self):
        base = detect.Baseline()
        evs = session([ev(0.0, "A"), ev(0.2, "B"), ev(0.4, "C")])
        inc = detect.detect(evs, base)[0]
        gap_row = next(b for b in inc["breakdown"] if b["signal"] == "impossible-gap")
        self.assertEqual(gap_row["value"], 1.0)
        self.assertEqual(gap_row["weight"], detect.WEIGHTS["phys"])

    def test_one_scan_is_not_an_incident(self):
        base = detect.Baseline()
        self.assertEqual(detect.detect(session([ev(0.0, "A")]), base), [])

    def test_two_fast_scans_are_not_an_incident(self):
        base = detect.Baseline()
        self.assertEqual(detect.detect(session([ev(0.0, "A"), ev(0.3, "B")]), base), [])


class CompanionDiscount(unittest.TestCase):
    def test_habitual_pair_is_learned(self):
        base = detect.Baseline()
        for _ in range(5):
            base.learn(session([ev(0.0, "A"), ev(0.8, "B")]))
        self.assertGreater(base.habit(["A", "B"]), 0.5)

    def test_three_friends_stay_below_review(self):
        base = detect.Baseline()
        for _ in range(6):
            base.learn(session([ev(0.0, "A"), ev(0.7, "B"), ev(1.4, "C")]))
        inc = detect.detect(session([ev(0.0, "A"), ev(0.7, "B"), ev(1.4, "C")]),
                            base)[0]
        self.assertLess(inc["score"], 50,
                        "friends walking in together must not reach REVIEW")

    def test_impossible_gaps_are_never_discounted(self):
        base = detect.Baseline()
        for _ in range(6):
            base.learn(session([ev(0.0, "A"), ev(0.2, "B"), ev(0.4, "C")]))
        inc = detect.detect(session([ev(0.0, "A"), ev(0.2, "B"), ev(0.4, "C")]),
                            base)[0]
        gap_row = next(b for b in inc["breakdown"] if b["signal"] == "impossible-gap")
        self.assertEqual(gap_row["points"], gap_row["weight"],
                         "the impossible-gap points must survive any discount")


class Probing(unittest.TestCase):
    def test_several_rejected_cards_raise_probing(self):
        base = detect.Baseline()
        evs = session([ev(i * 2.0, "", result="DENIED") for i in range(4)])
        incidents = detect.detect(evs, base)
        self.assertTrue(any(i.get("kind") == "PROBING" for i in incidents))
        self.assertGreaterEqual(incidents[0]["score"], 70)

    def test_one_rejected_card_is_not_probing(self):
        base = detect.Baseline()
        evs = session([ev(0.0, "", result="DENIED")])
        self.assertEqual(detect.detect(evs, base), [])


class Timestamps(unittest.TestCase):
    def test_logged_time_is_used(self):
        self.assertEqual(detect.stamp(0, {"ts": "2026-11-07T10:15:00"}),
                         "2026-11-07 10:15:00")

    def test_missing_clock_is_labelled_not_invented(self):
        self.assertIn("no clock", detect.stamp(42.0, {"ts": "T+42s"}))


class Payload(unittest.TestCase):
    def test_students_and_percentages(self):
        base = detect.Baseline()
        evs = session([ev(0.0, "A"), ev(0.2, "B"), ev(0.4, "C")])
        payload = detect.build_payload([("s1", evs, detect.detect(evs, base))])
        self.assertEqual(len(payload["students"]), 3)
        for s in payload["students"]:
            self.assertGreaterEqual(s["percent"], 0)
            self.assertLessEqual(s["percent"], 100)
            self.assertEqual(s["total"], 1)

    def test_clear_runs_never_reach_the_payload(self):
        base = detect.Baseline()
        evs = session([ev(0.0, "A"), ev(0.6, "B"), ev(1.2, "C")])
        payload = detect.build_payload([("s1", evs, detect.detect(evs, base))])
        for inc in payload["incidents"]:
            self.assertNotEqual(inc["band"], "CLEAR")

    def test_breakdown_is_complete_and_adds_up(self):
        base = detect.Baseline()
        evs = session([ev(0.0, "A"), ev(0.2, "B"), ev(0.4, "C")])
        inc = detect.detect(evs, base)[0]
        self.assertEqual(len(inc["breakdown"]), 7)
        total = round(sum(b["points"] for b in inc["breakdown"]), 3)
        self.assertAlmostEqual(total, inc["base_score"], places=2)


if __name__ == "__main__":
    unittest.main()
