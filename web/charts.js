/* Result-only visualizations. All values come from the simulator response. */
(() => {
  "use strict";

  const INDICATORS = {
    T1: "Разгрузка дорог", T2: "Общественный транспорт",
    E1: "Озеленение", E2: "Качество воздуха",
    S1: "Школы и детсады", S2: "Медпомощь",
    B1: "Безопасность улиц", B2: "Безопасность движения",
    C1: "Надёжность ЖКХ", C2: "Обращения жителей"
  };
  const format = (value, digits = 2) => Number(value).toFixed(digits).replace(".", ",");
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const element = (tag, className, label) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (label !== undefined) node.textContent = label;
    return node;
  };
  const clamp = (value) => Math.max(0, Math.min(100, value));

  function drawScore(container, result, districts) {
    const average = result.population_weighted_average;
    const worst = Math.min(...districts.map(([, item]) => item.score));
    const critical = result.critical_count;
    if (![average, worst, critical, result.score].every(finite)) return;

    const section = element("section", "district-viz__score");
    section.setAttribute("aria-label", "Состав итогового показателя качества жизни");
    section.append(element("h4", "district-viz__heading", "Из чего складывается Score"));
    const formula = element("p", "district-viz__formula",
      `0,7 × ${format(average)} + 0,3 × ${format(worst)} − ${critical} = ${format(result.score)}`);
    section.append(formula);

    const components = [
      { name: "Средний с учётом населения", value: 0.7 * average, tone: "average" },
      { name: "Худший район", value: 0.3 * worst, tone: "worst" }
    ];
    const bar = element("div", "district-viz__composition");
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", components.map((item) => `${item.name}: ${format(item.value)}`).join("; ") +
      `; штраф за ${critical} критических показателей: −${critical}; итог: ${format(result.score)}`);
    components.forEach(({ value, tone }) => {
      const segment = element("span", `district-viz__segment district-viz__segment--${tone}`);
      segment.style.width = `${clamp(value)}%`;
      bar.append(segment);
    });
    section.append(bar);
    const legend = element("div", "district-viz__legend");
    components.forEach(({ name, value, tone }) => {
      const item = element("span", `district-viz__legend-item district-viz__legend-item--${tone}`,
        `${name}: +${format(value)}`);
      legend.append(item);
    });
    legend.append(element("span", "district-viz__legend-item district-viz__legend-item--penalty",
      `Критические показатели: −${critical}`));
    section.append(legend);
    container.append(section);
  }

  function drawDistricts(container, result, districts) {
    const section = element("section", "district-viz__districts");
    section.setAttribute("aria-label", "Баллы и изменения по районам");
    section.append(element("h4", "district-viz__heading", "Пять районов после решений"));
    const list = element("div", "district-viz__list");
    districts.forEach(([name, data]) => {
      if (!finite(data.score)) return;
      const item = element("div", "district-viz__district");
      const heading = element("div", "district-viz__district-heading");
      heading.append(element("strong", "", name));
      heading.append(element("span", "", format(data.score)));
      item.append(heading);
      const track = element("div", "district-viz__track");
      track.setAttribute("role", "meter");
      track.setAttribute("aria-label", `Балл района ${name}`);
      track.setAttribute("aria-valuemin", "0");
      track.setAttribute("aria-valuemax", "100");
      track.setAttribute("aria-valuenow", String(data.score));
      track.setAttribute("aria-valuetext", `${format(data.score)} из 100`);
      const fill = element("span", "district-viz__fill");
      fill.style.width = `${clamp(data.score)}%`;
      track.append(fill);
      item.append(track);
      const deltaData = result.deltas?.[name];
      const keyChanges = deltaData && typeof deltaData === "object"
        ? Object.entries(deltaData)
          .filter(([key, value]) => key in INDICATORS && finite(value) && value !== 0)
          .sort((left, right) => Math.abs(right[1]) - Math.abs(left[1]) || left[0].localeCompare(right[0]))
          .slice(0, 3)
        : [];
      const deltaLine = element("div", "district-viz__changes");
      if (keyChanges.length === 0) {
        deltaLine.append(element("span", "district-viz__unchanged", "Без изменений показателей"));
      } else {
        keyChanges.forEach(([key, value]) => {
          const label = `${INDICATORS[key]}: ${value > 0 ? "+" : ""}${format(value, 1)}`;
          deltaLine.append(element("span", value > 0 ? "district-viz__change" : "district-viz__change district-viz__change--negative", label));
        });
      }
      item.append(deltaLine);
      list.append(item);
    });
    section.append(list);
    section.append(element("p", "district-viz__note", "Дельты — изменение показателей по шкале 0–100. Показаны три крупнейших изменения каждого района."));
    container.append(section);
  }

  window.renderDistrictCharts = function renderDistrictCharts(container, result) {
    if (!container || typeof container.replaceChildren !== "function") return;
    container.replaceChildren();
    if (!result?.valid || !result.districts || typeof result.districts !== "object") return;
    const districts = Object.entries(result.districts)
      .filter(([, data]) => data && finite(data.score));
    if (!districts.length) return;
    container.classList.add("district-viz");
    drawScore(container, result, districts);
    drawDistricts(container, result, districts);
  };
})();
