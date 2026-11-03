"""Algorithmes choisis par l'utilisateur, utilisés en priorité par le solveur.

Pour une orbite donnée, le solveur n'emploie plus les commutateurs de la
bibliothèque mais ces algorithmes, précédés d'un placement (quelques coups qui
amènent les pièces dans la position de l'algorithme) et suivis de son inverse.
La bibliothèque ne sert plus que de secours si aucun placement court n'existe.
"""

from __future__ import annotations

from dataclasses import dataclass

from .puzzle import Puzzle

# puzzle -> type de pièce -> algorithmes ; chaque algorithme est découpé en
# temps nommés avec les mots de l'utilisateur.
USER_ALGS = {
    "3x3": {
        "midge": [
            {"name": "Algorithme des arêtes, Up (l'arête de devant part à gauche)",
             "parts": [("Front x2", "F2"), ("Up", "U"), ("Centre monte", "M'"), ("Up x2", "U2"),
                       ("Centre descend", "M"), ("Up, même sens", "U"), ("Front x2", "F2")]},
            {"name": "Algorithme des arêtes, Up' (l'arête de devant part à droite)",
             "parts": [("Front x2", "F2"), ("Up'", "U'"), ("Centre monte", "M'"), ("Up x2", "U2"),
                       ("Centre descend", "M"), ("Up', même sens", "U'"), ("Front x2", "F2")]},
        ],
    },
}

MAX_SETUP = 5


@dataclass
class UserAlg:
    name: str
    parts: list[tuple[str, list[int]]]
    seq: list[int]


class AlgTable:
    """Pour chaque 3-cycle de facettes : le placement le plus court et l'algorithme à jouer."""

    def __init__(self, pz: Puzzle, kind: str, algs: list[UserAlg]):
        self.pz = pz
        self.kind = kind
        self.algs = algs
        self.table: dict[tuple, tuple[list[int], int]] = {}
        from .solver import _canon  # import local : solver importe ce module

        frontier = []
        for i, alg in enumerate(algs):
            P = pz.seq_perm(alg.seq)
            moved = [s for s in range(pz.n) if P[s] != s]
            for a in moved:
                cyc = _canon((a, int(P[a]), int(P[P[a]])))
                if cyc not in self.table:
                    self.table[cyc] = ([], i)
                    frontier.append(cyc)
        inv_perms = [pz.moves[pz.inverse[m]].perm for m in range(len(pz.moves))]
        # placement S : la séquence S + algorithme + S' réalise S^-1(cycle)
        for _ in range(MAX_SETUP):
            nxt = []
            for cyc in frontier:
                setup, i = self.table[cyc]
                for m in pz.frame_moves:  # placements avec les faces extérieures seulement
                    if setup and pz.moves[setup[0]].axis == pz.moves[m].axis:
                        continue
                    p = inv_perms[m]
                    t = _canon((int(p[cyc[0]]), int(p[cyc[1]]), int(p[cyc[2]])))
                    if t not in self.table:
                        self.table[t] = ([m] + setup, i)
                        nxt.append(t)
            frontier = nxt

    def lookup(self, a: int, b: int, c: int):
        from .solver import _canon
        return self.table.get(_canon((a, b, c)))

    def cost(self, a: int, b: int, c: int) -> int | None:
        e = self.lookup(a, b, c)
        if e is None:
            return None
        setup, i = e
        return 2 * len(setup) + len(self.algs[i].seq)


def user_algs(pz: Puzzle) -> dict[str, AlgTable]:
    """Tables des algorithmes de l'utilisateur pour ce puzzle, par type de pièce."""
    out = {}
    for kind, algs in USER_ALGS.get(pz.id, {}).items():
        index = {m.name: i for i, m in enumerate(pz.moves)}
        parsed = []
        for a in algs:
            parts = []
            for label, text in a["parts"]:
                parts.append((label, [index[t["name"]] for t in pz.parse(text)]))
            parsed.append(UserAlg(a["name"], parts, [m for _, ms in parts for m in ms]))
        out[kind] = AlgTable(pz, kind, parsed)
    return out
