// Lecture des couleurs d'une face à la caméra.
// Le gabarit affiché est exactement la face du puzzle vue de l'extérieur,
// avec la face voisine indiquée en haut.

export class CameraScanner {
  constructor(video, canvas) {
    this.video = video;
    this.canvas = canvas;
    this.stream = null;
    this.refs = null;        // couleurs de référence (Lab), apprises au fil des validations
    this.samples = null;     // dernière capture : { id: lab }
    this.result = null;      // dernière capture : { id: indice de couleur }
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

  // Les couleurs de la palette sont des couleurs d'écran, bien plus saturées
  // qu'une facette vue par une webcam. Tant qu'une couleur n'a pas été vue
  // réellement (centre fixe ou facette validée), sa référence est une
  // estimation : palette désaturée, corrigée de la dominante de l'éclairage
  // dès que le blanc a été calibré.
  setPalette(palette) {
    this.palette = palette;
    this.base = palette.map((p) => rgbToLab(hexToRgb(p.hex)));
    this.refs = this.base.map(() => null);   // Lab mesuré à la caméra, ou null
    this.white = this._achromaticIndex();
  }

  // Indice de la couleur la plus claire et la moins saturée (le blanc).
  _achromaticIndex() {
    let best = 0, bs = -Infinity;
    this.base.forEach(([L, a, b], i) => {
      const s = L - 2 * Math.hypot(a, b);
      if (s > bs) { bs = s; best = i; }
    });
    return best;
  }

  _ref(i) {
    if (this.refs[i]) return this.refs[i];
    const [L, a, b] = this.base[i];
    let ref = [L, CAMERA_CHROMA * a, CAMERA_CHROMA * b];
    const w = this.refs[this.white];
    if (w) {
      // balance des blancs : même rapport de luminance et même dominante que le blanc mesuré
      const [Lw, aw, bw] = this.base[this.white];
      ref = [ref[0] * (w[0] / Lw), ref[1] + (w[1] - aw), ref[2] + (w[2] - bw)];
    }
    return ref;
  }

  // Centre fixe de la face (3x3, 5x5, Megaminx...) : sa couleur est connue d'avance.
  _fixedCenter(puzzle, faceIndex) {
    if (!puzzle.orbits) return null;
    return puzzle.stickers.find((s) => s.face === faceIndex && puzzle.orbits[s.orbit]?.fixed) || null;
  }

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

  capture(puzzle, faceIndex) {
    const w = this.canvas.width, h = this.canvas.height;
    const off = document.createElement("canvas");
    off.width = w; off.height = h;
    const octx = off.getContext("2d", { willReadFrequently: true });
    octx.drawImage(this.video, 0, 0, w, h);
    const face = puzzle.faces[faceIndex];
    const T = this._transform(face);
    const sample = (s) => {
      const pts = s.poly2d.map(T);
      const [cx, cy] = centroid(pts);
      const r = Math.max(2, 0.3 * Math.min(...pts.map(([x, y]) => Math.hypot(x - cx, y - cy))));
      const data = octx.getImageData(Math.round(cx - r), Math.round(cy - r), Math.round(2 * r), Math.round(2 * r)).data;
      // médiane par canal : robuste aux reflets
      const ch = [[], [], []];
      for (let i = 0; i < data.length; i += 4) { ch[0].push(data[i]); ch[1].push(data[i + 1]); ch[2].push(data[i + 2]); }
      return rgbToLab(ch.map((a) => a.sort((x, y) => x - y)[a.length >> 1]));
    };
    // 1. le centre fixe donne la vraie couleur de la face, sous l'éclairage actuel
    const center = this._fixedCenter(puzzle, faceIndex);
    if (center) this.refs[puzzle.solved[center.id]] = sample(center);
    // 2. classement des facettes avec les références à jour
    const colors = {};
    this.samples = {};
    for (const s of puzzle.stickers) {
      if (s.face !== faceIndex || s.ignored) continue;
      const lab = sample(s);
      this.samples[s.id] = lab;
      colors[s.id] = s === center ? puzzle.solved[s.id] : this.classify(lab);
    }
    this.result = { face: faceIndex, colors };
    return colors;
  }

  classify(lab) {
    let best = 0, bd = Infinity;
    for (let i = 0; i < this.base.length; i++) {
      const d = labDistance(lab, this._ref(i));
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }

  // Apprentissage : la couleur validée par l'utilisateur devient (ou affine) la référence.
  learn(finalColors) {
    if (!this.samples) return;
    for (const [id, lab] of Object.entries(this.samples)) {
      const c = finalColors[id];
      if (c === undefined || c < 0) continue;
      const ref = this.refs[c];
      this.refs[c] = ref ? ref.map((v, k) => 0.5 * v + 0.5 * lab[k]) : lab.slice();
    }
  }
}

// Saturation typique d'une facette vue par une webcam, rapportée à la palette d'écran.
const CAMERA_CHROMA = 0.55;

// Distance de couleur : la luminance compte peu (exposition variable, reflets),
// la teinte et la saturation comptent pleinement. Comparer en a/b sépare le
// blanc (a, b proches de 0) d'un bleu pâle (b nettement négatif) même quand
// leurs luminances se rapprochent.
export function labDistance(p, q) {
  return 0.2 * (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2;
}

function centroid(pts) {
  const n = pts.length;
  return pts.reduce((a, [x, y]) => [a[0] + x / n, a[1] + y / n], [0, 0]);
}

function hexToRgb(hex) {
  const v = parseInt(hex.slice(1), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

function rgbToLab([r, g, b]) {
  const lin = (c) => { c /= 255; return c > 0.04045 ? ((c + 0.055) / 1.055) ** 2.4 : c / 12.92; };
  const R = lin(r), G = lin(g), B = lin(b);
  let x = (R * 0.4124 + G * 0.3576 + B * 0.1805) / 0.95047;
  let y = R * 0.2126 + G * 0.7152 + B * 0.0722;
  let z = (R * 0.0193 + G * 0.1192 + B * 0.9505) / 1.08883;
  const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  x = f(x); y = f(y); z = f(z);
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)];
}
