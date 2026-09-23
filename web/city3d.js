"use strict";

/*
 * A dependency-free, perspective-projected 3D city model. Geometry is a
 * deliberately fictional diagram: no building or platform represents a real
 * location, population or calculated indicator.
 */
(function () {
  const SHAPES = [
    { name: "Есиль", points: [[-2.7, -2.55], [-0.55, -2.75], [-0.3, -0.9], [-2.45, -0.75]], label: [-1.52, -1.82] },
    { name: "Нура", points: [[0.02, -2.65], [2.7, -2.42], [2.62, -0.48], [0.28, -0.72]], label: [1.48, -1.64] },
    { name: "Сарыарка", points: [[-3.05, -0.35], [-1.12, -0.55], [-0.98, 1.78], [-2.83, 1.56]], label: [-2.0, 0.55] },
    { name: "Байконур", points: [[-0.66, -0.45], [1.05, -0.29], [1.26, 1.72], [-0.62, 1.75]], label: [0.26, 0.52] },
    { name: "Алматы", points: [[1.57, -0.08], [3.03, 0.08], [3.08, 2.24], [1.56, 2.08]], label: [2.28, 1.07] }
  ];
  const OUTLINE = [[-3.44, -3.15], [3.38, -3.15], [3.48, 2.72], [-3.42, 2.72]];
  const INITIATIVE_FORMS = {
    M1: "Автобусная полоса", M2: "Светофоры", M3: "ЛРТ", M4: "Парк",
    M5: "Чистое топливо", M6: "Озеленение", M7: "Школа и детсад",
    M8: "Поликлиника", M9: "Спорт", M10: "Свет и камеры",
    M11: "Переходы", M12: "Цифровые сервисы", M13: "Инженерные сети",
    M14: "Аварийные бригады"
  };
  const CITY_FORMS = new Set(["M2", "M6", "M12", "M14"]);
  // The colors come from Egor's original paper/green/lime/orange interface.
  const COLOR = {
    paper: "#f5f3eb", panel: "#fffefa", ink: "#243c35",
    green: "#294d40", lime: "#dce6b4", orange: "#b67147"
  };
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const roundScore = (value) => finite(value) ? value.toFixed(2).replace(".", ",") : "—";

  function inPolygon(x, z, points) {
    let inside = false;
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      const a = points[i], b = points[j];
      if ((a[1] > z) !== (b[1] > z) && x < (b[0] - a[0]) * (z - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
    }
    return inside;
  }

  function generateBuildings(shape, index) {
    const points = shape.points;
    const xs = points.map((point) => point[0]), zs = points.map((point) => point[1]);
    const buildings = [];
    let counter = 0;
    for (let x = Math.min(...xs) + 0.31; x < Math.max(...xs) - 0.19; x += 0.42) {
      for (let z = Math.min(...zs) + 0.31; z < Math.max(...zs) - 0.16; z += 0.42) {
        const variation = ((counter * 7 + index * 11) % 9) / 9;
        const driftX = ((counter * 3 + index) % 3 - 1) * 0.045;
        const driftZ = ((counter * 5 + index) % 3 - 1) * 0.045;
        counter++;
        if ((counter + index * 3) % 6 === 0 || !inPolygon(x + driftX, z + driftZ, points)) continue;
        const width = 0.16 + (counter % 3) * 0.035;
        const depth = 0.16 + (counter % 4) * 0.025;
        const height = 0.21 + variation * 0.55 + (counter % 13 === 0 ? 0.43 : 0);
        buildings.push({ x: x + driftX, z: z + driftZ, width, depth, height });
      }
    }
    return buildings;
  }
  SHAPES.forEach((shape, index) => { shape.buildings = generateBuildings(shape, index); });

  function createElement(tag, className, text) {
    const element = document.createElement(tag);
    element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function drawInitiativeModel(ctx, project, polygon, line, item, progress, mode) {
    const x = item.x, z = item.z, base = item.city ? 0.23 : 0.19 * progress;
    const s = item.city ? 0.75 : 0.78;
    const after = mode === "result" && !item.preview;
    const edge = item.preview ? COLOR.orange : COLOR.green;
    const roofColor = item.preview ? "rgba(182,113,71,.72)" : after ? COLOR.lime : "rgba(220,230,180,.72)";
    const wallColor = item.preview ? "rgba(182,113,71,.3)" : after ? "rgba(41,77,64,.85)" : "rgba(41,77,64,.35)";
    const darkWall = item.preview ? "rgba(182,113,71,.56)" : after ? COLOR.green : "rgba(41,77,64,.58)";
    const p = (dx, dy, dz) => project(x + dx * s, base + dy * s, z + dz * s);
    const slab = (dx, dz, w, d, h, top = roofColor) => {
      const a = [p(dx - w, 0, dz - d), p(dx + w, 0, dz - d), p(dx + w, 0, dz + d), p(dx - w, 0, dz + d)];
      const b = [p(dx - w, h, dz - d), p(dx + w, h, dz - d), p(dx + w, h, dz + d), p(dx - w, h, dz + d)];
      polygon([a[0], a[1], b[1], b[0]], wallColor, edge, .6);
      polygon([a[1], a[2], b[2], b[1]], darkWall, edge, .6);
      polygon([a[2], a[3], b[3], b[2]], wallColor, edge, .6);
      polygon([a[3], a[0], b[0], b[3]], darkWall, edge, .6);
      polygon(b, top, edge, 1.2);
    };
    const floor = (dx, dz, w, d, fill = roofColor) =>
      polygon([p(dx - w, .02, dz - d), p(dx + w, .02, dz - d), p(dx + w, .02, dz + d), p(dx - w, .02, dz + d)], fill, edge, 1);
    const rod = (a, b, weight = 2) => line(p(...a), p(...b), edge, weight);
    const dot = (dx, dy, dz, radius = 3, color = edge) => {
      const center = p(dx, dy, dz);
      ctx.beginPath(); ctx.arc(center.x, center.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = color; ctx.fill();
    };

    // Fourteen tiny architectural metaphors. Their dimensions never encode
    // cost, predicted effects, completion or real infrastructure locations.
    switch (item.id) {
      case "M1": // bus lane and vehicle
        floor(0, 0, .41, .31, "rgba(41,77,64,.13)");
        rod([-.32, .04, -.1], [.32, .04, -.1], 3);
        rod([-.32, .04, .14], [.32, .04, .14], 3);
        slab(-.04, .02, .22, .11, .2);
        break;
      case "M2": // signal mast
        slab(0, 0, .09, .09, .48);
        slab(0, 0, .15, .12, .1);
        dot(0, .19, -.13, 2.4, COLOR.orange);
        dot(0, .31, -.13, 2.4, roofColor);
        dot(0, .43, -.13, 2.4, edge);
        break;
      case "M3": // elevated dual tracks
        slab(-.29, 0, .055, .09, .37);
        slab(.29, 0, .055, .09, .37);
        rod([-.4, .39, -.12], [.4, .39, -.12], 3);
        rod([-.4, .39, .12], [.4, .39, .12], 3);
        break;
      case "M4": // park with three tree crowns
        floor(0, 0, .42, .34, "rgba(220,230,180,.6)");
        [[-.24, -.14], [.2, -.1], [0, .18]].forEach(([tx, tz]) => {
          slab(tx, tz, .035, .035, .23, edge);
          slab(tx, tz, .13, .13, .12, roofColor);
        });
        break;
      case "M5": // clean fuel converter
        slab(-.1, 0, .26, .22, .23);
        slab(.18, -.05, .07, .07, .51, roofColor);
        rod([.07, .42, -.14], [.3, .42, -.14], 2);
        break;
      case "M6": // windbreak and greening
        floor(0, 0, .43, .3, "rgba(220,230,180,.55)");
        [-.28, 0, .28].forEach((tx) => {
          slab(tx, 0, .035, .035, .25, edge);
          slab(tx, 0, .12, .12, .16, roofColor);
        });
        break;
      case "M7": // paired school and kindergarten
        slab(-.16, 0, .22, .24, .4);
        slab(.25, .06, .14, .18, .25);
        rod([-.17, .42, 0], [-.17, .61, 0]);
        polygon([p(-.17, .61, 0), p(.03, .56, 0), p(-.17, .5, 0)], roofColor, edge);
        break;
      case "M8": // clinic cross
        slab(0, 0, .34, .25, .32);
        slab(0, -.07, .06, .03, .51, roofColor);
        slab(0, -.07, .2, .03, .41, roofColor);
        break;
      case "M9": // sports court and goal
        floor(0, 0, .41, .28, "rgba(220,230,180,.55)");
        rod([0, .03, -.28], [0, .03, .28]);
        rod([-.3, .03, 0], [.3, .03, 0]);
        rod([.26, .03, -.2], [.26, .27, -.2]);
        dot(.26, .26, -.2, 3, roofColor);
        break;
      case "M10": // lighting and camera
        [-.24, .24].forEach((tx) => {
          slab(tx, 0, .04, .04, .52, edge);
          rod([tx, .52, 0], [tx + .16, .52, 0], 2);
          dot(tx + .16, .51, 0, 3.4, roofColor);
        });
        break;
      case "M11": // raised safe crossing
        floor(0, 0, .41, .29, "rgba(41,77,64,.13)");
        [-.24, -.08, .08, .24].forEach((tx) => floor(tx, 0, .035, .24, roofColor));
        slab(.34, -.2, .025, .025, .3, edge);
        break;
      case "M12": // digital portal
        slab(-.22, 0, .07, .08, .52);
        slab(.22, 0, .07, .08, .52);
        slab(0, 0, .3, .08, .09, roofColor);
        rod([-.17, .24, 0], [.17, .24, 0]);
        dot(0, .24, 0, 3, roofColor);
        break;
      case "M13": // heat and water networks
        floor(0, 0, .42, .29, "rgba(41,77,64,.13)");
        rod([-.35, .15, -.12], [.35, .15, -.12], 5);
        rod([-.35, .06, .12], [.35, .06, .12], 5);
        slab(-.27, -.12, .06, .06, .2, roofColor);
        slab(.27, .12, .06, .06, .13, roofColor);
        break;
      case "M14": // response vehicle and beacon
        slab(-.08, 0, .32, .18, .22);
        slab(.24, 0, .12, .18, .34);
        dot(-.22, .01, .2, 3, edge);
        dot(.25, .01, .2, 3, edge);
        dot(.24, .4, 0, 3.6, COLOR.orange);
        break;
    }
    const plate = p(0, .72, 0);
    ctx.font = '700 10px "Avenir Next Condensed", "Arial Narrow", Arial, sans-serif';
    ctx.textBaseline = "middle";
    ctx.fillStyle = item.preview ? COLOR.orange : COLOR.green;
    ctx.fillRect(plate.x - 13, plate.y - 8, 26, 16);
    ctx.fillStyle = COLOR.panel;
    ctx.textAlign = "center";
    ctx.fillText(item.id, plate.x, plate.y + .5);
  }


  window.createCityScene = function createCityScene(container, options = {}) {
    if (!(container instanceof Element)) throw new TypeError("createCityScene requires a DOM container");
    const onSelect = typeof options.onSelect === "function" ? options.onSelect : () => {};
    const root = createElement("div", "city3d");
    root.setAttribute("role", "group");
    root.setAttribute("aria-label", "Условная трёхмерная схема пяти районов");
    const canvas = createElement("canvas", "city3d__canvas");
    canvas.setAttribute("aria-hidden", "true");
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) root.classList.add("is-no-canvas");
    const top = createElement("div", "city3d__top");
    const brand = createElement("div", "city3d__brand");
    brand.append(createElement("span", "city3d__signal"), createElement("span", "city3d__brand-name", "ASTANA / CITY LAB"));
    const modeLabel = createElement("span", "city3d__mode", "ИСХОДНОЕ СОСТОЯНИЕ");
    top.append(brand, modeLabel);
    const districtLayer = createElement("div", "city3d__districts");
    districtLayer.setAttribute("aria-label", "Выберите район");
    const initiativeLayer = createElement("div", "city3d__initiatives");
    initiativeLayer.setAttribute("role", "list");
    initiativeLayer.setAttribute("aria-label", "Инициативы на условной сцене");
    const controls = createElement("div", "city3d__controls");
    const directions = [
      ["left", "Повернуть влево", "↶"],
      ["right", "Повернуть вправо", "↷"],
      ["up", "Поднять обзор", "↑"],
      ["down", "Опустить обзор", "↓"],
      ["zoom-in", "Приблизить", "+"],
      ["zoom-out", "Отдалить", "−"]
    ];
    const controlButtons = directions.map(([action, label, glyph]) => {
      const button = createElement("button", "city3d__control", glyph);
      button.type = "button";
      button.dataset.action = action;
      button.setAttribute("aria-label", label);
      controls.append(button);
      return button;
    });
    const foot = createElement("div", "city3d__foot");
    const legend = createElement("div", "city3d__legend");
    const legendText = createElement("span", "", "НАЖМИТЕ НА РАЙОН · ТЯНИТЕ ДЛЯ ОБЗОРА");
    legend.append(createElement("span", "city3d__legend-mark"), legendText);
    const disclaimer = createElement("span", "city3d__disclaimer", "Условная схема · не географическая карта");
    foot.append(legend, disclaimer);
    const status = createElement("span", "city3d__sr", "");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    const surface = createElement("div", "city3d__surface");
    surface.append(canvas, top, districtLayer, controls, foot);
    root.append(surface, initiativeLayer, status);
    container.replaceChildren(root);

    const districtButtons = new Map();
    SHAPES.forEach((shape, index) => {
      const button = createElement("button", "city3d__district");
      button.type = "button";
      button.dataset.name = shape.name;
      button.innerHTML = '<span class="city3d__district-index">0' + (index + 1) +
        '</span><span class="city3d__district-body"><strong></strong><small></small></span><span class="city3d__district-arrow" aria-hidden="true">↗</span>';
      button.querySelector("strong").textContent = shape.name;
      districtLayer.append(button);
      districtButtons.set(shape.name, button);
    });

    let data = { districts: {}, selected: null, affected: [], resultDistricts: null, mode: "baseline", decisions: [], measures: {} };
    let yaw = -0.34, pitch = 0.89, zoom = 1;
    let width = 0, height = 0, pixelRatio = 1;
    let projectedDistricts = [];
    let projectedBuildings = [];
    let hovered = null;
    let dropPreview = null;
    let initiativePreview = null;
    let drag = null;
    let animationFrame = 0;
    let revealStart = 0;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const aborter = new AbortController();
    let destroyed = false;

    function project(x, y, z) {
      const sy = Math.sin(yaw), cy = Math.cos(yaw);
      const sp = Math.sin(pitch), cp = Math.cos(pitch);
      const depth = x * sy * cp + y * sp + z * cy * cp;
      const perspective = 14 / (14 - depth);
      const scale = Math.min(width / 8.8, height / 6.55) * zoom;
      return {
        x: width * 0.5 + (x * cy - z * sy) * scale * perspective,
        y: height * 0.56 - (y * cp - (x * sy + z * cy) * sp) * scale * perspective,
        depth
      };
    }

    function polygon(points, fill, stroke, lineWidth = 1) {
      if (!points.length) return;
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length; i++) ctx.lineTo(points[i].x, points[i].y);
      ctx.closePath();
      if (fill) { ctx.fillStyle = fill; ctx.fill(); }
      if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = lineWidth; ctx.stroke(); }
    }

    function line(a, b, color, lineWidth = 1) {
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.lineWidth = lineWidth;
      ctx.strokeStyle = color;
      ctx.stroke();
    }

    function drawGrid() {
      const gradient = ctx.createRadialGradient(width * 0.5, height * 0.43, 24, width * 0.5, height * 0.5, Math.max(width, height) * 0.8);
      gradient.addColorStop(0, COLOR.panel);
      gradient.addColorStop(0.58, COLOR.paper);
      gradient.addColorStop(1, "#e9eddf");
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, width, height);
      ctx.save();
      ctx.lineWidth = 1;
      for (let x = -7; x <= 7; x += 0.5) {
        line(project(x, -0.25, -6), project(x, -0.25, 6), "rgba(41,77,64,.09)");
      }
      for (let z = -6; z <= 6; z += 0.5) {
        line(project(-7, -0.25, z), project(7, -0.25, z), "rgba(41,77,64,.09)");
      }
      ctx.restore();
      const edge = OUTLINE.map(([x, z]) => project(x, -0.14, z));
      polygon(edge, "rgba(220,230,180,.55)", "rgba(41,77,64,.25)", 1.5);
      for (let i = 0; i < OUTLINE.length; i++) {
        const a = OUTLINE[i], b = OUTLINE[(i + 1) % OUTLINE.length];
        line(project(a[0], -0.14, a[1]), project(a[0], -0.28, a[1]), "rgba(41,77,64,.25)");
        polygon([
          project(a[0], -0.14, a[1]), project(b[0], -0.14, b[1]),
          project(b[0], -0.28, b[1]), project(a[0], -0.28, a[1])
        ], "rgba(41,77,64,.3)", null);
      }
    }

    function drawRoads() {
      const roads = [
        [[-2.8, -0.58], [2.86, -0.36]],
        [[-0.82, -2.83], [1.39, 2.42]],
        [[-3.2, 1.93], [3.29, 2.42]]
      ];
      roads.forEach(([a, b], index) => {
        const first = project(a[0], -0.095, a[1]), last = project(b[0], -0.095, b[1]);
        line(first, last, "rgba(41,77,64,.11)", 7);
        ctx.setLineDash([2, 8]);
        line(first, last, index === 0 ? "rgba(182,113,71,.5)" : "rgba(41,77,64,.35)", 1);
        ctx.setLineDash([]);
      });
    }

    function drawPlatform(shape, highlighted, active, vulnerable, preview, progress) {
      const topHeight = 0.17 * progress;
      const topPoints = shape.points.map(([x, z]) => project(x, topHeight, z));
      const bottomPoints = shape.points.map(([x, z]) => project(x, -0.09, z));
      for (let i = 0; i < shape.points.length; i++) {
        const j = (i + 1) % shape.points.length;
        polygon([topPoints[i], topPoints[j], bottomPoints[j], bottomPoints[i]],
          preview ? "#c6d39e" : active ? "#91ab94" : highlighted ? "#d7c5ab" : vulnerable ? "#d9b79d" : "#cbd7bc",
          active ? "rgba(41,77,64,.6)" : "rgba(41,77,64,.22)");
      }
      const fill = preview ? "#e4ecc5" : active ? "#dce6b4" : highlighted ? "#eedcc9" : vulnerable ? "#efd5c4" : "#e4ead9";
      const border = preview ? COLOR.green : active ? COLOR.green : highlighted ? COLOR.orange : vulnerable ? COLOR.orange : "rgba(41,77,64,.56)";
      ctx.save();
      ctx.shadowBlur = preview ? 22 : active ? 15 : highlighted || vulnerable ? 9 : 4;
      ctx.shadowColor = preview || active ? "rgba(41,77,64,.3)" : highlighted || vulnerable ? "rgba(182,113,71,.3)" : "rgba(41,77,64,.12)";
      polygon(topPoints, fill, border, preview || active ? 2.5 : 1.3);
      ctx.restore();
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(topPoints[0].x, topPoints[0].y);
      topPoints.slice(1).forEach((point) => ctx.lineTo(point.x, point.y));
      ctx.closePath();
      ctx.clip();
      shape.points.forEach(([x, z]) => {
        const a = project(x - 2.5, topHeight + 0.003, z - 1.5);
        const b = project(x + 2.5, topHeight + 0.003, z + 1.5);
        line(a, b, "rgba(41,77,64,.055)");
      });
      ctx.restore();
      return topPoints;
    }

    function drawBuilding(building, active, affected, preview, progress) {
      const x = building.x, z = building.z, w = building.width, d = building.depth;
      const base = 0.17 * progress;
      const high = base + building.height * progress;
      const floor = [
        project(x - w, base, z - d), project(x + w, base, z - d),
        project(x + w, base, z + d), project(x - w, base, z + d)
      ];
      const roof = [
        project(x - w, high, z - d), project(x + w, high, z - d),
        project(x + w, high, z + d), project(x - w, high, z + d)
      ];
      const isBright = building.height > 0.79;
      const top = preview ? COLOR.lime : active ? "#c6d8b2" : affected ? "#e6cda8" : isBright ? "#b8cbb3" : "#d8e1ca";
      polygon([floor[0], floor[1], roof[1], roof[0]], active ? "#789787" : "#98ac9d", null);
      polygon([floor[1], floor[2], roof[2], roof[1]], active ? "#547763" : affected ? "#b89a78" : "#789683", null);
      polygon([floor[2], floor[3], roof[3], roof[2]], active ? "#6c8a78" : "#8da995", null);
      polygon([floor[3], floor[0], roof[0], roof[3]], active ? "#6a8977" : "#9eb2a3", null);
      polygon(roof, top, "rgba(41,77,64,.45)", 0.5);
      if (isBright && progress > 0.85) {
        const c = project(x, high, z);
        ctx.fillStyle = preview ? COLOR.green : active ? COLOR.green : COLOR.lime;
        ctx.fillRect(c.x - 1.2, c.y - 1.2, 2.4, 2.4);
      }
      return [
        roof,
        [floor[0], floor[1], roof[1], roof[0]],
        [floor[1], floor[2], roof[2], roof[1]],
        [floor[2], floor[3], roof[3], roof[2]],
        [floor[3], floor[0], roof[0], roof[3]]
      ];
    }

    function placedInitiatives() {
      const districtSlots = new Map(), citySlots = [];
      const placed = [];
      const add = (measureId, district, preview) => {
        if (!Object.hasOwn(INITIATIVE_FORMS, measureId)) return;
        const city = CITY_FORMS.has(measureId);
        if (city ? district !== null : !districtButtons.has(district)) return;
        let x, z;
        if (city) {
          const index = citySlots.length;
          citySlots.push(measureId);
          x = -2.48 + index * 1.44;
          z = 2.12;
        } else {
          const shape = SHAPES.find((item) => item.name === district);
          const index = districtSlots.get(district) || 0;
          districtSlots.set(district, index + 1);
          // Keep the sculptures near distinct platform corners so the
          // district's accessible DOM badge does not cover a packed group.
          const vertex = index < 4 ? shape.points[index] : [
            (shape.points[0][0] + shape.points[1][0]) / 2,
            (shape.points[0][1] + shape.points[1][1]) / 2
          ];
          x = shape.label[0] * .26 + vertex[0] * .74;
          z = shape.label[1] * .26 + vertex[1] * .74;
        }
        placed.push({ id: measureId, district, city, preview, x, z });
      };
      data.decisions.forEach((decision) => add(decision.measure_id, decision.district, false));
      if (initiativePreview) add(initiativePreview.measureId, initiativePreview.district, true);
      return placed;
    }

    function drawInitiatives(progress) {
      const items = placedInitiatives();
      if (items.some((item) => item.city)) {
        const cityColor = data.mode === "result" ? "rgba(41,77,64,.25)" : "rgba(41,77,64,.14)";
        const rail = [[-3.02, 1.88], [2.48, 1.88], [2.48, 2.42], [-3.02, 2.42]];
        const top = rail.map(([x, z]) => project(x, .2, z));
        const lower = rail.map(([x, z]) => project(x, -.08, z));
        for (let index = 0; index < rail.length; index++) {
          const next = (index + 1) % rail.length;
          polygon([top[index], top[next], lower[next], lower[index]], "rgba(41,77,64,.34)", "rgba(41,77,64,.45)", 1);
        }
        polygon(top, "rgba(220,230,180,.82)", COLOR.green, 1.4);
        SHAPES.forEach((shape) => {
          const center = project(shape.label[0], .2, shape.label[1]);
          line(project(0, .21, 2.12), center, cityColor, 1.2);
        });
      }
      items.sort((a, b) => project(a.x, 0, a.z).depth - project(b.x, 0, b.z).depth)
        .forEach((item) => drawInitiativeModel(ctx, project, polygon, line, item, progress, data.mode));
    }

    function refreshInitiativeList() {
      initiativeLayer.replaceChildren();
      const items = placedInitiatives();
      if (!items.length) {
        initiativeLayer.append(createElement("span", "city3d__initiative-empty", "Перенесите меру на район или выберите её в каталоге"));
        return;
      }
      items.forEach((item) => {
        const measure = data.measures[item.id];
        const name = typeof measure?.name === "string" ? measure.name : INITIATIVE_FORMS[item.id];
        const target = item.city ? "Весь город" : item.district;
        const stateName = item.preview ? "Предпросмотр" : data.mode === "result" ? "В расчёте" : "В пакете";
        const chip = createElement("div", "city3d__initiative" + (item.preview ? " is-preview" : data.mode === "result" ? " is-result" : " is-plan"));
        chip.setAttribute("role", "listitem");
        chip.setAttribute("aria-label", `${item.id}: ${name}. ${target}. ${stateName}. Условная модель, не фактическое строительство.`);
        chip.append(createElement("b", "city3d__initiative-id", item.id),
          createElement("span", "city3d__initiative-copy", `${name} · ${target}`),
          createElement("small", "city3d__initiative-state", stateName));
        initiativeLayer.append(chip);
      });
    }

    function refreshLabels() {
      const scores = data.mode === "result" && data.resultDistricts ? data.resultDistricts : data.districts;
      const scored = SHAPES.map((shape) => ({ name: shape.name, score: scores?.[shape.name]?.score }))
        .filter((item) => finite(item.score));
      const weakest = scored.length ? scored.reduce((least, item) => item.score < least.score ? item : least).name : null;
      SHAPES.forEach((shape) => {
        const button = districtButtons.get(shape.name);
        const isSelected = data.selected === shape.name;
        const isAffected = data.affected.includes(shape.name);
        const isWeakest = weakest === shape.name;
        const isDropPreview = dropPreview === shape.name;
        const score = scores?.[shape.name]?.score;
        const scoreText = roundScore(score);
        button.classList.toggle("is-selected", isSelected);
        button.classList.toggle("is-affected", isAffected && !isSelected && !isDropPreview);
        button.classList.toggle("is-vulnerable", isWeakest && !isSelected && !isAffected && !isDropPreview);
        button.classList.toggle("is-drop-preview", isDropPreview);
        button.setAttribute("aria-pressed", String(isSelected));
        button.setAttribute("aria-label", shape.name + ", " + (finite(score) ? "районный балл " + scoreText : "районный балл недоступен") + (isWeakest ? ", самый низкий районный балл" : "") + (isAffected ? ", в охвате выбранной меры" : "") + (isSelected ? ", выбран" : "") + (isDropPreview ? ", цель перетаскивания" : ""));
        button.querySelector("small").textContent = finite(score) ? (isWeakest ? "МИНИМУМ " : "БАЛЛ ") + scoreText : "ВЫБРАТЬ РАЙОН";
        const point = project(shape.label[0], 0.32, shape.label[1]);
        button.style.left = point.x + "px";
        button.style.top = point.y + "px";
      });
    }

    function draw(time = performance.now()) {
      animationFrame = 0;
      if (destroyed || !ctx || width < 2 || height < 2) return;
      const progress = reducedMotion ? 1 : revealStart ? clamp((time - revealStart) / 750, 0, 1) : 1;
      ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      drawGrid();
      drawRoads();
      projectedDistricts = [];
      projectedBuildings = [];
      const scores = data.mode === "result" && data.resultDistricts ? data.resultDistricts : data.districts;
      const scored = SHAPES.map((shape) => ({ name: shape.name, score: scores?.[shape.name]?.score }))
        .filter((item) => finite(item.score));
      const weakest = scored.length ? scored.reduce((least, item) => item.score < least.score ? item : least).name : null;
      const ordered = SHAPES.map((shape) => {
        const center = project(shape.label[0], 0, shape.label[1]);
        return { shape, depth: center.depth };
      }).sort((a, b) => a.depth - b.depth);
      ordered.forEach(({ shape }) => {
        const active = data.selected === shape.name || hovered === shape.name;
        const affected = data.affected.includes(shape.name);
        const preview = dropPreview === shape.name;
        const vulnerable = shape.name === weakest && !affected && !active && !preview;
        const polygonPoints = drawPlatform(shape, affected, active, vulnerable, preview, progress);
        projectedDistricts.push({ name: shape.name, points: polygonPoints });
        shape.buildings
          .slice()
          .sort((a, b) => project(a.x, 0, a.z).depth - project(b.x, 0, b.z).depth)
          .forEach((building) => projectedBuildings.push({
            name: shape.name,
            faces: drawBuilding(building, active, affected, preview, progress)
          }));
      });
      drawInitiatives(progress);
      refreshLabels();
      if (progress < 1) animationFrame = requestAnimationFrame(draw);
      else animationFrame = 0;
    }

    function requestDraw() {
      if (!animationFrame) animationFrame = requestAnimationFrame(draw);
    }

    function resize() {
      const bounds = canvas.getBoundingClientRect();
      width = bounds.width;
      height = bounds.height;
      pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.round(width * pixelRatio));
      canvas.height = Math.max(1, Math.round(height * pixelRatio));
      requestDraw();
    }

    function pointInScreenPolygon(x, y, points) {
      let inside = false;
      for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
        const a = points[i], b = points[j];
        if ((a.y > y) !== (b.y > y) && x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x) inside = !inside;
      }
      return inside;
    }

    function hitTest(x, y) {
      for (let i = projectedBuildings.length - 1; i >= 0; i--) {
        const building = projectedBuildings[i];
        if (building.faces.some((face) => pointInScreenPolygon(x, y, face))) return building.name;
      }
      for (let i = projectedDistricts.length - 1; i >= 0; i--) {
        const district = projectedDistricts[i];
        if (pointInScreenPolygon(x, y, district.points)) return district.name;
      }
      return null;
    }

    function pickDistrict(clientX, clientY) {
      if (destroyed || !finite(clientX) || !finite(clientY)) return null;
      const bounds = root.getBoundingClientRect();
      if (clientX < bounds.left || clientX > bounds.right || clientY < bounds.top || clientY > bounds.bottom) return null;
      for (const [name, button] of districtButtons) {
        const rect = button.getBoundingClientRect();
        if (rect.width && rect.height && clientX >= rect.left && clientX <= rect.right &&
          clientY >= rect.top && clientY <= rect.bottom) return name;
      }
      if (!ctx) return null;
      const canvasBounds = canvas.getBoundingClientRect();
      if (clientX < canvasBounds.left || clientX > canvasBounds.right ||
        clientY < canvasBounds.top || clientY > canvasBounds.bottom) return null;
      // Orbit, tilt and zoom may have changed since the previous animation frame.
      if (animationFrame) {
        cancelAnimationFrame(animationFrame);
        animationFrame = 0;
        draw();
      }
      return hitTest(clientX - canvasBounds.left, clientY - canvasBounds.top);
    }

    function refreshLegend() {
      legendText.textContent = dropPreview ? "ОТПУСТИТЕ МЕРУ: " + dropPreview.toUpperCase() :
        data.affected.length ? "ЯНТАРНЫЙ = ОХВАТ МЕРЫ" :
          ctx ? "НАЖМИТЕ НА РАЙОН · ТЯНИТЕ ДЛЯ ОБЗОРА" : "ВЫБЕРИТЕ РАЙОН ИЗ СПИСКА";
    }

    function position(event) {
      const bounds = canvas.getBoundingClientRect();
      return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
    }

    canvas.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const point = position(event);
      drag = { x: point.x, y: point.y, yaw, pitch, moved: false };
      canvas.setPointerCapture(event.pointerId);
    }, { signal: aborter.signal });
    canvas.addEventListener("pointermove", (event) => {
      const point = position(event);
      if (drag) {
        const dx = point.x - drag.x, dy = point.y - drag.y;
        if (Math.hypot(dx, dy) > 5) drag.moved = true;
        if (drag.moved) {
          yaw = drag.yaw + dx * 0.006;
          pitch = clamp(drag.pitch + dy * 0.004, 0.48, 1.23);
          canvas.style.cursor = "grabbing";
          requestDraw();
        }
      } else {
        const next = hitTest(point.x, point.y);
        if (next !== hovered) { hovered = next; requestDraw(); }
        canvas.style.cursor = next ? "pointer" : "grab";
      }
    }, { signal: aborter.signal });
    canvas.addEventListener("pointerup", (event) => {
      if (!drag) return;
      const point = position(event);
      if (!drag.moved) {
        const name = hitTest(point.x, point.y);
        if (name) onSelect(name);
      }
      drag = null;
      canvas.style.cursor = hovered ? "pointer" : "grab";
    }, { signal: aborter.signal });
    canvas.addEventListener("pointercancel", () => { drag = null; canvas.style.cursor = "grab"; }, { signal: aborter.signal });
    canvas.addEventListener("pointerleave", () => {
      if (!drag && hovered) { hovered = null; requestDraw(); }
    }, { signal: aborter.signal });
    canvas.addEventListener("wheel", (event) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      zoom = clamp(zoom * (event.deltaY > 0 ? 0.91 : 1.09), 0.68, 1.42);
      requestDraw();
    }, { passive: false, signal: aborter.signal });

    districtButtons.forEach((button, name) => {
      button.addEventListener("click", () => onSelect(name), { signal: aborter.signal });
      button.addEventListener("pointerenter", () => { hovered = name; requestDraw(); }, { signal: aborter.signal });
      button.addEventListener("pointerleave", () => { hovered = null; requestDraw(); }, { signal: aborter.signal });
      button.addEventListener("focus", () => { hovered = name; requestDraw(); }, { signal: aborter.signal });
      button.addEventListener("blur", () => { hovered = null; requestDraw(); }, { signal: aborter.signal });
      button.addEventListener("keydown", (event) => {
        if (!["ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown"].includes(event.key)) return;
        event.preventDefault();
        const index = SHAPES.findIndex((shape) => shape.name === name);
        const direction = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
        districtButtons.get(SHAPES[(index + direction + SHAPES.length) % SHAPES.length].name).focus();
      }, { signal: aborter.signal });
    });
    controlButtons.forEach((button) => {
      button.addEventListener("click", () => {
        switch (button.dataset.action) {
          case "left": yaw -= 0.18; break;
          case "right": yaw += 0.18; break;
          case "up": pitch = clamp(pitch + 0.12, 0.48, 1.23); break;
          case "down": pitch = clamp(pitch - 0.12, 0.48, 1.23); break;
          case "zoom-in": zoom = clamp(zoom * 1.12, 0.68, 1.42); break;
          case "zoom-out": zoom = clamp(zoom / 1.12, 0.68, 1.42); break;
        }
        requestDraw();
      }, { signal: aborter.signal });
    });

    const resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
    if (resizeObserver) resizeObserver.observe(canvas);
    else window.addEventListener("resize", resize, { signal: aborter.signal });
    resize();
    if (!reducedMotion) {
      revealStart = performance.now();
      requestDraw();
    }

    return {
      update(next = {}) {
        if (destroyed) return;
        const candidateResult = next.resultDistricts && typeof next.resultDistricts === "object" ? next.resultDistricts : null;
        const hasResult = next.mode === "result" && candidateResult &&
          SHAPES.every((shape) => finite(candidateResult[shape.name]?.score));
        data = {
          districts: next.districts && typeof next.districts === "object" ? next.districts : {},
          selected: typeof next.selected === "string" ? next.selected : null,
          affected: Array.isArray(next.affected) ? next.affected : [],
          resultDistricts: hasResult ? candidateResult : null,
          mode: hasResult ? "result" : "baseline",
          decisions: Array.isArray(next.decisions) ? next.decisions.filter((item) =>
            item && typeof item.measure_id === "string" &&
            (CITY_FORMS.has(item.measure_id) ? item.district === null : districtButtons.has(item.district))) : [],
          measures: next.measures && typeof next.measures === "object" ? next.measures : {}
        };
        modeLabel.textContent = data.mode === "result" ? "ПОСЛЕ РЕШЕНИЙ" :
          data.decisions.length ? "ПРОЕКТ ПАКЕТА / ДО РАСЧЁТА" : "ИСХОДНОЕ СОСТОЯНИЕ";
        root.classList.toggle("is-result", data.mode === "result");
        root.classList.toggle("has-affected", data.affected.length > 0);
        refreshLegend();
        status.textContent = data.selected ? "Выбран район " + data.selected : "Показаны пять районов города";
        // Keep the accessible district controls current even when Canvas is unavailable.
        refreshLabels();
        refreshInitiativeList();
        requestDraw();
      },
      pickDistrict,
      setDropPreview(name) {
        if (destroyed) return;
        const next = districtButtons.has(name) ? name : null;
        if (next === dropPreview) return;
        dropPreview = next;
        root.classList.toggle("has-drop-preview", Boolean(next));
        refreshLegend();
        status.textContent = next ? "Отпустите меру над районом " + next :
          data.selected ? "Выбран район " + data.selected : "Показаны пять районов города";
        refreshLabels();
        requestDraw();
      },
      setInitiativePreview(next) {
        if (destroyed) return;
        const measureId = next && typeof next.measureId === "string" ? next.measureId : null;
        const district = next && Object.hasOwn(next, "district") ? next.district : undefined;
        const valid = measureId && Object.hasOwn(INITIATIVE_FORMS, measureId) &&
          (CITY_FORMS.has(measureId) ? district === null : districtButtons.has(district));
        const preview = valid ? { measureId, district } : null;
        if (preview?.measureId === initiativePreview?.measureId && preview?.district === initiativePreview?.district) return;
        initiativePreview = preview;
        root.classList.toggle("has-initiative-preview", Boolean(preview));
        refreshInitiativeList();
        requestDraw();
      },
      destroy() {
        if (destroyed) return;
        destroyed = true;
        aborter.abort();
        if (resizeObserver) resizeObserver.disconnect();
        if (animationFrame) cancelAnimationFrame(animationFrame);
        root.remove();
      }
    };
  };

  window.createInitiativeDiorama = function createInitiativeDiorama(container) {
    if (!(container instanceof Element)) throw new TypeError("createInitiativeDiorama requires a DOM container");
    const root = createElement("div", "initiative3d");
    root.setAttribute("role", "group");
    root.setAttribute("tabindex", "0");
    root.setAttribute("aria-label", "Условная трёхмерная модель меры. Стрелками можно повернуть обзор.");
    const canvas = createElement("canvas", "initiative3d__canvas");
    canvas.setAttribute("aria-hidden", "true");
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) root.classList.add("is-no-canvas");
    const top = createElement("div", "initiative3d__top");
    const code = createElement("b", "initiative3d__code", "СЦЕНА МЕРЫ");
    const stateLabel = createElement("span", "initiative3d__state", "ВЫБЕРИТЕ МЕРУ");
    top.append(code, stateLabel);
    const caption = createElement("div", "initiative3d__caption", "Условная 3D-модель инициативы");
    root.append(canvas, top, caption);
    container.replaceChildren(root);

    let measure = null, district = null, mode = "preview";
    let width = 0, height = 0, dpr = 1, yaw = -.55;
    let frame = 0, drag = null, destroyed = false;
    const aborter = new AbortController();

    function project(x, y, z) {
      const sy = Math.sin(yaw), cy = Math.cos(yaw);
      const pitch = .83, sp = Math.sin(pitch), cp = Math.cos(pitch);
      const depth = x * sy * cp + y * sp + z * cy * cp;
      const scale = Math.min(width / 2.45, height / 1.75);
      const perspective = 8 / (8 - depth);
      return {
        x: width * .5 + (x * cy - z * sy) * scale * perspective,
        y: height * .67 - (y * cp - (x * sy + z * cy) * sp) * scale * perspective
      };
    }
    function polygon(points, fill, stroke, lineWidth = 1) {
      ctx.beginPath(); ctx.moveTo(points[0].x, points[0].y);
      points.slice(1).forEach((point) => ctx.lineTo(point.x, point.y));
      ctx.closePath();
      if (fill) { ctx.fillStyle = fill; ctx.fill(); }
      if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = lineWidth; ctx.stroke(); }
    }
    function line(a, b, color, lineWidth = 1) {
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = color; ctx.lineWidth = lineWidth; ctx.stroke();
    }
    function draw() {
      frame = 0;
      if (destroyed || !ctx || width < 2 || height < 2) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = COLOR.paper; ctx.fillRect(0, 0, width, height);
      for (let grid = -2; grid <= 2; grid += .5) {
        line(project(grid, -.2, -2), project(grid, -.2, 2), "rgba(41,77,64,.08)");
        line(project(-2, -.2, grid), project(2, -.2, grid), "rgba(41,77,64,.08)");
      }
      const base = [[-.86, -.6], [.86, -.6], [.86, .6], [-.86, .6]];
      const topFace = base.map(([x, z]) => project(x, .05, z));
      const lowerFace = base.map(([x, z]) => project(x, -.12, z));
      for (let index = 0; index < 4; index++) {
        const next = (index + 1) % 4;
        polygon([topFace[index], topFace[next], lowerFace[next], lowerFace[index]], "rgba(41,77,64,.28)", "rgba(41,77,64,.35)");
      }
      polygon(topFace, mode === "result" ? COLOR.lime : COLOR.panel, COLOR.green, 1.5);
      if (!measure) {
        const center = project(0, .08, 0);
        ctx.fillStyle = COLOR.green;
        ctx.font = '700 21px "Avenir Next Condensed", "Arial Narrow", Arial, sans-serif';
        ctx.textAlign = "center";
        ctx.fillText("+", center.x, center.y + 7);
        return;
      }
      if (measure.scope === "city") {
        const outer = [[-.67, -.42], [.67, -.42], [.67, .42], [-.67, .42]];
        outer.forEach(([x, z]) => {
          const spot = project(x, .1, z);
          ctx.fillStyle = COLOR.green;
          ctx.fillRect(spot.x - 2.5, spot.y - 2.5, 5, 5);
          line(project(0, .1, 0), spot, "rgba(41,77,64,.45)", 1);
        });
        const fifth = project(0, .09, .42);
        ctx.fillStyle = COLOR.green; ctx.fillRect(fifth.x - 2.5, fifth.y - 2.5, 5, 5);
        line(project(0, .1, 0), fifth, "rgba(41,77,64,.45)", 1);
      }
      drawInitiativeModel(ctx, project, polygon, line,
        { id: measure.id, x: 0, z: 0, city: false, preview: mode === "preview" }, 1, mode);
    }
    function requestDraw() { if (!frame) frame = requestAnimationFrame(draw); }
    function resize() {
      const bounds = canvas.getBoundingClientRect();
      width = bounds.width; height = bounds.height;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.round(width * dpr));
      canvas.height = Math.max(1, Math.round(height * dpr));
      requestDraw();
    }
    canvas.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      drag = { x: event.clientX, yaw };
      canvas.setPointerCapture(event.pointerId);
    }, { signal: aborter.signal });
    canvas.addEventListener("pointermove", (event) => {
      if (!drag) return;
      yaw = drag.yaw + (event.clientX - drag.x) * .008;
      requestDraw();
    }, { signal: aborter.signal });
    canvas.addEventListener("pointerup", () => { drag = null; }, { signal: aborter.signal });
    canvas.addEventListener("pointercancel", () => { drag = null; }, { signal: aborter.signal });
    root.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      yaw += event.key === "ArrowLeft" ? -.2 : .2;
      requestDraw();
    }, { signal: aborter.signal });
    const resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
    if (resizeObserver) resizeObserver.observe(canvas);
    else window.addEventListener("resize", resize, { signal: aborter.signal });
    resize();

    return {
      update(next = {}) {
        if (destroyed) return;
        measure = next.measure && Object.hasOwn(INITIATIVE_FORMS, next.measure.id) ? next.measure : null;
        district = measure?.scope === "city" ? null : typeof next.district === "string" ? next.district : null;
        mode = ["preview", "plan", "result"].includes(next.mode) ? next.mode : "plan";
        code.textContent = measure ? measure.id + " / " + (measure.scope === "city" ? "ВЕСЬ ГОРОД" : district || "РАЙОН") : "СЦЕНА МЕРЫ";
        stateLabel.textContent = measure ? mode === "result" ? "В РАСЧЁТЕ" : mode === "preview" ? "ПРЕДПРОСМОТР" : "В ПАКЕТЕ" : "ВЫБЕРИТЕ МЕРУ";
        caption.textContent = measure ? `${measure.name || INITIATIVE_FORMS[measure.id]} · условная 3D-модель` : "Выберите меру для 3D-просмотра";
        root.setAttribute("aria-label", measure ? `Условная модель ${measure.id}: ${measure.name || INITIATIVE_FORMS[measure.id]}. ${measure.scope === "city" ? "Весь город" : district || "Район не выбран"}. ${stateLabel.textContent}. Стрелками можно повернуть обзор.` : "Сцена меры пуста. Стрелками можно повернуть обзор.");
        root.classList.toggle("is-preview", mode === "preview" && Boolean(measure));
        root.classList.toggle("is-result", mode === "result" && Boolean(measure));
        requestDraw();
      },
      destroy() {
        if (destroyed) return;
        destroyed = true;
        aborter.abort();
        resizeObserver?.disconnect();
        if (frame) cancelAnimationFrame(frame);
        root.remove();
      }
    };
  };
})();
