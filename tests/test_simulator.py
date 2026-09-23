import itertools
import json
import unittest

from src.simulator import catalog, simulate


EXAMPLE = [
    {"measure_id": "M7", "district": "Нура"},
    {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M12", "district": None},
    {"measure_id": "M5", "district": "Сарыарка"},
]


def pick(*items):
    return [{"measure_id": measure, "district": district} for measure, district in items]


class SimulatorTest(unittest.TestCase):
    def test_catalog_and_base_score(self):
        data = catalog()
        self.assertEqual(len(data["districts"]), 5)
        self.assertEqual(len(data["measures"]), 14)
        self.assertEqual(data["budget"], 100)
        self.assertAlmostEqual(data["base_score"], 52.55768, places=8)
        self.assertAlmostEqual(sum(value["population_share"] for value in data["districts"].values()), 1)
        json.dumps(data, ensure_ascii=False)

    def test_document_example(self):
        result = simulate(EXAMPLE)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["cost"], 95)
        self.assertEqual(result["remaining_budget"], 5)
        self.assertAlmostEqual(result["score"], 56.54307, places=8)
        self.assertAlmostEqual(result["population_weighted_average"], 58.0776, places=8)
        self.assertAlmostEqual(result["districts"]["Нура"]["score"], 52.9625, places=8)
        self.assertEqual(result["critical_count"], 0)
        self.assertEqual(result["applied_synergies"], [{"measures": ["M10", "M12"], "district": "Нура", "indicator": "B1", "bonus": 2}])
        self.assertEqual(result["deltas"]["Нура"]["B1"], 12.5)
        json.dumps(result, ensure_ascii=False)

    def test_order_independent(self):
        expected = simulate(EXAMPLE)
        for order in itertools.permutations(EXAMPLE):
            self.assertEqual(simulate(list(order)), expected)

    def test_invalid_has_reason_without_score(self):
        cases = [
            EXAMPLE[:4],
            EXAMPLE + [EXAMPLE[0]],
            EXAMPLE[:4] + [EXAMPLE[0]],
            EXAMPLE[:4] + [{"measure_id": "M99", "district": "Нура"}],
            EXAMPLE[:4] + [{"measure_id": "M5", "district": "Москва"}],
            EXAMPLE[:3] + [{"measure_id": "M12", "district": "Нура"}, EXAMPLE[4]],
            pick(("M1", "Нура"), ("M2", None), ("M3", "Есиль"), ("M10", "Нура"), ("M12", None)),
            pick(("M4", "Нура"), ("M7", "Нура"), ("M10", "Нура"), ("M12", None), ("M9", "Нура")),
            pick(("M5", "Нура"), ("M13", "Нура"), ("M10", "Нура"), ("M12", None), ("M9", "Нура")),
            pick(("M3", "Нура"), ("M5", "Сарыарка"), ("M7", "Нура"), ("M8", "Нура"), ("M13", "Есиль")),
            pick(("M7", "Нура"), ("M8", "Нура"), ("M9", "Нура"), ("M10", "Нура"), ("M12", None)),
        ]
        for decisions in cases:
            with self.subTest(decisions=decisions):
                result = simulate(decisions)
                self.assertFalse(result["valid"])
                self.assertTrue(result["errors"])
                self.assertNotIn("score", result)
                self.assertAlmostEqual(result["base_score"], 52.55768, places=8)
        self.assertAlmostEqual(simulate(None)["base_score"], 52.55768, places=8)

    def test_scope_and_same_district_conflicts(self):
        result = simulate(pick(("M4", "Сарыарка"), ("M7", "Нура"), ("M10", "Нура"), ("M12", None), ("M9", "Нура")))
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["deltas"]["Есиль"]["C2"], 4.375)
        self.assertEqual(result["deltas"]["Сарыарка"]["E1"], 9)
        self.assertEqual(result["deltas"]["Нура"]["E1"], 0)

    def test_multiple_synergies_without_lag(self):
        decisions = pick(("M1", "Нура"), ("M2", None), ("M5", "Сарыарка"), ("M6", None), ("M12", None))
        result = simulate(decisions)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(len(result["applied_synergies"]), 2)
        self.assertEqual(result["deltas"]["Нура"]["T1"], 4.5 + 3 + 2)
        self.assertEqual(result["deltas"]["Сарыарка"]["E2"], 8.75 + 1.5 + 2)


if __name__ == "__main__":
    unittest.main()
