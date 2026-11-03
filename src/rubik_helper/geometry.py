"""Géométrie générique des puzzles à rotation de faces.

Un puzzle est décrit par un polyèdre (cube ou dodécaèdre, rayon inscrit 1)
et, pour chaque face, une liste de profondeurs de coupe : un plan de coupe
est l'ensemble des points x tels que dot(x, n_face) = profondeur.

À partir de là on calcule :
  - les facettes (stickers) : chaque face est découpée par les plans de coupe
    des autres faces ;
  - les pièces : facettes appartenant à la même cellule du solide découpé ;
  - les mouvements : rotation d'une tranche (région entre deux plans
    parallèles) autour de la normale de la face.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

EPS = 1e-7
PHI = (1 + 5**0.5) / 2


# ---------------------------------------------------------------------------
# Polyèdres
# ---------------------------------------------------------------------------

def _rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Matrice de rotation qui envoie le vecteur unitaire a sur b."""
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-12:
        if c > 0:
            return np.eye(3)
        # rotation de 180° autour d'un axe perpendiculaire
        axis = np.cross(a, [1, 0, 0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0, 1, 0])
        axis /= np.linalg.norm(axis)
        return axis_angle_matrix(axis, math.pi)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1 / (1 + c))


def axis_angle_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    c, s = math.cos(angle), math.sin(angle)
    C = 1 - c
    return np.array([
        [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
    ])


def cube_normals() -> tuple[list[str], np.ndarray]:
    # Repère Three.js : y vers le haut, z vers l'observateur.
    names = ["U", "F", "R", "D", "B", "L"]
    normals = np.array([
        [0, 1, 0], [0, 0, 1], [1, 0, 0],
        [0, -1, 0], [0, 0, -1], [-1, 0, 0],
    ], dtype=float)
    return names, normals


def dodecahedron_normals() -> tuple[list[str], np.ndarray]:
    """Normales des 12 faces, orientées : U en haut, F devant.

    Noms usuels du Megaminx. Paires opposées : U/D, F/B, R/DBL, L/DBR,
    BR/DL, BL/DR.
    """
    raw = []
    for s1 in (-1, 1):
        for s2 in (-1, 1):
            raw.append((0, s1 * 1, s2 * PHI))
            raw.append((s1 * 1, s2 * PHI, 0))
            raw.append((s2 * PHI, 0, s1 * 1))
    raw = np.array(raw, dtype=float)
    raw /= np.linalg.norm(raw, axis=1, keepdims=True)
    # U = raw[0] envoyé sur +y
    up = raw[0]
    R1 = _rotation_between(up, np.array([0.0, 1.0, 0.0]))
    pts = raw @ R1.T
    # voisin de U le plus proche de +z (devant) -> F exactement devant
    neigh = [i for i in range(12) if 0.3 < pts[i] @ np.array([0, 1, 0]) < 0.6]
    f = max(neigh, key=lambda i: pts[i][2])
    ang = math.atan2(pts[f][0], pts[f][2])
    R2 = axis_angle_matrix(np.array([0, 1, 0]), -ang)
    pts = pts @ R2.T
    pts[np.abs(pts) < 1e-12] = 0.0

    y = np.array([0, 1, 0])

    def azimuth(p):  # angle vu de dessus, 0 = devant (+z), croissant vers la droite (+x)
        return math.atan2(p[0], p[2]) % (2 * math.pi)

    top = [i for i in range(12) if pts[i] @ y > 0.99][0]
    bottom = [i for i in range(12) if pts[i] @ y < -0.99][0]
    upper = sorted([i for i in range(12) if 0.3 < pts[i] @ y < 0.6], key=lambda i: azimuth(pts[i]))
    lower = sorted([i for i in range(12) if -0.6 < pts[i] @ y < -0.3], key=lambda i: azimuth(pts[i]))
    # anneau supérieur, de face puis vers la droite : F, R, BR, BL, L
    names_upper = ["F", "R", "BR", "BL", "L"]
    order = [top] + upper
    names = ["U"] + names_upper
    # anneau inférieur : chaque face est nommée d'après l'opposée de l'anneau supérieur
    opposite_name = {"F": "B", "R": "DBL", "BR": "DL", "BL": "DR", "L": "DBR"}
    for i, nm in zip(upper, names_upper):
        opp = min(lower, key=lambda j: float(pts[i] @ pts[j]))
        order.append(opp)
        names.append(opposite_name[nm])
    order.append(bottom)
    names.append("D")
    return names, pts[order]


# ---------------------------------------------------------------------------
# Découpe de polygones convexes
# ---------------------------------------------------------------------------

def split_polygon(poly: list[np.ndarray], n: np.ndarray, d: float):
    """Coupe un polygone convexe par le plan dot(x, n) = d.

    Renvoie (partie au-dessus, partie en dessous) ; une partie vide vaut None.
    """
    vals = [float(p @ n) - d for p in poly]
    if all(v >= -EPS for v in vals):
        return poly, None
    if all(v <= EPS for v in vals):
        return None, poly
    above, below = [], []
    m = len(poly)
    for i in range(m):
        p, q = poly[i], poly[(i + 1) % m]
        vp, vq = vals[i], vals[(i + 1) % m]
        if vp >= -EPS:
            above.append(p)
        if vp <= EPS:
            below.append(p)
        if (vp > EPS and vq < -EPS) or (vp < -EPS and vq > EPS):
            t = vp / (vp - vq)
            x = p + t * (q - p)
            above.append(x)
            below.append(x)
    return _dedupe(above), _dedupe(below)


def _dedupe(poly):
    out = []
    for p in poly:
        if not out or np.linalg.norm(p - out[-1]) > 1e-9:
            out.append(p)
    if len(out) > 1 and np.linalg.norm(out[0] - out[-1]) < 1e-9:
        out.pop()
    return out if len(out) >= 3 else None


def polygon_area(poly) -> float:
    s = np.zeros(3)
    for i in range(len(poly)):
        s += np.cross(poly[i], poly[(i + 1) % len(poly)])
    return float(np.linalg.norm(s)) / 2


def face_polygon(normals: np.ndarray, idx: int) -> list[np.ndarray]:
    """Polygone de la face idx : plan dot(x,n)=1 limité par les autres faces."""
    n = normals[idx]
    a = np.cross(n, [0.3, 0.5, 0.7])
    a /= np.linalg.norm(a)
    b = np.cross(n, a)
    big = 10.0
    poly = [n + big * (sa * a + sb * b) for sa, sb in ((1, 1), (-1, 1), (-1, -1), (1, -1))]
    for j, m in enumerate(normals):
        if j == idx:
            continue
        _, poly = split_polygon(poly, m, 1.0)
    # orientation anti-horaire vue de l'extérieur
    c = sum(poly) / len(poly)
    if np.dot(np.cross(poly[0] - c, poly[1] - c), n) < 0:
        poly = poly[::-1]
    return poly


# ---------------------------------------------------------------------------
# Puzzle géométrique
# ---------------------------------------------------------------------------

@dataclass
class Sticker:
    id: int
    face: int
    poly: list[np.ndarray]
    center: np.ndarray


@dataclass
class Layer:
    """Tranche tournante : points x avec lo < dot(x, n_face) < hi."""
    face: int
    index: int          # 1 = couche extérieure, 2 = deuxième couche...
    lo: float
    hi: float
    middle: bool = False  # tranche centrale d'un cube impair (M, E, S)


@dataclass
class Geometry:
    kind: str                  # "cube" ou "dodeca"
    face_names: list[str]
    normals: np.ndarray
    order: int                 # ordre de symétrie d'une face (4 ou 5)
    stickers: list[Sticker] = field(default_factory=list)
    layers: list[Layer] = field(default_factory=list)
    cuts: list[tuple[int, float]] = field(default_factory=list)

    @property
    def centers(self) -> np.ndarray:
        return np.array([s.center for s in self.stickers])


def build_geometry(kind: str, depths: list[float], middle_slices: bool = False) -> Geometry:
    """Construit facettes et tranches.

    depths : profondeurs de coupe décroissantes (identiques pour chaque face).
    middle_slices : ajoute pour un cube impair les tranches centrales.
    """
    if kind == "cube":
        names, normals = cube_normals()
        order = 4
    elif kind == "dodeca":
        names, normals = dodecahedron_normals()
        order = 5
    else:
        raise ValueError(kind)
    geo = Geometry(kind=kind, face_names=names, normals=normals, order=order)
    for f in range(len(normals)):
        for d in depths:
            geo.cuts.append((f, d))

    sid = 0
    for f, n in enumerate(normals):
        polys = [face_polygon(normals, f)]
        for g, d in geo.cuts:
            if abs(float(normals[g] @ n)) > 0.999:
                continue
            nxt = []
            for p in polys:
                a, b = split_polygon(p, normals[g], d)
                for part in (a, b):
                    if part is not None and polygon_area(part) > 1e-6:
                        nxt.append(part)
            polys = nxt
        # ordre stable : tri par angle puis distance au centre de la face
        for p in polys:
            c = sum(p) / len(p)
            geo.stickers.append(Sticker(id=sid, face=f, poly=p, center=c))
            sid += 1

    # tranches
    bounds = [1.0 + 1e-3] + list(depths)
    for f in range(len(normals)):
        for k in range(1, len(bounds)):
            geo.layers.append(Layer(face=f, index=k, lo=bounds[k], hi=bounds[k - 1]))
    if middle_slices:
        last = depths[-1]
        # M suit L, E suit D, S suit F (convention usuelle)
        for nm in ("L", "D", "F"):
            f = names.index(nm)
            geo.layers.append(Layer(face=f, index=len(depths) + 1, lo=-last, hi=last, middle=True))
    return geo


def layer_members(geo: Geometry, layer: Layer) -> np.ndarray:
    d = geo.centers @ geo.normals[layer.face]
    return np.where((d > layer.lo) & (d < layer.hi))[0]


def rotation_perm(geo: Geometry, R: np.ndarray, members: np.ndarray | None = None) -> np.ndarray:
    """Permutation des emplacements induite par la rotation R appliquée aux membres.

    perm[a] = emplacement où arrive le contenu de l'emplacement a.
    """
    C = geo.centers
    n = len(C)
    perm = np.arange(n)
    idx = np.arange(n) if members is None else members
    moved = C[idx] @ R.T
    # recherche du plus proche voisin
    dist = np.linalg.norm(moved[:, None, :] - C[None, :, :], axis=2)
    tgt = dist.argmin(axis=1)
    if dist[np.arange(len(idx)), tgt].max() > 1e-6:
        raise RuntimeError("rotation incompatible avec la géométrie")
    perm[idx] = tgt
    if len(set(perm.tolist())) != n:
        raise RuntimeError("permutation invalide")
    return perm


def symmetry_rotations(geo: Geometry) -> list[np.ndarray]:
    """Rotations propres conservant le polyèdre (24 pour le cube, 60 pour le dodécaèdre)."""
    N = geo.normals
    a, b = 0, max((j for j in range(len(N)) if j != 0), key=lambda j: N[0] @ N[j] if N[0] @ N[j] < 0.99 else -9)
    cab = float(N[a] @ N[b])
    src = np.array([N[a], N[b], np.cross(N[a], N[b])]).T
    out = []
    for a2 in range(len(N)):
        for b2 in range(len(N)):
            if a2 == b2 or abs(float(N[a2] @ N[b2]) - cab) > 1e-6:
                continue
            dst = np.array([N[a2], N[b2], np.cross(N[a2], N[b2])]).T
            R = dst @ np.linalg.inv(src)
            out.append(R)
    return out


def face_frame(geo: Geometry, f: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Repère 2D d'une face vue de l'extérieur : (centre, droite, haut)."""
    n = geo.normals[f]
    world_up = np.array([0.0, 1.0, 0.0])
    if abs(n @ world_up) > 0.9:
        world_up = np.array([0.0, 0.0, -1.0 if n[1] > 0 else 1.0])
    up = world_up - (world_up @ n) * n
    up /= np.linalg.norm(up)
    right = np.cross(up, n)
    return n * 1.0, right, up
