// Patron 2D cliquable (SVG), construit à partir des coordonnées dépliées.
const SVG = "http://www.w3.org/2000/svg";

const LONG_PRESS_MS = 450;  // appui long : remplit la face, comme Maj + clic
const MOVE_SLOP = 8;        // déplacement toléré avant de parler de glissement

export class Net {
  constructor(container, onPick) {
    this.container = container;
    this.onPick = onPick;
    this._press = { timer: null, at: null, handled: false };
  }

  // Appui long sur une facette : équivalent tactile de Maj + clic (remplir la face).
  _bindLongPress(poly, sticker) {
    const press = this._press;
    const cancel = () => { clearTimeout(press.timer); press.timer = null; };
    poly.addEventListener("pointerdown", (e) => {
      press.at = [e.clientX, e.clientY];
      press.handled = false;
      cancel();
      press.timer = setTimeout(() => {
        press.timer = null;
        press.handled = true;
        navigator.vibrate?.(12);
        this.onPick(sticker.id, { shiftKey: true });
      }, LONG_PRESS_MS);
    });
    poly.addEventListener("pointermove", (e) => {
      if (press.at && Math.hypot(e.clientX - press.at[0], e.clientY - press.at[1]) > MOVE_SLOP) cancel();
    });
    for (const ev of ["pointerup", "pointercancel", "pointerleave"]) {
      poly.addEventListener(ev, cancel);
    }
  }

  load(puzzle) {
    this.puzzle = puzzle;
    this.container.innerHTML = "";
    const svg = document.createElementNS(SVG, "svg");
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const s of puzzle.stickers) {
      for (const [x, y] of s.net) {
        minX = Math.min(minX, x); maxX = Math.max(maxX, x);
        minY = Math.min(minY, -y); maxY = Math.max(maxY, -y);
      }
    }
    const m = 0.15;
    svg.setAttribute("viewBox", `${minX - m} ${minY - m} ${maxX - minX + 2 * m} ${maxY - minY + 2 * m}`);
    this.polys = [];
    const faceCenters = puzzle.faces.map(() => [0, 0, 0]);
    for (const s of puzzle.stickers) {
      const p = document.createElementNS(SVG, "polygon");
      p.setAttribute("points", s.net.map(([x, y]) => `${x},${-y}`).join(" "));
      if (s.ignored) p.classList.add("ignored");
      if (!s.ignored) {
        p.addEventListener("click", (e) => { if (!this._press.handled) this.onPick(s.id, e); });
        this._bindLongPress(p, s);
      }
      svg.appendChild(p);
      this.polys.push(p);
      const c = s.net.reduce((a, [x, y]) => [a[0] + x / s.net.length, a[1] + y / s.net.length], [0, 0]);
      const fc = faceCenters[s.face];
      fc[0] += c[0]; fc[1] += c[1]; fc[2] += 1;
    }
    // nom des faces
    puzzle.faces.forEach((f, i) => {
      const fc = faceCenters[i];
      const t = document.createElementNS(SVG, "text");
      t.setAttribute("x", fc[0] / fc[2]);
      t.setAttribute("y", -fc[1] / fc[2] + 0.11);
      t.setAttribute("text-anchor", "middle");
      t.textContent = f.name;
      t.style.fill = "rgba(0,0,0,.55)";
      svg.appendChild(t);
    });
    svg.style.touchAction = "manipulation";
    svg.addEventListener("contextmenu", (e) => e.preventDefault());
    this.container.appendChild(svg);
  }

  setColors(colors, palette) {
    for (const s of this.puzzle.stickers) {
      const c = colors[s.id];
      let fill = "#5b6170";
      if (s.ignored) fill = "#26282c";
      else if (c >= 0) fill = palette[c].hex;
      this.polys[s.id].setAttribute("fill", fill);
    }
  }

  setHighlight(ids) {
    for (const p of this.polys) p.classList.remove("hl");
    for (const id of ids || []) this.polys[id]?.classList.add("hl");
  }

  setErrors(ids) {
    for (const p of this.polys) p.classList.remove("err");
    for (const id of ids || []) this.polys[id]?.classList.add("err");
  }
}
