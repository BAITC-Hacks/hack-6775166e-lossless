"""Exercise the browser's HTTP contract without credentials or model traffic."""

import json
import os
import sys
import threading
import unittest
from contextlib import ExitStack
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import explanation  # noqa: E402
import server  # noqa: E402
from simulator import simulate  # noqa: E402


EXAMPLE = [
    {"measure_id": "M7", "district": "Нура"},
    {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M12", "district": None},
    {"measure_id": "M5", "district": "Сарыарка"},
]


def choices(items):
    return {(item["measure_id"], item["district"]) for item in items}


class QuietHandler(server.Handler):
    def log_message(self, *_):
        pass


class HTTPIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contexts = ExitStack()
        cls.addClassCleanup(cls.contexts.close)
        cls.contexts.enter_context(patch.dict(os.environ, {
            "NVIDIA_API_KEY": "", "NVIDIA_MODEL": "",
            "OPENAI_API_KEY": "", "OPENAI_MODEL": "",
        }))
        # Never even read the checkout's .env or inherit a paid provider.
        cls.contexts.enter_context(patch.object(explanation, "_read_model_env_file", return_value={}))
        cls.contexts.enter_context(patch.object(
            explanation.request, "urlopen",
            side_effect=AssertionError("HTTP integration tests must not contact a model"),
        ))
        for selector in ("_select_with_openai", "_select_with_nvidia"):
            cls.contexts.enter_context(patch.object(
                explanation, selector,
                side_effect=AssertionError("Unexpected model selection in offline HTTP test"),
            ))
        server._optimal_scenario.cache_clear()
        cls.addClassCleanup(server._optimal_scenario.cache_clear)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.addClassCleanup(cls.httpd.server_close)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.thread.join, 5)
        cls.addClassCleanup(cls.httpd.shutdown)

    def request(self, route, decisions=None, **fields):
        connection = HTTPConnection(*self.httpd.server_address, timeout=20)
        try:
            if decisions is None:
                connection.request("GET", route)
            else:
                connection.request(
                    "POST", route,
                    body=json.dumps({"decisions": decisions, **fields}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
            response = connection.getresponse()
            self.assertEqual(response.getheader("Content-Type"), "application/json; charset=utf-8")
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_catalogue_has_common_baseline(self):
        status, result = self.request("/api/catalog")
        self.assertEqual(status, 200)
        self.assertAlmostEqual(result["base_score"], 52.55768, places=8)
        self.assertEqual(result["budget"], 100)
        self.assertEqual(len(result["districts"]), 5)
        self.assertEqual(len(result["measures"]), 14)

    def test_official_simulation_matches_engine_and_has_offline_explanation(self):
        status, result = self.request("/api/simulate", EXAMPLE)
        self.assertEqual(status, 200)
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["score"], 56.54307, places=8)
        self.assertEqual(result["cost"], 95)
        self.assertEqual(result.pop("explanation")["source"], "computed_facts")
        self.assertEqual(result, simulate(EXAMPLE))

    def test_invalid_plans_have_reasons_without_score_or_model_calls(self):
        with patch.object(explanation, "explain") as explain, \
                patch.object(explanation, "explain_comparison") as compare:
            for route, expected_status in (("/api/simulate", 200), ("/api/recommend-change", 400)):
                with self.subTest(route=route):
                    status, result = self.request(route, EXAMPLE[:4])
                    self.assertEqual(status, expected_status)
                    self.assertFalse(result["valid"])
                    self.assertTrue(result["errors"])
                    self.assertNotIn("score", result)
                    self.assertNotIn("explanation", result)
            explain.assert_not_called()
            compare.assert_not_called()

    def test_one_change_preserves_four_choices_and_returns_recomputed_plan(self):
        status, result = self.request("/api/recommend-change", EXAMPLE)
        self.assertEqual(status, 200)
        self.assertTrue(result["valid"])
        self.assertEqual(result["removed"], [{"measure_id": "M5", "district": "Сарыарка"}])
        self.assertEqual(result["added"], [{"measure_id": "M3", "district": "Нура"}])
        self.assertEqual(len(choices(EXAMPLE) & choices(result["decisions"])), 4)
        self.assertAlmostEqual(result["current"]["score"], 56.54307, places=8)
        self.assertAlmostEqual(result["proposed"]["score"], 57.20556, places=8)
        self.assertEqual(result["proposed"]["cost"], 100)
        self.assertAlmostEqual(result["score_delta"], 0.66249, places=8)
        self.assertEqual(result["cost_delta"], 5)
        self.assertEqual(result["current"], simulate(EXAMPLE))
        self.assertEqual(result["proposed"], simulate(result["decisions"]))
        self.assertEqual(result["explanation"]["source"], "computed_facts")

    def test_global_optimum_is_recomputed_and_has_no_improving_one_change(self):
        status, result = self.request("/api/optimize")
        self.assertEqual(status, 200)
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["score"], 57.236735, places=8)
        self.assertEqual(result["cost"], 98)
        self.assertEqual(choices(result["decisions"]), {
            ("M2", None), ("M3", "Нура"), ("M8", "Нура"),
            ("M9", "Нура"), ("M14", None),
        })
        self.assertEqual(result["optimization"]["proven_optimal_for"], "official_dataset")
        self.assertEqual(result["explanation"]["source"], "computed_facts")
        calculated = simulate(result["decisions"])
        self.assertEqual({key: result[key] for key in calculated}, calculated)
        status, recommendation = self.request("/api/recommend-change", result["decisions"])
        self.assertEqual(status, 200)
        self.assertEqual(recommendation["score_delta"], 0)
        self.assertEqual(recommendation["cost_delta"], 0)
        self.assertEqual(recommendation["removed"], [])
        self.assertEqual(recommendation["added"], [])
        self.assertEqual(recommendation["decisions"], result["decisions"])
        self.assertEqual(recommendation["current"], recommendation["proposed"])

    def test_http_routes_propagate_model_selection_without_changing_calculations(self):
        def select_known_facts(facts, _key, _model, _evidence):
            return {section: [next(iter(candidates))] for section, candidates in facts.items()}

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-placeholder", "OPENAI_MODEL": "test-model"}), \
                patch.object(explanation, "_select_with_openai", side_effect=select_known_facts) as selector:
            status, result = self.request("/api/simulate", EXAMPLE)
            self.assertEqual(status, 200)
            self.assertEqual(result["explanation"]["source"], "model")
            self.assertEqual(result["explanation"]["provider"], "openai")
            self.assertIn("56,54", result["explanation"]["text"])
            self.assertEqual(result["score"], simulate(EXAMPLE)["score"])
            status, recommendation = self.request("/api/recommend-change", EXAMPLE)
            self.assertEqual(status, 200)
            self.assertEqual(recommendation["explanation"]["source"], "model")
            self.assertEqual(recommendation["explanation"]["provider"], "openai")
            self.assertIn("57,21", recommendation["explanation"]["text"])
            self.assertEqual(recommendation["proposed"], simulate(recommendation["decisions"]))
            self.assertEqual(selector.call_count, 2)

    def test_advice_returns_three_verified_options_for_a_human_priority(self):
        question = "Не хочу ухудшать Сарыарку"
        with patch.object(explanation, "advise", wraps=explanation.advise) as advise, \
                patch.object(explanation, "explain") as explain, \
                patch.object(explanation, "explain_comparison") as compare:
            status, result = self.request("/api/advice", EXAMPLE, question=question)
            advise.assert_called_once()
            self.assertEqual(advise.call_args.args[0], question)
            explain.assert_not_called()
            compare.assert_not_called()
        self.assertEqual(status, 200)
        self.assertTrue(result["valid"])
        self.assertEqual([option["id"] for option in result["options"]],
                         ["current", "one_change", "optimum"])
        for option, score, cost in zip(result["options"],
                                       (56.54307, 57.20556, 57.236735), (95, 100, 98)):
            with self.subTest(option=option["id"]):
                self.assertAlmostEqual(option["result"]["score"], score, places=8)
                self.assertEqual(option["result"]["cost"], cost)
                self.assertEqual(option["result"], simulate(option["decisions"]))
                self.assertTrue(option["label"])
                self.assertTrue(option["tradeoff"])
        self.assertEqual(result["options"][0]["decisions"], EXAMPLE)
        self.assertIn("Сарыарка", result["options"][1]["tradeoff"])
        self.assertEqual(result["advice"]["source"], "computed_facts")
        self.assertEqual(result["advice"]["selected_option"], "none")
        self.assertTrue(result["advice"]["text"])

    def test_advice_rejects_invalid_plan_or_question_before_optimization_and_ai(self):
        cases = [(EXAMPLE[:4], "Что улучшить?"),
                 *((EXAMPLE, question) for question in (None, "", "   ", "а" * 501, 37, []))]
        with patch.object(explanation, "advise") as advise, \
                patch.object(server, "_one_change_scenario") as one_change, \
                patch.object(server, "_optimal_scenario") as optimum:
            for decisions, question in cases:
                with self.subTest(plan_size=len(decisions), question_type=type(question).__name__,
                                  question_length=len(question) if isinstance(question, str) else None):
                    status, result = self.request("/api/advice", decisions, question=question)
                    self.assertEqual(status, 400)
                    self.assertTrue(result.get("error") or result.get("errors"))
                    self.assertNotIn("score", result)
                    self.assertNotIn("options", result)
                    self.assertNotIn("advice", result)
            advise.assert_not_called()
            one_change.assert_not_called()
            optimum.assert_not_called()


if __name__ == "__main__":
    unittest.main()
