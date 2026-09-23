"""Local HTTP entry point for the HackAlem city simulator.

Run with ``python3 src/server.py``. The simulation and its numeric output live
in simulator.py; the HTTP layer never calculates a Score.
"""

import json
import os
from functools import lru_cache
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from simulator import catalog, simulate
from optimizer import best_one_change, optimize


ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
MAX_REQUEST_BYTES = 64 * 1024


@lru_cache(maxsize=1)
def _optimizer_payload():
    """Give both optimization modes the same canonical simulator inputs."""
    data = catalog()
    district_names = tuple(data["districts"])
    indicator_names = tuple(data["indicators"])
    category_codes = {
        "Транспорт": "T", "Экология": "E", "Соцсфера": "S",
        "Безопасность": "B", "Сервисы": "C",
    }
    return {
        "districts": district_names,
        "indicators": indicator_names,
        "rows": [[int(data["districts"][district]["indicators"][key]) for key in indicator_names]
                 for district in district_names],
        "population_percent": [round(data["districts"][district]["population_share"] * 100)
                               for district in district_names],
        "weights_percent": [round(data["indicators"][key]["weight"] * 100)
                            for key in indicator_names],
        "measures": {mid: [category_codes[measure["category"]], measure["cost"],
                           measure["lag_quarters"], measure["scope"] == "city",
                           measure["full_effects"]]
                     for mid, measure in data["measures"].items()},
        "budget": data["budget"], "decisions": 5,
        "horizon_quarters": data["horizon_quarters"],
    }


@lru_cache(maxsize=1)
def _optimal_scenario():
    """Find the exact best portfolio for the fixed official catalogue."""
    payload = _optimizer_payload()
    district_names = tuple(payload["districts"])
    found = optimize(payload)
    decisions = [{"measure_id": choice["id"],
                  "district": None if choice["district"] is None
                  else district_names[choice["district"]]}
                 for choice in found["choices"]]
    checked = simulate(decisions)
    if not checked["valid"] or abs(checked["score"] - found["score"]) > 1e-8:
        raise RuntimeError("Optimizer and simulator disagree")
    return decisions, checked


def _one_change_scenario(decisions, current):
    """Compare a user plan with its best valid one-decision patch."""
    payload = _optimizer_payload()
    district_names = tuple(payload["districts"])
    fixed = [{"id": item["measure_id"],
              "district": None if item.get("district") is None
              else district_names.index(item["district"])} for item in decisions]
    found = best_one_change(payload, fixed)
    proposed_decisions = [{"measure_id": item["id"],
                           "district": None if item["district"] is None
                           else district_names[item["district"]]}
                          for item in found["choices"]]
    proposed = simulate(proposed_decisions)
    if not proposed["valid"] or abs(proposed["score"] - found["score"]) > 1e-8:
        raise RuntimeError("Recommendation and simulator disagree")
    removed = [{"measure_id": item["id"],
                "district": None if item["district"] is None
                else district_names[item["district"]]} for item in found["removed"]]
    added = [{"measure_id": item["id"],
              "district": None if item["district"] is None
              else district_names[item["district"]]} for item in found["added"]]
    from explanation import explain_comparison
    return {"valid": True, "current": current, "proposed": proposed,
            "decisions": proposed_decisions, "removed": removed, "added": added,
            "score_delta": found["score_delta"], "cost_delta": found["cost_delta"],
            "explanation": explain_comparison(current, proposed, removed, added)}


def _fallback_explanation(result):
    """Describe computed facts when an optional model is unavailable."""
    changes = []
    for district, indicators in result["deltas"].items():
        for indicator, delta in indicators.items():
            if delta:
                changes.append((abs(delta), district, indicator, delta))
    changes.sort(reverse=True)
    highlights = [
        f"{district}: {indicator} {delta:+g}"
        for _, district, indicator, delta in changes[:3]
    ]
    weakest = min(result["districts"].items(), key=lambda item: item[1]["score"])
    text = (
        f"Рассчитанный Score изменился на {result['score_delta']:+.5f}. "
        + ("Наибольшие изменения: " + "; ".join(highlights) + ". " if highlights else "")
        + f"Слабейший район после мер — {weakest[0]} ({weakest[1]['score']:.2f}). "
        + f"Потрачено {result['cost']} из 100; остаток не повышает Score."
    )
    return {"text": text, "source": "computed_facts"}


def _explain(result):
    try:
        from explanation import explain
    except ImportError:
        return _fallback_explanation(result)
    try:
        return explain(result)
    except Exception as exc:
        print(f"Optional explanation unavailable: {type(exc).__name__}: {exc}")
        return _fallback_explanation(result)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlsplit(self.path).path
        if route == "/api/catalog":
            self._json(200, catalog())
            return
        if route == "/api/optimize":
            try:
                decisions, checked = _optimal_scenario()
                result = {**checked, "decisions": decisions,
                          "optimization": {"method": "exact_integer_enumeration",
                                           "proven_optimal_for": "official_dataset"}}
                result["explanation"] = _explain(result)
                self._json(200, result)
            except Exception as exc:
                print(f"Optimizer unavailable: {type(exc).__name__}: {exc}")
                self._json(500, {"error": "Подсказка оптимизатора сейчас недоступна."})
            return
        super().do_GET()

    def do_POST(self):
        route = urlsplit(self.path).path
        if route not in ("/api/simulate", "/api/recommend-change"):
            self._json(404, {"error": "Unknown API route"})
            return
        try:
            size = int(self.headers.get("Content-Length", ""))
            if size < 1 or size > MAX_REQUEST_BYTES:
                raise ValueError("Invalid request size")
            request = json.loads(self.rfile.read(size))
            if not isinstance(request, dict):
                raise ValueError("Expected a JSON object")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "Ожидается корректный JSON с решениями."})
            return
        decisions = request.get("decisions")
        result = simulate(decisions)
        if route == "/api/simulate":
            if result["valid"]:
                result["explanation"] = _explain(result)
            self._json(200, result)
            return
        if not result["valid"]:
            self._json(400, result)
            return
        try:
            self._json(200, _one_change_scenario(decisions, result))
        except Exception as exc:
            print(f"One-change recommendation unavailable: {type(exc).__name__}: {exc}")
            self._json(500, {"error": "Сравнение сценариев сейчас недоступно."})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"City simulator: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
