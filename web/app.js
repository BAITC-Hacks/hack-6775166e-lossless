"use strict";

// The server owns simulation and Score. This interface only composes decisions
// and displays catalogue fields and server results.
const API = { catalog: "/api/catalog", simulate: "/api/simulate", optimize: "/api/optimize", recommendChange: "/api/recommend-change", advice: "/api/advice" };
const VERIFICATION_DECISIONS = [
  { measure_id: "M7", district: "Нура" }, { measure_id: "M8", district: "Нура" },
  { measure_id: "M10", district: "Нура" }, { measure_id: "M12", district: null },
  { measure_id: "M5", district: "Сарыарка" }
];
const state = { catalog: null, measures: [], decisions: [], category: "Все", stage: "briefing", result: null, proposal: null, pending: null, busy: null, adviceBusy: false, revision: 0, selectedDistrict: null, measureView: "district", hoverMeasureId: null, resultView: "after", scene: null, drag: null };
const $ = (id) => document.getElementById(id);
const finite = (value) => typeof value === "number" && Number.isFinite(value);
const format = (value, digits = 2) => finite(value) ? value.toFixed(digits).replace(".", ",") : "—";
const categoryIcons = { "Транспорт": "bus", "Экология": "leaf", "Соцсфера": "school", "Безопасность": "shield", "Сервисы": "service" };
const categoryLabels = { "Соцсфера": "Соцсфера", "Экология": "Экология", "Сервисы": "Сервисы" };
const measureById = (id) => state.measures.find((measure) => measure.id === id);
const districtNames = () => Object.keys(state.catalog?.districts || {});
const weakNeeds = (name) => Object.entries(state.catalog?.districts?.[name]?.indicators || {})
  .filter(([, value]) => finite(value)).sort((a, b) => a[1] - b[1]).slice(0, 2);
const budget = () => finite(state.catalog?.budget) ? state.catalog.budget : 100;
const horizon = () => finite(state.catalog?.horizon_quarters) ? state.catalog.horizon_quarters : 8;
const city = (measure) => measure.scope === "city";
const locked = () => Boolean(state.busy);
const costOf = (decisions) => decisions.reduce((sum, decision) => sum + (measureById(decision.measure_id)?.cost || 0), 0);
const node = (tag, content, className) => {
  const element = document.createElement(tag);
  if (content !== undefined && content !== null) element.textContent = String(content);
  if (className) element.className = className;
  return element;
};
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}
function announce(message) { $("announcer").textContent = message; }
function indicatorName(key) { return state.catalog.indicators?.[key]?.name || key; }
function notice(message = "", error = false) {
  $("planner-notice").textContent = message;
  $("planner-notice").hidden = !message;
  $("planner-notice").classList.toggle("is-error", error);
}
function syncNavigation() {
  document.querySelectorAll("[data-stage]").forEach((button) => {
    const stage = button.dataset.stage;
    button.disabled = (stage !== "briefing" && !state.catalog) || (stage === "report" && !state.result);
    if (!button.classList.contains("stage-link")) return;
    button.classList.toggle("is-active", stage === state.stage);
    button.classList.toggle("is-complete", stage === "briefing" && state.stage !== "briefing" || stage === "planner" && state.stage === "report");
    if (stage === state.stage) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  });
}
function setStage(stage) {
  if (!state.catalog || !["briefing", "planner", "report"].includes(stage) || stage === "report" && !state.result) return;
  state.stage = stage;
  $("app").dataset.stage = stage;
  ["briefing", "planner", "report"].forEach((name) => { $(`stage-${name}`).hidden = name !== stage; });
  syncNavigation();
  renderDistrictRail();
  renderInspector();
  syncScene();
  const heading = $(`stage-${stage}`).querySelector("h1");
  heading.setAttribute("tabindex", "-1");
  if (stage === "report") heading.scrollIntoView({ block: "start", behavior: "instant" });
  else window.scrollTo({ top: 0, behavior: "instant" });
  heading.focus({ preventScroll: true });
}
function validate(decisions, requireFive = false) {
  const errors = [];
  if (requireFive && decisions.length !== 5) errors.push("Для подписания нужно ровно пять распоряжений.");
  if (decisions.length > 5) errors.push("В пакете уже пять распоряжений. Сначала уберите одно из них.");
  const ids = new Set();
  const counts = {};
  decisions.forEach((decision) => {
    const measure = measureById(decision.measure_id);
    if (!measure) { errors.push("В пакете есть неизвестное мероприятие."); return; }
    if (ids.has(measure.id)) errors.push("Каждое мероприятие можно выбрать только один раз.");
    ids.add(measure.id);
    counts[measure.category] = (counts[measure.category] || 0) + 1;
    if (city(measure) && decision.district !== null) errors.push("Для городской меры район не указывается.");
    if (!city(measure) && !districtNames().includes(decision.district)) errors.push("Выберите район для распоряжения.");
  });
  Object.entries(counts).forEach(([category, count]) => {
    if (count > 2) errors.push(`В направлении «${category}» уже две меры. Выберите другое направление.`);
  });
  if (costOf(decisions) > budget()) errors.push(`Не хватает ${format(costOf(decisions) - budget(), 0)} ед. бюджета. Замените или уберите другое распоряжение.`);
  // Catalogue conflict metadata is optional; the server always validates again.
  for (const conflict of state.catalog?.conflicts || []) {
    if (!Array.isArray(conflict.measures) || conflict.measures.length !== 2) continue;
    const first = decisions.find((item) => item.measure_id === conflict.measures[0]);
    const second = decisions.find((item) => item.measure_id === conflict.measures[1]);
    if (!first || !second) continue;
    if (conflict.scope === "any") errors.push(`${first.measure_id} и ${second.measure_id} несовместимы во всех районах.`);
    else if (conflict.scope === "same_district" && first.district && first.district === second.district) errors.push(`${first.measure_id} и ${second.measure_id} нельзя реализовать вместе в районе ${first.district}.`);
  }
  return [...new Set(errors)];
}
function setDecisions(decisions, message) {
  if (locked()) return;
  state.hoverMeasureId = null;
  state.resultView = "after";
  state.decisions = decisions.map((item) => ({ measure_id: item.measure_id, district: item.district }));
  state.revision += 1;
  state.result = null;
  state.proposal = null;
  clearAdvisorResponse();
  $("comparison").hidden = true;
  $("plan-errors").hidden = true;
  syncNavigation();
  renderPlanner();
  renderDistrictRail(); renderInspector(); syncScene();
  notice("");
  if (message) announce(message);
}
function displayDistrict(name) {
  const baseline = state.catalog?.districts?.[name];
  const after = state.stage === "report" && state.resultView === "after" && state.result?.districts?.[name];
  return after || baseline;
}
function syncScene() {
  if (!state.catalog) return;
  const focus = state.pending?.measureId || state.hoverMeasureId;
  const measure = focus && measureById(focus);
  const affected = measure ? (city(measure) ? districtNames() : [state.pending?.district || state.selectedDistrict].filter(Boolean)) : [];
  const coverage = $("coverage-districts");
  coverage.replaceChildren();
  $("coverage-label").textContent = measure ? `${measure.id} · ${city(measure) ? "весь город" : state.pending?.district || state.selectedDistrict}` : "Наведите на меру";
  districtNames().forEach((name) => {
    const chip = node("span", name, `coverage-chip${affected.includes(name) ? " is-affected" : ""}${name === state.selectedDistrict ? " is-selected" : ""}`);
    chip.dataset.dropDistrict = name;
    coverage.append(chip);
  });
  const cityChip = node("span", "Весь город", `coverage-chip coverage-city${measure && city(measure) ? " is-affected" : ""}`);
  cityChip.dataset.dropCity = "true";
  coverage.append(cityChip);
  if (!state.scene) return;
  try {
    state.scene.update({
      districts: state.catalog.districts,
      selected: state.selectedDistrict,
      affected,
      resultDistricts: state.result?.districts || null,
      mode: state.stage === "report" && state.resultView === "after" && state.result ? "result" : "baseline"
    });
  } catch (error) { console.error("City scene update failed", error); }
}
function renderDistrictRail() {
  const host = $("district-cards");
  host.replaceChildren();
  districtNames().forEach((name, index) => {
    const source = displayDistrict(name);
    const selected = name === state.selectedDistrict;
    const button = node("button", null, `rail-district${selected ? " is-active" : ""}`);
    button.type = "button";
    button.dataset.district = name;
    button.dataset.dropDistrict = name;
    button.setAttribute("aria-pressed", String(selected));
    button.setAttribute("aria-label", `${name}, качество района ${format(source?.score)}, ${selected ? "выбран" : "выбрать"}`);
    button.append(node("span", `0${index + 1}`, "rail-index"), node("strong", name), node("b", format(source?.score)));
    button.addEventListener("click", () => selectDistrict(name, true));
    host.append(button);
  });
}
function renderInspector() {
  const name = state.selectedDistrict;
  if (!name || !state.catalog?.districts?.[name]) return;
  const baseline = state.catalog.districts[name];
  const current = displayDistrict(name);
  const index = districtNames().indexOf(name);
  $("inspector-index").textContent = `0${index + 1} / 05`;
  $("district-inspector-title").textContent = name.toUpperCase();
  $("inspector-profile").textContent = baseline.profile || "Исходные показатели района.";
  $("inspector-score").textContent = format(current?.score);
  $("inspector-score-fill").style.width = `${Math.max(0, Math.min(100, current?.score || 0))}%`;
  const resultMode = state.stage === "report" && Boolean(state.result);
  const cityAfter = resultMode && state.resultView === "after" && finite(state.result?.score);
  $("deck-base-score").textContent = cityAfter ? format(state.result.score) : format(state.catalog.base_score);
  $("deck-score-label").textContent = cityAfter ? `город после · было ${format(state.catalog.base_score)}` : resultMode ? "город до решений / 100" : "город сейчас / 100";
  $("result-view-toggle").hidden = !resultMode;
  $("view-before").setAttribute("aria-pressed", String(state.resultView === "before"));
  $("view-after").setAttribute("aria-pressed", String(state.resultView === "after"));
  $("inspector-score-label").textContent = resultMode ? `Качество района · ${state.resultView === "after" ? "после" : "до"}` : "Качество жизни района";
  const change = $("inspector-score-change");
  const afterScore = state.result?.districts?.[name]?.score;
  change.hidden = !resultMode || state.resultView !== "after" || !finite(afterScore);
  change.textContent = finite(afterScore) ? `Было ${format(baseline.score)} → стало ${format(afterScore)}` : "";
  $("inspector-needs-label").textContent = resultMode ? "Слабые места до ваших решений" : "Два самых слабых показателя";
  const host = $("inspector-needs"); host.replaceChildren();
  weakNeeds(name).forEach(([key, baselineValue]) => {
    const value = finite(current?.indicators?.[key]) ? current.indicators[key] : baselineValue;
    const item = node("div", null, "need-item");
    const label = node("div", null, "need-label");
    label.append(node("span", indicatorName(key)), node("b", format(value, 0)));
    const meter = node("div", null, "need-meter");
    const fill = node("span"); fill.style.width = `${Math.max(0, Math.min(100, value))}%`; meter.append(fill);
    item.append(label, meter);
    if (resultMode && state.resultView === "after") {
      const delta = state.result?.deltas?.[name]?.[key];
      if (finite(delta) && delta !== 0) item.append(node("small", `${delta > 0 ? "+" : ""}${format(delta, 1)} после мер`, delta < 0 ? "need-delta is-negative" : "need-delta"));
    }
    host.append(item);
  });
  const action = $("district-action");
  action.querySelector("span").textContent = resultMode ? "Изменить решения" : `Меры для района ${name}`;
  $("inspector-note").textContent = resultMode
    ? "Выберите район на схеме и сравните «Было» и «Стало». Все значения получены из расчёта вашего пакета."
    : "Откройте район на схеме, затем направьте туда меры. Городские меры охватывают все пять районов.";
}
function selectDistrict(name, restoreFocus = false) {
  if (!state.catalog?.districts?.[name]) return;
  state.selectedDistrict = name;
  renderDistrictRail(); renderInspector(); syncScene();
  if (state.stage === "planner") renderMeasures();
  if (restoreFocus) $("district-cards").querySelector(`[data-district="${name}"]`)?.focus({ preventScroll: true });
  if (!state.pending && window.matchMedia("(max-width: 850px)").matches) requestAnimationFrame(() => {
    const title = $("district-inspector-title");
    title.setAttribute("tabindex", "-1");
    title.scrollIntoView({ block: "start", behavior: "instant" });
    title.focus({ preventScroll: true });
  });
  announce(`Выбран район ${name}. В досье показаны два слабых показателя.`);
}
function renderBriefing() {
  $("briefing-budget").textContent = format(budget(), 0);
  $("briefing-horizon").textContent = format(horizon(), 0);
  $("base-score").textContent = format(state.catalog.base_score);
  $("deck-base-score").textContent = format(state.catalog.base_score);
  renderDistrictRail(); renderInspector(); syncScene();
}
function renderCategories() {
  const host = $("category-tabs");
  host.replaceChildren();
  const categories = ["Все", ...new Set(state.measures.map((item) => item.category))];
  categories.forEach((category) => {
    const button = node("button", null, `category-tab${state.category === category ? " is-active" : ""}`);
    button.type = "button";
    button.setAttribute("aria-pressed", String(state.category === category));
    if (category !== "Все") button.append(icon(categoryIcons[category] || "city"));
    button.append(node("span", categoryLabels[category] || category));
    button.addEventListener("click", () => {
      state.category = category;
      renderCategories();
      renderMeasures();
      // Restore keyboard focus after replacing the filter controls.
      [...host.children].find((item) => item.getAttribute("aria-pressed") === "true")?.focus({ preventScroll: true });
    });
    host.append(button);
  });
}
let dragToastTimer;
function dragMessage(message, error = false) {
  const toast = $("drag-toast");
  clearTimeout(dragToastTimer);
  toast.textContent = message;
  toast.classList.toggle("is-error", error);
  toast.hidden = false;
  dragToastTimer = setTimeout(() => { toast.hidden = true; }, 3200);
  announce(message);
}
function dropError(measure, target) {
  if (!target) return "Перетащите меру на район или на цель «Весь город».";
  if (city(measure) && target.kind !== "city") return "Эта мера действует на весь город. Перетащите её на «Весь город».";
  if (!city(measure) && target.kind !== "district") return "Этой мере нужен конкретный район. Перетащите её на один из пяти районов.";
  return validate([...state.decisions, { measure_id: measure.id, district: target.kind === "city" ? null : target.name }])[0] || "";
}
function renderDropBoard(measure) {
  const host = $("drop-targets");
  host.replaceChildren();
  const targets = [...districtNames().map((name) => ({ kind: "district", name })), { kind: "city", name: "Весь город" }];
  targets.forEach((target, index) => {
    const button = node("button", null, "drop-target");
    button.type = "button";
    if (target.kind === "city") button.dataset.dropCity = "true";
    else button.dataset.dropDistrict = target.name;
    const error = dropError(measure, target);
    if (error) { button.classList.add("is-blocked"); button.title = error; }
    button.setAttribute("aria-label", `${target.name}${error ? `. ${error}` : ". Доступная цель"}`);
    button.append(node("small", target.kind === "city" ? "◎" : `0${index + 1}`), node("strong", target.name));
    host.append(button);
  });
  $("drop-board-hint").textContent = city(measure) ? "Цель: весь город" : "Выберите один из пяти районов";
}
function targetAt(clientX, clientY) {
  const element = document.elementFromPoint(clientX, clientY);
  const tile = element?.closest("[data-drop-district], [data-drop-city]");
  if (tile?.dataset.dropCity) return { kind: "city", name: "Весь город", element: tile };
  if (tile?.dataset.dropDistrict) return { kind: "district", name: tile.dataset.dropDistrict, element: tile };
  try {
    const name = state.scene?.pickDistrict?.(clientX, clientY);
    if (name && districtNames().includes(name)) return { kind: "district", name, element: null };
  } catch (error) { console.error("City pick failed", error); }
  return null;
}
function moveGhost(drag, clientX, clientY) {
  const rect = drag.ghost.getBoundingClientRect();
  const left = Math.min(window.innerWidth - rect.width - 8, Math.max(8, clientX + 15));
  const top = drag.pointerType === "mouse" ? clientY + 18 : clientY - rect.height - 22;
  drag.ghost.style.left = `${left}px`;
  drag.ghost.style.top = `${Math.max(8, Math.min(window.innerHeight - rect.height - 8, top))}px`;
}
function previewDrop(drag, clientX, clientY) {
  const target = targetAt(clientX, clientY);
  const key = target ? `${target.kind}:${target.name}` : "";
  if (drag.targetKey !== key || drag.target?.element !== target?.element) {
    document.querySelectorAll(".is-hot-drop").forEach((item) => item.classList.remove("is-hot-drop", "is-invalid-drop"));
    drag.targetKey = key;
    drag.target = target;
    const error = dropError(drag.measure, target);
    drag.ghost.classList.toggle("is-denied", Boolean(target && error));
    drag.ghost.classList.toggle("is-over", Boolean(target && !error));
    if (target?.element) {
      target.element.classList.add("is-hot-drop");
      target.element.classList.toggle("is-invalid-drop", Boolean(error));
    }
    if (key) $("drop-board-hint").textContent = error || `${drag.measure.id} → ${target.name}`;
    else $("drop-board-hint").textContent = city(drag.measure) ? "Цель: весь город" : "Выберите один из пяти районов";
    try { state.scene?.setDropPreview?.(target?.kind === "district" && !error ? target.name : null); }
    catch (error) { console.error("City drop preview failed", error); }
  }
}
function startMeasureDrag(drag, clientX, clientY) {
  drag.started = true;
  renderDropBoard(drag.measure);
  $("drop-board").hidden = false;
  document.body.classList.add("is-dragging-measure");
  drag.source.classList.add("is-being-dragged");
  drag.ghost = node("div", null, "drag-ghost");
  drag.ghost.append(node("small", `${drag.measure.id} / ${drag.measure.category}`), node("strong", drag.measure.name), node("b", `${format(drag.measure.cost, 0)} ед.`));
  document.body.append(drag.ghost);
  state.hoverMeasureId = drag.measure.id;
  syncScene();
  moveGhost(drag, clientX, clientY);
  previewDrop(drag, clientX, clientY);
}
function finishMeasureDrag(event, cancelled = false) {
  const drag = state.drag;
  if (!drag || event?.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  state.drag = null;
  try { drag.source.releasePointerCapture?.(drag.pointerId); } catch (_) { /* capture may already be released */ }
  if (!drag.started) {
    if (!cancelled && drag.pointerType === "mouse" && !drag.fromGrip) openMeasure(drag.measure.id);
    else if (cancelled) { state.hoverMeasureId = null; syncScene(); }
    return;
  }
  if (drag.fromGrip) {
    drag.source.dataset.justDragged = "true";
    setTimeout(() => { delete drag.source.dataset.justDragged; }, 450);
  }
  if (event && !cancelled) previewDrop(drag, event.clientX, event.clientY);
  // A slight finger slip should behave like a tap, even if the board appeared
  // underneath the finger while it was still near the source card.
  const shortTravel = !cancelled && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < (drag.pointerType === "mouse" ? 18 : 28);
  const target = cancelled || shortTravel ? null : drag.target;
  const error = cancelled ? "" : dropError(drag.measure, target);
  document.body.classList.remove("is-dragging-measure");
  $("drop-board").hidden = true;
  document.querySelectorAll(".is-hot-drop").forEach((item) => item.classList.remove("is-hot-drop", "is-invalid-drop"));
  drag.source.classList.remove("is-being-dragged");
  state.hoverMeasureId = null;
  try { state.scene?.setDropPreview?.(null); } catch (_) { /* optional scene API */ }
  if (drag.ghost) {
    if (target && !error) {
      const rect = target.element?.getBoundingClientRect();
      const centerX = rect ? rect.left + rect.width / 2 : event.clientX;
      const centerY = rect ? rect.top + rect.height / 2 : event.clientY;
      drag.ghost.classList.add("is-snapping");
      drag.ghost.style.left = `${centerX - drag.ghost.offsetWidth / 2}px`;
      drag.ghost.style.top = `${centerY - drag.ghost.offsetHeight / 2}px`;
      setTimeout(() => drag.ghost.remove(), 180);
    } else drag.ghost.remove();
  }
  if (shortTravel) { syncScene(); openMeasure(drag.measure.id); }
  else if (!cancelled && error) { syncScene(); notice(error, true); dragMessage(error, true); }
  else if (!cancelled && target) {
    const decision = { measure_id: drag.measure.id, district: target.kind === "city" ? null : target.name };
    const next = [...state.decisions, decision];
    setDecisions(next);
    const message = `${drag.measure.id} направлена: ${target.name}. ${next.length} из 5 решений, ${format(costOf(next), 0)} из ${format(budget(), 0)} ед. бюджета.`;
    dragMessage(message);
  } else syncScene();
}
function beginMeasureDrag(measureId, event, source, fromGrip = false) {
  if (state.drag || locked() || state.stage !== "planner" || event.button !== 0 && event.pointerType === "mouse") return;
  if (event.pointerType !== "mouse" && !fromGrip) return;
  const measure = measureById(measureId);
  if (!measure || state.decisions.some((item) => item.measure_id === measureId)) return;
  if (event.pointerType === "mouse" && !fromGrip && event.target.closest("button, a, input, select, textarea")) return;
  state.drag = { measure, source, fromGrip, pointerId: event.pointerId, pointerType: event.pointerType, x: event.clientX, y: event.clientY, started: false, target: null, targetKey: "", ghost: null };
  try { source.setPointerCapture(event.pointerId); } catch (_) { /* drag still works through window listeners */ }
}
window.addEventListener("pointermove", (event) => {
  const drag = state.drag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  if (!drag.started && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < (drag.pointerType === "mouse" ? 7 : 10)) return;
  if (!drag.started) startMeasureDrag(drag, event.clientX, event.clientY);
  event.preventDefault();
  moveGhost(drag, event.clientX, event.clientY);
  previewDrop(drag, event.clientX, event.clientY);
}, { passive: false });
window.addEventListener("pointerup", (event) => finishMeasureDrag(event));
window.addEventListener("pointercancel", (event) => finishMeasureDrag(event, true));
window.addEventListener("blur", () => finishMeasureDrag(null, true));
window.addEventListener("keydown", (event) => { if (event.key === "Escape" && state.drag) finishMeasureDrag(null, true); });
function renderMeasures() {
  state.hoverMeasureId = null;
  syncScene();
  const host = $("measure-cards");
  host.replaceChildren();
  const weak = new Set(weakNeeds(state.selectedDistrict).map(([key]) => key));
  const relevant = (measure) => city(measure) || Object.entries(measure.full_effects || {}).some(([key, value]) => weak.has(key) && value > 0);
  const visible = state.measures.filter((item) =>
    (state.category === "Все" || item.category === state.category)
    && (state.measureView === "all" || relevant(item)));
  visible.sort((a, b) => Number(relevant(b)) - Number(relevant(a)) || Number(a.id.slice(1)) - Number(b.id.slice(1)));
  $("catalog-count").textContent = `${visible.length} из ${state.measures.length} мер`;
  $("measure-context").textContent = state.measureView === "district"
    ? `Меры, улучшающие слабые показатели района ${state.selectedDistrict}, и все городские меры.`
    : "Все пять направлений и 14 мер. Районные меры назначаются при выборе.";
  $("view-district-measures").setAttribute("aria-pressed", String(state.measureView === "district"));
  $("view-all-measures").setAttribute("aria-pressed", String(state.measureView === "all"));
  if (!visible.length) {
    const empty = node("div", null, "measure-empty");
    empty.append(node("strong", "В этой категории нет мер под две главные задачи района."));
    const showAll = node("button", "Показать все 14 мер", "text-button");
    showAll.type = "button";
    showAll.addEventListener("click", () => { state.measureView = "all"; state.category = "Все"; renderCategories(); renderMeasures(); });
    empty.append(showAll); host.append(empty); return;
  }
  visible.forEach((measure) => {
    const selected = state.decisions.some((decision) => decision.measure_id === measure.id);
    const card = node("article", null, `measure-card${selected ? " is-selected" : ""}`);
    card.dataset.measureId = measure.id;
    const top = node("div", null, "measure-card-top");
    const symbol = node("span", null, "category-icon");
    symbol.dataset.category = measure.category;
    symbol.append(icon(categoryIcons[measure.category] || "city"));
    const price = node("span", format(measure.cost, 0), "measure-cost");
    price.append(node("small", "ед."));
    top.append(symbol, price);
    const meta = node("div", null, "measure-meta");
    const scope = node("span");
    scope.append(icon("city"), document.createTextNode(city(measure) ? "Все пять районов" : state.selectedDistrict));
    meta.append(scope);
    if (finite(measure.lag_quarters)) {
      const lag = node("span");
      lag.append(icon("clock"), document.createTextNode(`Эффект через ${measure.lag_quarters} кв.`));
      meta.append(lag);
    }
    const match = Object.entries(measure.full_effects || {}).filter(([key, value]) => weak.has(key) && value > 0).map(([key]) => key);
    if (match.length) card.append(node("span", `К задаче: ${match.map(indicatorName).join(" · ")}`, "measure-relevance"));
    const button = node("button", null, "measure-select");
    button.type = "button";
    button.disabled = selected || locked();
    button.setAttribute("aria-label", selected ? `${measure.id} уже в пакете` : `Выбрать ${measure.id}: ${measure.name}`);
    button.append(node("span", selected ? "В вашем пакете" : "Направить меру"), icon(selected ? "check" : "plus"));
    button.addEventListener("click", () => openMeasure(measure.id));
    const grip = node("button", null, `measure-drag-grip${!selected && state.decisions.length === 0 && visible[0] === measure ? " is-demo" : ""}`);
    grip.type = "button";
    grip.disabled = selected || locked();
    grip.setAttribute("aria-label", `Перетащить ${measure.id}: ${measure.name}. Для обычного выбора нажмите кнопку`);
    grip.title = "Перетащить на район или весь город";
    grip.append(node("span", "⠿", "grip-mark"));
    grip.addEventListener("pointerdown", (event) => beginMeasureDrag(measure.id, event, grip, true));
    grip.addEventListener("click", () => { if (!grip.dataset.justDragged) openMeasure(measure.id); delete grip.dataset.justDragged; });
    const actions = node("div", null, "measure-actions"); actions.append(button, grip);
    const highlight = () => { if (!state.drag?.started) { state.hoverMeasureId = measure.id; syncScene(); } };
    const unhighlight = () => { if (!state.drag?.started && state.hoverMeasureId === measure.id) { state.hoverMeasureId = null; syncScene(); } };
    card.addEventListener("pointerdown", (event) => beginMeasureDrag(measure.id, event, card));
    card.addEventListener("pointerenter", highlight);
    card.addEventListener("pointerleave", unhighlight);
    card.addEventListener("focusin", highlight);
    card.addEventListener("focusout", (event) => { if (!card.contains(event.relatedTarget)) unhighlight(); });
    card.append(top, node("p", `${measure.id} / ${categoryLabels[measure.category] || measure.category}`, "measure-category"), node("h3", measure.name), meta, actions);
    host.append(card);
  });
}
function renderSlots() {
  const host = $("decision-slots");
  host.replaceChildren();
  for (let index = 0; index < 5; index += 1) {
    const decision = state.decisions[index];
    const slot = node("div", null, `decision-slot${decision ? "" : " is-empty"}`);
    slot.append(node("span", String(index + 1).padStart(2, "0"), "decision-number"));
    if (!decision) slot.append(node("span", "Место для вашего решения"));
    else {
      const measure = measureById(decision.measure_id);
      const copy = node("div", null, "decision-copy");
      copy.append(node("strong", measure.name));
      const location = node("button", null, "decision-location");
      location.type = "button";
      location.disabled = city(measure) || locked();
      location.append(node("span", city(measure) ? "Весь город" : decision.district));
      if (!city(measure)) location.append(icon("arrow"));
      location.setAttribute("aria-label", `Район для ${measure.id}: ${decision.district || "весь город"}${city(measure) ? "" : ". Изменить район"}`);
      location.addEventListener("click", () => openMeasure(measure.id, index));
      copy.append(location);
      const right = node("div", null, "decision-right");
      const remove = node("button", null, "icon-button");
      remove.type = "button";
      remove.disabled = locked();
      remove.setAttribute("aria-label", `Убрать ${measure.id}: ${measure.name}`);
      remove.append(icon("close"));
      remove.addEventListener("click", () => {
        if (locked()) return;
        setDecisions(state.decisions.filter((_, position) => position !== index), `Распоряжение ${measure.id} убрано из пакета.`);
        const next = host.querySelector("button:not(:disabled)") || $("catalog-title");
        if (next.tagName !== "BUTTON") next.setAttribute("tabindex", "-1");
        next.focus({ preventScroll: true });
      });
      right.append(node("span", format(measure.cost, 0)), remove);
      slot.append(copy, right);
    }
    host.append(slot);
  }
}
function updateBudget() {
  const spent = costOf(state.decisions);
  const missing = 5 - state.decisions.length;
  $("deck-count").textContent = `${state.decisions.length}/5`;
  $("deck-budget").textContent = `${format(spent, 0)}/${format(budget(), 0)}`;
  $("mobile-plan-count").textContent = `${state.decisions.length} из 5 решений`;
  $("mobile-plan-budget").textContent = `${format(spent, 0)} / ${format(budget(), 0)} ед.`;
  $("decision-count").textContent = `${state.decisions.length} / 5`;
  $("budget-used").textContent = format(spent, 0);
  document.querySelector(".budget-total").textContent = `/ ${format(budget(), 0)}`;
  $("budget-fill").style.width = `${Math.min(100, spent / budget() * 100)}%`;
  $("budget-progress").setAttribute("aria-valuemax", String(budget()));
  $("budget-progress").setAttribute("aria-valuenow", String(Math.min(spent, budget())));
  $("budget-progress").closest(".budget-block").classList.toggle("over-budget", spent > budget());
  $("budget-hint").textContent = spent > budget() ? `Бюджет превышен на ${format(spent - budget(), 0)} ед.` : `На оставшиеся решения: ${format(budget() - spent, 0)} ед.`;
  const errors = validate(state.decisions, true);
  $("submit-plan").disabled = !!state.busy || errors.length > 0;
  $("submit-plan").querySelector("span").textContent = state.busy === "simulate" ? "Считаем последствия…" : "Подписать распоряжения";
  $("suggest-plan").disabled = !!state.busy;
  $("compare-plan").disabled = !!state.busy || !state.result;
  $("compare-plan").querySelector("span").textContent = state.busy === "optimize" ? "Оптимизатор считает план…" : "Сравнить с оптимумом";
  $("recommend-change").disabled = !!state.busy || !state.result;
  $("recommend-change").querySelector("span").textContent = state.busy === "recommend" ? "Ищем одну замену…" : "Улучшить одно распоряжение";
  $("suggest-plan").querySelector("span").textContent = state.busy === "optimize" ? "Оптимизатор считает план…" : "Оптимум по Score";
  $("sign-hint").textContent = state.busy === "simulate" ? "Проверяем пакет и готовим итоговый доклад" : state.busy === "optimize" ? "Оптимизатор рассчитывает вариант. Ваш пакет сохранён." : missing > 0 ? `Добавьте ещё ${missing} ${missing === 1 ? "распоряжение" : missing < 5 ? "распоряжения" : "распоряжений"}` : errors[0] || "Пакет готов к проверке и расчёту";
}
function renderPlanner() { renderCategories(); renderMeasures(); renderSlots(); updateBudget(); }
function setBusy(kind) {
  state.busy = kind;
  $("stage-planner").setAttribute("aria-busy", String(!!kind));
  $("example-scenario").disabled = !!kind;
  $("example-scenario").querySelector("span").textContent = kind === "simulate" ? "Считаем сценарий…" : "Показать проверочный сценарий";
  renderMeasures(); renderSlots(); updateBudget();
}
function pendingDecisions() {
  const pending = state.pending;
  const decision = { measure_id: pending.measureId, district: pending.district };
  return pending.editingIndex === null ? [...state.decisions, decision] : state.decisions.map((item, index) => index === pending.editingIndex ? decision : item);
}
function updatePending() {
  if (!state.pending) return;
  const errors = validate(pendingDecisions());
  const validation = $("measure-validation");
  validation.replaceChildren();
  errors.forEach((error) => validation.append(node("p", error)));
  validation.classList.toggle("is-neutral", errors.length === 1 && errors[0] === "Выберите район для распоряжения.");
  $("confirm-measure").disabled = errors.length > 0 || locked();
}
function openMeasure(measureId, editingIndex = null) {
  if (locked()) return;
  const measure = measureById(measureId);
  if (!measure) return;
  state.pending = { measureId, editingIndex, district: city(measure) ? null : editingIndex !== null ? state.decisions[editingIndex].district : state.selectedDistrict };
  syncScene();
  $("measure-category").textContent = `${measure.id} / ${categoryLabels[measure.category] || measure.category}`;
  $("measure-title").textContent = measure.name;
  const facts = $("measure-facts");
  facts.replaceChildren();
  const price = node("span"); price.append(node("strong", format(measure.cost, 0)), document.createTextNode("ед. бюджета"));
  facts.append(price);
  if (finite(measure.lag_quarters)) {
    const lag = node("span", null, "lag-fact");
    lag.append(node("strong", String(measure.lag_quarters)), document.createTextNode(`из ${horizon()} кварталов до эффекта`));
    facts.append(lag);
  }
  const effects = $("measure-effects"); effects.replaceChildren();
  const effectEntries = Object.entries(measure.full_effects || {}).filter(([, value]) => finite(value));
  effectEntries.forEach(([key, value]) => {
    const effect = node("span", null, `effect${value < 0 ? " is-negative" : ""}`);
    effect.append(node("span", indicatorName(key)), node("b", `${value > 0 ? "+" : ""}${format(value, Number.isInteger(value) ? 0 : 1)}`));
    effects.append(effect);
  });
  if (!effectEntries.length) effects.append(node("span", "Эффекты покажем в итоговом расчёте.", "effect"));
  $("district-choice-section").hidden = city(measure);
  $("city-scope-note").hidden = !city(measure);
  const options = $("district-options"); options.replaceChildren();
  if (!city(measure)) districtNames().forEach((name) => {
    const label = node("label", null, "district-option");
    const input = document.createElement("input");
    input.type = "radio"; input.name = "measure-district"; input.value = name;
    input.checked = state.pending.district === name;
    input.addEventListener("change", () => { state.pending.district = name; selectDistrict(name); updatePending(); syncScene(); });
    label.append(input, node("span", name), node("small", format(state.catalog.districts[name].score)));
    options.append(label);
  });
  $("confirm-measure").replaceChildren(document.createTextNode(editingIndex === null ? "Включить в пакет" : "Сохранить район"), icon(editingIndex === null ? "plus" : "check"));
  updatePending();
  $("measure-dialog").showModal();
  syncScene();
  const focusTarget = options.querySelector("input:checked") || options.querySelector("input") || $("confirm-measure");
  if (!focusTarget.disabled) focusTarget.focus();
}
function confirmMeasure() {
  if (!state.pending || locked()) return;
  const decisions = pendingDecisions();
  if (validate(decisions).length) { updatePending(); return; }
  const id = state.pending.measureId;
  const slotIndex = decisions.findIndex((decision) => decision.measure_id === id);
  $("measure-dialog").close();
  setDecisions(decisions, `Распоряжение ${id} в пакете. Выбрано ${decisions.length} из пяти.`);
  const focusTarget = $("decision-slots").children[slotIndex]?.querySelector("button:not(:disabled)");
  focusTarget?.focus({ preventScroll: true });
}
async function requestJson(url, options = {}) {
  const controller = new AbortController();
  // Result routes may include a model call (NVIDIA alone can take 45 seconds).
  const timeoutMs = url === API.catalog ? 30000 : 75000;
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally { clearTimeout(timeout); }
}
function showPlanErrors(errors) {
  const host = $("plan-errors");
  host.replaceChildren();
  const list = node("ul");
  errors.forEach((error) => list.append(node("li", typeof error === "string" ? error : "Сервер отклонил пакет решений.")));
  host.append(list); host.hidden = false;
  state.result = null; syncNavigation(); renderDistrictRail(); renderInspector(); syncScene();
  announce("Пакет не подписан. Проверьте причины рядом с распоряжениями.");
  host.scrollIntoView({ behavior: "smooth", block: "center" });
}
function displayExplanation(explanation) {
  const host = $("explanation"); host.replaceChildren();
  const source = $("explanation-source");
  if (explanation?.source === "model") source.textContent = `AI-разбор на основе рассчитанных фактов${explanation.provider === "nvidia" ? " · NVIDIA" : ""}`;
  else if (explanation?.source === "computed_facts") source.textContent = "AI-модель недоступна. Показан разбор по рассчитанным фактам.";
  else source.textContent = "Пояснение к результату сервера";
  const content = typeof explanation === "string" ? explanation : explanation?.text;
  if (typeof content !== "string" || !content.trim()) { host.append(node("p", "Советник сейчас недоступен. Результаты расчёта сохранены в докладе.")); return; }
  // Explanations are assembled from server facts. Localize labels and decimal
  // punctuation only; the simulator's values and Score are displayed unchanged.
  const displayText = ["computed_facts", "model"].includes(explanation?.source)
    ? content.replace(/\b[A-Z][0-9]\b/g, (key) => state.catalog?.indicators?.[key]?.name || key)
      .replace(/(\d)\.(\d)/g, "$1,$2")
    : content;
  displayText.trim().split(/\n+/).filter(Boolean).forEach((line) => {
    const match = line.match(/^(Сильные стороны|Риски|Компромиссы):\s*(.*)$/);
    if (match) {
      const section = node("section", null, "explanation-block");
      section.append(node("h3", match[1]), node("p", match[2])); host.append(section);
    } else host.append(node("p", line));
  });
}
function renderReport(result, decisions) {
  $("result-base").textContent = format(result.base_score);
  $("result-score").textContent = format(result.score);
  const delta = result.score_delta;
  $("result-change").hidden = !finite(delta);
  $("result-change").textContent = `${delta >= 0 ? "+" : ""}${format(delta)} к базе`;
  $("result-change").classList.toggle("is-negative", delta < 0);
  $("result-cost").textContent = `${format(result.cost, 0)} / ${format(budget(), 0)}`;
  $("result-remaining").textContent = `${format(result.remaining_budget, 0)} ед.`;
  $("result-critical").textContent = format(result.critical_count, 0);
  $("report-horizon").textContent = `ЧЕРЕЗ ${horizon()} КВАРТАЛОВ`;
  const chart = $("district-chart"); chart.replaceChildren();
  if (typeof window.renderDistrictCharts === "function") {
    try { window.renderDistrictCharts(chart, result); }
    catch (error) { console.error("District visualization unavailable", error); chart.replaceChildren(); }
  }
  const fallback = $("district-list"); fallback.replaceChildren();
  fallback.hidden = chart.childElementCount > 0;
  if (!chart.childElementCount) Object.entries(result.districts || {}).forEach(([name, values]) => {
    const row = node("div", null, "district-result-row"); row.append(node("span", name), node("strong", format(values?.score))); fallback.append(row);
  });
  const synergies = $("synergies"); synergies.replaceChildren();
  (result.applied_synergies || []).forEach((synergy) => {
    if (!Array.isArray(synergy.measures) || !finite(synergy.bonus)) return;
    synergies.append(node("p", `${synergy.measures.join(" + ")}: ${indicatorName(synergy.indicator)} +${format(synergy.bonus, 0)} · ${synergy.district}`));
  });
  displayExplanation(result.explanation);
  clearAdvisorResponse();
  const signed = $("signed-decisions"); signed.replaceChildren();
  decisions.forEach((decision, index) => {
    const measure = measureById(decision.measure_id);
    const card = node("article", null, "signed-decision");
    const number = node("span", `РАСПОРЯЖЕНИЕ 0${index + 1}`, "decision-number"); number.append(icon("check"));
    card.append(number, node("strong", measure.name), node("small", `${decision.district || "Весь город"} · ${format(measure.cost, 0)} ед.`));
    signed.append(card);
  });
}
async function calculate() {
  if (state.busy) return;
  const errors = validate(state.decisions, true);
  if (errors.length) { showPlanErrors(errors); return; }
  const revision = state.revision;
  const decisions = state.decisions.map((item) => ({ ...item }));
  state.result = null; state.proposal = null; $("comparison").hidden = true;
  renderDistrictRail(); renderInspector(); syncScene();
  syncNavigation(); notice(""); $("plan-errors").hidden = true;
  setBusy("simulate"); announce("Проверяем распоряжения и готовим доклад.");
  try {
    const result = await requestJson(API.simulate, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decisions }) });
    if (revision !== state.revision) return;
    if (result?.valid !== true || !finite(result.score)) {
      showPlanErrors(Array.isArray(result?.errors) && result.errors.length ? result.errors : ["Сервер не подтвердил результат. Попробуйте ещё раз."]); return;
    }
    state.result = result;
    state.resultView = "after";
    renderReport(result, decisions);
    setStage("report"); announce(`Пять распоряжений подписаны. Итоговый Score ${format(result.score)}.`);
  } catch (error) {
    console.error("Simulation request failed", error);
    if (revision === state.revision) showPlanErrors(["Не удалось получить расчёт. Ваш пакет сохранён — попробуйте подписать его ещё раз."]);
  } finally { setBusy(null); }
}
function validateProposal(result) {
  if (result?.valid !== true || !finite(result.score) || !finite(result.cost) || !Array.isArray(result.decisions) || result.decisions.length !== 5) throw new Error("Incomplete proposal");
  const decisions = result.decisions.map((decision) => ({ measure_id: decision?.measure_id, district: decision?.district }));
  if (validate(decisions, true).length) throw new Error("Invalid proposal");
  return decisions;
}
function signed(value) { return finite(value) ? `${value >= 0 ? "+" : ""}${format(value)}` : "—"; }
function renderComparison(current, proposed, decisions) {
  const host = $("comparison");
  host.hidden = !current;
  $("suggestion-dialog").classList.toggle("has-comparison", Boolean(current));
  if (!current) return;
  $("comparison-gap").textContent = `${signed(proposed.score - current.score)} к вашему Score`;
  const summary = $("comparison-summary"); summary.replaceChildren();
  for (const [label, result] of [["Ваш план", current], ["Рекомендация", proposed]]) {
    const affected = districtNames().filter((name) => Object.values(result.deltas?.[name] || {}).some((delta) => finite(delta) && delta !== 0)).length;
    const card = node("div", null, "comparison-stat");
    card.append(node("small", label), node("strong", format(result.score)), node("span", `Стоимость ${format(result.cost, 0)} / ${format(budget(), 0)} · затронуто районов: ${affected}`));
    summary.append(card);
  }
  const rows = $("comparison-districts"); rows.replaceChildren();
  const userBetter = [], proposedBetter = [];
  districtNames().forEach((name) => {
    const first = current.districts?.[name]?.score;
    const second = proposed.districts?.[name]?.score;
    const baseline = state.catalog.districts[name]?.score;
    const difference = finite(first) && finite(second) ? second - first : null;
    if (finite(difference) && difference > 0.00001) proposedBetter.push(name);
    if (finite(difference) && difference < -0.00001) userBetter.push(name);
    const scoreWithChange = (score) => finite(score) && finite(baseline) ? `${format(score)} (${signed(score - baseline)})` : format(score);
    const row = node("tr");
    const heading = node("th", name); heading.scope = "row";
    row.append(heading, node("td", scoreWithChange(first)), node("td", scoreWithChange(second)), node("td", signed(difference), finite(difference) && difference < 0 ? "comparison-negative" : "comparison-positive"));
    rows.append(row);
  });
  const tradeoffs = $("comparison-tradeoffs"); tradeoffs.replaceChildren();
  if (finite(current.cost) && finite(proposed.cost)) {
    const costDifference = proposed.cost - current.cost;
    tradeoffs.append(node("p", costDifference === 0 ? "Оба плана тратят одинаковый бюджет." : `Рекомендация тратит на ${format(Math.abs(costDifference), 0)} ед. ${costDifference > 0 ? "больше" : "меньше"}.`));
  }
  tradeoffs.append(node("p", proposedBetter.length ? `Выше районный балл: ${proposedBetter.join(", ")}.` : "Нет районов, где рекомендация повышает районный балл относительно вашего плана."));
  tradeoffs.append(node("p", userBetter.length ? `Ваш план сохраняет более высокий районный балл: ${userBetter.join(", ")}.` : "Нет районов, где ваш план даёт более высокий районный балл."));
  if (finite(current.critical_count) && finite(proposed.critical_count)) tradeoffs.append(node("p", `Показателей ниже 40: ваш план — ${format(current.critical_count, 0)}, рекомендация — ${format(proposed.critical_count, 0)}.`));
  const describe = (items) => items.map(({ measure_id, district }) => `${measure_id} / ${district || "город"}`).join(" · ");
  $("comparison-measures").textContent = `Ваш план: ${describe(state.decisions)}. Рекомендация: ${describe(decisions)}.`;
}
function sameDecisions(first, second) {
  const keys = (items) => items.map((item) => `${item.measure_id}/${item.district || "город"}`).sort().join("|");
  return keys(first) === keys(second);
}
function showSuggestion(result, decisions, explanation = null, removed = [], added = [], improved = true) {
  state.proposal = { result, decisions };
  renderComparison(state.result, result, decisions);
  const summary = $("suggestion-summary"); summary.replaceChildren();
  const score = node("div", "Score по модели"); score.prepend(node("strong", format(result.score)));
  const cost = node("div", "единиц бюджета"); cost.prepend(node("strong", format(result.cost, 0))); summary.append(score, cost);
  const host = $("suggestion-decisions"); host.replaceChildren();
  decisions.forEach((decision, index) => {
    const measure = measureById(decision.measure_id);
    const row = node("div", null, "suggestion-decision");
    const copy = node("div"); copy.append(node("strong", `${measure.id} · ${measure.name}`), node("small", `${decision.district || "Весь город"} · ${format(measure.cost, 0)} ед.`));
    row.append(node("span", String(index + 1).padStart(2, "0"), "decision-number"), copy); host.append(row);
  });
  $("suggestion-summary").hidden = Boolean(state.result);
  const ai = $("suggestion-ai");
  ai.hidden = !explanation;
  if (explanation) {
    const label = (item) => `${item.measure_id}/${item.district || "город"}`;
    $("suggestion-swap").textContent = improved
      ? `${removed.map(label).join(", ")} → ${added.map(label).join(", ")}`
      : "Улучшение заменой одного распоряжения не найдено";
    $("suggestion-ai-text").textContent = explanation.text || "Совет недоступен.";
    $("suggestion-ai-source").textContent = explanation.source === "model"
      ? `AI-разбор проверенных расчётов · ${explanation.provider || "модель"}`
      : "Разбор по рассчитанным фактам. AI-модель недоступна.";
  }
  $("apply-suggestion").hidden = !improved || sameDecisions(state.decisions, decisions);
  $("suggestion-dialog").showModal();
}
async function suggestPlan() {
  if (state.busy) return;
  notice(""); state.proposal = null; setBusy("optimize"); announce("Оптимизатор ищет лучший план по Score. Ваш пакет остаётся у вас.");
  try {
    const result = await requestJson(API.optimize);
    const decisions = validateProposal(result);
    $("suggestion-title").textContent = "Глобальный оптимум заданной модели.";
    $("suggestion-description").textContent = "Лучший допустимый план среди всех комбинаций пяти мер по формуле задачи. Сравните районы перед выбором.";
    showSuggestion(result, decisions);
  } catch (error) {
    console.error("Proposal request failed", error);
    if (state.stage === "report") setStage("planner");
    notice("Оптимизатор сейчас недоступен. Ваши распоряжения сохранены; можно продолжить свой план.", true);
  } finally { setBusy(null); }
}
async function recommendChange() {
  if (state.busy || !state.result) return;
  const revision = state.revision;
  const decisions = state.decisions.map((item) => ({ ...item }));
  setBusy("recommend"); announce("Оптимизатор ищет лучшую замену одного распоряжения.");
  try {
    const answer = await requestJson(API.recommendChange, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decisions })
    });
    if (revision !== state.revision || !state.result) return;
    if (answer?.valid !== true || !finite(answer.proposed?.score) || !finite(answer.current?.score)
        || Math.abs(answer.current.score - state.result.score) > 1e-8) throw new Error("Incomplete comparison");
    const proposed = { ...answer.proposed, decisions: answer.decisions };
    const next = validateProposal(proposed);
    $("suggestion-title").textContent = "Одна замена. Проверенный результат.";
    $("suggestion-description").textContent = "Оптимизатор сохранил четыре ваших решения и проверил лучшую допустимую замену симулятором.";
    showSuggestion(proposed, next, answer.explanation, answer.removed || [], answer.added || [], answer.score_delta > 0);
  } catch (error) {
    console.error("One-change recommendation failed", error);
    announce("Совет по одной замене сейчас недоступен. Ваш план сохранён.");
    notice("Совет по одной замене сейчас недоступен. Ваш план сохранён.", true);
  } finally { setBusy(null); }
}
function clearAdvisorResponse() {
  $("advisor-response").hidden = true;
  $("advisor-error").hidden = true;
  $("advisor-response-text").textContent = "";
  $("advisor-options").replaceChildren();
}
function renderAdvisorAnswer(answer) {
  const advice = answer?.advice;
  if (answer?.valid !== true || typeof advice?.text !== "string" || !advice.text.trim()
      || !Array.isArray(answer.options) || answer.options.length !== 3) throw new Error("Incomplete decision support");
  const byId = new Map();
  for (const option of answer.options) {
    if (!["current", "one_change", "optimum"].includes(option?.id) || byId.has(option.id)
        || typeof option.label !== "string" || !finite(option.result?.score) || !finite(option.result?.cost)) throw new Error("Invalid computed option");
    const decisions = validateProposal({ ...option.result, decisions: option.decisions });
    byId.set(option.id, { ...option, decisions });
  }
  if (byId.size !== 3 || Math.abs(byId.get("current").result.score - state.result.score) > 1e-8) throw new Error("Options do not match current plan");
  $("advisor-response-text").textContent = advice.text.trim();
  $("advisor-response-source").textContent = advice.source === "model"
    ? `AI-разбор проверенных расчётов${advice.model ? ` · ${advice.model}` : ""}`
    : "Разбор по рассчитанным фактам · AI-модель недоступна";
  const host = $("advisor-options"); host.replaceChildren();
  for (const id of ["current", "one_change", "optimum"]) {
    const option = byId.get(id);
    const card = node("article", null, "advisor-option");
    card.append(node("strong", option.label));
    if (advice.source === "model" && advice.selected_option === id) card.append(node("span", "Советник выделил для вашего приоритета", "advisor-option-picked"));
    card.append(node("span", format(option.result.score), "advisor-option-score"));
    card.append(node("small", `${format(option.result.cost, 0)} / ${format(budget(), 0)} ед. бюджета`));
    if (typeof option.tradeoff === "string" && option.tradeoff.trim()) card.append(node("p", option.tradeoff.trim()));
    if (id !== "current" && !sameDecisions(state.decisions, option.decisions)) {
      const button = node("button", "Сравнить с моим планом", "button button-secondary");
      button.type = "button";
      button.addEventListener("click", () => {
        if (state.busy || !state.result) return;
        $("suggestion-title").textContent = id === "optimum" ? "Оптимум заданной модели." : "Одна замена. Проверенный результат.";
        $("suggestion-description").textContent = id === "optimum"
          ? "Лучший допустимый план по Score среди всех комбинаций пяти мер. Сравните районы перед выбором."
          : "Лучшая допустимая замена одного распоряжения по Score. Сравните районы перед выбором.";
        showSuggestion(option.result, option.decisions);
      });
      card.append(button);
    }
    host.append(card);
  }
  $("advisor-response").hidden = false;
}
async function askAdvisor(event) {
  event.preventDefault();
  if (state.adviceBusy || !state.result || state.busy) return;
  const question = $("advisor-priority").value.trim();
  if (!question) { $("advisor-priority").focus(); return; }
  const revision = state.revision;
  const score = state.result.score;
  const decisions = state.decisions.map((item) => ({ ...item }));
  clearAdvisorResponse();
  state.adviceBusy = true;
  $("advisor-priority").disabled = true;
  $("ask-advisor").disabled = true;
  $("ask-advisor").textContent = "Советник разбирает варианты…";
  announce("Советник сопоставляет ваш приоритет с рассчитанными вариантами.");
  try {
    const answer = await requestJson(API.advice, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decisions, question })
    });
    if (revision !== state.revision || !state.result || score !== state.result.score) return;
    renderAdvisorAnswer(answer);
    announce("Разбор вашего приоритета готов. Показаны три рассчитанных варианта.");
  } catch (error) {
    console.error("Decision support unavailable", error);
    if (revision === state.revision) {
      $("advisor-error").textContent = "Не удалось разобрать приоритет. Ваш план и результаты расчёта сохранены; попробуйте ещё раз.";
      $("advisor-error").hidden = false;
      announce("Советник сейчас недоступен. Ваш план сохранён.");
    }
  } finally {
    state.adviceBusy = false;
    $("advisor-priority").disabled = false;
    $("ask-advisor").disabled = false;
    $("ask-advisor").replaceChildren(document.createTextNode("Разобрать варианты "), icon("arrow"));
  }
}
function applySuggestion() {
  if (!state.proposal || state.busy) return;
  const decisions = state.proposal.decisions;
  $("suggestion-dialog").close();
  setDecisions(decisions, "Рассчитанный план перенесён в пакет. Его можно изменить перед подписанием.");
  setStage("planner");
  notice("Рассчитанный план в вашем пакете. Проверьте пять распоряжений и подпишите, когда будете готовы.");
}
async function start() {
  $("loading").hidden = false; $("load-error").hidden = true;
  try {
    const catalog = await requestJson(API.catalog);
    if (!catalog || !finite(catalog.base_score) || !catalog.districts || typeof catalog.districts !== "object" || !Object.keys(catalog.districts).length || !catalog.measures || typeof catalog.measures !== "object") throw new Error("Incomplete catalogue");
    const measures = Object.entries(catalog.measures).map(([id, measure]) => ({ ...measure, id }));
    if (!measures.length || measures.some((item) => typeof item.name !== "string" || typeof item.category !== "string" || !finite(item.cost) || !["city", "district"].includes(item.scope))) throw new Error("Invalid measures");
    state.catalog = catalog;
    state.measures = measures.sort((a, b) => Number(a.id.slice(1)) - Number(b.id.slice(1)));
    state.selectedDistrict = Object.entries(catalog.districts)
      .filter(([, value]) => finite(value?.score))
      .sort((a, b) => a[1].score - b[1].score)[0]?.[0] || Object.keys(catalog.districts)[0];
    renderBriefing(); renderPlanner(); syncNavigation();
    $("app").hidden = false;
    requestAnimationFrame(() => {
      const host = $("city-scene");
      if (typeof window.createCityScene === "function") {
        try { state.scene?.destroy(); state.scene = window.createCityScene(host, { onSelect: (name) => selectDistrict(name) }); $("app").classList.add("has-scene"); syncScene(); }
        catch (error) { console.error("City scene unavailable", error); host.textContent = "Выберите район в строке под схемой."; }
      } else host.textContent = "Выберите район в строке под схемой.";
    });
  } catch (error) {
    console.error("Catalogue request failed", error);
    $("load-error-text").textContent = "Исходные данные города недоступны. Проверьте, что приложение запущено, и повторите попытку.";
    $("load-error").hidden = false;
  } finally { $("loading").hidden = true; }
}

document.querySelectorAll("[data-stage]").forEach((button) => button.addEventListener("click", () => setStage(button.dataset.stage)));
function openPlannerAtCatalog(view) {
  state.measureView = view;
  state.category = "Все";
  setStage("planner");
  renderMeasures();
  requestAnimationFrame(() => {
    const title = $("catalog-title");
    title.setAttribute("tabindex", "-1");
    title.scrollIntoView({ block: "start", behavior: "instant" });
    title.focus({ preventScroll: true });
  });
}
function showVerificationScenario() {
  if (!state.catalog || state.busy) return;
  setDecisions(VERIFICATION_DECISIONS, "Проверочный пакет загружен. Сервер рассчитывает его по обычным правилам.");
  setStage("planner");
  calculate();
}
$("start-shift").addEventListener("click", () => openPlannerAtCatalog("all"));
$("example-scenario").addEventListener("click", showVerificationScenario);
$("district-action").addEventListener("click", () => {
  if (state.stage === "report") {
    setStage("planner");
    requestAnimationFrame(() => $("portfolio-title").scrollIntoView({ block: "start", behavior: "instant" }));
    return;
  }
  openPlannerAtCatalog("district");
});
$("view-district-measures").addEventListener("click", () => { state.measureView = "district"; renderMeasures(); $("view-district-measures").focus({ preventScroll: true }); });
$("view-all-measures").addEventListener("click", () => { state.measureView = "all"; renderMeasures(); $("view-all-measures").focus({ preventScroll: true }); });
$("view-before").addEventListener("click", () => { state.resultView = "before"; renderDistrictRail(); renderInspector(); syncScene(); });
$("view-after").addEventListener("click", () => { state.resultView = "after"; renderDistrictRail(); renderInspector(); syncScene(); });
$("retry-catalog").addEventListener("click", start);
$("confirm-measure").addEventListener("click", confirmMeasure);
$("submit-plan").addEventListener("click", calculate);
$("suggest-plan").addEventListener("click", suggestPlan);
$("compare-plan").addEventListener("click", () => { if (state.result) suggestPlan(); });
$("recommend-change").addEventListener("click", recommendChange);
$("advisor-priority").addEventListener("input", clearAdvisorResponse);
$("advisor-form").addEventListener("submit", askAdvisor);
$("mobile-plan-jump").addEventListener("click", () => {
  const title = $("portfolio-title");
  title.setAttribute("tabindex", "-1");
  title.focus({ preventScroll: true });
  title.scrollIntoView({ block: "start" });
});
$("apply-suggestion").addEventListener("click", applySuggestion);
$("keep-my-plan").addEventListener("click", () => $("suggestion-dialog").close());
document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => {
  const rect = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
}));
$("measure-dialog").addEventListener("close", () => { state.pending = null; state.hoverMeasureId = null; syncScene(); });
start();
