import json
import os
import runpy
import sys
import tempfile
import unittest
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from src import explanation as explanation_module
from src.explanation import explain, explain_comparison, model_settings
from src.simulator import simulate


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


def saryarka_swap():
    decisions = [
        {"measure_id": "M7", "district": "Нура"},
        {"measure_id": "M8", "district": "Нура"},
        {"measure_id": "M10", "district": "Нура"},
        {"measure_id": "M12", "district": None},
        {"measure_id": "M5", "district": "Сарыарка"},
    ]
    removed = [decisions[-1]]
    added = [{"measure_id": "M3", "district": "Нура"}]
    return simulate(decisions), simulate(decisions[:-1] + added), removed, added


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
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
    module = ModuleType("openai")
    module.OpenAI = MagicMock(return_value=client)
    module.OpenAIError = FakeModelError
    return module, client


class ExplanationTests(unittest.TestCase):
    def setUp(self):
        # Tests must not use a developer's real .env or exported paid API keys.
        dotenv_patch = patch("src.explanation._DOTENV_PATH", Path("/nonexistent/model-test.env"))
        dotenv_patch.start()
        self.addCleanup(dotenv_patch.stop)
        env_patch = patch.dict(os.environ, {name: "" for name in
                                         ("NVIDIA_API_KEY", "NVIDIA_MODEL",
                                          "OPENAI_API_KEY", "OPENAI_MODEL")})
        env_patch.start()
        self.addCleanup(env_patch.stop)

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
                    patch.dict(sys.modules, {"explanation": explanation_module, "openai": sdk}):
                script = runpy.run_path(str(script_path), run_name="check_model_test")
                output = StringIO()
                with redirect_stdout(output):
                    exit_code = script["main"]()
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
                    patch.dict(sys.modules, {"explanation": explanation_module, "openai": sdk}):
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
        self.assertIn("strength_indicator", sent["input"])
        self.assertFalse(sent["store"])

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
        self.assertEqual(sdk.OpenAI.call_args.kwargs["timeout"], 45.0)
        self.assertEqual(sdk.OpenAI.call_args.kwargs["max_retries"], 0)
        sent = client.chat.completions.create.call_args.kwargs
        self.assertEqual(sent["model"], "explicit/model-id")
        self.assertEqual(sent["messages"][0]["role"], "system")
        self.assertEqual(sent["max_tokens"], 256)
        self.assertFalse(sent["stream"])

    def test_nvidia_timeout_falls_back_without_exposing_key(self):
        sdk, _ = fake_nvidia_sdk(error=FakeModelError("secret-key"))
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "secret-key", "NVIDIA_MODEL": "model-id",
                                  "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}), \
                patch.dict(sys.modules, {"openai": sdk}):
            answer = explain(RESULT, diagnostics=True)
        self.assertEqual(answer["source"], "computed_facts")
        self.assertEqual(answer["reason"], "model_unavailable")
        self.assertEqual(answer["error_type"], "FakeModelError")
        self.assertNotIn("secret-key", str(answer))

    def test_nvidia_without_optional_sdk_uses_fallback(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "secret-key", "NVIDIA_MODEL": "model-id",
                                  "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}), \
                patch.dict(sys.modules, {"openai": None}):
            answer = explain(RESULT)
        self.assertEqual(answer["source"], "computed_facts")
        self.assertEqual(answer["reason"], "model_unavailable")

    def test_nvidia_key_without_model_never_calls_api(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "secret-key", "NVIDIA_MODEL": "",
                                  "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}), \
                patch("src.explanation.request.urlopen") as mock_open:
            answer = explain(RESULT)
        self.assertEqual(answer["reason"], "model_not_configured")
        mock_open.assert_not_called()

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

    def test_comparison_offline_always_shows_saryarka_loss(self):
        current, proposed, removed, added = saryarka_swap()
        self.assertTrue(current["valid"] and proposed["valid"])
        loss = current["districts"]["Сарыарка"]["score"] - proposed["districts"]["Сарыарка"]["score"]
        self.assertGreater(loss, 0)
        self.assertEqual(explanation_module._fmt(loss), "1,21")
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "", "NVIDIA_MODEL": "",
                                  "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}):
            answer = explain_comparison(current, proposed, removed, added)
        self.assertEqual(answer["source"], "computed_facts")
        self.assertIn(f"Районный балл Сарыарка снизится на {explanation_module._fmt(loss)}.",
                      answer["text"])

    def test_comparison_model_selection_cannot_hide_saryarka_loss(self):
        current, proposed, removed, added = saryarka_swap()
        loss = current["districts"]["Сарыарка"]["score"] - proposed["districts"]["Сарыарка"]["score"]
        chosen = {"strengths": ["score_change"], "risks": ["weakest"],
                  "tradeoffs": ["budget"]}
        sdk, _ = fake_nvidia_sdk(json.dumps(chosen))
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key", "NVIDIA_MODEL": "test-model"}), \
                patch.dict(sys.modules, {"openai": sdk}):
            answer = explain_comparison(current, proposed, removed, added)
        self.assertEqual(answer["source"], "model")
        self.assertIn(f"Районный балл Сарыарка снизится на {explanation_module._fmt(loss)}.",
                      answer["text"])

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


if __name__ == "__main__":
    unittest.main()
