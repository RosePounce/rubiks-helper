"""Compléments : solution courte 3x3 (Kociemba), patron 2D, mélanges, palettes."""

from __future__ import annotations

import random

import numpy as np

from .geometry import face_frame, face_polygon
from .puzzle import Puzzle

# ---------------------------------------------------------------------------
# Palettes : la couleur d'indice i est celle de la face i dans l'état résolu
# par défaut.
# ---------------------------------------------------------------------------

CUBE_PALETTE = [  # ordre des faces : U F R D B L
    {"name": "Blanc", "hex": "#f5f5f5"},
    {"name": "Vert", "hex": "#16a34a"},
    {"name": "Rouge", "hex": "#dc2626"},
    {"name": "Jaune", "hex": "#facc15"},
    {"name": "Bleu", "hex": "#1d4ed8"},
    {"name": "Orange", "hex": "#f97316"},
]

MINX_PALETTE = [  # ordre des faces : U F R BR BL L B DBL DL DR DBR D
    {"name": "Blanc", "hex": "#f5f5f5"},
    {"name": "Vert foncé", "hex": "#15803d"},
    {"name": "Rouge", "hex": "#dc2626"},
    {"name": "Bleu foncé", "hex": "#1e3a8a"},
    {"name": "Jaune", "hex": "#facc15"},
    {"name": "Violet", "hex": "#7e22ce"},
    {"name": "Vert clair", "hex": "#86efac"},
    {"name": "Orange", "hex": "#f97316"},
    {"name": "Bleu clair", "hex": "#7dd3fc"},
    {"name": "Crème", "hex": "#fef3c7"},
    {"name": "Rose", "hex": "#f472b6"},
    {"name": "Gris", "hex": "#9ca3af"},
]


TETRA_PALETTE = [  # ordre des faces : U F L R
    {"name": "Rouge", "hex": "#dc2626"},
    {"name": "Vert", "hex": "#16a34a"},
    {"name": "Bleu", "hex": "#1d4ed8"},
    {"name": "Jaune", "hex": "#facc15"},
]


def palette(pz: Puzzle) -> list[dict]:
    if pz.geo.kind == "cube":
        return CUBE_PALETTE
    if pz.geo.kind == "tetra":
        return TETRA_PALETTE
    return MINX_PALETTE


# ---------------------------------------------------------------------------
# Patron 2D
# ---------------------------------------------------------------------------

_NET_TREES = {
    "tetra": ("B", [("B", "U"), ("B", "L"), ("B", "R")]),
    "cube": ("F", [("F", "U"), ("F", "D"), ("F", "L"), ("F", "R"), ("R", "B")]),
    "dodeca": ("U", [("U", "F"), ("U", "R"), ("U", "BR"), ("U", "BL"), ("U", "L"),
                     ("F", "DL"), ("DL", "D"), ("D", "DR"), ("D", "DBR"), ("D", "B"), ("D", "DBL")]),
}


def net_layout(pz: Puzzle) -> dict[int, list[list[float]]]:
    """Coordonnées 2D dépliées de chaque facette (repère : x à droite, y en haut)."""
    geo = pz.geo
    names = geo.face_names
    root, edges = _NET_TREES[geo.kind]
    # transformation de chaque face : point 2D local -> point du patron (R, t)
    T: dict[int, tuple[np.ndarray, np.ndarray]] = {names.index(root): (np.eye(2), np.zeros(2))}

    def local(f, v):
        c, r, u = face_frame(geo, f)
        return np.array([float((v - c) @ r), float((v - c) @ u)])

    for pn, cn in edges:
        p, c = names.index(pn), names.index(cn)
        vp = face_polygon(geo.normals, p)
        vc = face_polygon(geo.normals, c)
        shared = [v for v in vp if any(np.linalg.norm(v - w) < 1e-6 for w in vc)]
        a3, b3 = shared[0], shared[1]
        Rp, tp = T[p]
        A, B = Rp @ local(p, a3) + tp, Rp @ local(p, b3) + tp
        a, b = local(c, a3), local(c, b3)
        ang = np.arctan2(*(B - A)[::-1]) - np.arctan2(*(b - a)[::-1])
        R = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
        t = A - R @ a
        T[c] = (R, t)
    out = {}
    for s in geo.stickers:
        R, t = T[s.face]
        out[s.id] = [[round(float(x), 4) for x in (R @ local(s.face, v) + t)] for v in s.poly]
    return out


# ---------------------------------------------------------------------------
# Mélanges
# ---------------------------------------------------------------------------

def random_scramble(pz: Puzzle, rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    if pz.id == "megaminx":
        # notation WCA (Pochmann) : 7 lignes de 10 R/D puis U ou U'
        lines = []
        for _ in range(7):
            toks = []
            for i in range(10):
                toks.append(("R" if i % 2 == 0 else "D") + rng.choice(["++", "--"]))
            toks.append(rng.choice(["U", "U'"]))
            lines.append(" ".join(toks))
        return "\n".join(lines)
    n_moves = {3: 25, 4: 45, 5: 60, 6: 80, 7: 100}.get(pz.size, 60)
    if pz.family == "minx":
        n_moves = 70 if pz.size == 3 else 140
    cands = [i for i in pz.frame_moves]
    seq: list[int] = []
    while len(seq) < n_moves:
        mi = rng.choice(cands)
        if seq and pz.moves[seq[-1]].axis == pz.moves[mi].axis:
            continue
        seq.append(mi)
    return " ".join(pz.names(seq))


# ---------------------------------------------------------------------------
# Kociemba (3x3 uniquement)
# ---------------------------------------------------------------------------

def kociemba_solution(pz: Puzzle, colors: list[int], face_color: list[int]) -> list[str] | None:
    """Solution courte (environ 20 coups) par l'algorithme à deux phases de Kociemba."""
    if pz.id != "3x3":
        return None
    try:
        import kociemba
    except ImportError:
        return None
    geo = pz.geo
    letter_of_color = {face_color[f]: geo.face_names[f] for f in range(6)}
    parts = []
    for fn in "URFDLB":
        f = geo.face_names.index(fn)
        c, r, u = face_frame(geo, f)
        sts = [s for s in geo.stickers if s.face == f]
        sts.sort(key=lambda s: (-round(float((s.center - c) @ u), 3), round(float((s.center - c) @ r), 3)))
        parts.append("".join(letter_of_color[colors[s.id]] for s in sts))
    try:
        sol = kociemba.solve("".join(parts))
    except (ValueError, Exception):
        return None
    moves = sol.split()
    # vérification indépendante
    cur = np.asarray(colors)
    for tok in pz.parse(" ".join(moves)):
        perm = tok["perm"]
        out = np.empty_like(cur)
        out[perm] = cur
        cur = out
    expected = np.array([face_color[f] for f in pz.sticker_face])
    if not np.array_equal(cur, expected):
        return None
    return moves
