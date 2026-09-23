import json
import os
import unittest
from unittest.mock import patch

from src.explanation import explain


RESULT = {
    "valid": True,
    "base_score": 52.55768,
    "score": 56.54307,
    "cost": 95,
    "remaining_budget": 5,
    "districts": {"Нура": {"score": 48.1}, "Есиль": {"score": 61.2}},
    "deltas": {"Нура": {"S1": 10.0, "T1": -1.5}, "Есиль": {"S1": 0.0}},
    "contributions": [{"measure_id": "M7", "lag_factor": 0.625}],
    "applied_synergies": [{"measures": ["M10", "M12"], "district": "Нура", "indicator": "B1", "bonus": 2}],
    "critical_count": 1,
}


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return json.dumps(self.value).encode()


class ExplanationTests(unittest.TestCase):
    def test_offline_fallback_uses_calculated_values(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_MODEL": ""}):
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "computed_facts")
        self.assertIn("56,54", answer["text"])
        self.assertIn("95 из бюджета 100", answer["text"])
        self.assertIn("Нура", answer["text"])

    def test_model_can_only_select_existing_facts(self):
        selected = {"strengths": ["strength_indicator"], "risks": ["risk_negative"],
                    "tradeoffs": ["tradeoff_budget"]}
        response = {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(selected)}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"}), \
                patch("src.explanation.request.urlopen", return_value=FakeResponse(response)) as mock_open:
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "model")
        self.assertIn("+10,00", answer["text"])
        self.assertNotIn("56,54", answer["text"])
        sent = json.loads(mock_open.call_args.args[0].data)
        self.assertEqual(sent["model"], "test-model")
        self.assertIn("strength_indicator", sent["input"])
        self.assertFalse(sent["store"])

    def test_fabricated_number_is_not_displayed(self):
        response = {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": '{"strengths":["Score 999"],"risks":["risk_weakest"],"tradeoffs":["tradeoff_budget"]}'}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"}), \
                patch("src.explanation.request.urlopen", return_value=FakeResponse(response)):
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "computed_facts")
        self.assertNotIn("999", answer["text"])


if __name__ == "__main__":
    unittest.main()
