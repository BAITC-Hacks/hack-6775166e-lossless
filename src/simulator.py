"""Deterministic HackAlem city simulator. Source: task/Датасет районов.docx.

All numeric results are calculated with Decimal; floats are used only at the
JSON-compatible public boundary. No rounding is applied before the final UI.
"""

from collections import Counter
from decimal import Decimal


HORIZON = 8
BUDGET = 100
INDICATORS = {
    "T1": ("Транспорт", "Разгрузка дорог", "0.10"),
    "T2": ("Транспорт", "Доступность общественного транспорта", "0.10"),
    "E1": ("Экология", "Озеленение", "0.09"),
    "E2": ("Экология", "Качество воздуха", "0.11"),
    "S1": ("Соцсфера", "Школы и детсады", "0.11"),
    "S2": ("Соцсфера", "Поликлиники и первичная медпомощь", "0.11"),
    "B1": ("Безопасность", "Безопасность улиц", "0.09"),
    "B2": ("Безопасность", "Безопасность дорожного движения", "0.09"),
    "C1": ("Сервисы", "Надёжность ЖКХ", "0.10"),
    "C2": ("Сервисы", "Скорость решения обращений жителей", "0.10"),
}
DISTRICTS = {
    "Есиль": ("0.27", [45, 62, 68, 72, 48, 55, 78, 60, 75, 70], "Богатый, но с пробками на мостах и переполненными школами."),
    "Алматы": ("0.24", [40, 75, 50, 55, 60, 65, 62, 52, 50, 60], "Старый ЖКХ и пробки."),
    "Сарыарка": ("0.20", [50, 70, 42, 40, 62, 68, 58, 55, 45, 55], "Смог от частного сектора, слабое озеленение."),
    "Байконур": ("0.13", [52, 68, 55, 50, 58, 60, 52, 58, 55, 58], "Середняк без ярких перекосов."),
    "Нура": ("0.16", [55, 40, 45, 65, 38, 35, 55, 50, 60, 50], "Главный аутсайдер по соцсфере и транспорту."),
}
# id: category, label, scope, cost, lag, full effects
MEASURES = {
    "M1": ("Транспорт", "Выделенные полосы для автобусов", "district", 18, 2, {"T1": 6, "T2": 9}),
    "M2": ("Транспорт", "Умные светофоры (адаптивное управление)", "city", 22, 2, {"T1": 4, "B2": 3}),
    "M3": ("Транспорт", "Линия ЛРТ / расширение", "district", 30, 4, {"T1": 16, "T2": 20, "E2": 4}),
    "M4": ("Экология", "Парк / сквер", "district", 15, 2, {"E1": 12, "E2": 3, "B1": 2}),
    "M5": ("Экология", "Перевод частного сектора на чистое топливо", "district", 25, 3, {"E2": 14, "C1": 4}),
    "M6": ("Экология", "Городская программа озеленения и ветрозащитных полос", "city", 20, 4, {"E1": 5, "E2": 3}),
    "M7": ("Соцсфера", "Школа + детсад (модульное строительство)", "district", 24, 3, {"S1": 16}),
    "M8": ("Соцсфера", "Центр семейного здоровья / поликлиника", "district", 20, 3, {"S2": 14}),
    "M9": ("Соцсфера", "Дворовые спорт-хабы", "district", 10, 1, {"S1": 3, "S2": 3, "B1": 3}),
    "M10": ("Безопасность", "Освещение и камеры (расширение Safe City)", "district", 12, 1, {"B1": 12, "B2": 2}),
    "M11": ("Безопасность", "Безопасные переходы и школьные зоны", "district", 10, 1, {"B2": 12, "T1": -2}),
    "M12": ("Сервисы", "Единая цифровая платформа обращений", "city", 14, 1, {"C2": 5}),
    "M13": ("Сервисы", "Модернизация тепло- и водосетей", "district", 28, 4, {"C1": 18, "E2": 2}),
    "M14": ("Сервисы", "Аварийные бригады ЖКХ + раннее оповещение", "city", 16, 1, {"C1": 5, "C2": 2}),
}
SYNERGIES = (("M1", "M2", "T1", 2), ("M10", "M12", "B1", 2), ("M5", "M6", "E2", 2))


def _number(value):
    return float(value)


def _base_grid():
    keys = tuple(INDICATORS)
    return {name: dict(zip(keys, map(Decimal, values))) for name, (_, values, _) in DISTRICTS.items()}


def _score(grid):
    district_scores = {name: sum((grid[name][key] * Decimal(meta[2]) for key, meta in INDICATORS.items()), Decimal(0)) for name in DISTRICTS}
    average = sum((Decimal(DISTRICTS[name][0]) * value for name, value in district_scores.items()), Decimal(0))
    critical = sum(value < 40 for row in grid.values() for value in row.values())
    score = Decimal("0.7") * average + Decimal("0.3") * min(district_scores.values()) - critical
    return score, district_scores, average, critical


def catalog():
    """Return fixed initial conditions and the complete measure catalogue."""
    grid = _base_grid()
    score, district_scores, _, _ = _score(grid)
    return {
        "budget": BUDGET,
        "horizon_quarters": HORIZON,
        "base_score": _number(score),
        "indicators": {key: {"category": item[0], "name": item[1], "weight": float(item[2])} for key, item in INDICATORS.items()},
        "districts": {name: {"population_share": float(data[0]), "indicators": {key: _number(value) for key, value in grid[name].items()}, "score": _number(district_scores[name]), "profile": data[2]} for name, data in DISTRICTS.items()},
        "measures": {key: {"id": key, "category": item[0], "name": item[1], "scope": item[2], "cost": item[3], "lag_quarters": item[4], "full_effects": item[5].copy()} for key, item in MEASURES.items()},
        "synergies": [{"measures": [a, b], "indicator": indicator, "bonus": bonus, "district_of": a} for a, b, indicator, bonus in SYNERGIES],
        "conflicts": [{"measures": ["M1", "M3"], "scope": "any"}, {"measures": ["M4", "M7"], "scope": "same_district"}, {"measures": ["M5", "M13"], "scope": "same_district"}],
    }


def simulate(decisions):
    """Validate exactly five decisions, then calculate effects and score.

    Each decision is {"measure_id": "M7", "district": "Нура"}; city
    measures require district=None (or an omitted district key).
    """
    errors = []
    base_score = _number(_score(_base_grid())[0])
    if not isinstance(decisions, list):
        return {"valid": False, "errors": ["Решения должны быть списком из пяти объектов."], "cost": 0, "remaining_budget": BUDGET, "base_score": base_score}
    if len(decisions) != 5:
        errors.append("Нужно выбрать ровно пять мероприятий.")
    normalized = []
    for index, decision in enumerate(decisions, 1):
        if not isinstance(decision, dict):
            errors.append(f"Решение {index}: ожидается объект.")
            continue
        measure_id = decision.get("measure_id")
        if not isinstance(measure_id, str) or measure_id not in MEASURES:
            errors.append(f"Решение {index}: неизвестное мероприятие {measure_id!r}.")
            continue
        district = decision.get("district")
        measure = MEASURES[measure_id]
        if measure[2] == "district" and (not isinstance(district, str) or district not in DISTRICTS):
            errors.append(f"{measure_id}: укажите один из пяти районов.")
        if measure[2] == "city" and district is not None:
            errors.append(f"{measure_id}: городская мера не принимает район.")
        normalized.append((measure_id, district))
    ids = [measure_id for measure_id, _ in normalized]
    duplicates = [measure_id for measure_id, count in Counter(ids).items() if count > 1]
    if duplicates:
        errors.append("Мероприятие можно выбрать только один раз: " + ", ".join(sorted(duplicates)) + ".")
    counts = Counter(MEASURES[measure_id][0] for measure_id in ids)
    for category, count in sorted(counts.items()):
        if count > 2:
            errors.append(f"Направление «{category}»: максимум две меры, выбрано {count}.")
    by_id = dict(normalized)
    if "M1" in by_id and "M3" in by_id:
        errors.append("M1 и M3 несовместимы в любых районах.")
    for first, second in (("M4", "M7"), ("M5", "M13")):
        if first in by_id and second in by_id and by_id[first] == by_id[second]:
            errors.append(f"{first} и {second} несовместимы в одном районе.")
    cost = sum(MEASURES[measure_id][3] for measure_id in ids)
    if cost > BUDGET:
        errors.append(f"Бюджет превышен: {cost} > {BUDGET}.")
    if errors:
        return {"valid": False, "errors": errors, "cost": cost, "remaining_budget": BUDGET - cost, "base_score": base_score}

    grid = _base_grid()
    base = _base_grid()
    contributions = []
    # Sort to make all public arrays and arithmetic independent of input order.
    for measure_id, district in sorted(normalized):
        category, label, scope, measure_cost, lag, effects = MEASURES[measure_id]
        factor = Decimal(HORIZON - lag) / HORIZON
        affected = list(DISTRICTS) if scope == "city" else [district]
        scaled = {key: Decimal(value) * factor for key, value in effects.items()}
        for name in affected:
            for key, effect in scaled.items():
                grid[name][key] += effect
        contributions.append({"measure_id": measure_id, "district": district, "affected_districts": affected, "cost": measure_cost, "lag_factor": _number(factor), "scaled_effects": {key: _number(value) for key, value in scaled.items()}})
    applied_synergies = []
    for first, second, indicator, bonus in SYNERGIES:
        if first in by_id and second in by_id:
            district = by_id[first]
            grid[district][indicator] += bonus
            applied_synergies.append({"measures": [first, second], "district": district, "indicator": indicator, "bonus": bonus})
    for row in grid.values():
        for key, value in row.items():
            row[key] = max(Decimal(0), min(Decimal(100), value))
    score, district_scores, average, critical = _score(grid)
    base_score = _score(base)[0]
    deltas = {name: {key: _number(grid[name][key] - base[name][key]) for key in INDICATORS} for name in DISTRICTS}
    return {
        "valid": True,
        "errors": [],
        "cost": cost,
        "remaining_budget": BUDGET - cost,
        "base_score": _number(base_score),
        "score": _number(score),
        "score_delta": _number(score - base_score),
        "districts": {name: {"indicators": {key: _number(value) for key, value in grid[name].items()}, "score": _number(district_scores[name])} for name in DISTRICTS},
        "deltas": deltas,
        "contributions": contributions,
        "applied_synergies": applied_synergies,
        "population_weighted_average": _number(average),
        "critical_count": critical,
    }
