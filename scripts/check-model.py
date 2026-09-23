"""Run one controlled explanation request without printing API credentials.

Set a provider key and model in this checkout's .env or the shell.
Exit 0 only if a model selected verified facts for the official example.
"""

import json
import sys
from pathlib import Path
from time import monotonic


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from explanation import explain, model_settings  # noqa: E402
from simulator import simulate  # noqa: E402


DECISIONS = [
    {"measure_id": "M7", "district": "Нура"},
    {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M12", "district": None},
    {"measure_id": "M5", "district": "Сарыарка"},
]


def main():
    settings = model_settings()
    if not ((settings["NVIDIA_API_KEY"] and settings["NVIDIA_MODEL"])
            or (settings["OPENAI_API_KEY"] and settings["OPENAI_MODEL"])):
        print("Для проверки задайте пару ключа и модели в .env или окружении.", file=sys.stderr)
        return 2
    result = simulate(DECISIONS)
    if not result["valid"] or result["cost"] != 95 or abs(result["score"] - 56.54307) > 1e-8:
        raise RuntimeError("Контрольный сценарий не совпал с датасетом")
    started = monotonic()
    explanation = explain(result, diagnostics=True)
    print(json.dumps({"source": explanation.get("source"),
                      "provider": explanation.get("provider"),
                      "model": explanation.get("model"),
                      "reason": explanation.get("reason"),
                      "error_type": explanation.get("error_type"),
                      "http_status": explanation.get("http_status"),
                      "elapsed_seconds": round(monotonic() - started, 3),
                      "score": result["score"],
                      "cost": result["cost"],
                      "text": explanation.get("text")}, ensure_ascii=False, indent=2))
    return 0 if explanation.get("source") == "model" else 2


if __name__ == "__main__":
    raise SystemExit(main())
