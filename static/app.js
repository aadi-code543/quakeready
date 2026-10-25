// app.js - QuakeReady front end.
//
// The browser's jobs:
//   1. send the photo and settings to the Python server (/api/analyze)
//   2. draw the photo with colored boxes and fall zones on a <canvas>
//   3. show the score, fix list and editable item cards
//   4. when the user edits something, ask the server to redo the physics
//      (/api/recalculate) without running the AI again
//   5. play the "shake the room" animation, driven by the server's rocking
//      simulation, with a seismograph underneath
//   6. show the budget plan ("with $25, fix these first") and print the plan
//
// All coordinates from the server are in the photo's own pixels, so the canvas
// is sized to the photo and CSS shrinks it to fit the screen.

const $ = (id) => document.getElementById(id);

const COLORS = {
  high: "#dc2626", medium: "#d97706", low: "#16a34a",
  secured: "#2563eb", target: "#64748b",
};
const LEVEL_TEXT = { high: "Will tip", medium: "Could tip", low: "Low risk", secured: "Secured" };
const WALL_LEVEL_TEXT = { high: "Will fall", medium: "Could fall", low: "Low risk", secured: "Secured" };

// Everything the page currently knows. `result` is the server's last answer.
const state = {
  file: null,
  result: null,
  image: null,         // the <img> the canvas draws from
  background: null,    // same photo with hazards erased (for the animation)
  selectedId: null,
  animating: false,
  shaken: false,       // true after the shake animation, until Reset
};

// ------------------------------------------------------------ setup

function fillFloorSelects() {
  for (let n = 1; n <= 40; n++) {
    $("total-floors").add(new Option(n, n));
  }
  $("total-floors").value = "2";
  updateFloorOptions();
}

function updateFloorOptions() {
  const total = Number($("total-floors").value);
  const current = Math.min(Number($("floor").value) || 1, total);
  $("floor").innerHTML = "";
  for (let n = 1; n <= total; n++) {
    $("floor").add(new Option(n === 1 ? "1 (ground)" : n, n));
  }
  $("floor").value = String(current);
}

function setPhoto(file) {
  state.file = file;
  $("photo-label").textContent = `${file.name} (tap to choose a different photo)`;
  $("photo-drop").classList.add("has-photo");

  // Show a preview. URL.createObjectURL gives the browser a temporary
  // address for the file on this computer, so nothing is uploaded yet.
  // We free the old address first so previews don't pile up in memory.
  const preview = $("photo-preview");
  if (preview.src) URL.revokeObjectURL(preview.src);
  preview.src = URL.createObjectURL(file);
  preview.hidden = false;
}

function setStatus(text, isError = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", isError);
}

function settings() {
  return {
    floor: Number($("floor").value),
    total_floors: Number($("total-floors").value),
    scenario: $("scenario").value,
    quake_type: $("quake-type").value,
    budget: Math.max(0, Number($("budget").value) || 0),
  };
}

// ------------------------------------------------------------ talking to the server

async function scan(event) {
  event.preventDefault();
  if (!state.file) {
    setStatus("Choose a photo first.", true);
    return;
  }
  const form = new FormData();
  form.append("photo", state.file);
  form.append("address", $("address").value);
  for (const [key, value] of Object.entries(settings())) form.append(key, value);

  $("scan-btn").disabled = true;
  setStatus("Scanning... the first scan loads the AI model and can take a little while.");
  try {
    const response = await fetch("/api/analyze", { method: "POST", body: form });
    if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
    const result = await response.json();
    [state.image, state.background] = await Promise.all([
      loadImage(result.image), loadImage(result.background)]);
    state.selectedId = null;
    state.shaken = false;
    showResult(result);
    setStatus(`Found ${result.items.length} objects.`);
    $("results").hidden = false;
    $("results").scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    setStatus("Something went wrong: " + err.message, true);
  } finally {
    $("scan-btn").disabled = false;
  }
}

// Redo the physics after an edit. The server keeps no memory between
// requests, so we send everything it needs.
async function recalculate() {
  if (!state.result) return;
  const body = {
    items: state.result.items.map(({ zone, hits, explain, sim, ...rest }) => rest),
    pga: state.result.shaking.pga,
    ...settings(),
  };
  const response = await fetch("/api/recalculate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    setStatus("Couldn't update the results.", true);
    return;
  }
  const update = await response.json();
  showResult({ ...state.result, ...update, ...settings() });
}

async function updateAddress() {
  if (!state.result) return;
  const response = await fetch("/api/shaking?address=" + encodeURIComponent($("address").value));
  if (response.ok) {
    state.result.shaking = await response.json();
    await recalculate();
  }
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

// ------------------------------------------------------------ showing results

function showResult(result) {
  state.result = result;
  if (!state.animating) state.shaken = false;
  renderScore();
  renderFixList();
  renderItems();
  draw();
}

function itemById(id) {
  return state.result.items.find((it) => it.id === id);
}

function renderScore() {
  const r = state.result;
  const score = r.room_score;
  $("score-num").textContent = score;
  $("score").className = "score " + (score >= 80 ? "good" : score >= 50 ? "ok" : "bad");

  const floorText = r.floor > 1
    ? ` On floor ${r.floor} of ${r.total_floors}, upper-floor sway multiplies that by ${r.amplification}x, so furniture feels about ${r.demand_g.toFixed(2)} g.`
    : "";
  const source = r.shaking.source === "usgs" ? "USGS" : "offline USGS estimate";
  $("shaking-summary").textContent =
    `${r.shaking.place}: ${r.ground_g.toFixed(2)} g of ground shaking in the ${r.scenario_label} (${source}).` +
    floorText;
  renderSimCaption();
  drawSeismograph(null);
}

// The line under the seismograph, e.g. "Cascadia megaquake: 90 s simulated.
// Across 24 simulated quakes, about 2.3 things fell each time."
function renderSimCaption(clock) {
  const sim = state.result.simulation;
  const things = sim.expected_falls === 1 ? "thing" : "things";
  const base = `${sim.label}, ${sim.duration_s} s. Across ${sim.n_quakes} simulated quakes, ` +
    `about ${sim.expected_falls} ${things} fell each time.`;
  $("sim-caption").textContent = clock ? `${clock}  ·  ${base}` : base;
}

function renderFixList() {
  const list = $("fix-list");
  list.innerHTML = "";
  const r = state.result;
  if (r.fix_list.length === 0) {
    list.innerHTML = '<li class="empty">Nothing urgent in this room. Nice!</li>';
    $("fix-total").textContent = "";
    return;
  }
  const planIds = new Set(r.plan.ids);
  for (const id of r.fix_list) {
    const it = itemById(id);
    const li = document.createElement("li");
    const where = it.hits.length ? ` It ${it.hits[0].reason}.` : "";
    li.innerHTML = `<strong></strong> <span class="cost"></span><br><span></span>`;
    li.children[0].textContent = it.label;
    li.children[1].textContent = it.fix_cost ? `about $${it.fix_cost}` : "free";
    li.children[3].textContent = it.fix + where;
    if (planIds.has(id)) {
      li.classList.add("in-plan");
      const tag = document.createElement("span");
      tag.className = "plan-tag";
      tag.textContent = "Buy first";
      li.insertBefore(tag, li.children[1]);
    }
    li.addEventListener("click", () => select(id));
    list.appendChild(li);
  }
  $("fix-total").textContent = `(about $${r.fix_total_cost} total)`;
  renderPlan();
}

// "With $25: fix these 3 first (about $24). Room score 41 -> 77."
function renderPlan() {
  const plan = state.result.plan;
  const n = plan.ids.length;
  let text;
  if (state.result.fix_list.length === 0) {
    text = "";
  } else if (n === 0) {
    text = `$${plan.budget} isn't enough for any one fix here. The cheapest is about ` +
      `$${Math.min(...state.result.fix_list.map((id) => itemById(id).fix_cost))}.`;
  } else {
    text = `With $${plan.budget}: do the ${n} fix${n > 1 ? "es" : ""} marked "Buy first" ` +
      `(about $${plan.cost}). Room score ${plan.score_now} → ${plan.score_after}.`;
  }
  $("plan-summary").textContent = text;
}

function renderItems() {
  const box = $("items");
  box.innerHTML = "";
  // Most dangerous first, people/exit areas last.
  const order = { high: 0, medium: 1, low: 2, secured: 3 };
  const items = [...state.result.items].sort((a, b) =>
    (order[a.level] ?? 4) - (order[b.level] ?? 4) || (b.score ?? 0) - (a.score ?? 0));

  for (const it of items) {
    const card = document.createElement("div");
    card.className = "item " + (it.level || "target") + (it.id === state.selectedId ? " selected" : "");
    card.addEventListener("click", () => select(it.id));

    const levelText = it.kind === "wall" ? WALL_LEVEL_TEXT : LEVEL_TEXT;
    const badge = it.kind === "target" ? "People / exit" : levelText[it.level];
    card.innerHTML = `<h3><span></span><span class="badge"></span></h3>`;
    card.querySelector("h3 span").textContent = it.label;
    card.querySelector(".badge").textContent = badge;

    if (it.kind !== "target") {
      addParagraph(card, it.explain);
      if (it.sim && it.level !== "secured" && it.ratio >= 1) card.appendChild(fallMeter(it.sim));
      if (it.hits.length) addParagraph(card, "Danger: it " + it.hits.map((h) => h.reason).join(" and "), "warn");
    } else {
      addParagraph(card, "We check whether anything could fall here.");
    }

    if (it.kind === "tip") card.appendChild(dimensionInputs(it));

    const actions = document.createElement("div");
    actions.className = "actions";
    if (it.kind !== "target") {
      actions.appendChild(button(it.secured ? "Undo strapped" : "I strapped it", () => {
        it.secured = !it.secured;
        recalculate();
      }));
    }
    // "TV" stays uppercase, "Bookshelf" becomes "bookshelf".
    const name = it.label === it.label.toUpperCase() ? it.label : it.label.toLowerCase();
    actions.appendChild(button(`Not a ${name}`, () => {
      state.result.items = state.result.items.filter((x) => x.id !== it.id);
      recalculate();
    }));
    card.appendChild(actions);
    box.appendChild(card);
  }
}

// A small bar showing how often it fell in the simulated quakes.
function fallMeter(sim) {
  const wrap = document.createElement("div");
  wrap.className = "meter";
  wrap.innerHTML = `<span class="meter-bar"><span></span></span><span class="meter-text"></span>`;
  wrap.querySelector(".meter-bar span").style.width = `${Math.round(sim.p_fall * 100)}%`;
  wrap.querySelector(".meter-text").textContent = `${Math.round(sim.p_fall * 100)}% chance it falls`;
  return wrap;
}

function addParagraph(parent, text, className) {
  const p = document.createElement("p");
  p.textContent = text;
  if (className) p.className = className;
  parent.appendChild(p);
}

function button(text, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = text;
  b.addEventListener("click", (e) => { e.stopPropagation(); onClick(); });
  return b;
}

// Height and depth boxes. Typing a real measurement re-runs the physics.
let editTimer = null;
function dimensionInputs(it) {
  const wrap = document.createElement("div");
  wrap.className = "dims";
  for (const [field, name] of [["height_in", "Height (in)"], ["depth_in", "Depth (in)"]]) {
    const label = document.createElement("label");
    label.textContent = name + (field === "height_in" && !it.edited ? " est." : "");
    const input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.step = "1";
    input.value = Math.round(it[field]);
    input.addEventListener("click", (e) => e.stopPropagation());
    input.addEventListener("input", () => {
      const value = Number(input.value);
      if (!(value > 0)) return;
      it[field] = value;
      it.edited = true;
      clearTimeout(editTimer);
      editTimer = setTimeout(recalculate, 400);  // wait until typing pauses
    });
    label.appendChild(input);
    wrap.appendChild(label);
  }
  return wrap;
}

function select(id) {
  state.selectedId = state.selectedId === id ? null : id;
  renderItems();
  draw();
}

// ------------------------------------------------------------ drawing

function setupCanvas() {
  const canvas = $("canvas");
  canvas.width = state.result.width;
  canvas.height = state.result.height;
  return canvas.getContext("2d");
}

function lineWidth() {
  return Math.max(2, state.result.width / 320);
}

function draw() {
  if (!state.result || !state.image || state.animating || state.shaken) return;
  const ctx = setupCanvas();
  ctx.drawImage(state.image, 0, 0);
  const items = state.result.items;
  const hitIds = new Set();
  for (const it of items) {
    if (["high", "medium"].includes(it.level)) it.hits.forEach((h) => hitIds.add(h.id));
  }

  if ($("zones-toggle").checked) {
    for (const it of items) {
      if (["high", "medium"].includes(it.level)) drawZone(ctx, it);
    }
  }
  for (const it of items.filter((x) => x.kind === "target")) drawTarget(ctx, it, hitIds.has(it.id));
  for (const it of items.filter((x) => x.kind !== "target")) drawHazard(ctx, it);
}

function drawZone(ctx, it) {
  const z = it.zone;
  const color = it.level === "high" ? "220,38,38" : "217,119,6";
  ctx.save();
  ctx.fillStyle = `rgba(${color},0.22)`;
  ctx.strokeStyle = `rgba(${color},0.9)`;
  ctx.lineWidth = lineWidth();
  ctx.setLineDash([lineWidth() * 3, lineWidth() * 2]);
  ctx.beginPath();
  if (z.type === "rect") {
    ctx.rect(z.x1, z.y1, z.x2 - z.x1, z.y2 - z.y1);
  } else {
    // Only the front half of the oval, matching the server's hit test.
    ctx.rect(0, z.cy - 0.15 * z.ry, state.result.width, state.result.height);
    ctx.clip();
    ctx.beginPath();
    ctx.ellipse(z.cx, z.cy, z.rx, z.ry, 0, 0, Math.PI * 2);
  }
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

function drawTarget(ctx, it, isHit) {
  const [x1, y1, x2, y2] = it.box;
  ctx.save();
  ctx.lineWidth = lineWidth();
  ctx.setLineDash([lineWidth() * 2, lineWidth() * 2]);
  ctx.strokeStyle = isHit ? COLORS.high : "rgba(226,232,240,0.9)";
  if (isHit) {
    ctx.fillStyle = "rgba(220,38,38,0.12)";
    ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
  }
  ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
  ctx.restore();
  label(ctx, isHit ? `${it.label}: in fall zone!` : it.label, x1, y2, isHit ? COLORS.high : COLORS.target);
}

function drawHazard(ctx, it) {
  const [x1, y1, x2, y2] = it.box;
  const color = COLORS[it.level] || COLORS.target;
  const selected = it.id === state.selectedId;
  ctx.save();
  ctx.lineWidth = lineWidth() * (selected ? 2.2 : 1.2);
  ctx.strokeStyle = color;
  if (selected) { ctx.shadowColor = color; ctx.shadowBlur = 12; }
  ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
  ctx.restore();
  const detail = it.kind === "tip" && it.level !== "secured" ? ` · tips at ${it.threshold_g.toFixed(2)} g` : "";
  label(ctx, it.label + detail, x1, y1, color);
}

// A colored tag with white text sitting on top of the point (x, y).
function label(ctx, text, x, y, color) {
  const size = Math.max(12, state.result.width / 55);
  ctx.save();
  ctx.font = `600 ${size}px system-ui, sans-serif`;
  const w = ctx.measureText(text).width + size * 0.8;
  const h = size * 1.5;
  let top = y - h;
  if (top < 0) top = y;
  const left = Math.min(Math.max(0, x), state.result.width - w);
  ctx.fillStyle = color;
  ctx.fillRect(left, top, w, h);
  ctx.fillStyle = "#fff";
  ctx.textBaseline = "middle";
  ctx.fillText(text, left + size * 0.4, top + h / 2);
  ctx.restore();
}

// Tap the photo to select the smallest box under your finger.
function canvasClick(event) {
  if (!state.result) return;
  const rect = $("canvas").getBoundingClientRect();
  const x = (event.clientX - rect.left) * (state.result.width / rect.width);
  const y = (event.clientY - rect.top) * (state.result.height / rect.height);
  const under = state.result.items
    .filter(({ box: [x1, y1, x2, y2] }) => x >= x1 && x <= x2 && y >= y1 && y <= y2)
    .sort((a, b) => area(a.box) - area(b.box));
  if (under.length) select(under[0].id);
}

function area([x1, y1, x2, y2]) {
  return (x2 - x1) * (y2 - y1);
}

// ------------------------------------------------------------ seismograph

// Draw the simulated quake's ground acceleration as a wiggly line, like a
// seismograph. `playhead` (0 to 1) draws a marker for the animation.
function drawSeismograph(playhead) {
  const canvas = $("seismo");
  const ctx = canvas.getContext("2d");
  const W = canvas.width;
  const H = canvas.height;
  const accel = state.result.simulation.frames.accel;
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  ctx.fillStyle = dark ? "#111316" : "#fbfaf7";
  ctx.fillRect(0, 0, W, H);

  // Center line and the "starts to tip" level of the most fragile item, so
  // you can see every moment the shaking is strong enough to rock it.
  ctx.strokeStyle = dark ? "#33373d" : "#e2e0d8";
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke();
  const fragile = state.result.items.filter((it) => it.kind === "tip" && it.level !== "secured");
  if (fragile.length && state.result.demand_g > 0) {
    const level = Math.min(...fragile.map((it) => it.threshold_g)) / state.result.demand_g;
    if (level < 1) {
      ctx.setLineDash([6, 5]);
      ctx.strokeStyle = COLORS.high;
      for (const sign of [1, -1]) {
        const y = H / 2 - sign * level * (H / 2 - 6);
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
      }
      ctx.setLineDash([]);
    }
  }

  const upTo = playhead == null ? accel.length : Math.floor(playhead * accel.length);
  ctx.strokeStyle = dark ? "#eceae4" : "#1d2125";
  ctx.lineWidth = 1.4;
  ctx.globalAlpha = playhead == null ? 0.85 : 1;
  ctx.beginPath();
  for (let i = 0; i < upTo; i++) {
    const x = (i / (accel.length - 1)) * W;
    const y = H / 2 - accel[i] * (H / 2 - 6);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.globalAlpha = 1;
  if (playhead != null) {
    ctx.fillStyle = "#c2410c";
    ctx.fillRect(playhead * W - 1.5, 0, 3, H);
  }
}

// ------------------------------------------------------------ shake animation
//
// The server simulated each object rocking through a quake (rocking.py) and
// sent back, 20 times per simulated second:
//   * frames.ground  how far the floor has moved (-1 to 1)
//   * frames.angles  each object's lean angle in radians
//   * per-item fall_time  when (in seconds) it went past its tipping angle
// The animation just plays that back:
//   * the whole photo slides with the ground
//   * each object is cut out of the photo and leans by its simulated angle
//   * once an object passes its tipping angle, gravity takes over and it
//     falls the rest of the way (angle grows like time squared)
//   * wall items that come off their hooks drop straight down
// Where an object used to be, we show the server's "background plate": the
// photo with the hazards erased by OpenCV inpainting.
// A 90-second Cascadia quake would make a long video, so playback is sped up
// to at most MAX_PLAY_S seconds; the caption shows the real quake time.

const MAX_PLAY_S = 12;
const FALL_MS = 700;   // how long the final topple takes on screen

function shake() {
  if (!state.result || state.animating) return;
  state.animating = true;
  state.shaken = false;
  $("shake-btn").disabled = true;

  const ctx = setupCanvas();
  const W = state.result.width;
  const H = state.result.height;
  const sim = state.result.simulation;
  const { fps, ground, accel, angles } = sim.frames;
  const simSeconds = ground.length / fps;
  const speed = Math.max(1, simSeconds / MAX_PLAY_S);
  const hazards = state.result.items.filter((it) => it.kind !== "target" && it.level);

  const start = performance.now();
  function frame(now) {
    const realMs = now - start;
    const simT = Math.min(simSeconds, (realMs / 1000) * speed);
    const i = Math.min(ground.length - 1, Math.floor(simT * fps));

    // The photo slides with the ground, plus a little buzz from the acceleration.
    const dx = W * (0.018 * ground[i] + 0.004 * accel[i]);
    const dy = H * 0.003 * accel[(i + 7) % accel.length];

    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, W, H);
    ctx.save();
    ctx.translate(dx, dy);
    ctx.drawImage(state.image, 0, 0);

    // First work out where every hazard is this frame...
    let fell = 0;
    const poses = hazards.map((it) => {
      const info = it.sim;
      if (!info) return { it, angle: 0, drop: 0, moved: false };  // secured: moves with the room only
      const fallen = info.fall_time != null && simT >= info.fall_time;
      // Real milliseconds since it passed its tipping point.
      const sinceFall = fallen ? ((simT - info.fall_time) / speed) * 1000 : 0;
      if (fallen) fell++;

      if (it.kind === "wall") {
        if (!fallen) return { it, angle: 0, drop: 0, moved: false };
        const [, , , y2] = it.box;
        const p = Math.min(1, sinceFall / 1100);
        const drop = Math.min(p * p * H, Math.max(0, Math.min(it.zone.y2, H) - y2));
        return { it, angle: 0.25 * p, drop, moved: true };
      }

      let angle = angles[it.id][i];
      if (fallen) {
        // Gravity finishes the job: from its tipping angle down to the floor.
        const lastLean = angles[it.id][Math.min(angles[it.id].length - 1,
          Math.floor(info.fall_time * fps))];
        const sign = Math.sign(lastLean) || 1;
        const p = Math.min(1, sinceFall / FALL_MS);
        angle = sign * (info.alpha + (Math.PI / 2 * 0.92 - info.alpha) * p * p);
      }
      return { it, angle, drop: 0, moved: angle !== 0 };
    });

    // ...then erase the spots of everything that moved, and redraw every
    // hazard on top, biggest first. Boxes overlap (a monitor sits inside a
    // bookshelf's box), so erasing the bookshelf would otherwise also erase
    // a monitor that is standing still.
    if (poses.some((pose) => pose.moved)) {
      poses.filter((pose) => pose.moved).forEach((pose) => erase(ctx, pose.it));
      poses.sort((a, b) => area(b.it.box) - area(a.it.box))
        .forEach((pose) => drawPiece(ctx, pose.it, pose.angle, pose.drop));
    }
    ctx.restore();

    drawSeismograph(simT / simSeconds);
    renderSimCaption(`${clock(simT)} of ${clock(simSeconds)}` +
      (speed > 1 ? ` (${speed.toFixed(1)}x speed)` : ""));

    if (realMs < (simSeconds / speed) * 1000 + FALL_MS) {
      requestAnimationFrame(frame);
    } else {
      state.animating = false;
      state.shaken = true;
      $("shake-btn").disabled = false;
      banner(ctx, fell === 0 ? "Nothing fell in this quake. Nice!"
        : `${fell} item${fell > 1 ? "s" : ""} fell in this simulated quake. Check the fix list.`);
    }
  }
  requestAnimationFrame(frame);
}

// 75.3 -> "1:15"
function clock(seconds) {
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// Cover an item's original spot with the inpainted background.
function erase(ctx, it) {
  const [x1, y1, x2, y2] = it.box;
  const [bx, by, bw, bh] = [x1 - 2, y1 - 2, x2 - x1 + 4, y2 - y1 + 4];
  ctx.drawImage(state.background, bx, by, bw, bh, bx, by, bw, bh);
}

// Draw one item's cut-out, leaning by `angle` radians about one of its
// bottom corners, and moved down by `drop` pixels.
// The simulation rocks things front-to-back (toward the camera), which a
// flat photo can't show, so we draw the lean sideways instead. Positive
// angles lean toward the middle of the room (the photo's center).
function drawPiece(ctx, it, angle, drop) {
  const [x1, y1, x2, y2] = it.box;
  const w = x2 - x1;
  const h = y2 - y1;
  const towardCenter = (x1 + x2) / 2 < state.result.width / 2 ? 1 : -1;
  const dir = towardCenter * (Math.sign(angle) || 1);
  const pivotX = dir > 0 ? x2 : x1;   // it pivots on the corner it leans over
  ctx.save();
  ctx.translate(pivotX, y2 + drop);
  ctx.rotate(dir * Math.abs(angle));
  ctx.drawImage(state.image, x1, y1, w, h, x1 - pivotX, y1 - y2, w, h);
  ctx.restore();
}

function banner(ctx, text) {
  const W = state.result.width;
  const size = Math.max(16, W / 34);
  ctx.save();
  ctx.font = `700 ${size}px system-ui, sans-serif`;
  // Shrink the text if it's wider than the photo.
  const fit = Math.min(1, (W * 0.94) / ctx.measureText(text).width);
  ctx.font = `700 ${size * fit}px system-ui, sans-serif`;
  ctx.fillStyle = "rgba(0,0,0,0.65)";
  ctx.fillRect(0, 0, W, size * 2.2);
  ctx.fillStyle = "#fff";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, W / 2, size * 1.1);
  ctx.restore();
}

function reset() {
  state.shaken = false;
  draw();
  if (state.result) { drawSeismograph(null); renderSimCaption(); }
}

// ------------------------------------------------------------ wire it all up

fillFloorSelects();
$("photo").addEventListener("change", (e) => e.target.files[0] && setPhoto(e.target.files[0]));
$("scan-form").addEventListener("submit", scan);
$("total-floors").addEventListener("change", () => { updateFloorOptions(); recalculate(); });
$("floor").addEventListener("change", recalculate);
$("scenario").addEventListener("change", recalculate);
$("quake-type").addEventListener("change", recalculate);
$("budget").addEventListener("input", () => {
  clearTimeout(editTimer);
  editTimer = setTimeout(recalculate, 400);
});
$("print-btn").addEventListener("click", () => window.print());
$("address").addEventListener("change", updateAddress);
$("zones-toggle").addEventListener("change", draw);
$("shake-btn").addEventListener("click", shake);
$("reset-btn").addEventListener("click", reset);
$("canvas").addEventListener("click", canvasClick);

for (const btn of document.querySelectorAll("[data-sample]")) {
  btn.addEventListener("click", async () => {
    const name = btn.dataset.sample;
    const blob = await (await fetch("/static/samples/" + name)).blob();
    setPhoto(new File([blob], name, { type: blob.type }));
  });
}
