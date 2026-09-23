import json
import os
import runpy
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from copy import deepcopy
from pathlib import Path
from urllib.error import HTTPError, URLError
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from src import explanation
from src.explanation import explain, explain_comparison, model_settings


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


class FakeModelError(Exception):
    pass


def fake_nvidia_sdk(content=None, error=None):
    client = MagicMock()
    if error is not None:
        client.chat.completions.create.side_effect = error
    else:
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content, refusal=None))]
        )
    module = ModuleType("openai")
    module.OpenAI = MagicMock(return_value=client)
    module.OpenAIError = FakeModelError
    return module, client


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
        sdk, client = fake_nvidia_sdk(error=AssertionError("Unit tests must never call a real model"))
        self.contexts.enter_context(patch.dict(sys.modules, {"openai": sdk}))
        self.no_sdk_network = client.chat.completions.create
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
        sdk, client = fake_nvidia_sdk("```json\n" + json.dumps(chosen) + "\n```")
        env = {"NVIDIA_API_KEY": "test-nvidia-key", "NVIDIA_MODEL": "explicit/model-id",
               "OPENAI_API_KEY": "test-openai-key", "OPENAI_MODEL": "other-model"}
        with patch.dict(os.environ, env), patch.dict(sys.modules, {"openai": sdk}), \
                patch("src.explanation.request.urlopen") as mock_open:
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "model")
        self.assertEqual(answer["provider"], "nvidia")
        self.assertIn("M10, M12", answer["text"])
        self.assertIn("T2 (40,00)", answer["text"])
        self.assertIn("95 из бюджета 100", answer["text"])
        self.assertNotIn("56,54", answer["text"])
        mock_open.assert_not_called()
        self.assertEqual(sdk.OpenAI.call_args.kwargs["base_url"],
                         "https://integrate.api.nvidia.com/v1")
        self.assertEqual(sdk.OpenAI.call_args.kwargs["timeout"], 8)
        self.assertEqual(sdk.OpenAI.call_args.kwargs["max_retries"], 0)
        sent = client.chat.completions.create.call_args.kwargs
        self.assertEqual(sent["model"], "explicit/model-id")
        self.assertEqual(sent["messages"][0]["role"], "system")
        self.assertEqual(sent["max_tokens"], 512)
        self.assertFalse(sent["stream"])
        client.chat.completions.create.assert_called_once()
        client.close.assert_called_once()

    def test_nvidia_sdk_error_falls_back_without_exposing_key(self):
        sdk, _ = fake_nvidia_sdk(error=FakeModelError("secret-key"))
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "secret-key", "NVIDIA_MODEL": "model-id",
                                  "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}), \
                patch.dict(sys.modules, {"openai": sdk}):
            answer = explain(RESULT, diagnostics=True)
        self.assertEqual(answer["source"], "computed_facts")
        self.assertEqual(answer["reason"], "model_unavailable")
        self.assertEqual(answer["error_type"], "FakeModelError")
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
        sdk, client = fake_nvidia_sdk(json.dumps(chosen))
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key", "NVIDIA_MODEL": "explicit/model",
                                  "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}), \
                patch.dict(sys.modules, {"openai": sdk}):
            answer = explain_comparison(current, proposed, removed, added)
        self.assertEqual(answer["source"], "model")
        self.assertIn("M5/Сарыарка на M3/Нура", answer["text"])
        sent = client.chat.completions.create.call_args.kwargs
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
        def attributes(value):
            if isinstance(value, dict):
                return SimpleNamespace(**{key: attributes(item) for key, item in value.items()})
            if isinstance(value, list):
                return [attributes(item) for item in value]
            return value

        for provider, response in cases:
            sdk, client = fake_nvidia_sdk()
            client.chat.completions.create.return_value = attributes(response)
            with self.subTest(provider=provider, response=response), patch.dict(os.environ, {
                    provider.upper() + "_API_KEY": "test-key",
                    provider.upper() + "_MODEL": "test-model"}), \
                    patch("src.explanation.request.urlopen", return_value=FakeResponse(response)), \
                    patch.dict(sys.modules, {"openai": sdk}):
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
                    "OPENAI_API_KEY": secret, "OPENAI_MODEL": "configured-model"}), \
                    patch("src.explanation.request.urlopen", side_effect=error) as mock_open:
                answer = explain(RESULT, diagnostics=True)
            self.assertEqual(answer["source"], "computed_facts")
            self.assertEqual(answer["reason"], "model_unavailable")
            self.assertEqual(answer["provider"], "openai")
            self.assertEqual(answer["model"], "configured-model")
            self.assertEqual(answer["error_code"], code)
            if status is not None:
                self.assertEqual(answer["http_status"], status)
            self.assertNotIn(secret, json.dumps(answer))
            self.assertNotIn("fallback-key", json.dumps(answer))
            mock_open.assert_called_once()

    def test_default_failure_contract_does_not_include_diagnostics(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "model"}), \
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
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"}), \
                patch("src.explanation.request.urlopen", side_effect=[
                    FakeResponse(self.openai_response(json.dumps(self.selection()))),
                    FakeResponse(self.openai_response(json.dumps(chosen))),
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

    def test_openai_transport_does_not_require_openai_sdk(self):
        import builtins
        original_import = builtins.__import__

        def no_sdk(name, *args, **kwargs):
            if name == "openai" or name.startswith("openai."):
                raise AssertionError("OpenAI transport must work without the optional SDK")
            return original_import(name, *args, **kwargs)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"}), \
                patch("builtins.__import__", side_effect=no_sdk), \
                patch("src.explanation.request.urlopen", return_value=FakeResponse(
                    self.openai_response(json.dumps(self.selection())))):
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "model")
        self.assertEqual(answer["provider"], "openai")


    def test_model_settings_reads_env_file_and_process_override(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "# local model settings\n"
                "export NVIDIA_API_KEY='file$key'\n"
                'NVIDIA_MODEL="mistralai/mistral-nemotron"\n'
                "OPENAI_API_KEY=other#key # comment\n"
                "PORT=9000\n", encoding="utf-8")
            with patch("src.explanation._DOTENV_PATH", env_file), \
                    patch.dict(os.environ, {}, clear=True):
                settings = model_settings()
            self.assertEqual(settings["NVIDIA_API_KEY"], "file$key")
            self.assertEqual(settings["NVIDIA_MODEL"], "mistralai/mistral-nemotron")
            self.assertEqual(settings["OPENAI_API_KEY"], "other#key")
            self.assertNotIn("PORT", settings)
            with patch("src.explanation._DOTENV_PATH", env_file), \
                    patch.dict(os.environ, {"NVIDIA_API_KEY": ""}, clear=True):
                self.assertEqual(model_settings()["NVIDIA_API_KEY"], "")


    def test_check_model_reads_env_file_before_preflight(self):
        chosen = {"strengths": ["strength_score"], "risks": ["risk_residual"],
                  "tradeoffs": ["tradeoff_budget"]}
        sdk, _ = fake_nvidia_sdk(json.dumps(chosen))
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "check-model.py"
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("NVIDIA_API_KEY=file-key\nNVIDIA_MODEL=file-model\n", encoding="utf-8")
            with patch("src.explanation._DOTENV_PATH", env_file), \
                    patch.dict(os.environ, {}, clear=True), \
                    patch.dict(sys.modules, {"explanation": explanation, "openai": sdk}):
                script = runpy.run_path(str(script_path), run_name="check_model_test")
                output = StringIO()
                with redirect_stdout(output):
                    exit_code = script["main"]([])
        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["source"], "model")
        self.assertEqual(report["provider"], "nvidia")
        self.assertNotIn("file-key", output.getvalue())


    def test_check_model_comparison_reads_env_file_before_preflight(self):
        chosen = {"strengths": ["score_change"], "risks": ["weakest"],
                  "tradeoffs": ["measure_change"]}
        sdk, _ = fake_nvidia_sdk(json.dumps(chosen))
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "check-model-comparison.py"
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("NVIDIA_API_KEY=file-key\nNVIDIA_MODEL=file-model\n", encoding="utf-8")
            with patch("src.explanation._DOTENV_PATH", env_file), \
                    patch.dict(os.environ, {}, clear=True), \
                    patch.dict(sys.modules, {"explanation": explanation, "openai": sdk}):
                script = runpy.run_path(str(script_path), run_name="check_model_comparison_test")
                output = StringIO()
                with redirect_stdout(output):
                    exit_code = script["main"]()
        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["source"], "model")
        self.assertEqual(report["provider"], "nvidia")
        self.assertNotIn("file-key", output.getvalue())


    def test_comparison_uses_env_file_for_nvidia(self):
        chosen = {"strengths": ["score_change"], "risks": ["weakest"],
                  "tradeoffs": ["measure_change"]}
        sdk, _ = fake_nvidia_sdk(json.dumps(chosen))
        proposed = deepcopy(RESULT)
        proposed.update(score=57.20556, cost=100, remaining_budget=0)
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("NVIDIA_API_KEY=file-key\nNVIDIA_MODEL=file-model\n", encoding="utf-8")
            with patch("src.explanation._DOTENV_PATH", env_file), \
                    patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"openai": sdk}):
                answer = explain_comparison(
                    RESULT, proposed,
                    [{"measure_id": "M5", "district": "Сарыарка"}],
                    [{"measure_id": "M3", "district": "Нура"}])
        self.assertEqual(answer["source"], "model")
        self.assertEqual(answer["provider"], "nvidia")
        self.assertEqual(sdk.OpenAI.call_args.kwargs["api_key"], "file-key")
        self.assertEqual(sdk.OpenAI.return_value.chat.completions.create.call_args.kwargs["model"],
                         "file-model")


    def test_nvidia_without_optional_sdk_uses_fallback(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "secret-key", "NVIDIA_MODEL": "model-id",
                                  "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}), \
                patch.dict(sys.modules, {"openai": None}):
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "computed_facts")
        self.assertEqual(answer["reason"], "model_unavailable")


    def test_nvidia_sdk_errors_do_not_retry_or_fall_through_to_openai(self):
        secret = "never-print-this-provider-key"
        timeout = type("APITimeoutError", (FakeModelError,), {})(secret)
        connection = type("APIConnectionError", (FakeModelError,), {})(secret)
        cases = [(timeout, "timeout", None), (connection, "network_error", None)]
        for status, code in ((401, "authentication"), (429, "rate_limited"),
                             (503, "provider_error")):
            error = FakeModelError(secret)
            error.status_code = status
            cases.append((error, code, status))
        for error, code, status in cases:
            sdk, client = fake_nvidia_sdk(error=error)
            with self.subTest(code=code), patch.dict(os.environ, {
                    "NVIDIA_API_KEY": secret, "NVIDIA_MODEL": "configured-model",
                    "OPENAI_API_KEY": "fallback-key", "OPENAI_MODEL": "fallback-model"}), \
                    patch.dict(sys.modules, {"openai": sdk}):
                answer = explain(RESULT, diagnostics=True)
            self.assertEqual(answer["source"], "computed_facts")
            self.assertEqual(answer["reason"], "model_unavailable")
            self.assertEqual(answer["provider"], "nvidia")
            self.assertEqual(answer["error_type"], type(error).__name__)
            self.assertEqual(answer["error_code"], code)
            self.assertEqual(answer.get("http_status"), status)
            self.assertNotIn(secret, json.dumps(answer))
            self.assertNotIn("fallback-key", json.dumps(answer))
            client.chat.completions.create.assert_called_once()
            client.close.assert_called_once()
            self.no_network.assert_not_called()

    def test_cli_explicit_provider_and_config_never_use_other_provider(self):
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "check-model.py"
        with patch.dict(sys.modules, {"explanation": explanation}):
            script = runpy.run_path(str(script_path), run_name="check_model_test")
        env = {"NVIDIA_API_KEY": "secret-nvidia", "NVIDIA_MODEL": "nvidia-model",
               "OPENAI_API_KEY": "secret-openai", "OPENAI_MODEL": "openai-model"}
        with patch.dict(os.environ, env):
            output = StringIO()
            with redirect_stdout(output):
                exit_code = script["main"](["--provider", "openai", "--check-config"])
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.getvalue())["provider"], "openai")
            self.assertEqual(os.environ["NVIDIA_API_KEY"], "secret-nvidia")
            self.assertNotIn("secret", output.getvalue())
            self.no_network.assert_not_called()
            self.no_sdk_network.assert_not_called()
            chosen = {"strengths": ["strength_score"], "risks": ["risk_residual"],
                      "tradeoffs": ["tradeoff_budget"]}
            comparison = {"strengths": ["score_change"], "risks": ["weakest"],
                          "tradeoffs": ["measure_change"]}
            with patch("src.explanation.request.urlopen", side_effect=[
                    FakeResponse(self.openai_response(json.dumps(chosen))),
                    FakeResponse(self.openai_response(json.dumps(comparison))),
            ]) as transport, redirect_stdout(StringIO()) as result_output:
                exit_code = script["main"](["--provider", "openai", "--scenario", "both"])
            self.assertEqual(exit_code, 0)
            self.assertEqual(transport.call_count, 2)
            self.assertEqual(os.environ["NVIDIA_API_KEY"], "secret-nvidia")
            self.no_sdk_network.assert_not_called()
            results = json.loads(result_output.getvalue())["results"]
            self.assertTrue(all(item["provider"] == "openai" for item in results))
            self.assertEqual(results[1]["proposed_score"], 57.20556)

if __name__ == "__main__":
    unittest.main()
