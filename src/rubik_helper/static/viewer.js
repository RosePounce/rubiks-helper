// Vue 3D générique : facettes polygonales, animation des tranches, sélection.
import * as THREE from "three";
import { OrbitControls } from "/static/vendor/OrbitControls.js";

const UNKNOWN = 0x5b6170;
const IGNORED = 0x26282c;

export class Viewer {
  constructor(container, onPick) {
    this.container = container;
    this.onPick = onPick;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    container.appendChild(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enablePan = false;
    this.controls.enableDamping = true;
    this.scene.add(new THREE.AmbientLight(0xffffff, 1.6));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(3, 5, 6);
    this.camera.add(key);
    this.scene.add(this.camera);
    this.root = new THREE.Group();
    this.scene.add(this.root);
    this.pivot = new THREE.Group();
    this.scene.add(this.pivot);
    this.meshes = [];
    this.highlighted = new Set();
    this.errors = new Set();
    this.raycaster = new THREE.Raycaster();
    this._bindPicking();
    new ResizeObserver(() => this._resize()).observe(container);
    this._resize();
    this.resetView();
    const loop = (t) => {
      this.controls.update();
      this._pulse(t);
      this.renderer.render(this.scene, this.camera);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  resetView() {
    this.camera.position.set(2.6, 3.0, 5.6);
    this.camera.lookAt(0, 0, 0);
    this.controls.target.set(0, 0, 0);
    this.controls.update();
  }

  // Oriente la caméra vers une direction (pièce à montrer), à distance constante.
  focusOn(dir) {
    if (!dir) return;
    const d = new THREE.Vector3(...dir).normalize();
    const dist = this.camera.position.length();
    const from = this.camera.position.clone().normalize();
    const t0 = performance.now();
    const step = (now) => {
      const x = Math.min(1, (now - t0) / 450);
      const e = x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2;
      const v = from.clone().lerp(d, e);
      if (v.lengthSq() < 1e-6) v.set(0, 1, 0);
      this.camera.position.copy(v.normalize().multiplyScalar(dist));
      this.camera.lookAt(0, 0, 0);
      if (x < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  _resize() {
    const w = this.container.clientWidth || 400;
    const h = this.container.clientHeight || 400;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  load(puzzle) {
    this.puzzle = puzzle;
    this.root.clear();
    this.meshes = [];
    // corps noir
    const coreMat = new THREE.MeshLambertMaterial({ color: 0x0d0d0f });
    for (const f of puzzle.faces) {
      const n = new THREE.Vector3(...f.normal);
      const r = new THREE.Vector3(...f.right);
      const u = new THREE.Vector3(...f.up);
      const pts = f.outline.map(([x, y]) => n.clone().multiplyScalar(0.999).addScaledVector(r, x).addScaledVector(u, y));
      this.root.add(new THREE.Mesh(fanGeometry(pts), coreMat));
    }
    const shrink = puzzle.kind === "cube" ? 0.86 : 0.84;
    for (const s of puzzle.stickers) {
      const verts = s.poly.map((p) => new THREE.Vector3(...p));
      const c = verts.reduce((a, v) => a.add(v), new THREE.Vector3()).multiplyScalar(1 / verts.length);
      const n = new THREE.Vector3(...puzzle.faces[s.face].normal);
      const pts = verts.map((v) => c.clone().add(v.clone().sub(c).multiplyScalar(shrink)).addScaledVector(n, 0.004));
      const mat = new THREE.MeshLambertMaterial({ color: UNKNOWN, side: THREE.DoubleSide });
      const mesh = new THREE.Mesh(fanGeometry(pts), mat);
      mesh.userData.id = s.id;
      this.root.add(mesh);
      this.meshes.push(mesh);
    }
    const scale = puzzle.kind === "cube" ? 1 : 0.85;
    this.root.scale.setScalar(scale);
    this.pivot.scale.setScalar(scale);
    this.highlighted.clear();
    this.errors.clear();
  }

  setColors(colors, palette) {
    this.colors = colors;
    this.palette = palette;
    for (const m of this.meshes) {
      const s = this.puzzle.stickers[m.userData.id];
      const c = colors[s.id];
      let hex;
      if (s.ignored) hex = IGNORED;
      else if (c < 0) hex = UNKNOWN;
      else hex = parseInt(palette[c].hex.slice(1), 16);
      m.material.color.setHex(hex);
    }
  }

  setHighlight(ids) {
    this.highlighted = new Set(ids || []);
    this._resetEmissive();
  }

  setErrors(ids) {
    this.errors = new Set(ids || []);
    this._resetEmissive();
  }

  _resetEmissive() {
    for (const m of this.meshes) m.material.emissive.setHex(0x000000);
  }

  _pulse(t) {
    const k = 0.5 + 0.5 * Math.sin(t / 180);
    for (const id of this.highlighted) {
      const m = this.meshes[id];
      // éclaircit la couleur sans la changer (une teinte ajoutée fausserait la lecture)
      if (m) m.material.emissive.copy(m.material.color).multiplyScalar(0.15 + 0.55 * k);
    }
    for (const id of this.errors) {
      const m = this.meshes[id];
      if (m) m.material.emissive.setRGB(0.7 * k, 0.05, 0.05);
    }
  }

  // Anime une rotation de tranche ; renvoie une promesse résolue à la fin.
  animate(face, angle, members, duration) {
    if (duration <= 0) return Promise.resolve();
    const axis = new THREE.Vector3(...this.puzzle.faces[face].normal).normalize();
    const moving = members.map((i) => this.meshes[i]);
    for (const m of moving) this.pivot.add(m);
    this.pivot.quaternion.identity();
    return new Promise((resolve) => {
      const t0 = performance.now();
      const step = (now) => {
        const x = Math.min(1, (now - t0) / duration);
        const e = x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2;
        this.pivot.quaternion.setFromAxisAngle(axis, angle * e);
        if (x < 1) {
          requestAnimationFrame(step);
        } else {
          for (const m of moving) this.root.add(m);
          this.pivot.quaternion.identity();
          resolve();
        }
      };
      requestAnimationFrame(step);
    });
  }

  _bindPicking() {
    const el = this.renderer.domElement;
    let down = null;
    el.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
    el.addEventListener("pointerup", (e) => {
      if (!down) return;
      const moved = Math.hypot(e.clientX - down[0], e.clientY - down[1]);
      down = null;
      if (moved > 5 || !this.onPick) return;
      const rect = el.getBoundingClientRect();
      const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1);
      this.raycaster.setFromCamera(ndc, this.camera);
      const hit = this.raycaster.intersectObjects(this.meshes, false)[0];
      if (hit) this.onPick(hit.object.userData.id, e);
    });
  }
}

function fanGeometry(pts) {
  const g = new THREE.BufferGeometry();
  const pos = [];
  for (let i = 1; i < pts.length - 1; i++) {
    for (const p of [pts[0], pts[i], pts[i + 1]]) pos.push(p.x, p.y, p.z);
  }
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.computeVertexNormals();
  return g;
}
