"""Verify real AI explanations without printing credentials or provider errors.

No arguments preserves the single-plan check. Each requested scenario makes at
most one model request; configuration inspection makes none. NVIDIA uses the optional OpenAI SDK.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from time import perf_counter


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from explanation import explain, explain_comparison, model_settings  # noqa: E402
from simulator import simulate  # noqa: E402


DECISIONS = [
    {"measure_id": "M7", "district": "Нура"},
    {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M12", "district": None},
    {"measure_id": "M5", "district": "Сарыарка"},
]
PROPOSED = DECISIONS[:4] + [{"measure_id": "M3", "district": "Нура"}]


@contextmanager
def selected_provider(provider):
    """An explicit provider must never fall through to another provider."""
    names = () if provider == "auto" else tuple(
        f"{other}_{suffix}"
        for other in ("NVIDIA" if provider == "openai" else "OPENAI",)
        for suffix in ("API_KEY", "MODEL")
    )
    previous = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            # Empty values also prevent a worktree .env from restoring them.
            os.environ[name] = ""
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _safe_settings():
    """Select metadata only; model_settings() itself contains secret values."""
    settings = model_settings()
    for provider in ("nvidia", "openai"):
        prefix = provider.upper()
        if settings.get(f"{prefix}_API_KEY") and settings.get(f"{prefix}_MODEL"):
            return {"provider": provider, "model": settings[f"{prefix}_MODEL"],
                    "configured": True, "reason": None}
    return {"provider": None, "model": None,
            "configured": False, "reason": "model_not_configured"}


def _controls():
    current, proposed = simulate(DECISIONS), simulate(PROPOSED)
    for result, score, cost in ((current, 56.54307, 95), (proposed, 57.20556, 100)):
        if (not result["valid"] or result["cost"] != cost
                or abs(result["base_score"] - 52.55768) > 1e-8
                or abs(result["score"] - score) > 1e-8):
            raise RuntimeError("Контрольный сценарий не совпал с датасетом")
    return current, proposed


def _run(scenario, current, proposed, settings):
    started = perf_counter()
    if scenario == "single":
        answer = explain(current, diagnostics=True)
        controls = {"base_score": current["base_score"],
                    "score": current["score"], "cost": current["cost"]}
    else:
        answer = explain_comparison(
            current, proposed, DECISIONS[4:], PROPOSED[4:], diagnostics=True
        )
        controls = {"base_score": current["base_score"],
                    "current_score": current["score"], "current_cost": current["cost"],
                    "proposed_score": proposed["score"], "proposed_cost": proposed["cost"]}
    latency_ms = round((perf_counter() - started) * 1000, 1)
    # Do not include exception messages, HTTP bodies, headers, URLs or env values.
    error_type = answer.get("error_type")
    if not isinstance(error_type, str) or not re.fullmatch(r"[A-Za-z_]{1,64}", error_type):
        error_type = None
    http_status = answer.get("http_status")
    if type(http_status) is not int or not 100 <= http_status <= 599:
        http_status = None
    error_code = answer.get("error_code")
    if not isinstance(error_code, str) or error_code not in {
        "authentication", "rate_limited", "timeout", "invalid_model_output",
        "provider_error", "network_error",
    }:
        error_code = None
    return {
        "scenario": scenario,
        "source": answer.get("source"),
        "provider": (answer.get("provider") if answer.get("source") == "model"
                     else answer.get("provider") or settings.get("provider")),
        "model": (answer.get("model") if answer.get("source") == "model"
                  else answer.get("model") or settings.get("model")),
        "reason": answer.get("reason"),
        "error_code": error_code,
        "error_type": error_type,
        "http_status": http_status,
        **controls,
        "latency_ms": latency_ms,
        "elapsed_seconds": round(latency_ms / 1000, 3),
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "text": answer.get("text"),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("auto", "openai", "nvidia"), default="auto",
                        help="auto follows app priority; an explicit choice disables the other provider")
    parser.add_argument("--scenario", choices=("single", "comparison", "both"), default="single",
                        help="one request per scenario, no retries")
    parser.add_argument("--check-config", action="store_true",
                        help="show safe configuration metadata without a network request")
    args = parser.parse_args(argv)
    with selected_provider(args.provider):
        settings = _safe_settings()
        if args.check_config:
            print(json.dumps(settings, ensure_ascii=False, indent=2))
            return 0 if settings["configured"] else 2
        current, proposed = _controls()
        scenarios = ("single", "comparison") if args.scenario == "both" else (args.scenario,)
        results = [_run(scenario, current, proposed, settings) for scenario in scenarios]
        output = {"results": results} if args.scenario == "both" else results[0]
        print(json.dumps(output, ensure_ascii=False, indent=2))
        expected_provider = settings["provider"] if args.provider == "auto" else args.provider
        return 0 if expected_provider and all(
            row["source"] == "model" and row["provider"] == expected_provider
            for row in results
        ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
