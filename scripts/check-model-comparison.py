"""Make one controlled model call for the two-plan comparison, without logging keys."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from explanation import explain_comparison  # noqa: E402
from simulator import simulate  # noqa: E402


CURRENT = [
    {"measure_id": "M7", "district": "Нура"},
    {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M12", "district": None},
    {"measure_id": "M5", "district": "Сарыарка"},
]
PROPOSED = CURRENT[:4] + [{"measure_id": "M3", "district": "Нура"}]


def main():
    current, proposed = simulate(CURRENT), simulate(PROPOSED)
    if (not current["valid"] or not proposed["valid"]
            or abs(current["score"] - 56.54307) > 1e-8
            or abs(proposed["score"] - 57.20556) > 1e-8):
        raise RuntimeError("Контрольные расчёты не совпали с датасетом")
    answer = explain_comparison(current, proposed, CURRENT[4:], PROPOSED[4:])
    print(json.dumps({"source": answer.get("source"), "provider": answer.get("provider"),
                      "model": answer.get("model"), "reason": answer.get("reason"),
                      "current_score": current["score"], "proposed_score": proposed["score"],
                      "text": answer.get("text")}, ensure_ascii=False, indent=2))
    return 0 if answer.get("source") == "model" else 2


if __name__ == "__main__":
    raise SystemExit(main())
