import { Viewer } from "/static/viewer.js";
import { Net } from "/static/net.js";
import { CameraScanner } from "/static/camera.js";
import { labToHex } from "/static/colormatch.js";

const $ = (id) => document.getElementById(id);

const app = {
  puzzle: null,       // description du puzzle (API)
  colors: [],         // couleur affichée de chaque facette (-1 = inconnue)
  current: 0,         // couleur sélectionnée pour peindre
  moveIndex: {},      // nom de mouvement -> description
  solution: null,     // réponse du solveur
  mode: "guide",      // "guide" ou "short"
  plan: null,         // { moves: [...], steps: [...] } pour le mode affiché
  pos: 0,             // nombre de coups appliqués depuis l'état mélangé
  start: null,        // couleurs de l'état mélangé
  playing: false,
  busy: false,
  pick: null,         // couleur en cours d'étalonnage à la pipette
};

const viewer = new Viewer($("viewer"), (id, e) => paint(id, e));
const net = new Net($("net"), (id, e) => paint(id, e));
const scanner = new CameraScanner($("cam-video"), $("cam-overlay"));

// ---------------------------------------------------------------- utilitaires
async function api(path, body) {
  // Build GitHub Pages : pas de serveur, le moteur Python tourne dans le
  // navigateur (Pyodide). window.RHAPI, posé par boot.js, imite fetch().
  if (window.RHAPI) return window.RHAPI.call(path, body);
  const res = await fetch(path, body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : undefined);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || data.detail || `Erreur ${res.status}`);
    err.stickers = data.stickers || [];
    err.repairs = data.repairs || [];
    throw err;
  }
  return data;
}

function message(text, kind = "info") {
  const el = $("message");
  if (!text) { el.classList.add("hidden"); return; }
  el.className = `message ${kind}`;
  el.textContent = text;
}

function render() {
  viewer.setColors(app.colors, app.puzzle.palette);
  net.setColors(app.colors, app.puzzle.palette);
  updateCounts();
}

function speedMs() {
  const v = Number($("pl-speed").value);
  return Math.round(900 * Math.pow(0.04, v / 100)); // 900 ms -> ~36 ms
}

function applyPerm(colors, perm) {
  const out = new Array(colors.length);
  for (let a = 0; a < perm.length; a++) out[perm[a]] = colors[a];
  return out;
}

function applyInverse(colors, perm) {
  const out = new Array(colors.length);
  for (let a = 0; a < perm.length; a++) out[a] = colors[perm[a]];
  return out;
}

// --------------------------------------------------------------- chargement
async function loadPuzzleList() {
  const list = await api("/api/puzzles");
  const sel = $("puzzle");
  sel.innerHTML = list.map((p) => `<option value="${p.id}">${p.label}</option>`).join("");
  const saved = safeGet("puzzle");
  if (saved && list.some((p) => p.id === saved)) sel.value = saved;
  sel.addEventListener("change", () => loadPuzzle(sel.value));
  await loadPuzzle(sel.value);
}

async function loadPuzzle(id) {
  stopPlaying();
  safeSet("puzzle", id);
  $("status").textContent = "Chargement...";
  const p = await api(`/api/puzzles/${id}`);
  app.puzzle = p;
  app.moveIndex = Object.fromEntries(p.moves.map((m) => [m.name, m]));
  app.colors = p.solved.slice();
  app.current = 0;
  for (const s of p.stickers) if (s.ignored) app.colors[s.id] = -1;
  viewer.load(p);
  net.load(p);
  scanner.setPalette(p.palette);
  loadCalibration();
  buildPalette();
  buildCameraFaces();
  buildNotationHelp();
  clearSolution();
  app.cheat = null;
  if (app.rtab === "cheat") loadCheat();
  render();
  $("status").textContent = p.ready ? "" : "Bibliothèque de commutateurs en préparation (première utilisation)...";
  if (!p.ready) pollReady(id);
  message("");
}

async function pollReady(id) {
  for (let i = 0; i < 120; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    if (app.puzzle?.id !== id) return;
    const list = await api("/api/puzzles");
    if (list.find((p) => p.id === id)?.ready) { $("status").textContent = ""; return; }
  }
}

// ------------------------------------------------------------------ peinture
function buildPalette() {
  const el = $("palette");
  el.innerHTML = "";
  app.puzzle.palette.forEach((c, i) => {
    const b = document.createElement("button");
    b.className = "swatch" + (i === app.current ? " active" : "");
    b.innerHTML = `<span class="dot" style="background:${c.hex}"></span><span>${c.name}</span><span class="count"></span>`;
    b.addEventListener("click", () => {
      app.current = i;
      [...el.children].forEach((x, j) => x.classList.toggle("active", j === i));
    });
    el.appendChild(b);
  });
}

function updateCounts() {
  const p = app.puzzle;
  const expected = p.palette.map(() => 0);
  const got = p.palette.map(() => 0);
  for (const s of p.stickers) {
    if (s.ignored) continue;
    expected[p.solved[s.id]]++;
    const c = app.colors[s.id];
    if (c >= 0) got[c]++;
  }
  [...$("palette").children].forEach((b, i) => {
    const el = b.querySelector(".count");
    el.textContent = `${got[i]}/${expected[i]}`;
    el.classList.toggle("bad", got[i] > expected[i]);
  });
}

function paint(id, e) {
  if (app.busy) return;
  const s = app.puzzle.stickers[id];
  if (s.ignored) return;
  if (app.solution) clearSolution();
  if (e?.shiftKey) {
    for (const t of app.puzzle.stickers) if (t.face === s.face && !t.ignored) app.colors[t.id] = app.current;
  } else {
    app.colors[id] = app.current;
  }
  viewer.setErrors([]); net.setErrors([]);
  render();
}

$("btn-solved").addEventListener("click", () => {
  if (app.busy) return;
  clearSolution();
  app.colors = app.puzzle.solved.slice();
  for (const s of app.puzzle.stickers) if (s.ignored) app.colors[s.id] = -1;
  render();
  message("");
});

$("btn-clear").addEventListener("click", () => {
  if (app.busy) return;
  clearSolution();
  app.colors = app.colors.map(() => -1);
  render();
  message("Toutes les facettes sont à renseigner.", "info");
});

// -------------------------------------------------------------------- onglets
document.querySelectorAll(".tab[data-tab]").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab[data-tab]").forEach((x) => x.classList.toggle("active", x === t));
  for (const name of ["paint", "camera", "formula"]) $(`tab-${name}`).classList.toggle("hidden", t.dataset.tab !== name);
  if (t.dataset.tab !== "camera" && scanner.active) {
    scanner.stop();
    $("cam-capture").disabled = true;
    $("cam-accept").disabled = true;
    $("cam-start").textContent = "Activer la caméra";
  }
}));

// --------------------------------------------------------------------- caméra
function buildCameraFaces() {
  const sel = $("cam-face");
  sel.innerHTML = app.puzzle.faces.map((f, i) => `<option value="${i}">${f.name}</option>`).join("");
  scanner.result = null;
  $("cam-reread").disabled = true;
  if (scanner.active) scanner.drawOverlay(app.puzzle, 0);
  setPick(null);
  buildCalibration();
}

// Étalonnage : une couleur mesurée par couleur de la palette, propre à chaque
// famille de puzzle (cubes, Megaminx, Pyraminx) et à chaque appareil.
function calibrationKey() { return `calib:${app.puzzle.kind}`; }

function loadCalibration() {
  try { scanner.model.load(JSON.parse(safeGet(calibrationKey()) || "null")); } catch { /* étalonnage illisible */ }
}

function saveCalibration() { safeSet(calibrationKey(), JSON.stringify(scanner.model.dump())); }

function buildCalibration() {
  const el = $("calib-grid");
  el.innerHTML = "";
  app.puzzle.palette.forEach((c, i) => {
    const measured = scanner.model.measured(i);
    const b = document.createElement("button");
    b.className = "swatch" + (i === app.pick ? " active" : "");
    b.title = measured ? "Couleur mesurée : toucher pour la mesurer à nouveau" : "Pas encore mesurée";
    const hex = measured ? labToHex(scanner.model.refs[i]) : c.hex;
    b.innerHTML = `<span class="dot${measured ? "" : " unset"}" style="background:${hex}"></span><span>${c.name}</span>`;
    b.addEventListener("click", () => setPick(app.pick === i ? null : i));
    el.appendChild(b);
  });
}

function setPick(i) {
  app.pick = i;
  document.querySelector(".cam-wrap").classList.toggle("picking", i !== null);
  [...$("calib-grid").children].forEach((x, j) => x.classList.toggle("active", j === i));
  if (i === null) return;
  if (!scanner.active) message("Activez la caméra, puis touchez une facette de la couleur choisie.", "info");
  else message(`Touchez une facette ${app.puzzle.palette[i].name.toLowerCase()} sur l'image.`, "info");
}

$("cam-overlay").addEventListener("click", (e) => {
  if (app.pick === null || !scanner.active) return;
  const i = app.pick;
  if (!scanner.pick(e.clientX, e.clientY, i)) return;
  saveCalibration();
  // couleur suivante pas encore mesurée, pour enchaîner rapidement
  const n = app.puzzle.palette.length;
  let next = null;
  for (let k = 1; k < n; k++) if (!scanner.model.measured((i + k) % n)) { next = (i + k) % n; break; }
  buildCalibration();
  setPick(next);
  if (next === null) message(`${app.puzzle.palette[i].name} mesuré. Toutes les couleurs sont étalonnées.`, "ok");
});

$("calib-reset").addEventListener("click", () => {
  scanner.model.reset();
  saveCalibration();
  buildCalibration();
  setPick(null);
  message("Étalonnage effacé : retour aux couleurs par défaut.", "info");
});

$("cam-reread").addEventListener("click", () => {
  const got = scanner.reclassifyAll(app.puzzle);
  if (app.solution) clearSolution();
  for (const [id, c] of Object.entries(got)) app.colors[id] = c;
  render();
  if (scanner.active) scanner.drawOverlay(app.puzzle, Number($("cam-face").value));
  message("Toutes les faces ont été relues. Vérifiez le patron, puis lancez la résolution.", "ok");
});

$("cam-face").addEventListener("change", () => {
  scanner.result = null;
  $("cam-accept").disabled = true;
  if (scanner.active) scanner.drawOverlay(app.puzzle, Number($("cam-face").value));
  net.setHighlight(app.puzzle.stickers.filter((s) => s.face === Number($("cam-face").value)).map((s) => s.id));
});

$("cam-start").addEventListener("click", async () => {
  if (scanner.active) {
    scanner.stop();
    $("cam-start").textContent = "Activer la caméra";
    $("cam-capture").disabled = true;
    return;
  }
  try {
    await scanner.start();
    $("cam-start").textContent = "Couper la caméra";
    $("cam-capture").disabled = false;
    const f = Number($("cam-face").value);
    scanner.drawOverlay(app.puzzle, f);
    net.setHighlight(app.puzzle.stickers.filter((s) => s.face === f).map((s) => s.id));
  } catch (err) {
    message(`Caméra : ${err.message}`, "error");
  }
});

$("cam-capture").addEventListener("click", () => {
  const f = Number($("cam-face").value);
  const got = scanner.capture(app.puzzle, f);
  if (app.solution) clearSolution();
  for (const [id, c] of Object.entries(got)) app.colors[id] = c;
  render();
  scanner.drawOverlay(app.puzzle, f);
  $("cam-accept").disabled = false;
  const all = scanner.capturedFaces() === app.puzzle.faces.length;
  $("cam-reread").disabled = !all;
  message(all
    ? "Face lue. Toutes les faces sont capturées : « Relire toutes les faces » affine l'ensemble."
    : "Face lue. Corrigez si besoin en peignant sur le patron, puis validez.", "info");
});

$("cam-accept").addEventListener("click", () => {
  const f = Number($("cam-face").value);
  scanner.learn(app.colors);
  scanner.result = null;
  $("cam-accept").disabled = true;
  const sel = $("cam-face");
  const next = (f + 1) % app.puzzle.faces.length;
  sel.value = next;
  sel.dispatchEvent(new Event("change"));
  message(`Face ${app.puzzle.faces[f].name} validée. Face suivante : ${app.puzzle.faces[next].name}.`, "ok");
});

// -------------------------------------------------------------------- formule
function buildNotationHelp() {
  const p = app.puzzle;
  const el = $("notation-help");
  if (p.family === "cube") {
    el.innerHTML = `<ul>
      <li><code>R</code> quart de tour horaire de la face, <code>R'</code> antihoraire, <code>R2</code> demi-tour</li>
      <li>Faces : <code>U D F B L R</code></li>
      <li><code>Rw</code> ou <code>r</code> : deux couches ; <code>3Rw</code> : trois couches</li>
      <li><code>2R</code> : deuxième tranche seule ; <code>M E S</code> : tranche centrale (cubes impairs)</li>
      <li><code>x y z</code> : rotation du cube entier</li></ul>`;
  } else if (p.family === "tetra") {
    el.innerHTML = `<ul>
      <li><code>U</code> 1/3 de tour horaire du sommet, <code>U'</code> dans l'autre sens</li>
      <li>Sommets : <code>${p.faces.map((f) => f.name).join(" ")}</code> (tour du coin et de ses arêtes)</li>
      <li>Minuscules <code>u l r b</code> : la pointe seule</li></ul>`;
  } else {
    el.innerHTML = `<ul>
      <li><code>R</code> 1/5 de tour horaire, <code>R2</code> 2/5, <code>R2'</code> et <code>R'</code> dans l'autre sens</li>
      <li>Faces : <code>${p.faces.map((f) => f.name).join(" ")}</code></li>
      ${p.size > 3 ? "<li><code>2R</code> : deuxième tranche seule ; <code>Rw</code> : deux couches</li>" : ""}
      <li>Mélanges WCA : <code>R++ R-- D++ D--</code> (tout le puzzle sauf une face, 2/5 de tour)</li></ul>`;
  }
}

async function runFormula(fromSolved) {
  if (app.busy) return;
  const text = $("formula").value.trim();
  if (!text) { message("Saisissez une formule.", "info"); return; }
  clearSolution();
  let base = fromSolved ? app.puzzle.solved.slice() : app.colors.slice();
  if (fromSolved) for (const s of app.puzzle.stickers) if (s.ignored) base[s.id] = -1;
  if (!fromSolved && base.some((c, i) => c < 0 && !app.puzzle.stickers[i].ignored)) {
    message("L'état actuel est incomplet : appliquez plutôt la formule au puzzle résolu.", "error");
    return;
  }
  try {
    const res = await api("/api/formula", { puzzle: app.puzzle.id, formula: text, colors: base });
    app.colors = base;
    render();
    await playTokens(res.tokens);
    app.colors = res.colors;
    render();
    message(`Formule appliquée (${res.tokens.length} mouvements).`, "ok");
  } catch (err) {
    message(err.message, "error");
  }
}

async function playTokens(tokens) {
  const animate = $("chk-animate").checked;
  app.busy = true;
  try {
    for (const t of tokens) {
      if (animate) await viewer.animate(t.face, t.angle, t.members, Math.min(speedMs(), 160));
      app.colors = applyPerm(app.colors, t.perm);
      render();
    }
  } finally {
    app.busy = false;
  }
}

$("btn-apply-solved").addEventListener("click", () => runFormula(true));
$("btn-apply-current").addEventListener("click", () => runFormula(false));
$("btn-random").addEventListener("click", async () => {
  if (app.busy) return;
  const res = await api("/api/scramble", { puzzle: app.puzzle.id });
  $("formula").value = res.formula;
  await runFormula(true);
});

// ---------------------------------------------------------------- résolution
$("btn-solve").addEventListener("click", () => solve());

// repairs : corrections virtuelles (« Résoudre quand même »). La solution est
// calculée sur l'état corrigé mais jouée à partir de l'état réel : à la fin,
// seules les pièces mal remontées restent fausses.
async function solve(repairs = null) {
  if (app.busy) return;
  const missing = app.puzzle.stickers.filter((s) => !s.ignored && app.colors[s.id] < 0).map((s) => s.id);
  if (missing.length) {
    viewer.setErrors(missing); net.setErrors(missing);
    message(`${missing.length} facette(s) sans couleur (entourées en rouge).`, "error");
    return;
  }
  viewer.setErrors([]); net.setErrors([]);
  message(app.puzzle.ready ? "Calcul en cours..." :
    "Calcul en cours. La première résolution de ce puzzle prépare sa bibliothèque de commutateurs (jusqu'à une minute).", "info");
  $("btn-solve").disabled = true;
  const target = app.colors.slice();
  if (repairs) for (const r of repairs) for (const [id, c] of r.changes) target[id] = c;
  try {
    const res = await api("/api/solve", { puzzle: app.puzzle.id, colors: target });
    app.puzzle.ready = true;
    $("status").textContent = "";
    app.solution = res;
    app.start = app.colors.slice();
    app.withDefects = !!repairs;
    app.mode = "guide";
    if (res.move_count === 0 && !repairs) {
      message("Le puzzle est déjà résolu.", "ok");
      clearSolution();
      return;
    }
    message(repairs
      ? "Solution calculée en ignorant le défaut de remontage. Suivez-la sur le puzzle réel : à la fin, "
        + "seules les pièces mal remontées resteront fausses et seront montrées."
      : "Solution trouvée. Utilisez le lecteur pour la suivre coup par coup.", repairs ? "info" : "ok");
    showSolution();
  } catch (err) {
    viewer.setErrors(err.stickers); net.setErrors(err.stickers);
    if (err.repairs?.length) showRepairs(err.message, err.repairs);
    else message(err.message, "error");
  } finally {
    $("btn-solve").disabled = false;
  }
}

// Pastilles « face : couleur actuelle -> couleur attendue » d'une pièce.
function facesHtml(faces) {
  const pal = app.puzzle.palette;
  const dot = (c) => `<span class="dot" style="background:${pal[c].hex}" title="${pal[c].name}"></span>`;
  return `<table class="faces"><tr><th>Face (centre)</th><th>Montre</th><th>Doit montrer</th></tr>`
    + faces.map((f) => `<tr class="${f.now === f.target ? "" : "wrong"}">
        <td>${dot(f.face)} ${escapeHtml(pal[f.face].name)}</td>
        <td>${dot(f.now)} ${escapeHtml(pal[f.now].name)}</td>
        <td>${dot(f.target)} ${escapeHtml(pal[f.target].name)}</td></tr>`).join("")
    + `</table>`;
}

function itemHtml(it, key) {
  return `<div class="repair-item" data-key="${key}">
      <div class="repair-item-head"><strong>${escapeHtml(it.label)}</strong>
        <button class="secondary small show-btn">Montrer</button></div>
      <div class="where">${escapeHtml(it.where)}</div>
      <div class="instr">${escapeHtml(it.instruction)}</div>
      ${facesHtml(it.faces)}
    </div>`;
}

function bindItems(root, items, all) {
  root.querySelectorAll(".repair-item").forEach((d) => {
    const it = items[d.dataset.key];
    const show = () => { viewer.setErrors(it.stickers); net.setErrors(it.stickers); viewer.focusOn(it.focus); };
    d.querySelector(".show-btn").addEventListener("click", show);
    d.addEventListener("mouseenter", () => { viewer.setErrors(it.stickers); net.setErrors(it.stickers); });
    d.addEventListener("mouseleave", () => { viewer.setErrors(all); net.setErrors(all); });
  });
}

// Puzzle mal remonté : pièces en cause, correction physique, ou résolution malgré tout.
function showRepairs(text, repairs) {
  const el = $("message");
  el.className = "message error";
  const items = {};
  el.innerHTML = `<p class="repair-head">${escapeHtml(text)}</p>`
    + repairs.map((r, i) => `<div class="repair">
        <p class="repair-title">${escapeHtml(r.title)}</p>
        ${r.items.map((it, j) => { items[`${i}-${j}`] = it; return itemHtml(it, `${i}-${j}`); }).join("")}
      </div>`).join("")
    + `<div class="row">
         <button id="btn-anyway">Résoudre quand même</button>
         <button id="btn-repair" class="secondary">J'ai corrigé le puzzle</button>
       </div>
       <p class="repair-note">« Résoudre quand même » : suivez la solution sur votre puzzle tel quel ;
       à la fin, il ne restera que la ou les pièces mal remontées, faciles à repérer.
       « J'ai corrigé le puzzle » : après avoir fait la correction ci-dessus à la main.</p>`;
  const all = [...new Set(repairs.flatMap((r) => r.suspects))];
  bindItems(el, items, all);
  const first = Object.values(items)[0];
  if (first) viewer.focusOn(first.focus);
  $("btn-anyway").addEventListener("click", () => solve(repairs));
  $("btn-repair").addEventListener("click", () => {
    for (const r of repairs) for (const [id, c] of r.changes) app.colors[id] = c;
    viewer.setErrors([]); net.setErrors([]);
    render();
    solve();
  });
}

// Fin de lecture en mode « quand même » : pièces encore fausses, par pièce.
const PIECE_WORD = { corner: "coin", midge: "arête", wing: "aile" };

function remainingDefects() {
  const p = app.puzzle;
  const fc = app.solution.face_colors;
  const pal = p.palette;
  const byPiece = new Map();
  for (const s of p.stickers) {
    if (s.ignored) continue;
    if (app.colors[s.id] !== fc[s.face]) {
      if (!byPiece.has(s.piece)) byPiece.set(s.piece, []);
    }
  }
  const items = [];
  for (const piece of byPiece.keys()) {
    const sts = p.stickers.filter((s) => s.piece === piece);
    const kind = p.orbits[sts[0].orbit].kind;
    const word = PIECE_WORD[kind] || "pièce";
    const fem = word !== "coin";
    const now = sts.map((s) => app.colors[s.id]);
    const want = sts.map((s) => fc[s.face]);
    const sameSet = [...now].sort().join() === [...want].sort().join();
    const names = sts.map((s) => pal[fc[s.face]].name.toLowerCase());
    const where = names.length === 1 ? `sur la face ${names[0]}`
      : `entre les centres ${names.slice(0, -1).join(", ")} et ${names[names.length - 1]}`;
    const c = sts.flatMap((s) => s.poly).reduce((a, v) => [a[0] + v[0], a[1] + v[1], a[2] + v[2]], [0, 0, 0]);
    const n = Math.hypot(...c);
    items.push({
      label: `${word[0].toUpperCase()}${word.slice(1)} ` + now.map((x) => pal[x].name.toLowerCase()).join(" / "),
      where,
      instruction: sameSet
        ? `À sa place mais ${fem ? "tournée" : "tourné"} : ${fem ? "retournez-la" : "tournez-le"} sur place (démontage nécessaire).`
        : `Pas à sa place : ${fem ? "elle" : "il"} doit être ${fem ? "échangée" : "échangé"} avec l'autre pièce signalée.`,
      faces: sts.map((s) => ({ face: fc[s.face], now: app.colors[s.id], target: fc[s.face] })),
      stickers: sts.map((s) => s.id),
      focus: c.map((x) => x / n),
    });
  }
  return items;
}

function buildPlan() {
  const res = app.solution;
  const moves = [];
  const steps = [];
  if (app.mode === "short" && res.short) {
    steps.push({ stage: 0, stageTitle: "Solution optimisée", title: "Algorithme de Kociemba",
      detail: "Solution courte calculée par l'algorithme à deux phases. Efficace mais sans logique visible : "
        + "pour apprendre, préférez le guide pas à pas.", notation: "", highlight: [], from: 0, to: res.short.moves.length });
    moves.push(...res.short.moves);
    return { moves, steps, stages: [{ title: "Solution optimisée", detail: "", steps: [0] }] };
  }
  const stages = [];
  res.stages.forEach((sg, si) => {
    const ids = [];
    sg.steps.forEach((sp) => {
      ids.push(steps.length);
      steps.push({ stage: si, stageTitle: sg.title, title: sp.title, detail: sp.detail, notation: sp.notation,
        highlight: sp.highlight, from: moves.length, to: moves.length + sp.moves.length });
      moves.push(...sp.moves);
    });
    stages.push({ title: sg.title, detail: sg.detail, steps: ids });
  });
  return { moves, steps, stages };
}

function showSolution() {
  $("sol-empty").classList.add("hidden");
  $("sol").classList.remove("hidden");
  const res = app.solution;
  const modes = $("sol-modes");
  modes.innerHTML = "";
  if (res.short) {
    for (const [m, label] of [["guide", `Guide pas à pas (${res.move_count} coups)`], ["short", `Solution courte (${res.short.move_count} coups)`]]) {
      const b = document.createElement("button");
      b.className = "secondary small" + (app.mode === m ? " active" : "");
      b.textContent = label;
      b.addEventListener("click", () => {
        if (app.mode === m) return;
        stopPlaying();
        app.colors = app.start.slice();
        app.mode = m;
        render();
        showSolution();
      });
      modes.appendChild(b);
    }
  }
  app.plan = buildPlan();
  app.pos = 0;
  const nSteps = app.plan.steps.length;
  $("sol-summary").textContent = app.mode === "short"
    ? `${app.plan.moves.length} coups.`
    : `${app.plan.moves.length} coups répartis en ${nSteps} étapes. Chaque étape est une courte séquence `
      + `qui échange trois pièces (voir l'aide-mémoire).`;
  buildStages();
  updatePlayer();
}

function buildStages() {
  const el = $("sol-stages");
  el.innerHTML = "";
  app.plan.stages.forEach((sg, si) => {
    const d = document.createElement("details");
    d.dataset.stage = si;
    const n = sg.steps.reduce((a, i) => a + app.plan.steps[i].to - app.plan.steps[i].from, 0);
    d.innerHTML = `<summary>${si + 1}. ${sg.title}<span class="meta">${sg.steps.length} étape(s), ${n} coups</span></summary>`
      + (sg.detail ? `<div class="stage-detail">${sg.detail}</div>` : "");
    const ol = document.createElement("ol");
    for (const i of sg.steps) {
      const st = app.plan.steps[i];
      const li = document.createElement("li");
      li.dataset.step = i;
      li.innerHTML = `${escapeHtml(st.title)} <span class="len">(${st.to - st.from})</span>`;
      li.addEventListener("click", () => seek(st.from, true));
      ol.appendChild(li);
    }
    d.appendChild(ol);
    el.appendChild(d);
  });
}

function stepAt(pos) {
  const steps = app.plan.steps;
  for (let i = 0; i < steps.length; i++) if (pos < steps[i].to) return i;
  return steps.length - 1;
}

function updatePlayer() {
  const plan = app.plan;
  if (!plan) return;
  const done = app.pos >= plan.moves.length;
  const si = stepAt(Math.min(app.pos, plan.moves.length - 1));
  const st = plan.steps[si];
  const cur = $("sol-current");
  const chips = plan.moves.slice(st.from, st.to).map((m, k) => {
    const idx = st.from + k;
    const cls = idx < app.pos ? "mv done" : idx === app.pos ? "mv now" : "mv";
    return `<span class="${cls}" data-i="${idx}">${m}</span>`;
  }).join("");
  const defects = done && app.withDefects ? remainingDefects() : [];
  cur.innerHTML = done
    ? (defects.length
      ? `<div class="step-title">Terminé : ${defects.length === 1 ? "il reste une pièce" : `il reste ${defects.length} pièces`} à corriger à la main.</div>
         <div class="step-detail">Tout le reste est résolu. Corrigez ${defects.length === 1 ? "cette pièce" : "ces pièces"}
         sur le puzzle réel pour terminer :</div>
         ${defects.map((it, i) => itemHtml(it, i)).join("")}`
      : `<div class="step-title">Puzzle résolu.</div><div class="step-detail">${plan.moves.length} coups joués.</div>`)
    : `<div class="stage-name">${escapeHtml(st.stageTitle)} — étape ${si + 1}/${plan.steps.length}</div>
       <div class="step-title">${escapeHtml(st.title)}</div>
       ${st.detail ? `<div class="step-detail">${escapeHtml(st.detail)}</div>` : ""}
       <div class="moves">${chips}</div>`;
  cur.querySelectorAll(".mv").forEach((x) => x.addEventListener("click", () => seek(Number(x.dataset.i), true)));
  if (defects.length) {
    const all = defects.flatMap((it) => it.stickers);
    bindItems(cur, defects, all);
    viewer.setErrors(all); net.setErrors(all);
    viewer.focusOn(defects[0].focus);
  } else if (app.withDefects) {
    viewer.setErrors([]); net.setErrors([]);
  }
  // surbrillance des pièces de l'étape à son début
  const hl = !done && app.pos === st.from ? st.highlight : [];
  viewer.setHighlight(hl); net.setHighlight(hl);
  // liste des étapes
  document.querySelectorAll("#sol-stages li").forEach((li) => {
    const i = Number(li.dataset.step);
    li.classList.toggle("active", !done && i === si);
    li.classList.toggle("done", plan.steps[i].to <= app.pos);
  });
  document.querySelectorAll("#sol-stages details").forEach((d) => {
    if (!done && Number(d.dataset.stage) === st.stage && !d.open) d.open = true;
  });
  $("pl-play").textContent = app.playing ? "Pause" : "Lecture";
  $("pl-prev").disabled = app.pos === 0;
  $("pl-start").disabled = app.pos === 0;
  $("pl-next").disabled = done;
  $("pl-step").disabled = done;
  $("pl-end").disabled = done;
}

async function stepForward(animate = true) {
  const name = app.plan.moves[app.pos];
  const mv = app.moveIndex[name];
  if (animate) await viewer.animate(mv.face, mv.angle, mv.members, speedMs());
  app.colors = applyPerm(app.colors, mv.perm);
  app.pos++;
  render();
  updatePlayer();
}

async function stepBack(animate = true) {
  const name = app.plan.moves[app.pos - 1];
  const mv = app.moveIndex[name];
  if (animate) await viewer.animate(mv.face, -mv.angle, mv.members, speedMs());
  app.colors = applyInverse(app.colors, mv.perm);
  app.pos--;
  render();
  updatePlayer();
}

// saute directement à une position (sans animation)
function seek(target) {
  if (app.busy) return;
  stopPlaying();
  let c = app.start.slice();
  for (let i = 0; i < target; i++) c = applyPerm(c, app.moveIndex[app.plan.moves[i]].perm);
  app.colors = c;
  app.pos = target;
  render();
  updatePlayer();
}

async function guarded(fn) {
  if (app.busy) return;
  app.busy = true;
  try { await fn(); } finally { app.busy = false; updatePlayer(); }
}

$("pl-next").addEventListener("click", () => guarded(() => stepForward()));
$("pl-prev").addEventListener("click", () => guarded(() => stepBack()));
$("pl-start").addEventListener("click", () => seek(0));
$("pl-end").addEventListener("click", () => seek(app.plan.moves.length));
$("pl-step").addEventListener("click", () => guarded(async () => {
  const st = app.plan.steps[stepAt(app.pos)];
  while (app.pos < st.to) await stepForward(true);
}));
$("pl-play").addEventListener("click", () => {
  if (app.playing) { stopPlaying(); return; }
  if (app.busy) return;
  app.playing = true;
  updatePlayer();
  guarded(async () => {
    while (app.playing && app.pos < app.plan.moves.length) await stepForward(true);
    app.playing = false;
  });
});

function stopPlaying() {
  app.playing = false;
  if (app.plan) updatePlayer();
}

function clearSolution() {
  stopPlaying();
  app.solution = null;
  app.plan = null;
  $("sol").classList.add("hidden");
  $("sol-empty").classList.remove("hidden");
  viewer.setHighlight([]); net.setHighlight([]);
}

$("btn-reset-view").addEventListener("click", () => viewer.resetView());

document.addEventListener("keydown", (e) => {
  if (!app.plan || ["TEXTAREA", "INPUT", "SELECT"].includes(document.activeElement?.tagName)) return;
  if (e.key === "ArrowRight") { e.preventDefault(); $("pl-next").click(); }
  if (e.key === "ArrowLeft") { e.preventDefault(); $("pl-prev").click(); }
  if (e.key === " ") { e.preventDefault(); $("pl-play").click(); }
});

// --------------------------------------------------------------- aide-mémoire
app.rtab = "solution";
app.cheat = null;

document.querySelectorAll(".tab[data-rtab]").forEach((t) => t.addEventListener("click", () => {
  if (app.busy) return;
  const name = t.dataset.rtab;
  if (name === app.rtab) return;
  stopPlaying();
  app.rtab = name;
  document.querySelectorAll(".tab[data-rtab]").forEach((x) => x.classList.toggle("active", x === t));
  $("rtab-solution").classList.toggle("hidden", name !== "solution");
  $("rtab-cheat").classList.toggle("hidden", name !== "cheat");
  if (name === "cheat") {
    loadCheat();
  } else {
    // retour à la saisie de l'utilisateur
    render();
    viewer.setHighlight([]); net.setHighlight([]);
    if (app.plan) updatePlayer();
  }
}));

async function loadCheat() {
  const el = $("cheat");
  const id = app.puzzle.id;
  if (!app.cheat) {
    el.innerHTML = `<p class="hint">Chargement de l'aide-mémoire...</p>`;
    try {
      const data = await api(`/api/cheatsheet/${id}`);
      if (app.puzzle.id !== id) return;
      app.cheat = data;
    } catch (err) {
      el.innerHTML = `<p class="message error">${escapeHtml(err.message)}</p>`;
      return;
    }
  }
  renderCheat();
}

function partsHtml(parts) {
  return `<div class="seq">${parts.map((p) => `
    <div class="seq-part ${p.role}">
      <div class="seq-label">${escapeHtml(p.label)}</div>
      <div class="seq-moves">${p.moves.map((m) => `<span class="mv">${escapeHtml(m)}</span>`).join("")}</div>
    </div>`).join("")}</div>`;
}

function renderCheat() {
  const c = app.cheat;
  const el = $("cheat");
  el.innerHTML = `
    <h2>${escapeHtml(c.title)}</h2>
    <div class="cheat-intro">${c.intro.map((t) => `<p>${escapeHtml(t)}</p>`).join("")}</div>
    <p class="cheat-order">${escapeHtml(c.order)}</p>
    ${c.sections.map((sec, si) => `
      <details class="cheat-sec" ${si === 0 ? "open" : ""}>
        <summary>${si + 1}. ${escapeHtml(sec.title)}</summary>
        <p class="hint">${escapeHtml(sec.goal)} ${escapeHtml(sec.how)}</p>
        ${sec.examples.map((ex, ei) => `
          <div class="cheat-ex">
            <div class="cheat-ex-head">
              <span class="cheat-ex-title">${escapeHtml(ex.title)}</span>
              <span class="len">${ex.moves.length} coups</span>
              <button class="secondary small demo-btn" data-s="${si}" data-e="${ei}">Voir sur le puzzle</button>
            </div>
            ${partsHtml(ex.parts)}
            <div class="cheat-effect">${escapeHtml(ex.effect)} ${escapeHtml(ex.side)}</div>
          </div>`).join("")}
      </details>`).join("")}
    <h3>Cas particuliers</h3>
    ${c.tips.map((t) => `<div class="cheat-tip"><strong>${escapeHtml(t.title)}.</strong> ${escapeHtml(t.text)}</div>`).join("")}
  `;
  el.querySelectorAll(".demo-btn").forEach((b) => b.addEventListener("click", () => {
    const ex = c.sections[Number(b.dataset.s)].examples[Number(b.dataset.e)];
    demo(ex, b);
  }));
}

// Joue une séquence de l'aide-mémoire sur le puzzle résolu, dans la vue 3D.
async function demo(ex, btn) {
  if (app.busy) return;
  app.busy = true;
  const buttons = document.querySelectorAll(".demo-btn");
  buttons.forEach((b) => { b.disabled = true; });
  try {
    let colors = app.puzzle.solved.slice();
    for (const s of app.puzzle.stickers) if (s.ignored) colors[s.id] = -1;
    viewer.setColors(colors, app.puzzle.palette);
    viewer.setErrors([]);
    viewer.setHighlight(ex.highlight);
    viewer.focusOn(ex.focus);
    await new Promise((r) => setTimeout(r, 900));
    const chips = btn.closest(".cheat-ex").querySelectorAll(".mv");
    chips.forEach((x) => x.classList.remove("done", "now"));
    for (let i = 0; i < ex.moves.length; i++) {
      if (app.rtab !== "cheat") return;
      chips.forEach((x, k) => { x.classList.toggle("now", k === i); x.classList.toggle("done", k < i); });
      const mv = app.moveIndex[ex.moves[i]];
      await viewer.animate(mv.face, mv.angle, mv.members, Math.max(speedMs(), 250));
      colors = applyPerm(colors, mv.perm);
      viewer.setColors(colors, app.puzzle.palette);
    }
    chips.forEach((x) => { x.classList.remove("now"); x.classList.add("done"); });
    btn.textContent = "Rejouer";
  } finally {
    app.busy = false;
    buttons.forEach((b) => { b.disabled = false; });
  }
}

// -------------------------------------------------------------------- divers
function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function safeGet(k) { try { return localStorage.getItem(`rubik-helper:${k}`); } catch { return null; } }
function safeSet(k, v) { try { localStorage.setItem(`rubik-helper:${k}`, v); } catch { /* stockage indisponible */ } }

loadPuzzleList().catch((err) => message(`Chargement impossible : ${err.message}`, "error"));
