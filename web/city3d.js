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
    root.append(canvas, top, districtLayer, controls, foot, status);
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

    let data = { districts: {}, selected: null, affected: [], resultDistricts: null, mode: "baseline" };
    let yaw = -0.34, pitch = 0.89, zoom = 1;
    let width = 0, height = 0, pixelRatio = 1;
    let projectedDistricts = [];
    let projectedBuildings = [];
    let hovered = null;
    let dropPreview = null;
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
      gradient.addColorStop(0, "#17323d");
      gradient.addColorStop(0.58, "#0b1e2a");
      gradient.addColorStop(1, "#06131d");
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, width, height);
      ctx.save();
      ctx.lineWidth = 1;
      for (let x = -7; x <= 7; x += 0.5) {
        line(project(x, -0.25, -6), project(x, -0.25, 6), "rgba(82,137,149,.09)");
      }
      for (let z = -6; z <= 6; z += 0.5) {
        line(project(-7, -0.25, z), project(7, -0.25, z), "rgba(82,137,149,.09)");
      }
      ctx.restore();
      const edge = OUTLINE.map(([x, z]) => project(x, -0.14, z));
      polygon(edge, "rgba(16,47,59,.7)", "rgba(115,216,203,.22)", 1.5);
      for (let i = 0; i < OUTLINE.length; i++) {
        const a = OUTLINE[i], b = OUTLINE[(i + 1) % OUTLINE.length];
        line(project(a[0], -0.14, a[1]), project(a[0], -0.28, a[1]), "rgba(87,201,184,.25)");
        polygon([
          project(a[0], -0.14, a[1]), project(b[0], -0.14, b[1]),
          project(b[0], -0.28, b[1]), project(a[0], -0.28, a[1])
        ], "rgba(6,21,31,.9)", null);
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
        line(first, last, "rgba(92,234,216,.13)", 7);
        ctx.setLineDash([2, 8]);
        line(first, last, index === 0 ? "rgba(233,183,103,.55)" : "rgba(93,219,203,.45)", 1);
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
          preview ? "#32463b" : active ? "#184f5b" : highlighted ? "#305449" : vulnerable ? "#57363e" : "#102e3a",
          active ? "rgba(113,244,220,.44)" : "rgba(79,142,151,.18)");
      }
      const fill = preview ? "#3e5540" : active ? "#1f6570" : highlighted ? "#3a594a" : vulnerable ? "#65424b" : "#183b49";
      const border = preview ? "#dbff69" : active ? "#a6ffe8" : highlighted ? "#e7bd72" : vulnerable ? "#ffab92" : "rgba(113,211,204,.56)";
      ctx.save();
      ctx.shadowBlur = preview ? 30 : active ? 24 : highlighted || vulnerable ? 15 : 5;
      ctx.shadowColor = preview ? "#dbff69" : active ? "#6be5cb" : highlighted ? "#d5ad64" : vulnerable ? "#ff8e82" : "#2d9a9a";
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
        line(a, b, "rgba(118,216,205,.075)");
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
      const top = preview ? "#dbff69" : active ? "#a4e9d5" : affected ? "#d9c795" : isBright ? "#9bc8bf" : "#6caab1";
      polygon([floor[0], floor[1], roof[1], roof[0]], active ? "#317b80" : "#295d6a", null);
      polygon([floor[1], floor[2], roof[2], roof[1]], active ? "#3a8e8c" : affected ? "#90765c" : "#34717a", null);
      polygon([floor[2], floor[3], roof[3], roof[2]], active ? "#326c75" : "#234f60", null);
      polygon([floor[3], floor[0], roof[0], roof[3]], active ? "#205965" : "#194458", null);
      polygon(roof, top, "rgba(190,245,225,.45)", 0.5);
      if (isBright && progress > 0.85) {
        const c = project(x, high, z);
        ctx.fillStyle = preview ? "#dbff69" : active ? "#c9fff2" : "#d4e8c3";
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
          mode: hasResult ? "result" : "baseline"
        };
        modeLabel.textContent = data.mode === "result" ? "ПОСЛЕ РЕШЕНИЙ" : "ИСХОДНОЕ СОСТОЯНИЕ";
        root.classList.toggle("is-result", data.mode === "result");
        root.classList.toggle("has-affected", data.affected.length > 0);
        refreshLegend();
        status.textContent = data.selected ? "Выбран район " + data.selected : "Показаны пять районов города";
        // Keep the accessible district controls current even when Canvas is unavailable.
        refreshLabels();
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
})();
