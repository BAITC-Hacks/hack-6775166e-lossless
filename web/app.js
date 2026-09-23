"use strict";

const API = { catalog: "/api/catalog", simulate: "/api/simulate", optimize: "/api/optimize" };
const state = { catalog: null, decisions: Array.from({ length: 5 }, () => ({ measure_id: "", district: null })), currentResult: null, recommendation: null, revision: 0 };
const $ = (id) => document.getElementById(id);
const formatScore = (value) => Number.isFinite(Number(value)) ? Number(value).toFixed(2).replace(".", ",") : "—";
const text = (tag, value, className) => {
  const element = document.createElement(tag);
  element.textContent = String(value ?? "");
  if (className) element.className = className;
  return element;
};

function districts() {
  const source = state.catalog?.districts;
  if (Array.isArray(source)) return source.map((item) => typeof item === "string" ? item : item.name || item.id).filter(Boolean);
  if (source && typeof source === "object") return Object.keys(source);
  return [];
}

function measures() {
  const source = state.catalog?.measures;
  const list = Array.isArray(source) ? source : Object.entries(source || {}).map(([id, value]) => ({ id, ...value }));
  return list.map((item) => ({
    ...item,
    id: item.id || item.measure_id || item.code,
    name: item.name || item.title || item.label || "Мероприятие",
    category: item.category || item.direction || item.sector || "Другое",
    cost: Number(item.cost ?? item.price ?? 0),
    scope: item.scope || item.type || item.level || "Район"
  })).filter((item) => item.id).sort((a, b) => Number(a.id.slice(1)) - Number(b.id.slice(1)));
}

function isCity(measure) {
  return /город|city|global/i.test(String(measure?.scope || ""));
}

function selectedMeasure(id) { return measures().find((measure) => measure.id === id); }

function option(value, label) {
  const element = document.createElement("option");
  element.value = value;
  element.textContent = label;
  return element;
}

function renderSlots() {
  const host = $("decision-slots");
  host.replaceChildren();
  state.decisions.forEach((decision, index) => {
    const row = text("div", "", "decision-row");
    row.append(text("span", String(index + 1).padStart(2, "0"), "decision-number"));

    const measureField = text("label", "", "measure-field");
    measureField.append(text("span", "Мероприятие", "field-label"));
    const measureSelect = document.createElement("select");
    measureSelect.setAttribute("aria-label", `Мероприятие ${index + 1}`);
    measureSelect.append(option("", "Выбрать меру"));
    measures().forEach((measure) => measureSelect.append(option(measure.id, `${measure.id} · ${measure.name} · ${measure.cost}`)));
    measureSelect.value = decision.measure_id;
    measureSelect.addEventListener("change", () => {
      decision.measure_id = measureSelect.value;
      decision.district = null;
      renderSlots();
      updateBudget();
      hideResult();
    });
    measureField.append(measureSelect);
    row.append(measureField);

    const districtField = text("label", "", "district-field");
    districtField.append(text("span", "Район", "field-label"));
    const districtSelect = document.createElement("select");
    districtSelect.setAttribute("aria-label", `Район для решения ${index + 1}`);
    const selected = selectedMeasure(decision.measure_id);
    if (!selected) {
      districtSelect.append(option("", "Сначала мера"));
      districtSelect.disabled = true;
    } else if (isCity(selected)) {
      districtSelect.append(option("", "Весь город"));
      districtSelect.disabled = true;
      decision.district = null;
    } else {
      districtSelect.append(option("", "Выбрать район"));
      districts().forEach((name) => districtSelect.append(option(name, name)));
      districtSelect.value = decision.district || "";
      districtSelect.addEventListener("change", () => {
        decision.district = districtSelect.value || null;
        hideResult();
      });
    }
    districtField.append(districtSelect);
    row.append(districtField);
    host.append(row);
  });
}

function renderCatalog() {
  const host = $("catalog-groups");
  host.replaceChildren();
  const groups = new Map();
  measures().forEach((measure) => {
    if (!groups.has(measure.category)) groups.set(measure.category, []);
    groups.get(measure.category).push(measure);
  });
  groups.forEach((items, category) => {
    const group = text("section", "", "catalog-group");
    const heading = text("h3", category);
    heading.append(text("span", String(items.length).padStart(2, "0")));
    group.append(heading);
    items.forEach((measure) => {
      const card = text("div", "", "measure-card");
      const top = text("div", "", "measure-top");
      const name = text("div", "", "measure-name");
      name.append(text("span", measure.id, "measure-id"), document.createTextNode(measure.name));
      top.append(name, text("span", measure.cost, "measure-cost"));
      card.append(top, text("p", isCity(measure) ? "Весь город" : "Для выбранного района", "measure-meta"));
      group.append(card);
    });
    host.append(group);
  });
}

function updateBudget() {
  const used = state.decisions.reduce((total, decision) => total + (selectedMeasure(decision.measure_id)?.cost || 0), 0);
  $("budget-used").textContent = String(used);
  $("budget-fill").style.width = `${Math.min(used, 100)}%`;
  $("budget-progress").setAttribute("aria-valuenow", String(Math.min(used, 100)));
  $("budget-progress").parentElement.classList.toggle("over-budget", used > 100);
  $("budget-hint").textContent = used > 100 ? `Превышение бюджета на ${used - 100} ед. Сервер вернёт причину отказа.` : `Остаток ${100 - used} ед. не повышает Score.`;
}

function hideResult() {
  state.currentResult = null;
  state.recommendation = null;
  state.revision += 1;
  $("result-section").hidden = true;
  $("comparison").hidden = true;
  optimizerError("");
}

function optimizerError(message) {
  const host = $("optimizer-error");
  host.textContent = message || "";
  host.hidden = !message;
}

function showErrors(errors) {
  state.currentResult = null;
  state.recommendation = null;
  $("comparison").hidden = true;
  $("result-section").hidden = false;
  $("valid-result").hidden = true;
  const host = $("result-errors");
  host.hidden = false;
  host.replaceChildren(text("strong", "Сценарий не рассчитан"));
  const list = document.createElement("ul");
  (Array.isArray(errors) ? errors : [errors]).filter(Boolean).forEach((error) => list.append(text("li", typeof error === "string" ? error : error.message || JSON.stringify(error))));
  host.append(list);
  $("result-section").scrollIntoView({ behavior: "smooth", block: "start" });
}

function districtRows(result) {
  const items = result.districts;
  if (Array.isArray(items)) return items.map((entry) => [entry.name || entry.id || entry.district, entry]);
  return Object.entries(items || {});
}

function renderDistricts(result) {
  const chartHost = $("district-chart");
  chartHost.replaceChildren();
  if (typeof window.renderDistrictCharts === "function") {
    try { window.renderDistrictCharts(chartHost, result); }
    catch (error) { console.error("Ошибка визуализации районов:", error); chartHost.replaceChildren(); }
  }
  const host = $("district-list");
  host.replaceChildren();
  districtRows(result).forEach(([name, values]) => {
    const row = text("div", "", "district-row");
    const value = typeof values === "number" ? values : values.score ?? values.district_score ?? values.value;
    const baseline = typeof values === "object" ? values.base_score ?? values.baseline ?? state.catalog?.districts?.[name]?.score : undefined;
    const deltaSource = result.deltas?.[name];
    const delta = typeof deltaSource === "number" ? deltaSource : values?.delta ?? values?.score_delta ?? (Number.isFinite(Number(baseline)) && Number.isFinite(Number(value)) ? Number(value) - Number(baseline) : undefined);
    row.append(text("span", name), text("b", formatScore(value)));
    const change = text("span", Number.isFinite(Number(delta)) ? `${Number(delta) >= 0 ? "+" : ""}${formatScore(delta)}` : "", "delta");
    if (Number(delta) < 0) change.classList.add("negative");
    row.append(change);
    host.append(row);
  });
  if (!host.childElementCount && !chartHost.childElementCount) host.append(text("p", "Подробные показатели районов не получены."));
}

function renderExplanation(explanation) {
  const host = $("explanation");
  host.replaceChildren();
  if (typeof explanation === "string" && explanation.trim()) {
    explanation.trim().split(/\n\s*\n/).forEach((paragraph) => host.append(text("p", paragraph)));
  } else if (typeof explanation?.text === "string") {
    host.append(text("p", explanation.text));
    if (explanation.source === "computed_facts") host.append(text("small", "Проверяемое объяснение по рассчитанным фактам. AI-модель недоступна.", "explanation-source"));
  } else if (explanation && typeof explanation === "object") {
    Object.entries(explanation).forEach(([key, value]) => {
      if (value == null || value === "") return;
      host.append(text("h4", key.replaceAll("_", " ")));
      if (Array.isArray(value)) {
        const list = document.createElement("ul");
        value.forEach((item) => list.append(text("li", typeof item === "string" ? item : JSON.stringify(item))));
        host.append(list);
      } else host.append(text("p", typeof value === "string" ? value : JSON.stringify(value)));
    });
  } else host.append(text("p", "Объяснение недоступно. Числовой результат рассчитан отдельно."));
}

function showResult(result) {
  if (!result?.valid || !Number.isFinite(Number(result.score))) {
    showErrors(result?.errors?.length ? result.errors : ["Сервер не подтвердил корректный расчёт."]);
    return;
  }
  $("result-section").hidden = false;
  $("comparison").hidden = true;
  $("result-errors").hidden = true;
  $("valid-result").hidden = false;
  const base = Number(result.base_score ?? state.catalog.base_score);
  const score = Number(result.score);
  $("result-base").textContent = formatScore(base);
  $("result-score").textContent = formatScore(score);
  $("result-change").textContent = `${score >= base ? "+" : ""}${formatScore(score - base)}`;
  renderDistricts(result);
  renderExplanation(result.explanation);
  const details = $("result-details");
  details.replaceChildren();
  details.append(text("span", `Стоимость: ${result.cost ?? "—"} / 100`, "detail-pill"));
  details.append(text("span", `Остаток: ${result.remaining_budget ?? "—"}`, "detail-pill"));
  const synergies = result.applied_synergies;
  if (Array.isArray(synergies) && synergies.length) details.append(text("span", `Синергии: ${synergies.length}`, "detail-pill"));
  $("result-section").scrollIntoView({ behavior: "smooth", block: "start" });
}

function districtScore(result, name) { return Number(result.districts?.[name]?.score); }
function districtScoreWithChange(result, name) {
  const score = districtScore(result, name);
  const baseline = Number(state.catalog?.districts?.[name]?.score);
  return Number.isFinite(baseline) ? `${formatScore(score)} (${signed(score - baseline)})` : formatScore(score);
}
function affectedDistricts(result) {
  return districts().filter((name) => Object.values(result.deltas?.[name] || {}).some((value) => Number(value) !== 0));
}
function signed(value) { return `${value >= 0 ? "+" : ""}${formatScore(value)}`; }

function renderComparison(current, proposed) {
  const gap = Number(proposed.score) - Number(current.score);
  $("comparison-gap").textContent = `${signed(gap)} к вашему Score`;
  const summary = $("comparison-summary");
  summary.replaceChildren();
  for (const [label, result] of [["Ваш план", current], ["Рекомендация", proposed]]) {
    const card = text("div", "", "comparison-stat");
    card.append(text("small", label), text("strong", formatScore(result.score)), text("span", `Стоимость ${result.cost} / 100 · затронуто районов: ${affectedDistricts(result).length}`));
    summary.append(card);
  }
  const rows = $("comparison-districts");
  rows.replaceChildren();
  const userBetter = [];
  const proposedBetter = [];
  districts().forEach((name) => {
    const first = districtScore(current, name);
    const second = districtScore(proposed, name);
    if (!Number.isFinite(first) || !Number.isFinite(second)) return;
    const difference = second - first;
    if (difference > 0.00001) proposedBetter.push(name);
    if (difference < -0.00001) userBetter.push(name);
    const row = document.createElement("tr");
    row.append(text("th", name), text("td", districtScoreWithChange(current, name)), text("td", districtScoreWithChange(proposed, name)));
    const delta = text("td", signed(difference), difference < 0 ? "comparison-negative" : "comparison-positive");
    row.append(delta);
    rows.append(row);
  });
  const tradeoffs = $("comparison-tradeoffs");
  tradeoffs.replaceChildren();
  const costDifference = Number(proposed.cost) - Number(current.cost);
  const costMessage = costDifference === 0 ? "Оба плана тратят одинаковый бюджет." : `Рекомендация тратит на ${Math.abs(costDifference)} ед. ${costDifference > 0 ? "больше" : "меньше"}.`;
  tradeoffs.append(text("p", costMessage));
  tradeoffs.append(text("p", proposedBetter.length ? `Выше районный балл: ${proposedBetter.join(", ")}.` : "Нет районов, где рекомендация повышает районный балл относительно вашего плана."));
  tradeoffs.append(text("p", userBetter.length ? `Ваш план сохраняет более высокий районный балл: ${userBetter.join(", ")}.` : "Нет районов, где ваш план даёт более высокий районный балл."));
  if (Number.isFinite(Number(current.critical_count)) && Number.isFinite(Number(proposed.critical_count))) {
    tradeoffs.append(text("p", `Критических показателей: ваш план — ${current.critical_count}, рекомендация — ${proposed.critical_count}.`));
  }
  const userMeasures = state.decisions.map(({ measure_id, district }) => `${measure_id}${district ? ` / ${district}` : " / город"}`).join(" · ");
  const proposedMeasures = proposed.decisions.map(({ measure_id, district }) => `${measure_id}${district ? ` / ${district}` : " / город"}`).join(" · ");
  $("comparison-measures").textContent = `Ваш план: ${userMeasures}. Рекомендация: ${proposedMeasures}.`;
  $("comparison").hidden = false;
  $("comparison").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function calculate() {
  const button = $("submit-plan");
  const revision = state.revision;
  button.disabled = true;
  $("suggest-plan").disabled = true;
  optimizerError("");
  button.firstElementChild.textContent = "Считаем последствия…";
  try {
    const decisions = state.decisions.filter((item) => item.measure_id).map((item) => ({ measure_id: item.measure_id, district: item.district }));
    const response = await fetch(API.simulate, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decisions }) });
    const result = await response.json();
    if (!response.ok && !Array.isArray(result.errors)) throw new Error(`Сервер вернул HTTP ${response.status}`);
    if (revision !== state.revision) return;
    showResult(result);
    state.currentResult = result.valid && Number.isFinite(Number(result.score)) ? result : null;
  } catch (error) { showErrors([`Не удалось связаться с сервером: ${error.message}`]); }
  finally { button.disabled = false; $("suggest-plan").disabled = false; button.firstElementChild.textContent = "Рассчитать сценарий"; }
}

async function suggestPlan() {
  if (!state.currentResult?.valid) {
    optimizerError("Сначала рассчитайте корректный ручной план, чтобы сравнить его с рекомендацией.");
    return;
  }
  const button = $("suggest-plan");
  const revision = state.revision;
  button.disabled = true;
  $("submit-plan").disabled = true;
  button.firstElementChild.textContent = "Ищем план…";
  optimizerError("");
  try {
    const response = await fetch(API.optimize);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    if (!result?.valid || !Number.isFinite(Number(result.score)) || !Array.isArray(result.decisions) || result.decisions.length !== 5) {
      throw new Error(Array.isArray(result?.errors) && result.errors.length ? result.errors.join(" ") : "сервер вернул неполный план");
    }
    const ids = new Set();
    const proposed = result.decisions.map((decision) => {
      const measure = selectedMeasure(decision?.measure_id);
      if (!measure || ids.has(measure.id)) throw new Error("сервер вернул неизвестные или повторяющиеся мероприятия");
      ids.add(measure.id);
      const district = isCity(measure) ? null : decision.district;
      if (!isCity(measure) && !districts().includes(district)) throw new Error("сервер не указал район для одной из мер");
      return { measure_id: measure.id, district };
    });
    if (revision !== state.revision || !state.currentResult?.valid) throw new Error("ручной план изменился во время поиска");
    state.recommendation = { ...result, decisions: proposed };
    renderComparison(state.currentResult, state.recommendation);
  } catch (error) {
    optimizerError(`Не удалось сравнить планы: ${error.message}. Ваш ручной выбор сохранён.`);
  } finally {
    button.disabled = false;
    $("submit-plan").disabled = false;
    button.firstElementChild.textContent = "Сравнить с рекомендацией";
  }
}

function adoptPlan() {
  if (!state.recommendation?.valid) return;
  const result = state.recommendation;
  state.decisions = result.decisions.map(({ measure_id, district }) => ({ measure_id, district }));
  state.currentResult = result;
  state.recommendation = null;
  state.revision += 1;
  renderSlots();
  updateBudget();
  optimizerError("");
  showResult(result);
}

async function start() {
  try {
    const response = await fetch(API.catalog);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const catalog = await response.json();
    if (!catalog || !catalog.districts || !catalog.measures || !Number.isFinite(Number(catalog.base_score))) throw new Error("Неполный каталог");
    state.catalog = catalog;
    $("base-score").textContent = formatScore(catalog.base_score);
    renderSlots();
    renderCatalog();
    updateBudget();
    $("loading").hidden = true;
    $("app").hidden = false;
    $("submit-plan").addEventListener("click", calculate);
    $("suggest-plan").addEventListener("click", suggestPlan);
    $("adopt-plan").addEventListener("click", adoptPlan);
  } catch (error) {
    $("loading").hidden = true;
    $("app-error").textContent = `Не удалось загрузить исходные данные: ${error.message}. Обновите страницу после запуска сервера.`;
    $("app-error").hidden = false;
  }
}

start();
