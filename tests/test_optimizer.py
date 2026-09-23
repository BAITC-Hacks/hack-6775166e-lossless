"""Check nonlinear portfolio search against an independent score implementation."""

import itertools
import unittest

from benchmark import optimizer_benchmark as benchmark
from src.optimizer import best_one_change, optimize


def payload_for(case):
    return {
        "rows": case["rows"],
        "population_percent": case["population_percent"],
        "weights_percent": benchmark.WEIGHTS,
        "indicators": benchmark.INDICATORS,
        "measures": benchmark.MEASURES,
        "districts": benchmark.DISTRICTS,
        "budget": 100,
        "decisions": 5,
        "horizon_quarters": 8,
    }


def benchmark_choices(choices):
    return [(item["id"], item["district"]) for item in choices]


def fixed_oracle(case, fixed):
    """Enumerate completions using the benchmark's separate Score function."""
    fixed_ids = {mid for mid, _ in fixed}
    best = float("-inf")
    for extra_ids in itertools.combinations(
        (mid for mid in benchmark.ORDER if mid not in fixed_ids), 5 - len(fixed)
    ):
        locations = [(None,) if benchmark.MEASURES[mid][3] else range(5)
                     for mid in extra_ids]
        for districts in itertools.product(*locations):
            choices = list(fixed) + list(zip(extra_ids, districts))
            if benchmark.validate(choices) is None:
                best = max(best, benchmark.score(case, choices))
    return best


class ConditionalOptimizerTest(unittest.TestCase):
    def test_unrestricted_optimum_matches_known_oracle(self):
        case = benchmark.scenarios()[0]
        result = optimize(payload_for(case))
        self.assertAlmostEqual(result["score"], 57.236735, places=8)
        self.assertIsNone(benchmark.validate(benchmark_choices(result["choices"])))

    def test_fixed_decisions_match_independent_oracle_on_three_scenarios(self):
        fixed = [("M7", 4), ("M8", 4)]
        required = [{"id": mid, "district": district} for mid, district in fixed]
        scenarios = benchmark.scenarios()
        for case in (scenarios[0], scenarios[2], scenarios[3]):
            with self.subTest(scenario=case["name"]):
                result = optimize(payload_for(case), required_choices=required)
                choices = benchmark_choices(result["choices"])
                self.assertTrue(set(fixed).issubset(choices))
                self.assertIsNone(benchmark.validate(choices))
                self.assertAlmostEqual(result["score"], benchmark.score(case, choices), places=8)
                self.assertAlmostEqual(result["score"], fixed_oracle(case, fixed), places=8)

    def test_one_change_is_best_valid_neighbor(self):
        case = benchmark.scenarios()[0]
        payload = payload_for(case)
        current = [{"id": mid, "district": district} for mid, district in benchmark.CHECK_EXAMPLE]
        result = best_one_change(payload, current)
        actual = benchmark_choices(result["choices"])
        self.assertIsNone(benchmark.validate(actual))
        self.assertEqual(len(set(actual) - set(benchmark.CHECK_EXAMPLE)), 1)
        neighbor_best = benchmark.score(case, list(benchmark.CHECK_EXAMPLE))
        for omitted in range(5):
            fixed = list(benchmark.CHECK_EXAMPLE)
            fixed.pop(omitted)
            for mid in benchmark.ORDER:
                for district in ((None,) if benchmark.MEASURES[mid][3] else range(5)):
                    candidate = fixed + [(mid, district)]
                    if benchmark.validate(candidate) is None:
                        neighbor_best = max(neighbor_best, benchmark.score(case, candidate))
        self.assertAlmostEqual(result["score"], neighbor_best, places=8)
        self.assertAlmostEqual(result["score_delta"],
                               neighbor_best - benchmark.score(case, list(benchmark.CHECK_EXAMPLE)), places=8)
        self.assertEqual(result["previous_cost"], 95)
        self.assertEqual(result["cost"], 100)
        self.assertEqual(result["cost_delta"], 5)
        self.assertEqual(len(result["removed"]), 1)
        self.assertEqual(len(result["added"]), 1)

    def test_global_optimum_has_no_improving_one_change(self):
        payload = payload_for(benchmark.scenarios()[0])
        optimum = optimize(payload)
        result = best_one_change(payload, optimum["choices"])
        self.assertEqual(result["choices"], optimum["choices"])
        self.assertEqual(result["score_delta"], 0)
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["added"], [])

    def test_rejects_invalid_fixed_decisions(self):
        payload = payload_for(benchmark.scenarios()[0])
        invalid = (
            [{"id": "M7", "district": None}],
            [{"id": "M12", "district": 4}],
            [{"id": "M7", "district": 4}, {"id": "M7", "district": 3}],
            [{"id": "M1", "district": 4}, {"id": "M3", "district": 0}],
            [{"id": "M4", "district": 4}, {"id": "M7", "district": 4}],
        )
        for required in invalid:
            with self.subTest(required=required), self.assertRaises(ValueError):
                optimize(payload, required_choices=required)


if __name__ == "__main__":
    unittest.main()
