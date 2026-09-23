"""Grounded Russian explanations for a validated city simulation result.

The optional model selects *fact IDs*, never writes displayed numbers or prose.
Every displayed fact is constructed from the deterministic simulator output.
"""

import json
import os
from urllib import request


_API_URL = "https://api.openai.com/v1/responses"
_INSTRUCTIONS = (
    "Ты объясняешь результат городской симуляции. Верни только JSON-объект "
    "с ключами strengths, risks, tradeoffs. Значение каждого ключа — массив из "
    "одного или двух ID из соответствующей секции candidates. Выбирай самые "
    "важные факты; не добавляй текст, числа, новые ID или другие ключи."
)


def _fmt(number):
    return f"{number:.2f}".replace(".", ",")


def _facts(result):
    """Build display-ready facts solely from computed fields."""
    score_delta = result["score"] - result["base_score"]
    strengths = {
        "strength_score": f"Итоговый Score: {_fmt(result['score'])}; изменение: {score_delta:+.2f}.",
    }
    flattened = sorted(
        ((delta, district, indicator) for district, row in result["deltas"].items()
         for indicator, delta in row.items() if delta > 0),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    if flattened:
        delta, district, indicator = flattened[0]
        strengths["strength_indicator"] = (
            f"Наибольший прирост показателя: {indicator} в районе {district}, +{_fmt(delta)}."
        )
    if result.get("applied_synergies"):
        synergy = result["applied_synergies"][0]
        strengths["strength_synergy"] = (
            f"Синергия {', '.join(synergy['measures'])} добавила "
            f"+{_fmt(synergy['bonus'])} к {synergy['indicator']} в районе {synergy['district']}."
        )

    district, values = min(
        result["districts"].items(), key=lambda item: (item[1]["score"], item[0])
    )
    risks = {
        "risk_weakest": f"Самый низкий районный Score остаётся у района {district}: {_fmt(values['score'])}."
    }
    negatives = sorted(
        ((delta, district, indicator) for district, row in result["deltas"].items()
         for indicator, delta in row.items() if delta < 0),
        key=lambda item: (item[0], item[1], item[2]),
    )
    if negatives:
        delta, district, indicator = negatives[0]
        risks["risk_negative"] = (
            f"Показатель {indicator} в районе {district} снизился на {_fmt(abs(delta))}."
        )
    if result.get("critical_count", 0):
        risks["risk_critical"] = (
            f"После решений остаётся критических показателей ниже 40: {result['critical_count']}."
        )

    tradeoffs = {
        "tradeoff_budget": (
            f"Выбрано мер на {result['cost']} из бюджета 100; остаток "
            f"{result['remaining_budget']} не увеличивает Score."
        )
    }
    lagged = [item for item in result.get("contributions", []) if item["lag_factor"] < 1]
    if lagged:
        worst = min(lagged, key=lambda item: (item["lag_factor"], item["measure_id"]))
        tradeoffs["tradeoff_lag"] = (
            f"Из-за лага мера {worst['measure_id']} даёт в горизонте симуляции "
            f"{_fmt(worst['lag_factor'] * 100)}% полного эффекта."
        )
    return {"strengths": strengths, "risks": risks, "tradeoffs": tradeoffs}


def _render(facts, selections):
    names = {"strengths": "Сильные стороны", "risks": "Риски", "tradeoffs": "Компромиссы"}
    return "\n".join(
        f"{names[section]}: " + " ".join(facts[section][key] for key in selections[section])
        for section in names
    )


def _fallback(facts):
    return {section: list(items)[:2] for section, items in facts.items()}


def _select_with_model(facts, api_key, model):
    payload = {
        "model": model,
        "instructions": _INSTRUCTIONS,
        "input": json.dumps({"candidates": facts}, ensure_ascii=False, sort_keys=True),
        "store": False,
    }
    req = request.Request(
        _API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=8) as response:
        body = json.load(response)
    # Responses may have multiple output items; collect all output_text blocks.
    output = "".join(
        block.get("text", "")
        for item in body.get("output", []) if item.get("type") == "message"
        for block in item.get("content", []) if block.get("type") == "output_text"
    )
    selected = json.loads(output)
    if not isinstance(selected, dict) or set(selected) != set(facts):
        raise ValueError("Unexpected model selection shape")
    for section, chosen in selected.items():
        if (not isinstance(chosen, list) or not 1 <= len(chosen) <= 2
                or len(chosen) != len(set(chosen))
                or any(not isinstance(key, str) or key not in facts[section] for key in chosen)):
            raise ValueError("Model selected unverified fact")
    return selected


def explain(result):
    """Return a grounded explanation, with a transparent offline fallback.

    A model is used only when both OPENAI_API_KEY and OPENAI_MODEL are set.
    Invalid simulations do not have scores and are never explained.
    """
    if not result.get("valid"):
        return {"text": "", "source": "computed_facts", "reason": "invalid_result"}
    facts = _facts(result)
    api_key, model = os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_MODEL")
    if api_key and model:
        try:
            selected = _select_with_model(facts, api_key, model)
            return {"text": _render(facts, selected), "source": "model", "model": model}
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
    return {
        "text": _render(facts, _fallback(facts)),
        "source": "computed_facts",
        "reason": "model_unavailable" if api_key and model else "model_not_configured",
    }
