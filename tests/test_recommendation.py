import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from server import _one_change_scenario  # noqa: E402
from simulator import simulate  # noqa: E402


EXAMPLE = [
    {"measure_id": "M7", "district": "Нура"},
    {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M12", "district": None},
    {"measure_id": "M5", "district": "Сарыарка"},
]


class RecommendationTest(unittest.TestCase):
    def test_official_example_one_change_is_recomputed_and_explained(self):
        original = [dict(item) for item in EXAMPLE]
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "", "NVIDIA_MODEL": "",
                                  "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}):
            recommendation = _one_change_scenario(EXAMPLE, simulate(EXAMPLE))
        self.assertEqual(EXAMPLE, original)
        self.assertEqual(recommendation["removed"], [{"measure_id": "M5", "district": "Сарыарка"}])
        self.assertEqual(recommendation["added"], [{"measure_id": "M3", "district": "Нура"}])
        self.assertAlmostEqual(recommendation["current"]["score"], 56.54307, places=8)
        self.assertAlmostEqual(recommendation["proposed"]["score"], 57.20556, places=8)
        self.assertEqual(recommendation["proposed"]["cost"], 100)
        self.assertAlmostEqual(recommendation["score_delta"], 0.66249, places=8)
        self.assertEqual(simulate(recommendation["decisions"]), recommendation["proposed"])
        self.assertEqual(recommendation["explanation"]["source"], "computed_facts")


if __name__ == "__main__":
    unittest.main()
