"""Contract checks for the human-facing adviser, separate from optimization."""

import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from server import Handler, _advice_scenario  # noqa: E402
from simulator import simulate  # noqa: E402


EXAMPLE = [
    {"measure_id": "M7", "district": "Нура"},
    {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M12", "district": None},
    {"measure_id": "M5", "district": "Сарыарка"},
]
NO_MODEL = {"NVIDIA_API_KEY": "", "NVIDIA_MODEL": "",
            "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}


def post_advice(body):
    """Exercise the actual HTTP handler without opening a socket."""
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler = object.__new__(Handler)
    handler.path = "/api/advice"
    handler.headers = {"Content-Length": str(len(raw))}
    handler.rfile = io.BytesIO(raw)
    captured = {}
    handler._json = lambda status, payload: captured.update(status=status, body=payload)
    handler.do_POST()
    return captured["status"], captured["body"]


class HumanAdviceContractTest(unittest.TestCase):
    def test_official_example_has_three_simulated_options_and_real_tradeoff(self):
        with patch.dict(os.environ, NO_MODEL):
            status, answer = post_advice({
                "decisions": EXAMPLE,
                "question": "Почему рекомендация ухудшает Сарыарку?",
            })
        self.assertEqual(status, 200)
        self.assertTrue(answer["valid"])
        options = answer["options"]
        self.assertEqual([item["id"] for item in options],
                         ["current", "one_change", "optimum"])
        self.assertTrue(all(isinstance(item["label"], str) and item["label"]
                            and isinstance(item["tradeoff"], str)
                            for item in options))
        for item in options:
            calculated = simulate(item["decisions"])
            self.assertTrue(calculated["valid"])
            self.assertEqual(item["result"], calculated)
        current, one_change, optimum = (item["result"] for item in options)
        self.assertAlmostEqual(current["score"], 56.54307, places=8)
        self.assertEqual(current["cost"], 95)
        self.assertAlmostEqual(one_change["score"], 57.20556, places=8)
        self.assertEqual(one_change["cost"], 100)
        self.assertAlmostEqual(optimum["score"], 57.236735, places=8)
        self.assertEqual(optimum["cost"], 98)
        self.assertAlmostEqual(
            one_change["districts"]["Сарыарка"]["score"]
            - current["districts"]["Сарыарка"]["score"], -1.2125, places=8)
        self.assertAlmostEqual(
            one_change["districts"]["Нура"]["score"]
            - current["districts"]["Нура"]["score"], 2.02, places=8)
        self.assertIn("Сарыарка", options[1]["tradeoff"])
        self.assertEqual(answer["advice"]["source"], "computed_facts")
        self.assertEqual(answer["advice"]["selected_option"], "none")
        self.assertTrue(answer["advice"]["text"])

    def test_question_does_not_change_calculated_options(self):
        current = simulate(EXAMPLE)
        with patch.dict(os.environ, NO_MODEL):
            nura = _advice_scenario(EXAMPLE, current, "Что станет с Нурой?")
            saryarka = _advice_scenario(EXAMPLE, current,
                                        "Какой ценой улучшается результат для Сарыарки?")
        self.assertEqual(nura["options"], saryarka["options"])

    def test_model_selects_grounded_facts_without_changing_options(self):
        response = {"output": [{"type": "message", "content": [{"type": "output_text",
                     "text": json.dumps({"selected_option": "current",
                                         "fact_ids": ["current_district_2",
                                                      "one_change_district_2"]})}]}]}
        env = {**NO_MODEL, "OPENAI_API_KEY": "unit-test-key",
               "OPENAI_MODEL": "unit-test-model"}
        with patch.dict(os.environ, NO_MODEL):
            offline = _advice_scenario(EXAMPLE, simulate(EXAMPLE),
                                       "Не хочу ухудшать Сарыарку")
        with patch.dict(os.environ, env), \
                patch("explanation._post_json", return_value=response) as mock_post:
            modeled = _advice_scenario(EXAMPLE, simulate(EXAMPLE),
                                       "Не хочу ухудшать Сарыарку")
        self.assertEqual(modeled["options"], offline["options"])
        self.assertEqual(modeled["advice"]["source"], "model")
        self.assertEqual(modeled["advice"]["selected_option"], "current")
        self.assertIn("Сарыарка", modeled["advice"]["text"])
        self.assertNotIn("999", modeled["advice"]["text"])
        sent = mock_post.call_args.args[1]
        self.assertEqual(json.loads(sent["input"])["question"],
                         "Не хочу ухудшать Сарыарку")
        self.assertIn("one_change_district_2", json.loads(sent["input"])["candidates"])
        self.assertFalse(sent["store"])

    def test_invented_model_fact_id_falls_back_to_computed_facts(self):
        response = {"output": [{"type": "message", "content": [{"type": "output_text",
                     "text": json.dumps({"selected_option": "current",
                                         "fact_ids": ["current_district_2", "Score 999"]})}]}]}
        env = {**NO_MODEL, "OPENAI_API_KEY": "unit-test-key",
               "OPENAI_MODEL": "unit-test-model"}
        with patch.dict(os.environ, env), \
                patch("explanation._post_json", return_value=response):
            answer = _advice_scenario(EXAMPLE, simulate(EXAMPLE),
                                      "Не хочу ухудшать Сарыарку")
        self.assertEqual(answer["advice"]["source"], "computed_facts")
        self.assertEqual(answer["advice"]["selected_option"], "none")
        self.assertNotIn("999", answer["advice"]["text"])

    def test_explicit_no_decline_priority_rejects_model_choice_that_hurts_district(self):
        response = {"output": [{"type": "message", "content": [{"type": "output_text",
                     "text": json.dumps({"selected_option": "one_change",
                                         "fact_ids": ["one_change_overview",
                                                      "one_change_district_2"]})}]}]}
        env = {**NO_MODEL, "OPENAI_API_KEY": "unit-test-key",
               "OPENAI_MODEL": "unit-test-model"}
        with patch.dict(os.environ, env), \
                patch("explanation._post_json", return_value=response):
            answer = _advice_scenario(EXAMPLE, simulate(EXAMPLE),
                                      "Не ухудшать Сарыарку")
        self.assertEqual(answer["advice"]["source"], "computed_facts")
        self.assertEqual(answer["advice"]["selected_option"], "none")
        self.assertIn("Сарыарка", answer["advice"]["text"])

    def test_invalid_plan_has_reasons_but_no_score(self):
        with patch.dict(os.environ, NO_MODEL):
            status, answer = post_advice({"decisions": EXAMPLE[:-1],
                                          "question": "Что важнее?"})
        self.assertEqual(status, 400)
        self.assertFalse(answer["valid"])
        self.assertTrue(answer["errors"])
        self.assertNotIn("score", answer)
        self.assertNotIn("options", answer)

    def test_excessive_question_is_rejected_before_model_call(self):
        with patch.dict(os.environ, NO_MODEL):
            status, answer = post_advice({"decisions": EXAMPLE,
                                          "question": "а" * 10000})
        self.assertEqual(status, 400)
        self.assertNotIn("options", answer)


if __name__ == "__main__":
    unittest.main()
