"""Run one controlled explanation request without printing API credentials.

Set NVIDIA_API_KEY and NVIDIA_MODEL (or OpenAI equivalents) in the shell first.
Exit 0 only if a model selected verified facts for the official example.
"""

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from explanation import explain  # noqa: E402
from simulator import simulate  # noqa: E402


DECISIONS = [
    {"measure_id": "M7", "district": "Нура"},
    {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M12", "district": None},
    {"measure_id": "M5", "district": "Сарыарка"},
]


def main():
    result = simulate(DECISIONS)
    if not result["valid"] or result["cost"] != 95 or abs(result["score"] - 56.54307) > 1e-8:
        raise RuntimeError("Контрольный сценарий не совпал с датасетом")
    explanation = explain(result)
    print(json.dumps({"source": explanation.get("source"),
                      "model": explanation.get("model"),
                      "reason": explanation.get("reason"),
                      "score": result["score"],
                      "cost": result["cost"],
                      "text": explanation.get("text")}, ensure_ascii=False, indent=2))
    return 0 if explanation.get("source") == "model" else 2


if __name__ == "__main__":
    raise SystemExit(main())
