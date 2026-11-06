// Lecture des couleurs d'une face à la caméra.
// Le gabarit affiché est exactement la face du puzzle vue de l'extérieur,
// avec la face voisine indiquée en haut.
//
// Les teintes varient d'un fabricant à l'autre : la pipette (`pick`) mesure
// chaque couleur directement sur le puzzle. Chaque capture est conservée ; une
// fois toutes les faces capturées, la relecture globale (`reclassifyAll`)
// reclasse l'ensemble sous contrainte d'effectifs (chaque couleur apparaît
// autant de fois qu'il y a de facettes par face).

import { ColorModel, balancedAssign, meanLab, rgbToLab } from "./colormatch.js";

export class CameraScanner {
  constructor(video, canvas) {
    this.video = video;
    this.canvas = canvas;
    this.stream = null;
    this.model = null;
    this.faces = {};         // face capturée -> { id: lab }
    this.proposed = {};      // id -> couleur proposée par la dernière lecture
    this.pinned = {};        // id -> couleur corrigée à la main par l'utilisateur
    this.samples = null;     // dernière capture : { id: lab }
    this.result = null;      // dernière capture : { face, colors }
  }

  async start() {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Caméra indisponible : le navigateur exige une page sécurisée (https ou localhost).");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 960 } },
      audio: false,
    });
    this.video.srcObject = this.stream;
    await this.video.play();
    await new Promise((r) => (this.video.videoWidth ? r() : this.video.addEventListener("loadedmetadata", r, { once: true })));
    this.canvas.width = this.video.videoWidth;
    this.canvas.height = this.video.videoHeight;
  }

  stop() {
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = null;
  }

  get active() { return !!this.stream; }

  setPalette(palette) {
    this.palette = palette;
    this.model = new ColorModel(palette);
    this.faces = {};
    this.proposed = {};
    this.pinned = {};
    this.samples = null;
    this.result = null;
  }

  capturedFaces() { return Object.keys(this.faces).length; }

  _transform(face) {
    const w = this.canvas.width, h = this.canvas.height;
    const R = Math.max(...face.outline.map(([x, y]) => Math.hypot(x, y)));
    const scale = (0.42 * Math.min(w, h)) / R;
    return ([x, y]) => [w / 2 + x * scale, h / 2 - y * scale];
  }

  drawOverlay(puzzle, faceIndex) {
    const ctx = this.canvas.getContext("2d");
    const { width: w, height: h } = this.canvas;
    ctx.clearRect(0, 0, w, h);
    if (!w) return;
    const face = puzzle.faces[faceIndex];
    const T = this._transform(face);
    const stickers = puzzle.stickers.filter((s) => s.face === faceIndex);
    ctx.lineJoin = "round";
    for (const s of stickers) {
      const pts = s.poly2d.map(T);
      ctx.beginPath();
      pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.closePath();
      if (this.result && this.result.face === faceIndex) {
        const c = this.result.colors[s.id];
        if (c !== undefined) {
          ctx.fillStyle = this.palette[c].hex + "cc";
          ctx.fill();
        }
      }
      ctx.lineWidth = Math.max(2, w / 300);
      ctx.strokeStyle = s.ignored ? "rgba(255,255,255,.25)" : "rgba(255,255,255,.9)";
      ctx.stroke();
      if (!s.ignored) {
        const [cx, cy] = centroid(pts);
        ctx.beginPath();
        ctx.arc(cx, cy, Math.max(3, w / 220), 0, Math.PI * 2);
        ctx.fillStyle = "rgba(255,255,255,.9)";
        ctx.fill();
      }
    }
    // repère du haut
    ctx.font = `${Math.round(h / 22)}px system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.fillStyle = "rgba(0,0,0,.6)";
    const tw = ctx.measureText(face.top_label).width + h / 15;
    ctx.fillRect(w / 2 - tw / 2, h * 0.015, tw, h / 15);
    ctx.fillStyle = "#fff";
    ctx.fillText(face.top_label, w / 2, h * 0.065);
  }

  // Image courante de la caméra, dans un canevas lisible.
  _frame() {
    const w = this.canvas.width, h = this.canvas.height;
    const off = document.createElement("canvas");
    off.width = w; off.height = h;
    const ctx = off.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(this.video, 0, 0, w, h);
    return ctx;
  }

  // Couleur Lab médiane d'un carré de côté 2r centré en (cx, cy) : robuste aux reflets.
  _sample(ctx, cx, cy, r) {
    const data = ctx.getImageData(Math.round(cx - r), Math.round(cy - r), Math.round(2 * r), Math.round(2 * r)).data;
    const ch = [[], [], []];
    for (let i = 0; i < data.length; i += 4) { ch[0].push(data[i]); ch[1].push(data[i + 1]); ch[2].push(data[i + 2]); }
    return rgbToLab(ch.map((a) => a.sort((x, y) => x - y)[a.length >> 1]));
  }

  // Lit l'image de la caméra : une couleur par facette de la face.
  capture(puzzle, faceIndex) {
    const ctx = this._frame();
    const T = this._transform(puzzle.faces[faceIndex]);
    const samples = {};
    for (const s of puzzle.stickers) {
      if (s.face !== faceIndex || s.ignored) continue;
      const pts = s.poly2d.map(T);
      const [cx, cy] = centroid(pts);
      const r = Math.max(2, 0.3 * Math.min(...pts.map(([x, y]) => Math.hypot(x - cx, y - cy))));
      samples[s.id] = this._sample(ctx, cx, cy, r);
    }
    return this.ingest(faceIndex, samples);
  }

  // Pipette : la couleur sous le doigt (ou la souris) devient la référence de la couleur `c`.
  // Renvoie la couleur mesurée en RGB pour l'affichage, ou null hors de l'image.
  pick(clientX, clientY, c) {
    const rect = this.canvas.getBoundingClientRect();
    const w = this.canvas.width, h = this.canvas.height;
    const scale = Math.min(rect.width / w, rect.height / h);   // object-fit: contain
    const x = (clientX - rect.left - (rect.width - w * scale) / 2) / scale;
    const y = (clientY - rect.top - (rect.height - h * scale) / 2) / scale;
    if (x < 0 || y < 0 || x >= w || y >= h) return null;
    const lab = this._sample(this._frame(), x, y, Math.max(3, Math.min(w, h) / 80));
    this.model.calibrate(c, lab);
    return lab;
  }

  // Classe les facettes lues d'une face (séparé de `capture` pour pouvoir être testé).
  ingest(faceIndex, samples) {
    for (const id of Object.keys(samples)) delete this.pinned[id];   // nouvelle lecture
    this.faces[faceIndex] = samples;
    this.samples = samples;
    const colors = {};
    for (const [id, lab] of Object.entries(samples)) {
      colors[id] = this.model.classify(lab);
      this.proposed[id] = colors[id];
    }
    this.result = { face: faceIndex, colors };
    return colors;
  }

  // Validation d'une face : les couleurs corrigées à la main sont conservées
  // telles quelles par la relecture globale.
  learn(finalColors) {
    if (!this.samples) return;
    for (const id of Object.keys(this.samples)) {
      const c = finalColors[id];
      if (c === undefined || c < 0) continue;
      if (this.proposed[id] !== undefined && c !== this.proposed[id]) this.pinned[id] = c;
    }
  }

  // Relecture de toutes les faces capturées. Quand toutes le sont, chaque couleur
  // reçoit exactement le nombre de facettes attendu, et les références sont
  // recentrées sur les facettes qui leur sont attribuées (quelques itérations) :
  // elles s'adaptent ainsi aux teintes réelles du puzzle.
  reclassifyAll(puzzle) {
    const known = {}, free = [], labs = {};
    for (const samples of Object.values(this.faces)) {
      for (const [id, lab] of Object.entries(samples)) {
        labs[id] = lab;
        if (this.pinned[id] !== undefined) known[id] = this.pinned[id];
        else free.push(id);
      }
    }
    const k = this.model.size;
    const model = this.model.clone();
    const costs = () => free.map((id) => Array.from({ length: k }, (_, c) => model.distance(labs[id], c)));
    let assign;
    if (this.capturedFaces() === puzzle.faces.length) {
      const capacity = new Array(k).fill(0);
      for (const s of puzzle.stickers) if (!s.ignored) capacity[puzzle.solved[s.id]]++;
      for (const c of Object.values(known)) capacity[c]--;
      if (capacity.every((x) => x >= 0)) {
        for (let it = 0; it < 5; it++) {
          const next = balancedAssign(costs(), capacity);
          if (assign && next.every((c, i) => c === assign[i])) break;
          assign = next;
          const groups = Array.from({ length: k }, () => []);
          free.forEach((id, i) => groups[assign[i]].push(labs[id]));
          for (const [id, c] of Object.entries(known)) groups[c].push(labs[id]);
          groups.forEach((g, c) => { if (g.length) model.calibrate(c, meanLab(g)); });
        }
      }
    }
    if (!assign) assign = costs().map((row) => row.indexOf(Math.min(...row)));
    const colors = { ...known };
    free.forEach((id, i) => { colors[id] = assign[i]; this.proposed[id] = assign[i]; });
    this.result = null;
    return colors;
  }
}

function centroid(pts) {
  const n = pts.length;
  return pts.reduce((a, [x, y]) => [a[0] + x / n, a[1] + y / n], [0, 0]);
}
