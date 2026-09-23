"""Run one controlled explanation request without printing API credentials.

Set NVIDIA_API_KEY and NVIDIA_MODEL in the shell first.
Exit 0 only if an NVIDIA model selected verified facts for the official example.
"""

import json
import os
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
    if not os.getenv("NVIDIA_API_KEY") or not os.getenv("NVIDIA_MODEL"):
        print("Для проверки NVIDIA задайте NVIDIA_API_KEY и NVIDIA_MODEL.", file=sys.stderr)
        return 2
    result = simulate(DECISIONS)
    if not result["valid"] or result["cost"] != 95 or abs(result["score"] - 56.54307) > 1e-8:
        raise RuntimeError("Контрольный сценарий не совпал с датасетом")
    explanation = explain(result)
    print(json.dumps({"source": explanation.get("source"),
                      "provider": explanation.get("provider"),
                      "model": explanation.get("model"),
                      "reason": explanation.get("reason"),
                      "score": result["score"],
                      "cost": result["cost"],
                      "text": explanation.get("text")}, ensure_ascii=False, indent=2))
    return 0 if (explanation.get("source") == "model"
                 and explanation.get("provider") == "nvidia") else 2


if __name__ == "__main__":
    raise SystemExit(main())
