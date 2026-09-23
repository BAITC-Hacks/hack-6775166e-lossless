import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from src import explanation
from src.explanation import explain, explain_comparison


RESULT = {
    "valid": True,
    "base_score": 52.55768,
    "score": 56.54307,
    "cost": 95,
    "remaining_budget": 5,
    "districts": {
        "Нура": {"score": 48.1, "indicators": {"T2": 40.0, "S1": 48.0}},
        "Есиль": {"score": 61.2, "indicators": {"T2": 62.0, "S1": 60.0}},
    },
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
    def setUp(self):
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        # Never inherit a developer's paid provider or local .env configuration.
        self.env = self.contexts.enter_context(patch.dict(os.environ, {
            "NVIDIA_API_KEY": "", "NVIDIA_MODEL": "",
            "OPENAI_API_KEY": "", "OPENAI_MODEL": "",
        }))
        self.temp = self.contexts.enter_context(tempfile.TemporaryDirectory())
        self.dotenv = Path(self.temp) / ".env"
        self.contexts.enter_context(patch("src.explanation._DOTENV_PATH", self.dotenv, create=True))
        self.no_network = self.contexts.enter_context(patch(
            "src.explanation.request.urlopen",
            side_effect=AssertionError("Unit tests must never call a real model"),
        ))

    @staticmethod
    def selection():
        return {"strengths": ["strength_indicator"], "risks": ["risk_negative"],
                "tradeoffs": ["tradeoff_budget"]}

    @staticmethod
    def openai_response(output):
        return {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": output}]}]}

    @staticmethod
    def nvidia_response(output):
        return {"choices": [{"finish_reason": "stop", "message": {"content": output}}]}

    def test_offline_fallback_uses_calculated_values(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_MODEL": ""}):
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "computed_facts")
        self.assertIn("56,54", answer["text"])
        self.assertIn("95 из бюджета 100", answer["text"])
        self.assertIn("Нура (48,10)", answer["text"])
        self.assertIn("T2 (40,00)", answer["text"])

    def test_plan_specific_residual_risk_and_budget_tradeoff(self):
        plan = deepcopy(RESULT)
        plan["score"] = 57.236735
        plan["cost"] = 98
        plan["remaining_budget"] = 2
        plan["districts"]["Нура"] = {
            "score": 54.0875, "indicators": {"S1": 40.625, "T2": 49.0}
        }
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "", "NVIDIA_MODEL": "",
                                  "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}):
            answer = explain(plan)
        self.assertIn("Нура (54,09)", answer["text"])
        self.assertIn("S1 (40,62)", answer["text"])
        self.assertIn("98 из бюджета 100; остаток 2", answer["text"])
        self.assertNotIn("T2 (40,00)", answer["text"])

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
        self.assertIn("T2 (40,00)", answer["text"])
        self.assertNotIn("56,54", answer["text"])
        sent = json.loads(mock_open.call_args.args[0].data)
        self.assertEqual(sent["model"], "test-model")
        self.assertEqual(sent["max_output_tokens"], 512)
        self.assertEqual(sent["text"]["format"]["type"], "json_schema")
        self.assertTrue(sent["text"]["format"]["strict"])
        schema = sent["text"]["format"]["schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), {"strengths", "risks", "tradeoffs"})
        self.assertIn("strength_indicator", schema["properties"]["strengths"]["items"]["enum"])
        mock_open.assert_called_once()
        self.assertIn("strength_indicator", sent["input"])
        self.assertFalse(sent["store"])

    def test_configured_gpt56_sol_uses_bounded_fact_selection(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "gpt-5.6-sol"}), \
                patch("src.explanation.request.urlopen", return_value=FakeResponse(
                    self.openai_response(json.dumps(self.selection())))) as mock_open:
            answer = explain(RESULT)
        sent = json.loads(mock_open.call_args.args[0].data)
        self.assertEqual(answer["source"], "model")
        self.assertEqual(sent["model"], "gpt-5.6-sol")
        self.assertEqual(sent["reasoning"], {"effort": "none"})
        self.assertEqual(sent["max_output_tokens"], 512)

    def test_fabricated_number_is_not_displayed(self):
        response = {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": '{"strengths":["Score 999"],"risks":["risk_residual"],"tradeoffs":["tradeoff_budget"]}'}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"}), \
                patch("src.explanation.request.urlopen", return_value=FakeResponse(response)):
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "computed_facts")
        self.assertNotIn("999", answer["text"])

    def test_nvidia_has_priority_and_selects_only_verified_facts(self):
        chosen = {"strengths": ["strength_synergy"], "risks": ["risk_negative"],
                  "tradeoffs": ["tradeoff_lag"]}
        response = {"choices": [{"message": {"content": json.dumps(chosen)}}]}
        env = {"NVIDIA_API_KEY": "test-nvidia-key", "NVIDIA_MODEL": "explicit/model-id",
               "OPENAI_API_KEY": "test-openai-key", "OPENAI_MODEL": "other-model"}
        with patch.dict(os.environ, env), \
                patch("src.explanation.request.urlopen", return_value=FakeResponse(response)) as mock_open:
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "model")
        self.assertEqual(answer["provider"], "nvidia")
        self.assertIn("M10, M12", answer["text"])
        self.assertIn("T2 (40,00)", answer["text"])
        self.assertIn("95 из бюджета 100", answer["text"])
        self.assertNotIn("56,54", answer["text"])
        req = mock_open.call_args.args[0]
        sent = json.loads(req.data)
        self.assertEqual(req.full_url, "https://integrate.api.nvidia.com/v1/chat/completions")
        self.assertEqual(sent["model"], "explicit/model-id")
        self.assertEqual(sent["max_tokens"], 512)
        self.assertFalse(sent["stream"])
        mock_open.assert_called_once()
        self.assertEqual(sent["messages"][0]["role"], "system")
        self.assertEqual(mock_open.call_args.kwargs["timeout"], 8)

    def test_nvidia_timeout_falls_back_without_exposing_key(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "secret-key", "NVIDIA_MODEL": "model-id",
                                  "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}), \
                patch("src.explanation.request.urlopen", side_effect=TimeoutError("slow")):
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "computed_facts")
        self.assertEqual(answer["reason"], "model_unavailable")
        self.assertNotIn("secret-key", str(answer))

    def test_nvidia_key_without_model_never_calls_api(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "secret-key", "NVIDIA_MODEL": "",
                                  "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}), \
                patch("src.explanation.request.urlopen") as mock_open:
            answer = explain(RESULT)
        self.assertEqual(answer["reason"], "model_not_configured")
        mock_open.assert_not_called()

    def test_incomplete_nvidia_configuration_uses_configured_openai(self):
        with patch.dict(os.environ, {
                "NVIDIA_API_KEY": "nvidia-without-model", "NVIDIA_MODEL": "",
                "OPENAI_API_KEY": "openai-key", "OPENAI_MODEL": "openai-model"}), \
                patch("src.explanation.request.urlopen", return_value=FakeResponse(
                    self.openai_response(json.dumps(self.selection())))) as mock_open:
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "model")
        self.assertEqual(answer["provider"], "openai")
        self.assertEqual(mock_open.call_args.args[0].full_url, "https://api.openai.com/v1/responses")
        mock_open.assert_called_once()

    def test_comparison_model_receives_both_calculations_and_only_selects_facts(self):
        current = deepcopy(RESULT)
        proposed = deepcopy(RESULT)
        proposed.update(score=57.20556, cost=100, remaining_budget=0)
        proposed["districts"]["Нура"]["score"] = 50.1
        proposed["districts"]["Нура"]["indicators"]["S1"] = 50.0
        removed = [{"measure_id": "M5", "district": "Сарыарка"}]
        added = [{"measure_id": "M3", "district": "Нура"}]
        chosen = {"strengths": ["score_change"], "risks": ["more_cost"],
                  "tradeoffs": ["measure_change"]}
        response = {"choices": [{"message": {"content": json.dumps(chosen)}}]}
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key", "NVIDIA_MODEL": "explicit/model",
                                  "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}), \
                patch("src.explanation.request.urlopen", return_value=FakeResponse(response)) as mock_open:
            answer = explain_comparison(current, proposed, removed, added)
        self.assertEqual(answer["source"], "model")
        self.assertIn("M5/Сарыарка на M3/Нура", answer["text"])
        sent = json.loads(mock_open.call_args.args[0].data)
        evidence = json.loads(sent["messages"][1]["content"])["calculated_evidence"]
        self.assertEqual(evidence["current"]["deltas"], current["deltas"])
        self.assertEqual(evidence["current"]["contributions"], current["contributions"])
        self.assertEqual(evidence["proposed"]["score"], proposed["score"])

    def test_comparison_offline_uses_verified_values(self):
        current = deepcopy(RESULT)
        proposed = deepcopy(RESULT)
        proposed.update(score=57.20556, cost=100, remaining_budget=0)
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "", "NVIDIA_MODEL": "",
                                  "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}):
            answer = explain_comparison(current, proposed,
                                        [{"measure_id": "M5", "district": "Сарыарка"}],
                                        [{"measure_id": "M3", "district": "Нура"}])
        self.assertEqual(answer["source"], "computed_facts")
        self.assertIn("56,54 до 57,21", answer["text"])

    def test_markdown_fenced_json_still_requires_verified_fact_ids(self):
        chosen = {"strengths": ["strength_indicator"], "risks": ["risk_negative"],
                  "tradeoffs": ["tradeoff_budget"]}
        fenced = "```json\n" + json.dumps(chosen) + "\n```"
        response = {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": fenced}]}]}
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "", "NVIDIA_MODEL": "",
                                  "OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"}), \
                patch("src.explanation.request.urlopen", return_value=FakeResponse(response)):
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "model")
        self.assertIn("+10,00", answer["text"])

    def test_malformed_or_unverified_selections_never_become_model_answers(self):
        invalid_outputs = {
            "malformed_json": "{not json}",
            "root_array": "[]",
            "null": "null",
            "missing_section": json.dumps({"strengths": ["strength_indicator"]}),
            "empty_section": json.dumps({**self.selection(), "risks": []}),
            "too_many_facts": json.dumps({**self.selection(), "strengths": [
                "strength_indicator", "strength_score", "strength_synergy"]}),
            "duplicate_fact": json.dumps({**self.selection(), "risks": [
                "risk_negative", "risk_negative"]}),
            "unknown_fact": json.dumps({**self.selection(), "risks": ["risk_invented"]}),
            "wrong_section": json.dumps({**self.selection(), "risks": ["strength_score"]}),
            "wrong_value_type": json.dumps({**self.selection(), "risks": "risk_negative"}),
            "non_string_id": json.dumps({**self.selection(), "risks": [12]}),
            "object_id": json.dumps({**self.selection(), "risks": [{"id": "risk_negative"}]}),
            "extra_text": json.dumps({**self.selection(), "summary": "Score 999"}),
            "text_outside_fence": "Summary\n```json\n" + json.dumps(self.selection()) + "\n```",
        }
        for name, output in invalid_outputs.items():
            with self.subTest(name=name), patch.dict(os.environ, {
                    "OPENAI_API_KEY": "secret-test-key", "OPENAI_MODEL": "test-model"}), \
                    patch("src.explanation.request.urlopen", return_value=FakeResponse(
                        self.openai_response(output))) as mock_open:
                answer = explain(RESULT, diagnostics=True)
            self.assertEqual(answer["source"], "computed_facts")
            self.assertEqual(answer["reason"], "model_unavailable")
            self.assertEqual(answer["error_code"], "invalid_model_output")
            self.assertIn("56,54", answer["text"])
            self.assertNotIn("999", answer["text"])
            self.assertNotIn("secret-test-key", str(answer))
            mock_open.assert_called_once()

    def test_incomplete_or_refused_provider_response_is_not_accepted(self):
        selected = json.dumps(self.selection())
        incomplete = self.openai_response(selected)
        incomplete["status"] = "incomplete"
        refusal = self.openai_response(selected)
        refusal["output"][0]["content"].append({"type": "refusal", "refusal": "No"})
        cases = [
            ("openai", incomplete),
            ("openai", refusal),
            ("openai", {"status": "completed", "output": []}),
            ("openai", {"status": "completed", "output": "not-an-array"}),
            ("nvidia", {"choices": [{"finish_reason": "length", "message": {"content": selected}}]}),
            ("nvidia", {"choices": [{"finish_reason": "stop", "message": {
                "content": selected, "refusal": "No"}}]}),
            ("nvidia", {"choices": []}),
            ("nvidia", {"choices": [{"finish_reason": "stop", "message": {"content": None}}]}),
            ("nvidia", []),
        ]
        for provider, response in cases:
            with self.subTest(provider=provider, response=response), patch.dict(os.environ, {
                    provider.upper() + "_API_KEY": "test-key",
                    provider.upper() + "_MODEL": "test-model"}), \
                    patch("src.explanation.request.urlopen", return_value=FakeResponse(response)):
                answer = explain(RESULT, diagnostics=True)
            self.assertEqual(answer["source"], "computed_facts")
            self.assertEqual(answer["error_code"], "invalid_model_output")

    def test_provider_errors_are_diagnosed_without_retries_or_secrets(self):
        from http.client import IncompleteRead

        secret = "never-print-this-provider-key"
        cases = [
            (TimeoutError(secret), "timeout", None),
            (URLError(TimeoutError(secret)), "timeout", None),
            (URLError(secret), "network_error", None),
            (IncompleteRead(secret.encode(), 100), "network_error", None),
            (HTTPError("https://example.invalid/" + secret, 401, secret, {}, None), "authentication", 401),
            (HTTPError("https://example.invalid/" + secret, 429, secret, {}, None), "rate_limited", 429),
            (HTTPError("https://example.invalid/" + secret, 503, secret, {}, None), "provider_error", 503),
        ]
        for error, code, status in cases:
            with self.subTest(code=code, status=status), patch.dict(os.environ, {
                    "NVIDIA_API_KEY": secret, "NVIDIA_MODEL": "configured-model",
                    "OPENAI_API_KEY": "fallback-key", "OPENAI_MODEL": "fallback-model"}), \
                    patch("src.explanation.request.urlopen", side_effect=error) as mock_open:
                answer = explain(RESULT, diagnostics=True)
            self.assertEqual(answer["source"], "computed_facts")
            self.assertEqual(answer["reason"], "model_unavailable")
            self.assertEqual(answer["provider"], "nvidia")
            self.assertEqual(answer["model"], "configured-model")
            self.assertEqual(answer["error_code"], code)
            if status is not None:
                self.assertEqual(answer["http_status"], status)
            self.assertNotIn(secret, json.dumps(answer))
            self.assertNotIn("fallback-key", json.dumps(answer))
            mock_open.assert_called_once()

    def test_default_failure_contract_does_not_include_diagnostics(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "secret", "NVIDIA_MODEL": "model"}), \
                patch("src.explanation.request.urlopen", side_effect=TimeoutError("secret")):
            answer = explain(RESULT)
        self.assertEqual(set(answer), {"text", "source", "reason"})

    def test_explanations_never_mutate_the_calculated_inputs(self):
        current = deepcopy(RESULT)
        proposed = deepcopy(RESULT)
        proposed.update(score=57.20556, cost=100, remaining_budget=0)
        removed = [{"measure_id": "M5", "district": "Сарыарка"}]
        added = [{"measure_id": "M3", "district": "Нура"}]
        before = deepcopy((current, proposed, removed, added))
        chosen = {"strengths": ["score_change"], "risks": ["more_cost"],
                  "tradeoffs": ["measure_change"]}
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key", "NVIDIA_MODEL": "test-model"}), \
                patch("src.explanation.request.urlopen", side_effect=[
                    FakeResponse(self.nvidia_response(json.dumps(self.selection()))),
                    FakeResponse(self.nvidia_response(json.dumps(chosen))),
                ]) as mock_open:
            self.assertEqual(explain(current)["source"], "model")
            self.assertEqual(explain_comparison(current, proposed, removed, added)["source"], "model")
        self.assertEqual((current, proposed, removed, added), before)
        self.assertEqual(mock_open.call_count, 2)

    def test_invalid_result_does_not_call_model(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key", "NVIDIA_MODEL": "test-model"}):
            answer = explain({"valid": False, "errors": ["Too many measures"]})
            comparison = explain_comparison(RESULT, {"valid": False}, [], [])
        self.assertEqual(answer["reason"], "invalid_result")
        self.assertEqual(comparison["reason"], "invalid_result")
        self.no_network.assert_not_called()

    def test_dotenv_settings_are_loaded_without_export_or_execution(self):
        # Removing the four blank variables exposes .env while retaining test isolation.
        with patch.dict(os.environ, {}, clear=True):
            self.dotenv.write_text(
                "# local provider\n"
                "export NVIDIA_API_KEY='file-key'\n"
                'NVIDIA_MODEL="file/model"\n'
                "OPENAI_API_KEY=$(never-execute-this)\n"
                "UNRELATED_KEY=ignore-me\n",
                encoding="utf-8",
            )
            settings = explanation.model_settings()
            self.assertEqual(settings["NVIDIA_API_KEY"], "file-key")
            self.assertEqual(settings["NVIDIA_MODEL"], "file/model")
            self.assertEqual(settings["OPENAI_API_KEY"], "$(never-execute-this)")
            self.assertNotIn("UNRELATED_KEY", settings)
            self.assertNotIn("NVIDIA_API_KEY", os.environ)
        self.no_network.assert_not_called()

    def test_explicit_empty_environment_overrides_dotenv(self):
        self.dotenv.write_text("NVIDIA_API_KEY=file-key\nNVIDIA_MODEL=file-model\n", encoding="utf-8")
        settings = explanation.model_settings()
        self.assertEqual(settings["NVIDIA_API_KEY"], "")
        self.assertEqual(settings["NVIDIA_MODEL"], "")
        self.assertEqual(explain(RESULT)["reason"], "model_not_configured")
        self.no_network.assert_not_called()

    def test_bad_dotenv_encoding_preserves_process_configuration(self):
        self.dotenv.write_bytes(b"NVIDIA_API_KEY=\xff\xfe")
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "environment-key", "NVIDIA_MODEL": "model"}):
            settings = explanation.model_settings()
        self.assertEqual(settings["NVIDIA_API_KEY"], "environment-key")
        self.assertEqual(settings["NVIDIA_MODEL"], "model")

    def test_nvidia_transport_does_not_require_openai_sdk(self):
        import builtins
        original_import = builtins.__import__

        def no_sdk(name, *args, **kwargs):
            if name == "openai" or name.startswith("openai."):
                raise AssertionError("NVIDIA transport must work without the optional SDK")
            return original_import(name, *args, **kwargs)

        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key", "NVIDIA_MODEL": "test-model"}), \
                patch("builtins.__import__", side_effect=no_sdk), \
                patch("src.explanation.request.urlopen", return_value=FakeResponse(
                    self.nvidia_response(json.dumps(self.selection())))):
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "model")
        self.assertEqual(answer["provider"], "nvidia")


if __name__ == "__main__":
    unittest.main()
