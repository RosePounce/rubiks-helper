// Reconnaissance des couleurs lues à la caméra : modèle de couleurs et
// affectation globale. Aucune dépendance au navigateur (testable sous Node).

// Saturation typique d'une facette vue par une webcam, rapportée à la palette d'écran.
export const CAMERA_CHROMA = 0.55;

// Poids de la luminance dans la distance. Faible face à une couleur estimée
// (l'exposition de la caméra est inconnue), plus fort face à une couleur
// mesurée sous le même éclairage : c'est elle qui sépare vert clair et vert
// foncé, bleu clair et bleu foncé, blanc, crème et gris sur le Megaminx.
export const LUM_WEIGHT_ESTIMATED = 0.2;
export const LUM_WEIGHT_MEASURED = 0.6;

export function labDistance(p, q, lw = LUM_WEIGHT_MEASURED) {
  return lw * (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2;
}

export function hexToRgb(hex) {
  const v = parseInt(hex.slice(1), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

export function rgbToLab([r, g, b]) {
  const lin = (c) => { c /= 255; return c > 0.04045 ? ((c + 0.055) / 1.055) ** 2.4 : c / 12.92; };
  const R = lin(r), G = lin(g), B = lin(b);
  let x = (R * 0.4124 + G * 0.3576 + B * 0.1805) / 0.95047;
  let y = R * 0.2126 + G * 0.7152 + B * 0.0722;
  let z = (R * 0.0193 + G * 0.1192 + B * 0.9505) / 1.08883;
  const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  x = f(x); y = f(y); z = f(z);
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)];
}

// Références de couleur : mesurées à la caméra quand c'est possible, sinon
// estimées à partir de la palette d'écran.
export class ColorModel {
  constructor(palette) {
    this.base = palette.map((p) => rgbToLab(hexToRgb(p.hex)));
    this.refs = this.base.map(() => null);   // Lab mesuré, ou null
    this.white = achromaticIndex(this.base);
  }

  get size() { return this.base.length; }

  measured(i) { return !!this.refs[i]; }

  clone() {
    const m = Object.create(ColorModel.prototype);
    m.base = this.base;
    m.white = this.white;
    m.refs = this.refs.map((r) => (r ? r.slice() : null));
    return m;
  }

  // Étalonnage enregistrable (références mesurées, null si non mesurée).
  dump() { return this.refs.map((r) => (r ? r.map((v) => Math.round(v * 10) / 10) : null)); }

  load(refs) {
    if (!Array.isArray(refs) || refs.length !== this.size) return;
    this.refs = refs.map((r) => (Array.isArray(r) && r.length === 3 ? r.slice() : null));
  }

  reset() { this.refs = this.base.map(() => null); }

  // Couleur estimée : palette désaturée, puis balance des blancs si le blanc a été mesuré.
  ref(i) {
    if (this.refs[i]) return this.refs[i];
    const [L, a, b] = this.base[i];
    let r = [L, CAMERA_CHROMA * a, CAMERA_CHROMA * b];
    const w = this.refs[this.white];
    if (w) {
      const [Lw, aw, bw] = this.base[this.white];
      r = [r[0] * (w[0] / Lw), r[1] + (w[1] - aw), r[2] + (w[2] - bw)];
    }
    return r;
  }

  distance(lab, i) {
    return labDistance(lab, this.ref(i), this.refs[i] ? LUM_WEIGHT_MEASURED : LUM_WEIGHT_ESTIMATED);
  }

  classify(lab) {
    let best = 0, bd = Infinity;
    for (let i = 0; i < this.size; i++) {
      const d = this.distance(lab, i);
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }

  // Mesure directe (centre fixe) : remplace la référence.
  calibrate(i, lab) { this.refs[i] = lab.slice(); }
}

// Indice de la couleur la plus claire et la moins saturée (le blanc).
function achromaticIndex(labs) {
  let best = 0, bs = -Infinity;
  labs.forEach(([L, a, b], i) => {
    const s = L - 2 * Math.hypot(a, b);
    if (s > bs) { bs = s; best = i; }
  });
  return best;
}

// Affectation sous contrainte d'effectifs : chaque couleur c reçoit au plus
// capacity[c] éléments (exactement si la somme des capacités vaut le nombre
// d'éléments), en minimisant la distance totale. Glouton par coût croissant,
// puis échanges deux à deux et déplacements vers une couleur non pleine tant
// qu'ils font baisser le coût total.
export function balancedAssign(cost, capacity) {
  const n = cost.length, k = capacity.length;
  const left = capacity.slice();
  const out = new Array(n).fill(-1);
  const pairs = [];
  for (let i = 0; i < n; i++) for (let c = 0; c < k; c++) pairs.push([cost[i][c], i, c]);
  pairs.sort((x, y) => x[0] - y[0]);
  for (const [, i, c] of pairs) {
    if (out[i] < 0 && left[c] > 0) { out[i] = c; left[c]--; }
  }
  // capacités insuffisantes (ne devrait pas arriver) : plus proche couleur
  for (let i = 0; i < n; i++) {
    if (out[i] < 0) out[i] = cost[i].indexOf(Math.min(...cost[i]));
  }
  for (let pass = 0; pass < 100; pass++) {
    let improved = false;
    for (let i = 0; i < n; i++) {
      for (let c = 0; c < k; c++) {
        if (left[c] > 0 && c !== out[i] && cost[i][c] < cost[i][out[i]] - 1e-9) {
          left[out[i]]++; left[c]--; out[i] = c; improved = true;
        }
      }
      for (let j = i + 1; j < n; j++) {
        const p = out[i], q = out[j];
        if (p === q) continue;
        if (cost[i][q] + cost[j][p] < cost[i][p] + cost[j][q] - 1e-9) {
          out[i] = q; out[j] = p; improved = true;
        }
      }
    }
    if (!improved) break;
  }
  return out;
}

export function meanLab(labs) {
  const m = [0, 0, 0];
  for (const l of labs) for (let k = 0; k < 3; k++) m[k] += l[k] / labs.length;
  return m;
}

// Lab -> couleur CSS (pour afficher une couleur mesurée).
export function labToHex([L, a, b]) {
  const fy = (L + 16) / 116, fx = fy + a / 500, fz = fy - b / 200;
  const inv = (t) => (t ** 3 > 0.008856 ? t ** 3 : (t - 16 / 116) / 7.787);
  const x = 0.95047 * inv(fx), y = inv(fy), z = 1.08883 * inv(fz);
  const lin = [
    3.2406 * x - 1.5372 * y - 0.4986 * z,
    -0.9689 * x + 1.8758 * y + 0.0415 * z,
    0.0557 * x - 0.2040 * y + 1.0570 * z,
  ];
  const g = (v) => Math.round(255 * Math.min(1, Math.max(0, v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055)));
  return "#" + lin.map((v) => g(v).toString(16).padStart(2, "0")).join("");
}
