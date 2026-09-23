"""Exact portfolio optimizer for the fixed HackAlem rule set.

Reads a benchmark scenario JSON from stdin; emits {"choices": [{"id", "district"}]}.
The rows and population are taken from input. No benchmark code or answer is imported.
Scores use integer eighths, so ties and critical thresholds are exact.
"""

from __future__ import annotations

import itertools
import json
import sys


def _required_locations(payload, required_choices):
    """Validate fixed decisions and map their IDs to district indexes."""
    if not isinstance(required_choices, (list, tuple)):
        raise ValueError("Required choices must be a list")
    required = {}
    measures = payload["measures"]
    districts = payload["districts"]
    for choice in required_choices:
        if not isinstance(choice, dict):
            raise ValueError("Required choices must be objects")
        mid = choice.get("id")
        if mid not in measures or mid in required:
            raise ValueError("Required measure IDs must be known and unique")
        location = choice.get("district")
        city = measures[mid][3]
        if city and location is not None:
            raise ValueError(f"{mid} is citywide")
        if not city and (type(location) is not int or location not in range(len(districts))):
            raise ValueError(f"{mid} needs a district index")
        required[mid] = location
    if len(required) > payload["decisions"]:
        raise ValueError("Too many required choices")
    if sum(measures[mid][1] for mid in required) > payload["budget"]:
        raise ValueError("Required choices exceed the budget")
    if "M1" in required and "M3" in required:
        raise ValueError("M1/M3 conflict")
    for first, second in (("M4", "M7"), ("M5", "M13")):
        if first in required and second in required and required[first] == required[second]:
            raise ValueError(f"{first}/{second} district conflict")
    if any(sum(measures[mid][0] == category for mid in required) > 2
           for category in ("T", "E", "S", "B", "C")):
        raise ValueError("More than two required choices in one category")
    return required


def optimize(payload, required_choices=()):
    """Return an exact optimum, optionally preserving fixed choices.

    The objective is the full nonlinear city Score. A fixed choice is an
    {"id": "M7", "district": 4} object; citywide district is null.
    """
    rows = payload["rows"]
    pop = payload["population_percent"]
    weights = payload["weights_percent"]
    indicators = payload["indicators"]
    measures = payload["measures"]
    order = tuple(measures)
    districts = payload["districts"]
    assert len(rows) == len(pop) == len(districts) == 5
    assert len(weights) == len(indicators) == 10
    assert payload["decisions"] == 5 and payload["horizon_quarters"] == 8
    assert sum(pop) == 100
    assert all(len(row) == 10 for row in rows)
    required = _required_locations(payload, required_choices)
    idx = {name: i for i, name in enumerate(indicators)}
    base = [8 * value for row in rows for value in row]
    # Every (measure, location) becomes a sparse vector of exact eighths.
    options = {}
    for mid in order:
        cat, cost, lag, city, effects = measures[mid]
        locations = (required[mid],) if mid in required else ((None,) if city else tuple(range(5)))
        options[mid] = []
        for d in locations:
            changes = []
            for target in range(5) if city else (d,):
                for key, amount in effects.items():
                    changes.append((target * 10 + idx[key], amount * (8 - lag)))
            options[mid].append((d, tuple(changes)))

    best = -10**30
    winner = None
    budget = payload["budget"]
    for ids in itertools.combinations(order, 5):
        if not set(required).issubset(ids):
            continue
        if sum(measures[mid][1] for mid in ids) > budget:
            continue
        if "M1" in ids and "M3" in ids:
            continue
        if any(sum(measures[mid][0] == category for mid in ids) > 2 for category in ("T", "E", "S", "B", "C")):
            continue
        has_12 = "M12" in ids
        has_2 = "M2" in ids
        has_6 = "M6" in ids
        for picks in itertools.product(*(options[mid] for mid in ids)):
            chosen = {mid: item[0] for mid, item in zip(ids, picks)}
            if "M4" in chosen and "M7" in chosen and chosen["M4"] == chosen["M7"]:
                continue
            if "M5" in chosen and "M13" in chosen and chosen["M5"] == chosen["M13"]:
                continue
            state = base.copy()
            for _, changes in picks:
                for position, delta in changes:
                    state[position] += delta
            if has_2 and "M1" in chosen:
                state[chosen["M1"] * 10 + idx["T1"]] += 16
            if has_12 and "M10" in chosen:
                state[chosen["M10"] * 10 + idx["B1"]] += 16
            if has_6 and "M5" in chosen:
                state[chosen["M5"] * 10 + idx["E2"]] += 16
            critical = 0
            district_values = []
            for d in range(5):
                start = d * 10
                value = 0
                for k in range(10):
                    cell = max(0, min(800, state[start + k]))
                    critical += cell < 320
                    value += weights[k] * cell
                district_values.append(value)
            scaled_score = 7 * sum(p * value for p, value in zip(pop, district_values)) + 300 * min(district_values) - 800000 * critical
            if scaled_score > best:
                best = scaled_score
                winner = [{"id": mid, "district": location} for mid, (location, _) in zip(ids, picks)]
    if winner is None:
        raise ValueError("No feasible portfolio")
    return {"choices": winner, "score": best / 800000, "method": "exact_integer_enumeration"}


def best_one_change(payload, current_choices):
    """Find the best valid plan reachable by replacing one decision.

    Every candidate preserves four of the five original (measure, district)
    choices. The current plan is returned if no strictly better neighbor exists.
    """
    if len(current_choices) != payload["decisions"]:
        raise ValueError("A complete current portfolio is required")
    current = optimize(payload, required_choices=current_choices)
    best = current
    for omitted in range(len(current_choices)):
        fixed = current_choices[:omitted] + current_choices[omitted + 1:]
        candidate = optimize(payload, required_choices=fixed)
        if candidate["score"] > best["score"]:
            best = candidate
    old = {(choice["id"], choice.get("district")) for choice in current_choices}
    new = {(choice["id"], choice["district"]) for choice in best["choices"]}
    costs = payload["measures"]
    previous_cost = sum(costs[mid][1] for mid, _ in old)
    recommended_cost = sum(costs[mid][1] for mid, _ in new)
    return {**best, "previous_score": current["score"],
            "score_delta": round(best["score"] - current["score"], 8),
            "previous_cost": previous_cost, "cost": recommended_cost,
            "cost_delta": recommended_cost - previous_cost,
            "removed": [{"id": mid, "district": district} for mid, district in sorted(old - new)],
            "added": [{"id": mid, "district": district} for mid, district in sorted(new - old)]}


def main():
    payload = json.load(sys.stdin)
    if "current_choices" in payload and "required_choices" in payload:
        raise ValueError("Use either current_choices or required_choices")
    if "current_choices" in payload:
        result = best_one_change(payload, payload["current_choices"])
    else:
        result = optimize(payload, payload.get("required_choices", ()))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
