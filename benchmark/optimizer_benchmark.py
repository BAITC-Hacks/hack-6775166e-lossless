"""Deterministic stress scenarios and an exact oracle for the HackAlem simulator.

Standard library only. This is a benchmark of the specified toy scoring model,
not a prediction of real municipal outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "task" / "Датасет районов.docx"
SOURCE_SHA256 = "434128bfede06afe4d115c13a82fce874a3cf494a24679e1b227b88d4a8aba86"
SEED = 20260923
DISTRICTS = ("Есиль", "Алматы", "Сарыарка", "Байконур", "Нура")
INDICATORS = ("T1", "T2", "E1", "E2", "S1", "S2", "B1", "B2", "C1", "C2")
WEIGHTS = (10, 10, 9, 11, 11, 11, 9, 9, 10, 10)  # /100
BASE_POP = (27, 24, 20, 13, 16)  # /100
BASE_ROWS = (
    (45, 62, 68, 72, 48, 55, 78, 60, 75, 70),
    (40, 75, 50, 55, 60, 65, 62, 52, 50, 60),
    (50, 70, 42, 40, 62, 68, 58, 55, 45, 55),
    (52, 68, 55, 50, 58, 60, 52, 58, 55, 58),
    (55, 40, 45, 65, 38, 35, 55, 50, 60, 50),
)
# id: (category, cost, lag, citywide, full effects)
MEASURES = {
    "M1": ("T", 18, 2, False, {"T1": 6, "T2": 9}),
    "M2": ("T", 22, 2, True, {"T1": 4, "B2": 3}),
    "M3": ("T", 30, 4, False, {"T1": 16, "T2": 20, "E2": 4}),
    "M4": ("E", 15, 2, False, {"E1": 12, "E2": 3, "B1": 2}),
    "M5": ("E", 25, 3, False, {"E2": 14, "C1": 4}),
    "M6": ("E", 20, 4, True, {"E1": 5, "E2": 3}),
    "M7": ("S", 24, 3, False, {"S1": 16}),
    "M8": ("S", 20, 3, False, {"S2": 14}),
    "M9": ("S", 10, 1, False, {"S1": 3, "S2": 3, "B1": 3}),
    "M10": ("B", 12, 1, False, {"B1": 12, "B2": 2}),
    "M11": ("B", 10, 1, False, {"B2": 12, "T1": -2}),
    "M12": ("C", 14, 1, True, {"C2": 5}),
    "M13": ("C", 28, 4, False, {"C1": 18, "E2": 2}),
    "M14": ("C", 16, 1, True, {"C1": 5, "C2": 2}),
}
ORDER = tuple(MEASURES)
CITY = None
CHECK_EXAMPLE = (("M7", 4), ("M8", 4), ("M10", 4), ("M12", CITY), ("M5", 2))


def scenarios(seed: int = SEED) -> list[dict]:
    """Fixed cases target critical thresholds, clipping, and unequal need."""
    rng = random.Random(seed)
    jitter = [[max(0, min(100, value + rng.randint(-8, 8))) for value in row]
              for row in BASE_ROWS]
    threshold = [list(row) for row in BASE_ROWS]
    for d, k, value in ((4, 4, 39), (4, 5, 39), (2, 3, 39), (1, 8, 39)):
        threshold[d][k] = value
    saturation = [list(row) for row in BASE_ROWS]
    for d in range(5):
        saturation[d][2] = 97
        saturation[d][6] = 98
        saturation[d][9] = 99
    return [
        {"name": "official", "rows": BASE_ROWS, "population_percent": BASE_POP},
        {"name": "seeded_jitter", "rows": jitter, "population_percent": BASE_POP},
        {"name": "critical_boundary", "rows": threshold, "population_percent": BASE_POP},
        {"name": "saturation", "rows": saturation, "population_percent": BASE_POP},
    ]


def validate(choices: list[tuple[str, int | None]]) -> str | None:
    if len(choices) != 5:
        return "exactly five decisions required"
    ids = [m for m, _ in choices]
    if len(set(ids)) != 5:
        return "measure IDs must be unique"
    if any(m not in MEASURES for m in ids):
        return "unknown measure"
    if sum(MEASURES[m][1] for m in ids) > 100:
        return "budget exceeded"
    if any(sum(MEASURES[m][0] == category for m in ids) > 2 for category in "TESBC"):
        return "more than two measures in category"
    for m, d in choices:
        if MEASURES[m][3] and d is not CITY:
            return f"{m} is citywide"
        if not MEASURES[m][3] and (not isinstance(d, int) or d not in range(5)):
            return f"{m} needs district 0..4"
    selected = dict(choices)
    if "M1" in selected and "M3" in selected:
        return "M1/M3 conflict"
    for a, b in (("M4", "M7"), ("M5", "M13")):
        if a in selected and b in selected and selected[a] == selected[b]:
            return f"{a}/{b} district conflict"
    return None


def score(scenario: dict, choices: list[tuple[str, int | None]]) -> float:
    error = validate(choices)
    if error:
        raise ValueError(error)
    # Eighths are exact: full effect * (8 - lag)/8.
    state = [[8 * v for v in row] for row in scenario["rows"]]
    selected = dict(choices)
    for m, district in choices:
        _, _, lag, citywide, effects = MEASURES[m]
        for d in (range(5) if citywide else (district,)):
            for indicator, value in effects.items():
                state[d][INDICATORS.index(indicator)] += value * (8 - lag)
    for a, b, indicator in (("M1", "M2", "T1"), ("M10", "M12", "B1"),
                            ("M5", "M6", "E2")):
        if a in selected and b in selected:
            state[selected[a]][INDICATORS.index(indicator)] += 16
    districts = []
    critical = 0
    for row in state:
        clipped = [max(0, min(800, v)) for v in row]
        critical += sum(v < 320 for v in clipped)
        districts.append(sum(w * v for w, v in zip(WEIGHTS, clipped)) / 800)
    avg = sum(p * d for p, d in zip(scenario["population_percent"], districts)) / 100
    return 0.7 * avg + 0.3 * min(districts) - critical


def exact_oracle(scenario: dict) -> tuple[float, list[tuple[str, int | None]], int]:
    """Enumerate all feasible portfolios; strict tie break follows catalog order."""
    best = float("-inf")
    winner = []
    evaluated = 0
    # Pre-filter IDs before assigning districts; citywide actions have one choice.
    for ids in itertools.combinations(ORDER, 5):
        if sum(MEASURES[m][1] for m in ids) > 100:
            continue
        if "M1" in ids and "M3" in ids:
            continue
        if any(sum(MEASURES[m][0] == c for m in ids) > 2 for c in "TESBC"):
            continue
        locations = [(CITY,) if MEASURES[m][3] else range(5) for m in ids]
        for ds in itertools.product(*locations):
            choices = list(zip(ids, ds))
            if validate(choices):
                continue
            evaluated += 1
            value = score(scenario, choices)
            if value > best + 1e-10:
                best, winner = value, choices
    return best, winner, evaluated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--scenario", default="official", choices=[s["name"] for s in scenarios()])
    parser.add_argument("--optimizer", nargs="+", help="command reading scenario JSON on stdin and returning JSON choices")
    parser.add_argument("--oracle", action="store_true", help="compute exact best portfolio")
    parser.add_argument("--self-test", action="store_true", help="check source constants, rules and invariants")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("self-test: OK")
        return
    case = next(s for s in scenarios(args.seed) if s["name"] == args.scenario)
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256, "source DOCX changed; recheck transcribed constants"
    assert len(DISTRICTS) == len(case["rows"]) == 5
    assert sum(case["population_percent"]) == 100
    assert all(len(row) == 10 and all(0 <= x <= 100 for x in row) for row in case["rows"])
    if case["name"] == "official":
        assert abs(baseline_score(case) - 52.55768) < 1e-8
        assert abs(score(case, list(CHECK_EXAMPLE)) - 56.54307) < 1e-8
    payload = {"schema": 1, "name": case["name"], "seed": args.seed,
               "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
               "districts": DISTRICTS, "indicators": INDICATORS, "weights_percent": WEIGHTS,
               "population_percent": case["population_percent"], "rows": case["rows"],
               "measures": MEASURES, "budget": 100, "decisions": 5, "horizon_quarters": 8}
    if not args.optimizer and not args.oracle:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    result = {"scenario": case["name"], "seed": args.seed,
              "baseline_score": baseline_score(case), "source_sha256": payload["source_sha256"]}
    if args.oracle:
        started = time.perf_counter()
        best, choices, count = exact_oracle(case)
        result["oracle"] = {"score": best, "choices": choices,
                            "feasible_portfolios": count, "seconds": time.perf_counter() - started}
    if args.optimizer:
        started = time.perf_counter()
        proc = subprocess.run(args.optimizer, input=json.dumps(payload, ensure_ascii=False),
                              text=True, capture_output=True, timeout=120, check=True)
        elapsed = time.perf_counter() - started
        raw = json.loads(proc.stdout)
        choices = [(x["id"], x.get("district")) for x in raw["choices"]]
        problem = validate(choices)
        result["optimizer"] = {"valid": problem is None, "error": problem,
                               "seconds": elapsed, "choices": choices}
        if problem is None:
            result["optimizer"]["score"] = score(case, choices)
            if args.oracle:
                result["optimizer"]["regret"] = best - result["optimizer"]["score"]
    print(json.dumps(result, ensure_ascii=False, indent=2))


def baseline_score(scenario: dict) -> float:
    rows = scenario["rows"]
    districts = [sum(w * v for w, v in zip(WEIGHTS, row)) / 100 for row in rows]
    avg = sum(p * d for p, d in zip(scenario["population_percent"], districts)) / 100
    critical = sum(v < 40 for row in rows for v in row)
    return 0.7 * avg + 0.3 * min(districts) - critical


def self_test() -> None:
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256, "source DOCX changed; recheck transcribed constants"
    case = scenarios()[0]
    assert abs(baseline_score(case) - 52.55768) < 1e-8
    assert abs(score(case, list(CHECK_EXAMPLE)) - 56.54307) < 1e-8
    assert score(case, list(CHECK_EXAMPLE)) == score(case, list(reversed(CHECK_EXAMPLE)))
    assert scenarios(SEED) == scenarios(SEED)
    assert scenarios(SEED)[1] != scenarios(SEED + 1)[1]
    for test in scenarios():
        assert len(test["rows"]) == 5
        assert sum(test["population_percent"]) == 100
        assert all(len(row) == 10 and all(0 <= x <= 100 for x in row) for row in test["rows"])
    assert validate(list(CHECK_EXAMPLE)) is None
    assert validate(list(CHECK_EXAMPLE[:-1])) == "exactly five decisions required"
    assert validate([("M1", 0), ("M3", 1), ("M8", 4), ("M10", 4), ("M12", None)]) == "M1/M3 conflict"
    assert validate([("M4", 4), ("M7", 4), ("M8", 3), ("M10", 4), ("M12", None)]) == "M4/M7 district conflict"
    assert validate([("M5", 4), ("M13", 4), ("M8", 3), ("M10", 4), ("M12", None)]) == "M5/M13 district conflict"
    assert validate([("M7", 4), ("M8", 4), ("M10", 4), ("M12", 0), ("M5", 2)]) == "M12 is citywide"
    assert validate([("M7", 4), ("M8", 4), ("M10", 4), ("M12", None), ("M5", None)]) == "M5 needs district 0..4"


if __name__ == "__main__":
    main()
