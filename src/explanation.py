"""Grounded Russian explanations for a validated city simulation result.

The optional model selects *fact IDs*, never writes displayed numbers or prose.
Every displayed fact is constructed from the deterministic simulator output.
"""

import json
import os
from urllib import request


_OPENAI_API_URL = "https://api.openai.com/v1/responses"
_NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
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
    indicator, level = min(
        values["indicators"].items(), key=lambda item: (item[1], item[0])
    )
    risks = {
        "risk_residual": (
            f"Район с самым низким Score — {district} ({_fmt(values['score'])}); "
            f"его самый слабый показатель — {indicator} ({_fmt(level)})."
        )
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
            f"После решений остаётся критических показателей: {result['critical_count']}."
        )

    tradeoffs = {
        "tradeoff_budget": (
            f"Выбрано мер на {result['cost']} из бюджета "
            f"{result['cost'] + result['remaining_budget']}; остаток "
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
    # Required computed facts remain visible even if the model omits their IDs.
    selections = {section: list(keys) for section, keys in selections.items()}
    for section, required in (("risks", "risk_residual"), ("tradeoffs", "tradeoff_budget")):
        if required not in selections[section]:
            selections[section].insert(0, required)
    return "\n".join(
        f"{names[section]}: " + " ".join(facts[section][key] for key in selections[section])
        for section in names
    )


def _fallback(facts):
    return {section: list(items)[:2] for section, items in facts.items()}


def _validate_selection(output, facts):
    selected = json.loads(output)
    if not isinstance(selected, dict) or set(selected) != set(facts):
        raise ValueError("Unexpected model selection shape")
    for section, chosen in selected.items():
        if (not isinstance(chosen, list) or not 1 <= len(chosen) <= 2
                or len(chosen) != len(set(chosen))
                or any(not isinstance(key, str) or key not in facts[section] for key in chosen)):
            raise ValueError("Model selected unverified fact")
    return selected


def _post_json(url, payload, api_key):
    if not url.startswith("https://"):
        raise ValueError("Model API URL must use HTTPS")
    req = request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=8) as response:
        return json.load(response)


def _select_with_openai(facts, api_key, model):
    payload = {
        "model": model,
        "instructions": _INSTRUCTIONS,
        "input": json.dumps({"candidates": facts}, ensure_ascii=False, sort_keys=True),
        "store": False,
    }
    body = _post_json(_OPENAI_API_URL, payload, api_key)
    # Responses may have multiple output items; collect all output_text blocks.
    output = "".join(
        block.get("text", "")
        for item in body.get("output", []) if item.get("type") == "message"
        for block in item.get("content", []) if block.get("type") == "output_text"
    )
    return _validate_selection(output, facts)


def _select_with_nvidia(facts, api_key, model):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _INSTRUCTIONS},
            {"role": "user", "content": json.dumps({"candidates": facts}, ensure_ascii=False, sort_keys=True)},
        ],
        "stream": False,
    }
    body = _post_json(_NVIDIA_API_URL, payload, api_key)
    output = body["choices"][0]["message"]["content"]
    if not isinstance(output, str):
        raise ValueError("Model did not return text")
    return _validate_selection(output, facts)


def explain(result):
    """Return a grounded explanation, with a transparent offline fallback.

    NVIDIA_API_KEY + NVIDIA_MODEL take priority over OpenAI configuration.
    Models are never guessed: both key and explicit model ID are required.
    Invalid simulations do not have scores and are never explained.
    """
    if not result.get("valid"):
        return {"text": "", "source": "computed_facts", "reason": "invalid_result"}
    facts = _facts(result)
    nvidia_key, nvidia_model = os.getenv("NVIDIA_API_KEY"), os.getenv("NVIDIA_MODEL")
    openai_key, openai_model = os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_MODEL")
    if nvidia_key and nvidia_model:
        api_key, model, provider, selector = nvidia_key, nvidia_model, "nvidia", _select_with_nvidia
    elif openai_key and openai_model:
        api_key, model, provider, selector = openai_key, openai_model, "openai", _select_with_openai
    else:
        api_key = model = provider = selector = None
    if api_key and model:
        try:
            selected = selector(facts, api_key, model)
            return {"text": _render(facts, selected), "source": "model",
                    "provider": provider, "model": model}
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            pass
    return {
        "text": _render(facts, _fallback(facts)),
        "source": "computed_facts",
        "reason": "model_unavailable" if api_key and model else "model_not_configured",
    }
