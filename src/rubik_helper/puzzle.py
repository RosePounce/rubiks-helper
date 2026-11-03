"""Modèle combinatoire d'un puzzle : pièces, orbites, mouvements, notation.

Convention des permutations : perm[a] = emplacement où arrive le contenu
de l'emplacement a. L'état est un tableau `cont` : cont[emplacement] =
facette d'origine actuellement à cet emplacement.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import cached_property

import numpy as np

from .geometry import (
    Geometry,
    axis_angle_matrix,
    build_geometry,
    face_frame,
    layer_members,
    rotation_perm,
    symmetry_rotations,
)


@dataclass
class Move:
    name: str
    face: int
    layer: int            # 1 = extérieure ; 0 = rotation complète ou mouvement spécial
    amount: int           # en pas de 360/ordre degrés, sens horaire vu de la face
    perm: np.ndarray
    middle: bool = False
    axis: int = 0         # identifiant d'axe (faces opposées = même axe)
    region: tuple = ()    # identifiant de tranche, pour la fusion des mouvements
    members: list[int] = field(default_factory=list)


@dataclass
class Orbit:
    id: int
    kind: str             # corner, midge, wing, center, xcenter, tcenter, oblique
    label: str
    pieces: list[int]
    size: int             # nombre de facettes par pièce
    twist_step: int       # orientations accessibles : multiples de twist_step
    ignored: bool = False
    fixed: bool = False   # orbite d'une seule pièce (centre fixe)


class Puzzle:
    def __init__(self, pid: str, label: str, geo: Geometry, family: str, size: int,
                 ignored_kinds: tuple[str, ...] = ()):
        self.id = pid
        self.label = label
        self.geo = geo
        self.family = family     # "cube" ou "minx"
        self.size = size         # N pour NxN, ordre équivalent pour les minx
        self.n = len(geo.stickers)
        self.sticker_face = np.array([s.face for s in geo.stickers])
        self.ignored_kinds = ignored_kinds
        self._build_moves()
        self._build_pieces()
        self._build_orbits()

    # ------------------------------------------------------------------ moves
    def _amount_suffix(self, a: int) -> str:
        o = self.geo.order
        if o == 3:
            return {1: "", 2: "'"}[a]
        if o == 4:
            return {1: "", 2: "2", 3: "'"}[a]
        return {1: "", 2: "2", 3: "2'", 4: "'"}[a]

    def _axis_id(self, f: int) -> int:
        n = self.geo.normals
        for g in range(len(n)):
            if abs(float(n[f] @ n[g]) + 1) < 1e-6:
                return min(f, g)
        return f

    def _build_moves(self):
        geo = self.geo
        o = geo.order
        self.moves: list[Move] = []
        for L in geo.layers:
            mem = layer_members(geo, L)
            name_face = geo.face_names[L.face]
            if L.middle:
                base = {"L": "M", "D": "E", "F": "S"}[name_face]
            elif geo.kind == "tetra":
                # pointe (index 1) en minuscule, anneau/tour de sommet (index 2) en majuscule
                base = name_face.lower() if L.index == 1 else name_face
            elif L.index == 1:
                base = name_face
            else:
                base = f"{L.index}{name_face}"
            # identifiant de tranche commun aux deux faces opposées
            n = geo.normals[L.face]
            ax = self._axis_id(L.face)
            sign = 1 if ax == L.face else -1
            region = (ax, round(sign * L.lo, 6), round(sign * L.hi, 6))
            for a in range(1, o):
                R = axis_angle_matrix(n, -2 * math.pi * a / o)
                perm = rotation_perm(geo, R, mem)
                self.moves.append(Move(name=base + self._amount_suffix(a), face=L.face, layer=L.index,
                                       amount=a, perm=perm, middle=L.middle, axis=ax,
                                       region=region, members=mem.tolist()))
        self.move_index = {m.name: i for i, m in enumerate(self.moves)}
        # mouvements « de cadre » : ceux qui ne déplacent pas les centres fixes
        self.frame_moves = [i for i, m in enumerate(self.moves) if not m.middle]
        # inverse de chaque mouvement
        self.inverse = []
        for m in self.moves:
            inv_amount = o - m.amount
            key = (m.face, m.layer, m.middle, inv_amount)
            self.inverse.append(next(j for j, q in enumerate(self.moves)
                                     if (q.face, q.layer, q.middle, q.amount) == key))

    # ----------------------------------------------------------------- pieces
    def _build_pieces(self):
        geo = self.geo
        sig_to_piece: dict[tuple, int] = {}
        self.piece_of = np.zeros(self.n, dtype=int)
        self.pieces: list[list[int]] = []
        for s in geo.stickers:
            p = s.center - 1e-4 * geo.normals[s.face]
            sig = tuple(bool(p @ geo.normals[f] > d) for f, d in geo.cuts)
            if sig not in sig_to_piece:
                sig_to_piece[sig] = len(self.pieces)
                self.pieces.append([])
            pid = sig_to_piece[sig]
            self.pieces[pid].append(s.id)
            self.piece_of[s.id] = pid

    def _build_orbits(self):
        P = len(self.pieces)
        parent = list(range(P))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for mi in self.frame_moves:
            perm = self.moves[mi].perm
            for p, st in enumerate(self.pieces):
                q = self.piece_of[perm[st[0]]]
                a, b = find(p), find(q)
                if a != b:
                    parent[a] = b
        groups: dict[int, list[int]] = {}
        for p in range(P):
            groups.setdefault(find(p), []).append(p)

        # ordre canonique des facettes de chaque pièce, propagé par les mouvements
        order: dict[int, list[int]] = {}
        for root, members in groups.items():
            p0 = min(members)
            order[p0] = self._ccw_order(self.pieces[p0])
            queue = [p0]
            while queue:
                p = queue.pop()
                for mi in self.frame_moves:
                    perm = self.moves[mi].perm
                    q = int(self.piece_of[perm[order[p][0]]])
                    if q not in order:
                        order[q] = [int(perm[s]) for s in order[p]]
                        queue.append(q)
        self.pieces = [order[p] for p in range(P)]
        self.sticker_index = np.zeros(self.n, dtype=int)   # rang de la facette dans sa pièce
        for p, st in enumerate(self.pieces):
            for j, s in enumerate(st):
                self.sticker_index[s] = j

        self.orbits: list[Orbit] = []
        self.orbit_of_piece = np.zeros(P, dtype=int)
        for members in sorted(groups.values(), key=lambda m: min(m)):
            k = len(self.pieces[members[0]])
            # pas de torsion accessible
            g = k
            for mi in self.frame_moves:
                perm = self.moves[mi].perm
                for p in members:
                    s0 = self.pieces[p][0]
                    t = int(perm[s0])
                    off = int(self.sticker_index[t])
                    g = math.gcd(g, off)
            kind = self._classify(members)
            oid = len(self.orbits)
            self.orbits.append(Orbit(id=oid, kind=kind, label="", pieces=sorted(members), size=k,
                                     twist_step=g if g else k, ignored=kind in self.ignored_kinds,
                                     fixed=len(members) == 1 and k == 1))
            for p in members:
                self.orbit_of_piece[p] = oid
        self._label_orbits()

    def _ccw_order(self, stickers: list[int]) -> list[int]:
        geo = self.geo
        if len(stickers) < 3:
            return sorted(stickers)
        axis = sum(geo.normals[geo.stickers[s].face] for s in stickers)
        axis = axis / np.linalg.norm(axis)
        ref = geo.normals[geo.stickers[stickers[0]].face]
        u = ref - (ref @ axis) * axis
        u /= np.linalg.norm(u)
        v = np.cross(axis, u)

        def ang(s):
            w = geo.normals[geo.stickers[s].face]
            return math.atan2(float(w @ v), float(w @ u)) % (2 * math.pi)

        return sorted(stickers, key=ang)

    def _classify(self, members: list[int]) -> str:
        k = len(self.pieces[members[0]])
        if self.geo.kind == "tetra":
            if k == 2:
                return "midge"
            # k == 3 : pointe (près du sommet) ou coin axial (dans l'anneau)
            c = sum(self.geo.stickers[s].center for s in self.pieces[members[0]]) / k
            return "tip" if float((self.geo.normals @ c).min()) < -5 / 3 else "corner"
        n_edges = 12 if self.geo.kind == "cube" else 30
        if k == 3:
            return "corner"
        if k == 2:
            return "midge" if len(members) == n_edges else "wing"
        if len(members) == 1:
            return "center"
        # centre : position relative au centre de la face
        s = self.geo.stickers[self.pieces[members[0]][0]]
        fc = self.geo.normals[s.face]
        v = s.center - fc
        if np.linalg.norm(v) < 1e-6:
            return "center"
        poly = np.array([p for p in _face_vertices(self.geo, s.face)])
        verts = poly - fc
        edges = (np.roll(poly, -1, axis=0) + poly) / 2 - fc

        def best(dirs):
            return max(float(v @ d) / (np.linalg.norm(v) * np.linalg.norm(d)) for d in dirs)

        if best(verts) > 0.9999:
            return "xcenter"
        if best(edges) > 0.9999:
            return "tcenter"
        return "oblique"

    def _label_orbits(self):
        base = {
            "corner": "Coins", "midge": "Arêtes", "wing": "Ailes (arêtes doubles)",
            "center": "Centres", "xcenter": "Centres X", "tcenter": "Centres T",
            "oblique": "Centres obliques", "tip": "Pointes",
        }
        has_wings = any(o.kind == "wing" for o in self.orbits)
        counts: dict[str, int] = {}
        for o in self.orbits:
            if o.fixed:
                o.label = "Centre fixe"
                continue
            counts[o.kind] = counts.get(o.kind, 0) + 1
        seen: dict[str, int] = {}
        center_kinds = [o.kind for o in self.orbits if not o.fixed and o.kind in
                        ("center", "xcenter", "tcenter", "oblique")]
        for o in self.orbits:
            if o.fixed:
                continue
            lbl = base[o.kind]
            if o.kind == "midge" and has_wings:
                lbl = "Arêtes centrales"
            if o.kind in ("xcenter", "center") and len(center_kinds) == 1:
                lbl = "Centres"
            if counts[o.kind] > 1:
                seen[o.kind] = seen.get(o.kind, 0) + 1
                lbl = f"{lbl} ({seen[o.kind]})"
            o.label = lbl

    # ------------------------------------------------------------- utilities
    @cached_property
    def symmetries(self) -> list[np.ndarray]:
        """Permutations d'emplacements des rotations du puzzle entier."""
        return [rotation_perm(self.geo, R) for R in symmetry_rotations(self.geo)]

    def identity(self) -> np.ndarray:
        return np.arange(self.n)

    def apply(self, cont: np.ndarray, perm: np.ndarray) -> np.ndarray:
        out = np.empty_like(cont)
        out[perm] = cont
        return out

    def seq_perm(self, seq: list[int]) -> np.ndarray:
        p = np.arange(self.n)
        for mi in seq:
            p = self.moves[mi].perm[p]
        return p

    def apply_seq(self, cont: np.ndarray, seq: list[int]) -> np.ndarray:
        for mi in seq:
            cont = self.apply(cont, self.moves[mi].perm)
        return cont

    def invert_seq(self, seq: list[int]) -> list[int]:
        return [self.inverse[mi] for mi in reversed(seq)]

    def colors(self, cont: np.ndarray) -> np.ndarray:
        return self.sticker_face[cont]

    def names(self, seq: list[int]) -> list[str]:
        return [self.moves[mi].name for mi in seq]

    # ---------------------------------------------------------------- notation
    def _anim_angle(self, amount: int) -> float:
        o = self.geo.order
        amount %= o
        if amount * 2 <= o:
            return -2 * math.pi * amount / o
        return 2 * math.pi * (o - amount) / o

    def _token(self, tok, face, amount, members, seq=None):
        o = self.geo.order
        R = axis_angle_matrix(self.geo.normals[face], -2 * math.pi * amount / o)
        mem = np.asarray(sorted(set(int(x) for x in members)), dtype=int)
        perm = rotation_perm(self.geo, R, mem)
        return {"name": tok, "perm": perm, "seq": seq or [], "face": face,
                "angle": self._anim_angle(amount), "members": mem.tolist()}

    def _special(self, token: str):
        """Rotations entières (x, y, z) et mouvements Pochmann (R++, D--)."""
        o = self.geo.order
        names = self.geo.face_names
        if self.family == "cube":
            m = re.fullmatch(r"([xyz])(2|')?", token)
            if m:
                f = names.index({"x": "R", "y": "U", "z": "F"}[m.group(1)])
                a = {None: 1, "2": 2, "'": 3}[m.group(2)]
                return self._token(token, f, a, range(self.n))
        else:
            m = re.fullmatch(r"([RD])(\+\+|--)", token)
            if m:
                # R++ : tout sauf la couche DBL, 2/5 de tour horaire vu de R.
                # D++ : tout sauf la couche U, 2/5 de tour horaire vu de D.
                f = names.index(m.group(1))
                keep = names.index("DBL" if m.group(1) == "R" else "U")
                a = 2 if m.group(2) == "++" else o - 2
                d1 = max(L.lo for L in self.geo.layers if L.face == keep and L.index == 1)
                dots = self.geo.centers @ self.geo.normals[keep]
                return self._token(token, f, a, np.where(dots < d1)[0])
        return None

    def parse(self, text: str) -> list[dict]:
        """Analyse une formule.

        Chaque jeton donne : nom, permutation, mouvements de base équivalents
        (vide pour une rotation entière), face, angle et facettes pour l'animation.
        """
        out = []
        tokens = text.replace("(", " ").replace(")", " ").replace(",", " ").split()
        o = self.geo.order
        faces = sorted(self.geo.face_names, key=len, reverse=True)
        face_re = "|".join(faces)
        lower = {f.lower(): f for f in self.geo.face_names if len(f) == 1} if self.family == "cube" else {}
        alt = f"|[{''.join(lower)}]" if lower else ""
        pat = re.compile(rf"^(\d*)({face_re}{alt})(w?)(2'|2|3|'|)$")
        for tok in tokens:
            sp = self._special(tok)
            if sp is not None:
                out.append(sp)
                continue
            if tok in self.move_index:
                mi = self.move_index[tok]
                mv = self.moves[mi]
                out.append({"name": tok, "perm": mv.perm, "seq": [mi], "face": mv.face,
                            "angle": self._anim_angle(mv.amount), "members": mv.members})
                continue
            m = pat.match(tok)
            if not m:
                raise ValueError(f"Mouvement inconnu : « {tok} »")
            num, face, wide, suf = m.groups()
            if face in lower:
                face, wide = lower[face], "w"
            amount = {"": 1, "2": 2 % o, "'": o - 1, "2'": o - 2, "3": 3 % o}[suf]
            f = self.geo.face_names.index(face)
            depth = int(num) if num else (2 if wide else 1)
            layers = list(range(1, depth + 1)) if wide else [depth]
            seq, members = [], []
            for li in layers:
                cand = [i for i, mv in enumerate(self.moves)
                        if mv.face == f and mv.layer == li and not mv.middle and mv.amount == amount]
                if not cand:
                    seq = None
                    break
                seq.append(cand[0])
                members += self.moves[cand[0]].members
            if seq is None:
                mem = self._deep_layer_members(f, layers)
                if mem is None:
                    raise ValueError(f"Couche hors limites : « {tok} »")
                out.append(self._token(tok, f, amount, mem))
                continue
            t = self._token(tok, f, amount, members, seq)
            out.append(t)
        return out

    def _deep_layer_members(self, f: int, layers: list[int]):
        """Couches au-delà de celles décrites par les générateurs (ex. 3Rw sur 5x5)."""
        if self.family != "cube" or max(layers) > self.size:
            return None
        N = self.size
        dots = self.geo.centers @ self.geo.normals[f]
        lo = 1 - 2 * max(layers) / N - 1e-6
        hi = 1 - 2 * (min(layers) - 1) / N + 1e-6
        return np.where((dots > lo) & (dots < hi))[0]

    def apply_formula(self, cont: np.ndarray, text: str) -> np.ndarray:
        for t in self.parse(text):
            cont = self.apply(cont, t["perm"])
        return cont

    # ------------------------------------------------------------ export JSON
    def to_json(self) -> dict:
        geo = self.geo
        faces = []
        for f, nm in enumerate(geo.face_names):
            c, r, u = face_frame(geo, f)
            # voisin le plus « en haut » pour guider la prise de vue (sur le tétraèdre,
            # les faces adjacentes ont un produit scalaire de -1/3)
            lo = -0.5 if geo.kind == "tetra" else -0.1
            neigh = [g for g in range(len(geo.normals)) if lo < geo.normals[f] @ geo.normals[g] < 0.99]
            best = max(float(geo.normals[g] @ u) for g in neigh)
            tops = [g for g in neigh if float(geo.normals[g] @ u) > best - 1e-4]
            faces.append({"name": nm, "normal": geo.normals[f].round(6).tolist(),
                          "right": r.round(6).tolist(), "up": u.round(6).tolist(),
                          "top_neighbor": tops[0],
                          "top_label": (f"face {geo.face_names[tops[0]]} en haut" if len(tops) == 1 else
                                        "jonction " + " / ".join(geo.face_names[g] for g in tops) + " en haut"),
                          "outline": [[round(float((v - c) @ r), 5), round(float((v - c) @ u), 5)]
                                      for v in _face_vertices(geo, f)]})
        stickers = []
        ignored = {s for o in self.orbits if o.ignored for p in o.pieces for s in self.pieces[p]}
        for s in geo.stickers:
            c, r, u = face_frame(geo, s.face)
            stickers.append({
                "id": s.id, "face": s.face,
                "poly": [[round(float(x), 5) for x in v] for v in s.poly],
                "poly2d": [[round(float((v - c) @ r), 5), round(float((v - c) @ u), 5)] for v in s.poly],
                "piece": int(self.piece_of[s.id]),
                "orbit": int(self.orbit_of_piece[self.piece_of[s.id]]),
                "ignored": s.id in ignored,
            })
        moves = [{"name": m.name, "face": m.face, "angle": self._anim_angle(m.amount),
                  "members": m.members, "perm": m.perm.tolist()} for m in self.moves]
        return {
            "id": self.id, "label": self.label, "family": self.family, "kind": geo.kind,
            "size": self.size, "order": geo.order, "faces": faces, "stickers": stickers,
            "moves": moves,
            "orbits": [{"id": o.id, "label": o.label, "kind": o.kind, "pieces": len(o.pieces),
                        "ignored": o.ignored, "fixed": o.fixed} for o in self.orbits],
            "fixed_centers": any(o.fixed for o in self.orbits),
        }


def _face_vertices(geo: Geometry, f: int):
    from .geometry import face_polygon
    return face_polygon(geo.normals, f)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

CATALOG = {
    "3x3": ("Cube 3x3", "cube", 3),
    "4x4": ("Cube 4x4", "cube", 4),
    "5x5": ("Cube 5x5", "cube", 5),
    "6x6": ("Cube 6x6", "cube", 6),
    "7x7": ("Cube 7x7", "cube", 7),
    "pyraminx": ("Pyraminx", "tetra", 3),
    "megaminx": ("Megaminx (équivalent 3x3)", "minx", 3),
    "master-kilominx": ("Master Kilominx (équivalent 4x4)", "minx", 4),
    "gigaminx": ("Gigaminx (équivalent 5x5)", "minx", 5),
}

_cache: dict[str, Puzzle] = {}


def get_puzzle(pid: str) -> Puzzle:
    if pid in _cache:
        return _cache[pid]
    if pid not in CATALOG:
        raise KeyError(pid)
    label, family, N = CATALOG[pid]
    if family == "cube":
        depths = [1 - 2 * k / N for k in range(1, N // 2 + 1)]
        geo = build_geometry("cube", depths, middle_slices=(N % 2 == 1))
        pz = Puzzle(pid, label, geo, family, N)
    elif family == "tetra":
        # tétraèdre coupé parallèlement aux faces à -1/3 et -5/3 (arêtes en trois)
        geo = build_geometry("tetra", [-1 / 3, -5 / 3])
        pz = Puzzle(pid, label, geo, family, N)
    elif pid == "megaminx":
        geo = build_geometry("dodeca", [0.7])
        pz = Puzzle(pid, label, geo, family, N)
    elif pid == "gigaminx":
        geo = build_geometry("dodeca", [0.86, 0.66])
        pz = Puzzle(pid, label, geo, family, N)
    elif pid == "master-kilominx":
        # Modélisé comme un Gigaminx dont les pièces « du milieu » (centre,
        # centres T, arêtes centrales) sont ignorées, exactement comme un 4x4
        # est un 5x5 sans sa tranche centrale.
        geo = build_geometry("dodeca", [0.86, 0.66])
        pz = Puzzle(pid, label, geo, family, N, ignored_kinds=("center", "tcenter", "midge"))
    else:
        raise KeyError(pid)
    _cache[pid] = pz
    return pz
