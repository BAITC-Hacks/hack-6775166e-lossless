"""Make one grounded human-priority model call without printing credentials."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from server import _advice_scenario  # noqa: E402
from simulator import simulate  # noqa: E402


CURRENT = [
    {"measure_id": "M7", "district": "Нура"},
    {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M12", "district": None},
    {"measure_id": "M5", "district": "Сарыарка"},
]


def main():
    result = simulate(CURRENT)
    if not result["valid"] or abs(result["score"] - 56.54307) > 1e-8:
        raise RuntimeError("Контрольный расчёт не совпал с датасетом")
    answer = _advice_scenario(
        CURRENT, result, "Почему замена улучшает Score, но ухудшает Сарыарку?")
    advice = answer["advice"]
    print(json.dumps({
        "source": advice["source"], "provider": advice.get("provider"),
        "model": advice.get("model"), "reason": advice.get("reason"),
        "selected_option": advice["selected_option"],
        "scores": {option["id"]: option["result"]["score"]
                   for option in answer["options"]},
        "text": advice["text"],
    }, ensure_ascii=False, indent=2))
    return 0 if advice["source"] == "model" else 2


if __name__ == "__main__":
    raise SystemExit(main())
