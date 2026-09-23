"""Grounded Russian explanations for a validated city simulation result.

The optional model selects *fact IDs*, never writes displayed numbers or prose.
Every displayed fact is constructed from the deterministic simulator output.
"""

import json
import os
from pathlib import Path
from urllib import request


_OPENAI_API_URL = "https://api.openai.com/v1/responses"
_NVIDIA_API_BASE_URL = "https://integrate.api.nvidia.com/v1"
_MODEL_ENV_KEYS = ("NVIDIA_API_KEY", "NVIDIA_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL")
_DOTENV_PATH = Path(__file__).resolve().parents[1] / ".env"
_INSTRUCTIONS = (
    "Ты объясняешь результат городской симуляции. Верни только JSON-объект "
    "с ключами strengths, risks, tradeoffs. Значение каждого ключа — массив из "
    "одного или двух ID из соответствующей секции candidates. Выбирай самые "
    "важные факты; не добавляй текст, числа, новые ID или другие ключи."
)


def _read_model_env_file():
    """Read model settings from this checkout's .env without executing it."""
    try:
        lines = _DOTENV_PATH.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
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
            quote = value[0]
            if len(value) >= 2 and value.endswith(quote):
                value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        values[name] = value
    return values


def model_settings():
    """Return model settings; process variables override .env, including empty ones."""
    file_values = _read_model_env_file()
    return {name: os.environ[name] if name in os.environ else file_values.get(name)
            for name in _MODEL_ENV_KEYS}


def _fmt(number):
    return f"{number:.2f}".replace(".", ",")


def _fmt_signed(number):
    return f"{number:+.2f}".replace(".", ",")


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
    for section, required in (("risks", "risk_residual"),
                              ("tradeoffs", "tradeoff_budget"),
                              ("risks", "district_decline")):
        if required in facts[section] and required not in selections[section]:
            selections[section].insert(0, required)
    return "\n".join(
        f"{names[section]}: " + " ".join(facts[section][key] for key in selections[section])
        for section in names
    )


def _fallback(facts):
    return {section: list(items)[:2] for section, items in facts.items()}


def _validate_selection(output, facts):
    cleaned = output.strip()
    lines = cleaned.splitlines()
    if len(lines) >= 3 and lines[0] in ("```json", "```") and lines[-1] == "```":
        cleaned = "\n".join(lines[1:-1]).strip()
    selected = json.loads(cleaned)
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
    # The first request with a new strict schema can take longer to process.
    with request.urlopen(req, timeout=20) as response:
        return json.load(response)


def _structured_text_format(name, properties):
    """Constrain OpenAI Responses output to the supplied verified IDs."""
    return {"format": {
        "type": "json_schema", "name": name, "strict": True,
        "schema": {
            "type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False,
        },
    }}


def _select_with_openai(facts, api_key, model, evidence):
    properties = {
        section: {"type": "array", "items": {"type": "string", "enum": sorted(candidates)},
                  "minItems": 1, "maxItems": 2}
        for section, candidates in facts.items()
    }
    payload = {
        "model": model,
        "instructions": _INSTRUCTIONS,
        "input": json.dumps({"candidates": facts, "calculated_evidence": evidence},
                            ensure_ascii=False, sort_keys=True),
        "text": _structured_text_format("city_fact_selection", properties),
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


def _select_with_nvidia(facts, api_key, model, evidence):
    try:
        from openai import OpenAI, OpenAIError
    except ImportError as exc:
        raise OSError("NVIDIA model client is not installed") from exc
    try:
        client = OpenAI(base_url=_NVIDIA_API_BASE_URL,
                        api_key=api_key, timeout=45.0, max_retries=0)
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _INSTRUCTIONS},
                {"role": "user", "content": json.dumps(
                    {"candidates": facts, "calculated_evidence": evidence},
                    ensure_ascii=False, sort_keys=True)},
            ],
            max_tokens=256,
            stream=False,
        )
    except OpenAIError as exc:
        raise OSError("NVIDIA model request failed") from exc
    output = completion.choices[0].message.content
    if not isinstance(output, str):
        raise ValueError("Model did not return text")
    return _validate_selection(output, facts)


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
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            failure = exc
    answer = {
        "text": _render(facts, _fallback(facts)),
        "source": "computed_facts",
        "reason": "model_unavailable" if api_key and model else "model_not_configured",
    }
    if diagnostics and failure is not None:
        cause = failure.__cause__ or failure
        answer["error_type"] = type(cause).__name__
        status = getattr(cause, "status_code", None)
        if isinstance(status, int):
            answer["http_status"] = status
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


_ADVISOR_INSTRUCTIONS = (
    "Ты помогаешь человеку выбрать среди уже рассчитанных сценариев синтетического "
    "города. Математический оптимум и все числа рассчитаны программой; ничего не "
    "пересчитывай и не меняй. Истолкуй вопрос пользователя и выбери наиболее "
    "уместный готовый вариант для обсуждения, учитывая районные потери и расходы. "
    "Если человек спрашивает только об отличиях и не просит выбрать план, "
    "используй selected_option=none. "
    "Если человек просит не ухудшать район относительно его плана, не выбирай "
    "вариант с отрицательной разницей для этого района. Выбирай selected_option "
    "только из allowed_options, уже проверенных программой. Верни только JSON-объект "
    "с полями selected_option и fact_ids. fact_ids: от 2 до 5 разных ID из candidates, которые прямо "
    "отвечают на вопрос. Если selected_option не none, включи минимум один fact_id "
    "с префиксом выбранного варианта. Не добавляй текст, числа или другие поля."
)


def _advice_facts(options, indicator_names=None):
    """Offer only simulator-derived statements for the model to cite."""
    current = options[0]["result"]
    facts = {}
    labels = {option["id"]: option["label"] for option in options}
    for option in options:
        oid, result = option["id"], option["result"]
        score_delta = result["score"] - current["score"]
        cost_delta = result["cost"] - current["cost"]
        facts[f"{oid}_overview"] = (
            f"{labels[oid]}: Score {_fmt(result['score'])} "
            f"({_fmt_signed(score_delta)} к вашему плану), расходы {result['cost']} "
            f"({cost_delta:+d}), показателей ниже 40: {result['critical_count']}."
        )
        for index, (district, row) in enumerate(result["districts"].items()):
            base = current["districts"][district]
            delta = row["score"] - base["score"]
            facts[f"{oid}_district_{index}"] = (
                f"{labels[oid]}: район {district} — {_fmt(row['score'])}, "
                f"{_fmt_signed(delta)} к вашему плану."
            )
            if oid == "current":
                continue
            for indicator, value in row["indicators"].items():
                difference = value - base["indicators"][indicator]
                if abs(difference) >= 1e-9:
                    name = (indicator_names or {}).get(indicator, indicator)
                    facts[f"{oid}_indicator_{index}_{indicator}"] = (
                        f"{labels[oid]}: показатель {name} ({indicator}) в районе {district} "
                        f"{_fmt(value)}, {_fmt_signed(difference)} к вашему плану."
                    )
        if oid == "current":
            continue
        old = {(item["measure_id"], item.get("district"))
               for item in options[0]["decisions"]}
        new = {(item["measure_id"], item.get("district"))
               for item in option["decisions"]}
        removed = ", ".join(f"{mid}/{district or 'город'}" for mid, district in sorted(old - new))
        added = ", ".join(f"{mid}/{district or 'город'}" for mid, district in sorted(new - old))
        facts[f"{oid}_measures"] = (
            f"{labels[oid]}: убрать {removed}; добавить {added}."
            if old != new else f"{labels[oid]}: набор мер совпадает с вашим планом."
        )
    return facts


def _validate_advice_selection(output, facts, allowed_options):
    cleaned = output.strip()
    lines = cleaned.splitlines()
    if len(lines) >= 3 and lines[0] in ("```json", "```") and lines[-1] == "```":
        cleaned = "\n".join(lines[1:-1]).strip()
    chosen = json.loads(cleaned)
    if not isinstance(chosen, dict) or set(chosen) != {"selected_option", "fact_ids"}:
        raise ValueError("Unexpected advisor response")
    oid = chosen["selected_option"]
    ids = chosen["fact_ids"]
    if oid not in allowed_options:
        raise ValueError("Unknown option")
    if (not isinstance(ids, list) or not 2 <= len(ids) <= 5
            or len(ids) != len(set(ids))
            or any(not isinstance(fid, str) or fid not in facts for fid in ids)):
        raise ValueError("Advisor selected unverified facts")
    if oid != "none" and not any(fid.startswith(oid + "_") for fid in ids):
        raise ValueError("Selected option has no evidence")
    return oid, ids


def _advisor_model_selection(question, facts, allowed_options, api_key, model, provider):
    user_input = json.dumps({"question": question, "allowed_options": allowed_options,
                             "candidates": facts},
                            ensure_ascii=False, sort_keys=True)
    if provider == "openai":
        properties = {
            "selected_option": {"type": "string", "enum": allowed_options},
            "fact_ids": {"type": "array", "items": {"type": "string", "enum": sorted(facts)},
                         "minItems": 2, "maxItems": 5},
        }
        body = _post_json(_OPENAI_API_URL, {
            "model": model, "instructions": _ADVISOR_INSTRUCTIONS,
            "input": user_input,
            "text": _structured_text_format("city_advisor_selection", properties),
            "store": False,
        }, api_key)
        output = "".join(
            block.get("text", "")
            for item in body.get("output", []) if item.get("type") == "message"
            for block in item.get("content", []) if block.get("type") == "output_text"
        )
    else:
        try:
            from openai import OpenAI, OpenAIError
        except ImportError as exc:
            raise OSError("NVIDIA model client is not installed") from exc
        try:
            client = OpenAI(base_url=_NVIDIA_API_BASE_URL,
                            api_key=api_key, timeout=45.0, max_retries=0)
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": _ADVISOR_INSTRUCTIONS},
                          {"role": "user", "content": user_input}],
                max_tokens=256,
                stream=False,
            )
        except OpenAIError as exc:
            raise OSError("NVIDIA advisor request failed") from exc
        output = completion.choices[0].message.content
    if not isinstance(output, str):
        raise ValueError("Advisor returned no text")
    return _validate_advice_selection(output, facts, allowed_options)


_DISTRICT_STEMS = {"Есиль": "есил", "Алматы": "алмат", "Сарыарка": "сарыарк",
                   "Байконур": "байконур", "Нура": "нур"}


def _mentioned_districts(question, district_names):
    normalized_question = question.casefold().replace("ь", "").replace("ё", "е")
    return [district for district in district_names
            if _DISTRICT_STEMS.get(district, district.casefold()) in normalized_question]


def _explicit_no_decline_districts(question, district_names):
    normalized = question.casefold().replace("ё", "е")
    if not any(phrase in normalized for phrase in
               ("не ухудш", "не хочу ухудш", "не хотим ухудш", "без ухудш",
                "не сниж", "без сниж", "не потер", "сохран")):
        return []
    return _mentioned_districts(question, district_names)


def _advice_fallback(question, facts, district_names):
    """Expose relevant computed comparisons when the optional model is absent."""
    chosen = [f"{oid}_overview" for oid in ("current", "one_change", "optimum")]
    for index, district in enumerate(district_names):
        if district in _mentioned_districts(question, district_names):
            chosen.extend(f"{oid}_district_{index}"
                          for oid in ("current", "one_change", "optimum"))
    return "none", [fid for fid in chosen if fid in facts]


def _contradicts_no_decline(question, options, selected_option):
    if selected_option in ("current", "none"):
        return False
    original = options[0]["result"]["districts"]
    proposed = next(option["result"]["districts"] for option in options
                    if option["id"] == selected_option)
    return any(proposed[district]["score"] < original[district]["score"] - 1e-9
               for district in _explicit_no_decline_districts(question, original))


def _admissible_advice_options(question, options):
    """Restrict the model to plans satisfying explicit district priorities."""
    return [option["id"] for option in options
            if not _contradicts_no_decline(question, options, option["id"])] + ["none"]


def _fallback_district_summary(question, options):
    """State only comparisons that hold for both computed alternatives."""
    current = options[0]["result"]["districts"]
    statements = []
    for district in _mentioned_districts(question, current):
        changes = [option["result"]["districts"][district]["score"]
                   - current[district]["score"] for option in options[1:]]
        if all(change < -1e-9 for change in changes):
            statements.append(f"Оба альтернативных варианта снижают балл района «{district}».")
        elif all(change > 1e-9 for change in changes):
            statements.append(f"Оба альтернативных варианта повышают балл района «{district}».")
    return " ".join(statements)


def advise(question, options, indicator_names=None):
    """Interpret a human priority over fixed, verified plans; never change them."""
    if [option.get("id") for option in options] != ["current", "one_change", "optimum"]:
        raise ValueError("Expected the three verified scenarios")
    facts = _advice_facts(options, indicator_names)
    settings = model_settings()
    nvidia_key, nvidia_model = settings["NVIDIA_API_KEY"], settings["NVIDIA_MODEL"]
    openai_key, openai_model = settings["OPENAI_API_KEY"], settings["OPENAI_MODEL"]
    if nvidia_key and nvidia_model:
        api_key, model, provider = nvidia_key, nvidia_model, "nvidia"
    elif openai_key and openai_model:
        api_key, model, provider = openai_key, openai_model, "openai"
    else:
        api_key = model = provider = None
    source = "computed_facts"
    district_names = tuple(options[0]["result"]["districts"])
    allowed_options = _admissible_advice_options(question, options)
    selected_option, selected_facts = _advice_fallback(question, facts, district_names)
    if api_key and model:
        try:
            proposed_option, proposed_facts = _advisor_model_selection(
                question, facts, allowed_options, api_key, model, provider)
            if _contradicts_no_decline(question, options, proposed_option):
                raise ValueError("Advisor contradicts an explicit district constraint")
            selected_option, selected_facts = proposed_option, proposed_facts
            source = "model"
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            pass
    label = next((option["label"] for option in options
                  if option["id"] == selected_option), None)
    intro = (f"С учётом вашего вопроса рассмотрите вариант «{label}». "
             if label else "Сравните рассчитанные варианты с вашим приоритетом. ")
    if source == "computed_facts":
        summary = _fallback_district_summary(question, options)
        if summary:
            intro += summary + " "
    text = intro.strip() + "\n" + "\n".join(f"• {facts[fid]}" for fid in selected_facts)
    answer = {"text": text, "source": source, "selected_option": selected_option}
    if source == "model":
        answer.update(provider=provider, model=model)
    else:
        answer["reason"] = "model_unavailable" if api_key and model else "model_not_configured"
    return answer
