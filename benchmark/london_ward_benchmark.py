"""External-data stress case for the toy optimizer; not an Astana estimate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
import time
from pathlib import Path

from optimizer_benchmark import (INDICATORS, MEASURES, SOURCE, SOURCE_SHA256,
                                 WEIGHTS, baseline_score, exact_oracle, score,
                                 validate)

HERE = Path(__file__).resolve().parent
RAW = HERE / "ward-profiles-excel-version.csv"
RAW_SHA256 = "1a3b61c3dd6a47472e31bbeab04338d4feba00fa25eaea422257e235d7603620"
RAW_URL = "https://data.london.gov.uk/download/f33fb38c-cb37-48e3-8298-84c0d3cc5a6c/772d2d64-e8c6-46cb-86f9-e52b4c7851bc/ward-profiles-excel-version.csv"
WARD_CODES = ("E05000026", "E05000027", "E05000028", "E05000029", "E05000030")
# These are ten genuine London measurements, not equivalents of the Astana
# indicators with the same slot names. Reversed fields: lower raw value better.
FIELDS = (
    ("T1", "Cars per household - 2011", True),
    ("T2", "Average Public Transport Accessibility score - 2014", False),
    ("E1", "% area that is open space - 2014", False),
    ("E2", "% travel by bicycle to work - 2011", False),
    ("S1", "Average GCSE capped point scores - 2014", False),
    ("S2", "Male life expectancy -2009-13", False),
    ("B1", "Crime rate - 2014/15", True),
    ("B2", "Number Killed or Seriously Injured on the roads - 2014", True),
    ("C1", "Median Household income estimate (2012/13)", False),
    ("C2", "Claimant rate of key out-of-work benefits (working age client group) (2014)", True),
)


def number(value: str) -> float | None:
    if not value or value.strip().lower() in {"n/a", "na", "-"}:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def scenario() -> tuple[dict, dict]:
    raw = RAW.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != RAW_SHA256:
        raise ValueError(f"London CSV SHA-256 changed: {actual}")
    records = list(csv.DictReader(io.StringIO(raw.decode("latin-1"))))
    wards = [r for r in records if r["New code"].startswith("E050")]
    selected = [next(r for r in wards if r["New code"] == code) for code in WARD_CODES]
    if len({r["New code"] for r in selected}) != 5:
        raise ValueError("Five distinct wards required")
    population = [number(r["Population - 2015"]) for r in selected]
    if any(v is None or v <= 0 for v in population):
        raise ValueError("Selected ward population missing")
    denomin = sum(population)
    shares = [100 * v / denomin for v in population]
    if abs(sum(shares) - 100) > 1e-9:
        raise AssertionError("Population weights do not sum to 100")
    rows = [[] for _ in selected]
    mapping = []
    for slot, column, reverse in FIELDS:
        valid = [v for r in wards if (v := number(r[column])) is not None]
        lo, hi = min(valid), max(valid)
        if lo == hi:
            raise ValueError(f"No variation in {column}")
        for row, ward in zip(rows, selected):
            value = number(ward[column])
            if value is None:
                raise ValueError(f"Missing {column} in {ward['New code']}; no imputation")
            normalized = 100 * (value - lo) / (hi - lo)
            row.append(100 - normalized if reverse else normalized)
        mapping.append({"slot": slot, "raw_column": column,
                        "reverse": reverse, "unit": "as in source header",
                        "reference_ward_count": len(valid),
                        "reference_missing": len(wards) - len(valid),
                        "reference_min": lo, "reference_max": hi})
    case = {"name": "london_ward_proxy", "rows": rows,
            "population_percent": shares}
    provenance = {"source_url": RAW_URL, "source_sha256": RAW_SHA256,
                  "source_licence": "Open Government Licence v2",
                  "source_page": "https://data.london.gov.uk/dataset/ward-profiles-and-atlas-exprl",
                  "ward_count_in_reference": len(wards),
                  "selected_raw_rows": [
                      {"ward": r["Ward name"], "code": r["New code"],
                       "population_2015": number(r["Population - 2015"]),
                       "measurements": {slot: number(r[col]) for slot, col, _ in FIELDS}}
                      for r in selected],
                  "normalization": "100*(x-min)/(max-min) across nonmissing London E050 ward rows; reverse as 100-normalized",
                  "fields": mapping}
    return case, provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", action="store_true")
    parser.add_argument("--optimizer", nargs="+", help="command reading scenario JSON on stdin")
    args = parser.parse_args()
    case, provenance = scenario()
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Official DOCX changed; recheck model constants")
    payload = {"schema": 1, "name": case["name"], "source_sha256": RAW_SHA256,
               "districts": [r["ward"] for r in provenance["selected_raw_rows"]],
               "indicators": INDICATORS, "weights_percent": WEIGHTS,
               "population_percent": case["population_percent"], "rows": case["rows"],
               "measures": MEASURES, "budget": 100, "decisions": 5, "horizon_quarters": 8}
    result = {"scenario": case["name"], "baseline_score": baseline_score(case),
              "provenance": provenance, "payload": payload}
    if args.oracle:
        start = time.perf_counter()
        best, choices, count = exact_oracle(case)
        result["oracle"] = {"score": best, "choices": choices,
                            "feasible_portfolios": count, "seconds": time.perf_counter() - start}
    if args.optimizer:
        start = time.perf_counter()
        proc = subprocess.run(args.optimizer, input=json.dumps(payload, ensure_ascii=False),
                              text=True, capture_output=True, timeout=120, check=True)
        choices = [(x["id"], x.get("district")) for x in json.loads(proc.stdout)["choices"]]
        problem = validate(choices)
        result["optimizer"] = {"valid": problem is None, "error": problem,
                               "choices": choices, "seconds": time.perf_counter() - start}
        if problem is None:
            result["optimizer"]["score"] = score(case, choices)
            if args.oracle:
                result["optimizer"]["regret"] = best - result["optimizer"]["score"]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
