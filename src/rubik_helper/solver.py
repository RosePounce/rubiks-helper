"""Solveur générique par commutateurs.

Principe (celui de la résolution à l'aveugle « 3-style ») :
  1. lire l'état à partir des couleurs ;
  2. corriger la parité de permutation avec un ou deux mouvements simples ;
  3. pour chaque orbite (centres, ailes, arêtes, coins), résoudre les pièces
     deux par deux avec des 3-cycles purs : un commutateur [X, Y] précédé
     d'un placement S et suivi de son inverse, noté [S : [X, Y]].

Le même code résout un cube NxN ou un dodécaèdre ; seule la bibliothèque de
commutateurs (calculée une fois puis mise en cache) dépend du puzzle.
"""

from __future__ import annotations

import itertools
import math
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .puzzle import Orbit, Puzzle

CACHE_VERSION = 6
CACHE_DIR = Path(os.environ.get("RUBIK_HELPER_CACHE", Path.home() / ".cache" / "rubik-helper"))


class SolveError(Exception):
    """Erreur de saisie ou état impossible ; le message est destiné à l'utilisateur."""

    def __init__(self, message: str, stickers: list[int] | None = None):
        super().__init__(message)
        self.stickers = stickers or []
        self.repairs: list[dict] = []   # corrections physiques proposées (puzzle mal remonté)


# ---------------------------------------------------------------------------
# Lecture de l'état
# ---------------------------------------------------------------------------

@dataclass
class State:
    cont: np.ndarray                 # emplacement -> facette d'origine
    face_color: list[int]            # face -> couleur
    color_mode: set[int]             # orbites à pièces identiques (traitées par couleur)
    home_color: np.ndarray           # emplacement -> couleur attendue
    colors: np.ndarray               # emplacement -> couleur actuelle


def _orbit_home_tuples(pz: Puzzle, orb: Orbit, face_color: list[int]):
    return {q: tuple(face_color[pz.sticker_face[s]] for s in pz.pieces[q]) for q in orb.pieces}


def corner_frames(pz: Puzzle, colors: np.ndarray):
    """Associations face -> couleur reconstruites à partir des coins.

    Sert aux puzzles sans centre fixe : la position de référence reçoit
    successivement chaque coin dans chaque orientation (24 ou 60 repères).
    Le premier repère proposé laisse en place le coin déjà présent.
    """
    corners = next(o for o in pz.orbits if o.kind == "corner")
    nf = len(pz.geo.face_names)
    tuples = []
    for p in corners.pieces:
        t = tuple(int(colors[s]) for s in pz.pieces[p])
        if -1 in t:
            raise SolveError("Toutes les facettes des coins doivent être renseignées.",
                             [s for s in pz.pieces[p] if colors[s] == -1])
        tuples.append(t)
    rots = {t[i:] + t[:i] for t in tuples for i in range(3)}
    ref = corners.pieces[0]
    ref_faces = [int(pz.sticker_face[s]) for s in pz.pieces[ref]]
    out = []
    seen = set()
    cand = [tuples[0]] + tuples[1:]
    for t in cand:
        for i in range(3):
            fc = [-1] * nf
            for j in range(3):
                fc[ref_faces[j]] = t[(j + i) % 3]
            changed = True
            while changed and -1 in fc:
                changed = False
                for p in corners.pieces:
                    fs = [int(pz.sticker_face[s]) for s in pz.pieces[p]]
                    known = [fc[f] for f in fs]
                    if known.count(-1) != 1:
                        continue
                    k = known.index(-1)
                    opts = set()
                    for r in rots:
                        if all(r[j] == known[j] for j in range(3) if j != k):
                            opts.add(r[k])
                    if len(opts) == 1:
                        fc[fs[k]] = opts.pop()
                        changed = True
            if -1 in fc or len(set(fc)) != nf:
                continue
            key = tuple(fc)
            if key not in seen:
                seen.add(key)
                out.append(fc)
    return out


def read_state(pz: Puzzle, colors: list[int], face_color: list[int]) -> State:
    colors = np.asarray(colors, dtype=int)
    home_color = np.array([face_color[f] for f in pz.sticker_face])
    cont = np.arange(pz.n)
    color_mode: set[int] = set()
    for orb in pz.orbits:
        if orb.fixed or orb.ignored:
            continue
        homes = _orbit_home_tuples(pz, orb, face_color)
        k, g = orb.size, orb.twist_step
        # pièces identiques ?
        canon = {}
        for q, h in homes.items():
            key = min(h[r:] + h[:r] for r in range(0, k, g))
            canon.setdefault(key, []).append(q)
        identical = any(len(v) > 1 for v in canon.values())
        if identical:
            if k != 1:
                raise SolveError("Orbite à pièces identiques non prise en charge.")
            color_mode.add(orb.id)
            # affectation arbitraire compatible avec les couleurs
            pool: dict[int, list[int]] = {}
            for q in orb.pieces:
                pool.setdefault(homes[q][0], []).append(pz.pieces[q][0])
            need = {}
            for p in orb.pieces:
                c = int(colors[pz.pieces[p][0]])
                need[c] = need.get(c, 0) + 1
            for c, nb in need.items():
                if c == -1:
                    raise SolveError(f"{orb.label} : facettes non renseignées.",
                                     [pz.pieces[p][0] for p in orb.pieces if colors[pz.pieces[p][0]] == -1])
                if nb != len(pool.get(c, [])):
                    bad = [pz.pieces[p][0] for p in orb.pieces if colors[pz.pieces[p][0]] == c]
                    raise SolveError(
                        f"{orb.label} : {nb} pièce(s) de cette couleur au lieu de {len(pool.get(c, []))}.", bad)
            for p in orb.pieces:
                s = pz.pieces[p][0]
                c = int(colors[s])
                lst = pool[c]
                pick = s if s in lst else lst[0]
                lst.remove(pick)
                cont[s] = pick
            continue
        # pièces distinctes : correspondance par couleurs avec rotation admise
        lookup = {}
        for q, h in homes.items():
            for r in range(0, k, g):
                lookup[h[r:] + h[:r]] = (q, r)
        used: dict[int, int] = {}
        for p in orb.pieces:
            st = pz.pieces[p]
            cur = tuple(int(colors[s]) for s in st)
            if -1 in cur:
                raise SolveError(f"{orb.label} : facettes non renseignées.", [s for s in st if colors[s] == -1])
            if cur not in lookup:
                raise SolveError(f"{orb.label} : cette combinaison de couleurs n'existe pas sur le puzzle.", st)
            q, r = lookup[cur]
            if q in used:
                raise SolveError(f"{orb.label} : la même pièce apparaît deux fois.", st + pz.pieces[used[q]])
            used[q] = p
            for j, s in enumerate(st):
                cont[s] = pz.pieces[q][(j + r) % k]
    return State(cont=cont, face_color=list(face_color), color_mode=color_mode,
                 home_color=home_color, colors=colors)


def frames_for(pz: Puzzle, colors: list[int]) -> list[list[int]]:
    colors = np.asarray(colors, dtype=int)
    fixed = [o for o in pz.orbits if o.fixed and not o.ignored]
    if fixed:
        fc = [-1] * len(pz.geo.face_names)
        for o in fixed:
            s = pz.pieces[o.pieces[0]][0]
            fc[pz.sticker_face[s]] = int(colors[s])
        if -1 in fc:
            raise SolveError("Les centres doivent être renseignés.",
                             [pz.pieces[o.pieces[0]][0] for o in fixed])
        if len(set(fc)) != len(fc):
            raise SolveError("Deux centres ont la même couleur.", [pz.pieces[o.pieces[0]][0] for o in fixed])
        return [fc]
    return corner_frames(pz, colors)


# ---------------------------------------------------------------------------
# Invariants et parité
# ---------------------------------------------------------------------------

def _piece_perm(pz: Puzzle, orb: Orbit, cont: np.ndarray) -> dict[int, int]:
    """position -> pièce d'origine."""
    return {p: int(pz.piece_of[cont[pz.pieces[p][0]]]) for p in orb.pieces}


def _parity(mapping: dict[int, int]) -> int:
    seen = set()
    par = 0
    for start in mapping:
        if start in seen:
            continue
        n = 0
        x = start
        while x not in seen:
            seen.add(x)
            x = mapping[x]
            n += 1
        par ^= (n - 1) & 1
    return par


def _distinct_orbits(pz: Puzzle, st: State) -> list[Orbit]:
    return [o for o in pz.orbits if not (o.fixed or o.ignored or o.id in st.color_mode)]


def check_orientation(pz: Puzzle, st: State):
    for orb in _distinct_orbits(pz, st):
        k = orb.size
        if k == 1:
            continue
        h = k
        for mi in pz.frame_moves:
            perm = pz.moves[mi].perm
            tot = sum(int(pz.sticker_index[perm[pz.pieces[p][0]]]) for p in orb.pieces)
            h = math.gcd(h, tot % k)
        h = h or k
        tot = sum(int(pz.sticker_index[st.cont[pz.pieces[p][0]]]) for p in orb.pieces)
        if tot % h:
            what = "coin tourné" if k == 3 else "arête retournée"
            raise SolveError(f"{orb.label} : état impossible (un {what} sur place). "
                             "Vérifiez les couleurs saisies ou remontez la pièce.")


def parity_fix(pz: Puzzle, st: State) -> list[int]:
    """Séquence la plus courte de mouvements de cadre qui rend paires toutes les orbites."""
    orbs = _distinct_orbits(pz, st)
    if not orbs:
        return []
    ident = np.arange(pz.n)

    def vec(cont):
        v = 0
        for i, o in enumerate(orbs):
            v |= _parity(_piece_perm(pz, o, cont)) << i
        return v

    target = vec(st.cont)
    if target == 0:
        return []
    mvec = {}
    for mi in pz.frame_moves:
        m = pz.moves[mi]
        if m.amount != 1:
            continue
        mvec[mi] = vec(pz.apply(ident, m.perm))
    # préférence : couches extérieures, puis tranches
    order = sorted(mvec, key=lambda mi: (pz.moves[mi].layer, mi))
    frontier = {0: []}
    for _ in range(4):
        nxt = {}
        for v, seq in frontier.items():
            for mi in order:
                w = v ^ mvec[mi]
                if w not in frontier and w not in nxt:
                    nxt[w] = seq + [mi]
        if target in nxt:
            return nxt[target]
        frontier.update(nxt)
    raise SolveError("État impossible : parité de permutation incohérente "
                     "(deux pièces échangées). Vérifiez les couleurs saisies.")


# ---------------------------------------------------------------------------
# Bibliothèque de commutateurs
# ---------------------------------------------------------------------------

@dataclass
class Library:
    ops: list[tuple[list[int], list[int], int]]           # (X, Y, orbite)
    table: dict[tuple[int, int, int], tuple[int, int]]    # triplet -> (longueur, setup, op)
    stats: dict = field(default_factory=dict)


_ORDER_KIND = {"center": 1, "xcenter": 1, "tcenter": 0, "oblique": 1, "midge": 2, "wing": 3, "corner": 4}


def orbit_rank(pz: Puzzle) -> dict[int, int]:
    """Ordre de résolution des orbites : centres, arêtes centrales, ailes, coins.

    Un commutateur utilisé pour une orbite peut déranger les orbites de rang
    supérieur (résolues plus tard), jamais celles déjà résolues.
    """
    orbs = [o for o in pz.orbits if not (o.fixed or o.ignored)]
    orbs.sort(key=lambda o: (_ORDER_KIND[o.kind], o.id))
    return {o.id: i for i, o in enumerate(orbs)}


def _canon(t):
    a, b, c = t
    m = min(t)
    if m == a:
        return (a, b, c)
    if m == b:
        return (b, c, a)
    return (c, a, b)


def build_library(pz: Puzzle) -> Library:
    n = pz.n
    gens = list(range(len(pz.moves)))
    perms = np.array([m.perm for m in pz.moves])
    inv = pz.inverse
    ident = np.arange(n)
    care = np.zeros(n, dtype=bool)
    for o in pz.orbits:
        if not o.ignored:
            for p in o.pieces:
                care[pz.pieces[p]] = True
    rank = orbit_rank(pz)
    BIG = 10**6
    slot_rank = np.full(n, BIG)
    for o in pz.orbits:
        if o.id in rank:
            for p in o.pieces:
                slot_rank[pz.pieces[p]] = rank[o.id]
    rank_orbit = {r: oid for oid, r in rank.items()}
    piece_of = pz.piece_of
    face = np.asarray(pz.sticker_face)
    identical = np.zeros(n, dtype=bool)
    for o in pz.orbits:
        if o.size == 1 and not o.fixed:
            for p in o.pieces:
                identical[pz.pieces[p]] = True

    # candidats X
    def same_axis(a, b):
        return pz.moves[a].axis == pz.moves[b].axis

    xs: list[list[int]] = [[a] for a in gens]
    for a in gens:
        for b in gens:
            if same_axis(a, b):
                continue
            xs.append([a, b, inv[a]])
            xs.append([a, b])
            xs.append([a, b, inv[a], inv[b]])

    inv_perms = np.array([pz.moves[i].perm for i in inv])
    best: dict[frozenset, tuple[tuple, list[int], list[int], int]] = {}
    for X in xs:
        pX = ident
        for mi in X:
            pX = perms[mi][pX]
        pXi = np.empty(n, dtype=int)
        pXi[pX] = ident
        # contenu : X puis Y puis X' puis Y'
        A = perms[:, pX]
        B = pXi[A]
        P = np.take_along_axis(inv_perms, B, axis=1)
        pmoved = (P != ident) & care[None, :]
        # un centre qui reste sur une face de même couleur n'est pas dérangé
        cmoved = (face[P] != face[None, :]) & care[None, :]
        moved = np.where(identical[None, :], cmoved, pmoved)
        rk = np.where(moved, slot_rank[None, :], BIG)
        first = rk.min(axis=1)
        in_first = pmoved & (slot_rank[None, :] == first[:, None])
        cnt = in_first.sum(axis=1)
        dirty = moved.sum(axis=1) - (moved & (slot_rank[None, :] == first[:, None])).sum(axis=1)
        ok = (first < BIG) & (cnt <= 15)
        for yi in np.nonzero(ok)[0]:
            oid = rank_orbit[int(first[yi])]
            k = pz.orbits[oid].size
            if cnt[yi] != 3 * k:
                continue
            row = P[yi]
            ms = np.nonzero(in_first[yi])[0]
            if len(set(piece_of[ms].tolist())) != 3:
                continue
            # 3-cycle pur sur l'orbite visée
            if not np.array_equal(row[row[row[ms]]], ms):
                continue
            key = frozenset((int(a), int(row[a])) for a in ms)
            score = (len(X) * 2 + 2, int(dirty[yi] > 0))
            if key not in best or best[key][0] > score:
                best[key] = (score, X, [int(gens[yi])], oid)

    ops = []
    table: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    for key, (score, X, Y, oid) in best.items():
        ln = score[0]
        idx = len(ops)
        ops.append((X, Y, oid))
        mp = dict(key)
        starts = [a for a in mp]
        cycles = set()
        for a in starts:
            cycles.add(_canon((a, mp[a], mp[mp[a]])))
        for cyc in cycles:
            # sans placement
            if cyc not in table or table[cyc][0] > ln:
                table[cyc] = (ln, -1, idx)
            # placement d'un mouvement : S C S^-1 a pour cycle S^-1(cyc)
            for s in gens:
                pinv = inv_perms[s]
                t = _canon((int(pinv[cyc[0]]), int(pinv[cyc[1]]), int(pinv[cyc[2]])))
                if t not in table or table[t][0] > ln + 2:
                    table[t] = (ln + 2, s, idx)
    stats = {"base_ops": len(ops), "table": len(table)}
    return Library(ops=ops, table=table, stats=stats)


_libs: dict[str, Library] = {}


def get_library(pz: Puzzle) -> Library:
    if pz.id in _libs:
        return _libs[pz.id]
    path = CACHE_DIR / f"{pz.id}-v{CACHE_VERSION}.pkl"
    lib = None
    if path.exists():
        try:
            with open(path, "rb") as fh:
                lib = pickle.load(fh)
        except Exception:
            lib = None
    if lib is None:
        lib = build_library(pz)
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as fh:
                pickle.dump(lib, fh)
        except OSError:
            pass
    _libs[pz.id] = lib
    return lib


# ---------------------------------------------------------------------------
# Recherche d'un 3-cycle quelconque
# ---------------------------------------------------------------------------

@dataclass
class Comm:
    setup: list[int]
    x: list[int]
    y: list[int]

    def seq(self, pz: Puzzle) -> list[int]:
        return (self.setup + self.x + self.y + pz.invert_seq(self.x) + pz.invert_seq(self.y)
                + pz.invert_seq(self.setup))


class CycleFinder:
    def __init__(self, pz: Puzzle, lib: Library):
        self.pz = pz
        self.lib = lib
        self.perms = [m.perm for m in pz.moves]
        self.cache: dict[tuple, Comm] = {}

    def _from_table(self, key, setup):
        ln, s, idx = self.lib.table[key]
        X, Y, _ = self.lib.ops[idx]
        full_setup = list(setup) + ([s] if s >= 0 else [])
        return Comm(setup=full_setup, x=list(X), y=list(Y)), ln + 2 * len(setup)

    def find(self, a: int, b: int, c: int, max_depth: int = 3) -> Comm:
        """Séquence dont l'effet est le cycle de facettes a -> b -> c (pièces rigides)."""
        key0 = (a, b, c)
        if key0 in self.cache:
            return self.cache[key0]
        table = self.lib.table
        k = _canon(key0)
        if k in table:
            res, _ = self._from_table(k, [])
            self.cache[key0] = res
            return res
        perms = self.perms
        gens = range(len(perms))
        frontier = [((a, b, c), [])]
        seen = {(a, b, c)}
        for depth in range(1, max_depth + 1):
            best = None
            nxt = []
            for (x, y, z), path in frontier:
                for m in gens:
                    p = perms[m]
                    t = (int(p[x]), int(p[y]), int(p[z]))
                    if t in seen:
                        continue
                    seen.add(t)
                    kt = _canon(t)
                    if kt in table:
                        cand, ln = self._from_table(kt, path + [m])
                        if best is None or ln < best[1]:
                            best = (cand, ln)
                    nxt.append((t, path + [m]))
            if best is not None:
                self.cache[key0] = best[0]
                return best[0]
            frontier = nxt
        raise SolveError("Aucun commutateur trouvé pour ce cycle (bibliothèque incomplète).")


# ---------------------------------------------------------------------------
# Résolution
# ---------------------------------------------------------------------------

@dataclass
class Step:
    title: str
    detail: str
    moves: list[int]
    notation: str = ""
    highlight: list[int] = field(default_factory=list)


@dataclass
class Stage:
    title: str
    detail: str
    steps: list[Step] = field(default_factory=list)


def cancel(pz: Puzzle, seq: list[int]) -> list[int]:
    """Fusionne les mouvements consécutifs d'un même axe (ils commutent)."""
    o = pz.geo.order
    out: list[int] = []
    for mi in seq:
        m = pz.moves[mi]
        # remonter la suite de mouvements du même axe
        j = len(out) - 1
        merged = False
        while j >= 0 and pz.moves[out[j]].axis == m.axis:
            q = pz.moves[out[j]]
            if (q.face, q.layer, q.middle) == (m.face, m.layer, m.middle):
                amt = (q.amount + m.amount) % o
                if amt == 0:
                    out.pop(j)
                else:
                    out[j] = next(i for i, r in enumerate(pz.moves)
                                  if (r.face, r.layer, r.middle, r.amount) == (m.face, m.layer, m.middle, amt))
                merged = True
                break
            j -= 1
        if not merged:
            out.append(mi)
    return out


def piece_name(pz: Puzzle, p: int) -> str:
    faces = [pz.geo.face_names[pz.sticker_face[s]] for s in pz.pieces[p]]
    orb = pz.orbits[pz.orbit_of_piece[p]]
    if orb.size == 1:
        return f"{orb.label.lower()} de la face {faces[0]}"
    return "-".join(faces)


def _choose_buffer(pz: Puzzle, orb: Orbit) -> int:
    v = np.array([0.35, 1.0, 0.6])
    best = None
    for p in orb.pieces:
        c = sum(pz.geo.stickers[s].center for s in pz.pieces[p]) / orb.size
        sc = float(c @ v)
        if best is None or sc > best[0]:
            best = (sc, p)
    return best[1]


class Solver:
    def __init__(self, pz: Puzzle):
        self.pz = pz
        self.lib = get_library(pz)
        self.finder = CycleFinder(pz, self.lib)
        from .algos import user_algs
        self.user = user_algs(pz)   # algorithmes de l'utilisateur, par type de pièce

    # ---- outils
    def _cost(self, a: int, b: int, c: int, orb: Orbit | None = None) -> int | None:
        """Longueur de la séquence réalisant a -> b -> c, None si absente.

        Si l'utilisateur a fourni un algorithme pour ce type de pièce, c'est lui qui compte.
        """
        if orb is not None and orb.kind in self.user:
            ln = self.user[orb.kind].cost(a, b, c)
            if ln is not None:
                return ln
        e = self.lib.table.get(_canon((a, b, c)))
        return e[0] if e else None

    def _side_effects(self, seq: list[int], target: Orbit) -> str:
        """Phrase décrivant les orbites dérangées par la séquence (résolues plus tard)."""
        pz = self.pz
        P = pz.seq_perm(seq)
        face = np.asarray(pz.sticker_face)
        hit = []
        for o in pz.orbits:
            if o.fixed or o.ignored or o.id == target.id:
                continue
            sl = [s for p in o.pieces for s in pz.pieces[p]]
            if o.size == 1:
                moved = any(face[P[s]] != face[s] for s in sl)
            else:
                moved = any(P[s] != s for s in sl)
            if moved:
                hit.append(o.label.lower())
        if not hit:
            return "Rien d'autre ne bouge."
        return ("Au passage, la séquence dérange des pièces d'une étape ultérieure (" + ", ".join(hit)
                + ") : ce n'est pas grave, elles seront résolues ensuite.")

    def _fmt(self, seq: list[int]) -> str:
        return " ".join(self.pz.names(seq))

    def _notation(self, comm: Comm) -> str:
        inner = f"[{self._fmt(comm.x)}, {self._fmt(comm.y)}]"
        if comm.setup:
            return f"[{self._fmt(comm.setup)} : {inner}]"
        return inner

    # ---- résolution d'une orbite à pièces distinctes
    def _best_distinct(self, orb: Orbit, cont: np.ndarray):
        """3-cycle qui place le plus de pièces par coup joué (None si aucun ne progresse).

        Pas d'emplacement tampon imposé : on suit les cycles de la permutation à
        partir de n'importe quelle pièce, et on retient le commutateur le plus court
        (deux pièces placées, trois quand la permutation contient un 3-cycle).
        """
        pz = self.pz
        po = pz.piece_of

        def ok(x):
            return all(cont[s] == s for s in pz.pieces[po[x]])

        best = None
        unsolved = [p for p in orb.pieces if any(cont[s] != s for s in pz.pieces[p])]
        for p in unsolved:
            a = pz.pieces[p][0]
            b = int(cont[a])
            if po[b] == p:
                continue  # pièce en place mais tournée : traitée par le repli
            cands = []
            c = int(cont[b])
            if po[c] not in (p, po[b]):
                cands.append(c)
            else:
                cands = [x for q in orb.pieces if q not in (p, po[b]) for x in pz.pieces[q]]
            for c in cands:
                ln = self._cost(a, b, c, orb)
                if ln is None:
                    continue
                before = ok(a) + ok(b) + ok(c)
                after = (int(cont[a]) == b) + (int(cont[b]) == c) + (int(cont[c]) == a)
                gain = after - before
                if gain <= 0:
                    continue
                score = (gain / ln, gain)
                if best is None or score > best[0]:
                    best = (score, (a, b, c))
        return best[1] if best else None

    def _buffer_targets(self, orb: Orbit, cont: np.ndarray, b: int):
        """Repli : cycle depuis l'emplacement tampon (pièces tournées sur place)."""
        pz = self.pz
        B = pz.pieces[b][0]
        g = orb.twist_step
        unsolved = [p for p in orb.pieces if any(cont[s] != s for s in pz.pieces[p])]
        x = int(cont[B])
        if pz.piece_of[x] != b:
            t1 = x
        else:
            others = [p for p in unsolved if p != b]
            if not others:
                raise SolveError(f"{orb.label} : pièce tampon tournée seule, état impossible.")
            t1 = pz.pieces[others[0]][0]
        p1 = int(pz.piece_of[t1])
        y = int(cont[t1])
        py = int(pz.piece_of[y])
        if py not in (b, p1) and (pz.sticker_index[y] - pz.sticker_index[t1]) % g == 0:
            t2 = y
        else:
            cand = [p for p in unsolved if p not in (b, p1)]
            if not cand:
                cand = [p for p in orb.pieces if p not in (b, p1)]
            t2 = pz.pieces[cand[0]][0]
        return B, t1, t2

    def _solve_distinct(self, orb: Orbit, cont: np.ndarray, stage: Stage, greedy: bool = True) -> np.ndarray:
        pz = self.pz
        b = _choose_buffer(pz, orb)
        guard = 6 * len(orb.pieces) + 10
        for _ in range(guard):
            if all(cont[s] == s for p in orb.pieces for s in pz.pieces[p]):
                return cont
            tri = self._best_distinct(orb, cont) if greedy else None
            if tri is None:
                tri = self._buffer_targets(orb, cont, b)
            a, t1, t2 = tri
            ua = self.user.get(orb.kind)
            hit = ua.lookup(a, t1, t2) if ua else None
            if hit is not None:
                setup, ai = hit
                alg = ua.algs[ai]
                seq = setup + alg.seq + pz.invert_seq(setup)
                how = (f"{alg.name} : {self._fmt(alg.seq)}." if not setup else
                       f"Placement {self._fmt(setup)}, puis {alg.name[0].lower() + alg.name[1:]} "
                       f"({self._fmt(alg.seq)}), puis placement à l'envers {self._fmt(pz.invert_seq(setup))}.")
                notation = ""
            else:
                comm = self.finder.find(a, t1, t2)
                seq = cancel(pz, comm.seq(pz))
                how = ""
                notation = self._notation(comm)
            pa, p1, p2 = (int(pz.piece_of[x]) for x in tri)
            placed = (int(cont[a]) == t1) + (int(cont[t1]) == t2) + (int(cont[t2]) == a)
            what = {0: "Prépare la suite : aucune pièce n'est encore placée.",
                    1: "Une pièce rejoint sa place.",
                    2: "Deux pièces rejoignent leur place.",
                    3: "Les trois pièces rejoignent leur place."}[placed]
            stage.steps.append(Step(
                title=f"3-cycle {piece_name(pz, pa)} → {piece_name(pz, p1)} → {piece_name(pz, p2)}",
                detail=" ".join(x for x in (what, how, self._side_effects(seq, orb)) if x),
                moves=seq, notation=notation,
                highlight=pz.pieces[pa] + pz.pieces[p1] + pz.pieces[p2]))
            cont = pz.apply_seq(cont, seq)
        raise SolveError(f"{orb.label} : la résolution ne converge pas.")

    # ---- résolution d'une orbite à pièces identiques (centres)
    def _solve_colors(self, orb: Orbit, cont: np.ndarray, home: np.ndarray, stage: Stage,
                      greedy: bool = True) -> np.ndarray:
        pz = self.pz
        b = _choose_buffer(pz, orb)
        B = pz.pieces[b][0]
        slots = [pz.pieces[p][0] for p in orb.pieces]
        col = pz.sticker_face  # couleur d'une facette d'origine = sa face

        def color(s):
            return int(col[cont[s]])

        def need(s):
            return int(home[s])

        guard = 3 * len(slots) + 10
        for _ in range(guard):
            bad = [s for s in slots if color(s) != need(s)]
            if not bad:
                return cont
            # choix glouton : le 3-cycle qui place le plus de centres par coup joué
            best = None
            for a in (bad if greedy else []):
                ca = color(a)
                for b in bad:
                    if b == a or need(b) != ca:
                        continue
                    cb = color(b)
                    for c in bad:
                        if c in (a, b) or pz.piece_of[c] in (pz.piece_of[a], pz.piece_of[b]):
                            continue
                        gain = 1 + (cb == need(c)) + (color(c) == need(a))
                        ln = self._cost(a, b, c)
                        if ln is None:
                            continue
                        score = (gain / ln, gain)
                        if best is None or score > best[0]:
                            best = (score, (a, b, c))
            if best is not None:
                A, t1, t2 = best[1]
            elif color(B) != need(B):
                A = B
                c = color(B)
                c1 = [s for s in bad if s != B and need(s) == c]
                c1.sort(key=lambda s: color(s) != need(B))
                t1 = c1[0]
                if color(t1) == need(B):
                    c2 = [s for s in slots if s not in (B, t1) and color(s) == need(B)]
                    c2.sort(key=lambda s: color(s) != need(s))
                else:
                    c2 = [s for s in bad if s not in (B, t1) and need(s) == color(t1)]
                    c2.sort(key=lambda s: color(s) != need(B))
                t2 = c2[0]
            else:
                A = B
                c1 = [s for s in bad if color(s) != need(B)]
                t1 = c1[0]
                c2 = [s for s in bad if s not in (B, t1) and need(s) == color(t1)]
                t2 = c2[0]
            comm = self.finder.find(A, t1, t2)
            seq = cancel(pz, comm.seq(pz))
            p1, p2 = int(pz.piece_of[t1]), int(pz.piece_of[t2])
            stage.steps.append(Step(
                title=f"3-cycle de centres : face {pz.geo.face_names[pz.sticker_face[A]]} → "
                      f"{pz.geo.face_names[pz.sticker_face[t1]]} → {pz.geo.face_names[pz.sticker_face[t2]]}",
                detail="Les centres d'une même couleur sont interchangeables : on les amène sur leur face. "
                       + self._side_effects(seq, orb),
                moves=seq, notation=self._notation(comm), highlight=[A, t1, t2]))
            cont = pz.apply_seq(cont, seq)
        raise SolveError(f"{orb.label} : la résolution ne converge pas.")

    def is_solved(self, st: State, cont: np.ndarray) -> bool:
        pz = self.pz
        for orb in pz.orbits:
            if orb.fixed or orb.ignored:
                continue
            for p in orb.pieces:
                for s in pz.pieces[p]:
                    if orb.id in st.color_mode:
                        if pz.sticker_face[cont[s]] != pz.sticker_face[s]:
                            return False
                    elif cont[s] != s:
                        return False
        return True

    def solve_state(self, st: State) -> list[Stage]:
        pz = self.pz
        check_orientation(pz, st)
        cont = st.cont.copy()
        stages: list[Stage] = []
        fix = parity_fix(pz, st)
        if fix:
            stages.append(Stage(
                title="Correction de parité",
                detail="Une orbite a une permutation impaire, impossible à corriger avec des 3-cycles. "
                       "Un quart de tour la rend paire avant de commencer.",
                steps=[Step(title="Parité", detail="Mouvement simple qui change la parité.",
                            moves=fix, notation=self._fmt(fix))]))
            cont = pz.apply_seq(cont, fix)
        home = np.array(pz.sticker_face)  # couleur attendue = face (après changement de repère)

        rank = orbit_rank(pz)
        orbs = sorted((o for o in pz.orbits if o.id in rank), key=lambda o: rank[o.id])
        for orb in orbs:
            # deux stratégies (choix glouton, emplacement tampon) : on garde la plus courte
            best = None
            for greedy in (True, False):
                stage = Stage(title=orb.label, detail=_STAGE_TEXT.get(orb.kind, ""))
                try:
                    if orb.id in st.color_mode:
                        out = self._solve_colors(orb, cont, home, stage, greedy)
                    else:
                        out = self._solve_distinct(orb, cont, stage, greedy)
                except SolveError:
                    if not greedy and best is None:
                        raise
                    continue
                ln = sum(len(sp.moves) for sp in stage.steps)
                if best is None or ln < best[0]:
                    best = (ln, stage, out)
            _, stage, cont = best
            if stage.steps:
                stages.append(stage)
        if not self.is_solved(st, cont):
            raise SolveError("La vérification finale a échoué.")
        return stages


_STAGE_TEXT = {
    "xcenter": "On regroupe les centres par couleur. Chaque étape est un commutateur qui échange "
               "trois centres sans rien déranger d'autre.",
    "center": "On regroupe les centres par couleur.",
    "tcenter": "Même principe pour les centres placés au milieu des bords de chaque face.",
    "oblique": "Centres hors diagonale : même principe, par 3-cycles.",
    "wing": "On apparie les arêtes : chaque commutateur place deux ailes à la fois.",
    "midge": "Arêtes : chaque commutateur place deux arêtes à la fois, orientation comprise.",
    "corner": "Coins : chaque commutateur place deux coins à la fois, orientation comprise.",
}


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def solve_colors(pz: Puzzle, colors: list[int]) -> dict:
    """Résout un puzzle décrit par ses couleurs (indice de palette par facette, -1 = inconnu)."""
    frames = frames_for(pz, colors)
    if not frames:
        raise SolveError("Impossible de déduire le schéma de couleurs à partir des coins.")
    from .diagnose import diagnose, repairs_error

    solver = Solver(pz)
    first_err = None
    for fc in frames:
        try:
            st = read_state(pz, colors, fc)
            repairs = diagnose(pz, colors, fc)
            if repairs:
                raise repairs_error(repairs)
            stages = solver.solve_state(st)
        except SolveError as e:
            # le premier repère est le plus probable : c'est son diagnostic qu'on rapporte
            first_err = first_err or e
            continue
        return _result(pz, stages, fc)
    raise first_err or SolveError("Aucun repère valable.")


def _result(pz: Puzzle, stages: list[Stage], fc: list[int]) -> dict:
    total = []
    for sg in stages:
        for sp in sg.steps:
            total.extend(sp.moves)
    return {
        "face_colors": fc,
        "move_count": len(total),
        "moves": pz.names(total),
        "stages": [{
            "title": sg.title, "detail": sg.detail,
            "steps": [{"title": sp.title, "detail": sp.detail, "notation": sp.notation,
                       "moves": pz.names(sp.moves), "highlight": sp.highlight} for sp in sg.steps],
        } for sg in stages],
    }
