"""Grounded Russian explanations for a validated city simulation result.

The optional model selects *fact IDs*, never writes displayed numbers or prose.
Every displayed fact is constructed from the deterministic simulator output.
"""

import json
import os
from http.client import HTTPException
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError


_OPENAI_API_URL = "https://api.openai.com/v1/responses"
_NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_MODEL_TIMEOUT_SECONDS = 8
_MODEL_ENV_KEYS = ("NVIDIA_API_KEY", "NVIDIA_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL")
_DOTENV_PATH = Path(__file__).resolve().parents[1] / ".env"
_INSTRUCTIONS = (
    "Ты объясняешь результат городской симуляции. Верни только JSON-объект "
    "с ключами strengths, risks, tradeoffs. Значение каждого ключа — массив из "
    "одного или двух ID из соответствующей секции candidates. Выбирай самые "
    "важные факты; не добавляй текст, числа, новые ID или другие ключи."
)


def _read_model_env_file():
    """Read this checkout's model settings as data, without shell evaluation."""
    try:
        lines = _DOTENV_PATH.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        return {}
    values = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or name not in _MODEL_ENV_KEYS:
            continue
        value = value.strip()
        if value.startswith(("'", '"')):
            closing = value.find(value[0], 1)
            if closing < 0:
                continue
            trailing = value[closing + 1:].strip()
            if trailing and not trailing.startswith("#"):
                continue
            value = value[1:closing]
        else:
            value = value.split(" #", 1)[0].rstrip()
        values[name] = value
    return values


def model_settings():
    """Internal credentials; process variables override .env, even when empty.

    The returned values include secrets and must never be logged or serialized.
    """
    file_values = _read_model_env_file()
    return {name: os.environ[name] if name in os.environ else file_values.get(name)
            for name in _MODEL_ENV_KEYS}


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
    for item in result.get("contributions", []):
        effects = item.get("scaled_effects", {})
        if effects:
            details = ", ".join(f"{key} {value:+.2f}" for key, value in sorted(effects.items()))
            location = item.get("district") or "весь город"
            strengths[f"measure_{item['measure_id']}"] = (
                f"Расчётный вклад {item['measure_id']} ({location}) в показатели: {details}."
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
        if required in facts[section] and required not in selections[section]:
            selections[section].insert(0, required)
    return "\n".join(
        f"{names[section]}: " + " ".join(facts[section][key] for key in selections[section])
        for section in names
    )


def _fallback(facts):
    return {section: list(items)[:2] for section, items in facts.items()}


class ModelOutputError(ValueError):
    """A model response did not select only allowed computed facts."""


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ModelOutputError("Duplicate model selection key")
        result[name] = value
    return result


def _validate_selection(output, facts):
    if not isinstance(output, str):
        raise ModelOutputError("Model did not return text")
    cleaned = output.strip()
    lines = cleaned.splitlines()
    if len(lines) >= 3 and lines[0] in ("```json", "```") and lines[-1] == "```":
        cleaned = "\n".join(lines[1:-1]).strip()
    try:
        selected = json.loads(cleaned, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as exc:
        raise ModelOutputError("Model did not return a complete JSON selection") from exc
    if not isinstance(selected, dict) or set(selected) != set(facts):
        raise ModelOutputError("Unexpected model selection shape")
    for section, chosen in selected.items():
        if (not isinstance(chosen, list) or not 1 <= len(chosen) <= 2
                or any(not isinstance(key, str) or key not in facts[section] for key in chosen)
                or len(chosen) != len(set(chosen))):
            raise ModelOutputError("Model selected unverified fact")
    return selected


def _selection_schema(facts):
    """Constrain Responses output to this calculation's available fact IDs."""
    return {
        "type": "object",
        "properties": {
            section: {"type": "array", "items": {"type": "string", "enum": list(items)},
                      "minItems": 1, "maxItems": 2}
            for section, items in facts.items()
        },
        "required": list(facts),
        "additionalProperties": False,
    }


def _post_json(url, payload, api_key):
    if not url.startswith("https://"):
        raise ValueError("Model API URL must use HTTPS")
    req = request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=_MODEL_TIMEOUT_SECONDS) as response:
        body = json.load(response)
    if not isinstance(body, dict):
        raise ModelOutputError("Unexpected provider response shape")
    return body


def _select_with_openai(facts, api_key, model, evidence):
    payload = {
        "model": model,
        "instructions": _INSTRUCTIONS,
        "input": json.dumps({"candidates": facts, "calculated_evidence": evidence},
                            ensure_ascii=False, sort_keys=True),
        "store": False,
        "max_output_tokens": 512,
        "text": {"format": {"type": "json_schema", "name": "city_explanation_facts",
                            "strict": True, "schema": _selection_schema(facts)}},
    }
    # The configured GPT-5.6 Sol supports none; this is a short selection task.
    # Preserve compatibility with other models that do not accept reasoning.
    if model == "gpt-5.6-sol":
        payload["reasoning"] = {"effort": "none"}
    body = _post_json(_OPENAI_API_URL, payload, api_key)
    if body.get("status") not in (None, "completed") or body.get("error"):
        raise ModelOutputError("Model response was not completed")
    output = body.get("output")
    if not isinstance(output, list):
        raise ModelOutputError("Model response has no output")
    texts = []
    for item in output:
        if not isinstance(item, dict):
            raise ModelOutputError("Unexpected output item")
        if item.get("type") != "message":
            continue
        if item.get("status") not in (None, "completed"):
            raise ModelOutputError("Model message was not completed")
        content = item.get("content")
        if not isinstance(content, list):
            raise ModelOutputError("Unexpected message content")
        for block in content:
            if not isinstance(block, dict) or block.get("type") == "refusal":
                raise ModelOutputError("Model did not provide a fact selection")
            if block.get("type") == "output_text":
                if not isinstance(block.get("text"), str):
                    raise ModelOutputError("Model output is not text")
                texts.append(block["text"])
    return _validate_selection("".join(texts), facts)


def _select_with_nvidia(facts, api_key, model, evidence):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _INSTRUCTIONS},
            {"role": "user", "content": json.dumps(
                {"candidates": facts, "calculated_evidence": evidence},
                ensure_ascii=False, sort_keys=True)},
        ],
        "max_tokens": 512,
        "stream": False,
    }
    body = _post_json(_NVIDIA_API_URL, payload, api_key)
    choices = body.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ModelOutputError("Unexpected model choices")
    choice = choices[0]
    if choice.get("finish_reason") not in (None, "stop"):
        raise ModelOutputError("Model response was not completed")
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("refusal"):
        raise ModelOutputError("Model did not provide a fact selection")
    return _validate_selection(message.get("content"), facts)


def _failure_diagnostics(failure):
    """Return only allowlisted metadata, never exception text or HTTP bodies."""
    details = {"error_type": type(failure).__name__}
    if isinstance(failure, HTTPError):
        details["http_status"] = failure.code
        details["error_code"] = ("authentication" if failure.code in (401, 403)
                                 else "rate_limited" if failure.code == 429
                                 else "provider_error")
    elif isinstance(failure, TimeoutError) or (
            isinstance(failure, URLError) and isinstance(failure.reason, TimeoutError)):
        details["error_code"] = "timeout"
    elif isinstance(failure, (ValueError, TypeError, KeyError, IndexError)):
        details["error_code"] = "invalid_model_output"
    else:
        details["error_code"] = "network_error"
    return details


def _explain_facts(facts, evidence, *, diagnostics=False):
    """Let the model select verified facts; never render free-form model text."""
    settings = model_settings()
    nvidia_key, nvidia_model = settings["NVIDIA_API_KEY"], settings["NVIDIA_MODEL"]
    openai_key, openai_model = settings["OPENAI_API_KEY"], settings["OPENAI_MODEL"]
    if nvidia_key and nvidia_model:
        api_key, model, provider, selector = nvidia_key, nvidia_model, "nvidia", _select_with_nvidia
    elif openai_key and openai_model:
        api_key, model, provider, selector = openai_key, openai_model, "openai", _select_with_openai
    else:
        api_key = model = provider = selector = None
    failure = None
    if api_key and model:
        try:
            selected = selector(facts, api_key, model, evidence)
            return {"text": _render(facts, selected), "source": "model",
                    "provider": provider, "model": model}
        except (OSError, HTTPException, ValueError, KeyError, TypeError, IndexError) as exc:
            failure = exc
    answer = {
        "text": _render(facts, _fallback(facts)),
        "source": "computed_facts",
        "reason": "model_unavailable" if api_key and model else "model_not_configured",
    }
    if diagnostics:
        answer.update(provider=provider, model=model)
        if failure is not None:
            answer.update(_failure_diagnostics(failure))
    return answer


def explain(result, *, diagnostics=False):
    """Explain one verified scenario from its complete calculated evidence.

    NVIDIA_API_KEY + NVIDIA_MODEL take priority over OpenAI configuration.
    Models are never guessed; invalid scenarios are never explained.
    """
    if not result.get("valid"):
        return {"text": "", "source": "computed_facts", "reason": "invalid_result"}
    return _explain_facts(_facts(result), result, diagnostics=diagnostics)


def explain_comparison(current, proposed, removed, added, *, diagnostics=False):
    """Explain a one-change recommendation from two verified simulations."""
    if not current.get("valid") or not proposed.get("valid"):
        return {"text": "", "source": "computed_facts", "reason": "invalid_result"}
    gain = proposed["score"] - current["score"]
    score_fact = (f"Замена повышает Score с {_fmt(current['score'])} до "
                  f"{_fmt(proposed['score'])}, на +{_fmt(gain)}.") if gain > 0 else (
                  f"Замена одной меры не повышает Score: {_fmt(current['score'])}.")
    strengths = {"score_change": score_fact}
    if proposed["critical_count"] < current["critical_count"]:
        strengths["critical_change"] = (
            f"Критических показателей ниже 40 стало "
            f"{proposed['critical_count']} вместо {current['critical_count']}.")
    district_changes = sorted(
        ((proposed["districts"][district]["score"] - data["score"], district)
         for district, data in current["districts"].items()), reverse=True)
    if district_changes and district_changes[0][0] > 0:
        change, district = district_changes[0]
        strengths["district_gain"] = f"Больше всего вырос районный балл {district}: +{_fmt(change)}."
    indicator_changes = sorted(
        ((proposed["districts"][district]["indicators"][indicator] - value,
          district, indicator)
         for district, row in current["districts"].items()
         for indicator, value in row["indicators"].items()),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    if indicator_changes and indicator_changes[0][0] > 0:
        change, district, indicator = indicator_changes[0]
        strengths["indicator_gain"] = (
            f"После замены показатель {indicator} в районе {district} выше на {_fmt(change)}."
        )
    weakest, values = min(proposed["districts"].items(), key=lambda item: item[1]["score"])
    risks = {"weakest": f"Самый низкий районный балл после замены — {weakest}: {_fmt(values['score'])}."}
    if proposed["cost"] > current["cost"]:
        risks["more_cost"] = (
            f"Расходы вырастут с {current['cost']} до {proposed['cost']} из бюджета 100.")
    declines = [(change, district) for change, district in district_changes if change < 0]
    if declines:
        change, district = min(declines)
        risks["district_decline"] = f"Районный балл {district} снизится на {_fmt(-change)}."
    if indicator_changes and indicator_changes[-1][0] < 0:
        change, district, indicator = indicator_changes[-1]
        risks["indicator_decline"] = (
            f"После замены показатель {indicator} в районе {district} ниже на {_fmt(-change)}."
        )
    removed_text = ", ".join(item["measure_id"] + ("/" + item["district"] if item["district"] else "/город") for item in removed)
    added_text = ", ".join(item["measure_id"] + ("/" + item["district"] if item["district"] else "/город") for item in added)
    tradeoffs = {"measure_change": (f"Заменить {removed_text} на {added_text}." if removed else
                                   "Улучшения заменой одной меры не найдено."),
                 "budget": f"Останется {proposed['remaining_budget']} из 100 бюджетных единиц."}
    facts = {"strengths": strengths, "risks": risks, "tradeoffs": tradeoffs}
    evidence = {"current": current, "proposed": proposed,
                "removed": removed, "added": added}
    answer = _explain_facts(facts, evidence, diagnostics=diagnostics)
    answer["text"] = ("Совет по проверенному сравнению: " if gain > 0 else
                      "Сравнение проверенных сценариев: ") + answer["text"]
    return answer
