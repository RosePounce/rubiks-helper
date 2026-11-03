"""Aide-mémoire : les quelques séquences à connaître pour résoudre chaque puzzle.

Pour chaque type de pièce, on retient dans la bibliothèque de commutateurs les
séquences les plus courtes qui échangent trois pièces sans rien déranger
d'autre (ou, à défaut, en ne dérangeant que des pièces résolues plus tard),
plus un exemple de placement. Les séquences sont données en entier, découpées
en quatre temps : préparation, tour, préparation à l'envers, tour à l'envers.
"""

from __future__ import annotations

import numpy as np

from .extras import palette
from .puzzle import Orbit, Puzzle
from .solver import Library, orbit_rank

_PIECE = {
    "corner": "coin", "midge": "arête", "wing": "aile", "center": "centre",
    "xcenter": "centre X", "tcenter": "centre T", "oblique": "centre oblique",
}
# nombre de faces voisines utiles pour situer une pièce sur sa face
_SIDES = {"wing": 1, "tcenter": 1, "xcenter": 2, "oblique": 2}

# orbites à position fixe, orientation seule (pointes et coins du Pyraminx)
_TWIST_TITLE = {"corner": "Coins", "tip": "Pointes"}
_TWIST_GOAL = {
    "corner": "Orienter les quatre coins : chacun est déjà à sa place, il suffit de le tourner.",
    "tip": "Orienter les quatre pointes.",
}
_TWIST_HOW = {
    "corner": "Un coin ne change jamais de place ; on le tourne d'un tiers de tour (le tour de son "
              "sommet) jusqu'à la bonne orientation. On oriente les coins d'abord : les séquences "
              "d'arêtes qui suivent les laisseront en place.",
    "tip": "Chaque pointe tourne toute seule, sans rien déranger : on la met dans le bon sens d'un "
           "simple tour. À faire quand on veut, en général à la fin.",
}

_GOAL = {
    "corner": "Placer les coins, orientation comprise.",
    "midge": "Placer les arêtes centrales, orientation comprise.",
    "wing": "Placer les ailes : chacune a une seule bonne place, à côté de sa jumelle.",
    "center": "Regrouper les centres par couleur.",
    "xcenter": "Regrouper les centres X (coins du centre de face) par couleur. "
               "Les centres d'une même couleur sont interchangeables.",
    "tcenter": "Regrouper les centres T (bords du centre de face) par couleur. "
               "Les centres d'une même couleur sont interchangeables.",
    "oblique": "Regrouper les centres obliques par couleur. "
               "Les centres d'une même couleur sont interchangeables.",
}

_VIEW = np.array([0.35, 1.0, 0.6])   # direction de la vue par défaut


def _cname(pal, f: int) -> str:
    return pal[f]["name"].lower()


def _piece_label(pz: Puzzle, p: int, pal) -> str:
    orb = pz.orbits[pz.orbit_of_piece[p]]
    faces = [int(pz.sticker_face[s]) for s in pz.pieces[p]]
    label = _PIECE.get(orb.kind, "pièce") + " " + " / ".join(_cname(pal, f) for f in faces)
    n = _SIDES.get(orb.kind, 0)
    if n:
        c = sum(pz.geo.stickers[s].center for s in pz.pieces[p])
        others = [g for g in range(len(pz.geo.normals)) if g not in faces]
        others.sort(key=lambda g: -float(pz.geo.normals[g] @ c))
        label += ", côté " + " / ".join(_cname(pal, g) for g in others[:n])
    return label


def _visibility(pz: Puzzle, pieces) -> float:
    return sum(float(sum(pz.geo.stickers[s].center for s in pz.pieces[p]) @ _VIEW) for p in pieces)


def _disturbed(pz: Puzzle, P: np.ndarray, target: Orbit) -> list[str]:
    face = np.asarray(pz.sticker_face)
    hit = []
    for o in pz.orbits:
        if o.fixed or o.ignored or o.id == target.id:
            continue
        sl = [s for p in o.pieces for s in pz.pieces[p]]
        moved = (any(face[P[s]] != face[s] for s in sl) if o.size == 1
                 else any(P[s] != s for s in sl))
        if moved:
            hit.append(o.label[0].lower() + o.label[1:])
    return hit


def _cycle_pieces(pz: Puzzle, P: np.ndarray, orb: Orbit) -> list[int]:
    """Pièces de l'orbite déplacées, dans l'ordre du cycle (A va en B, B en C)."""
    moved = [p for p in orb.pieces if P[pz.pieces[p][0]] != pz.pieces[p][0]]
    if len(moved) != 3:
        return moved
    a = moved[0]
    b = int(pz.piece_of[P[pz.pieces[a][0]]])
    c = int(pz.piece_of[P[pz.pieces[b][0]]])
    return [a, b, c]


def _example(pz: Puzzle, orb: Orbit, setup: list[int], X: list[int], Y: list[int], pal) -> dict:
    parts = [
        ("x", "Préparation", X),
        ("y", "Tour", Y),
        ("x", "Préparation à l'envers", pz.invert_seq(X)),
        ("y", "Tour à l'envers", pz.invert_seq(Y)),
    ]
    return _example_parts(pz, orb, setup, parts, pal)


def _example_parts(pz: Puzzle, orb: Orbit, setup: list[int], parts: list, pal) -> dict:
    """Exemple affichable : temps nommés (rôle, libellé, coups), entourés du placement éventuel."""
    allp = []
    if setup:
        allp.append(("placement", "Placement", setup))
    allp += parts
    if setup:
        allp.append(("placement", "Placement à l'envers", pz.invert_seq(setup)))
    seq = [m for _, _, ms in allp for m in ms]
    P = pz.seq_perm(seq)
    cyc = _cycle_pieces(pz, P, orb)
    names = [_piece_label(pz, p, pal) for p in cyc]
    if len(names) == 3:
        effect = (f"Le {names[0]} va à la place du {names[1]}, qui va à la place du {names[2]}, "
                  f"qui va à la place du premier.")
        effect = effect.replace("Le aile", "L'aile").replace("Le arête", "L'arête") \
            .replace("du aile", "de l'aile").replace("du arête", "de l'arête")
    else:
        effect = "Échange trois pièces."
    hit = _disturbed(pz, P, orb)
    side = ("Rien d'autre ne bouge." if not hit else
            "Dérange aussi : " + ", ".join(hit) + " (à résoudre après).")
    return {
        "parts": [{"role": r, "label": lbl, "moves": pz.names(ms)} for r, lbl, ms in allp],
        "moves": pz.names(seq),
        "effect": effect,
        "side": side,
        "highlight": [s for p in cyc for s in pz.pieces[p]],
        "focus": (lambda v: (v / np.linalg.norm(v)).round(4).tolist())(
            sum(pz.geo.stickers[s].center for p in cyc for s in pz.pieces[p])),
    }


def _user_examples(pz: Puzzle, orb: Orbit, table, pal) -> list[dict]:
    """Algorithmes de l'utilisateur, puis un exemple avec placement."""
    out = []
    for alg in table.algs:
        parts = [("y" if i % 2 else "x", lbl, ms) for i, (lbl, ms) in enumerate(alg.parts)]
        ex = _example_parts(pz, orb, [], parts, pal)
        ex["title"] = alg.name
        out.append(ex)
    alg = table.algs[0]
    ref = sorted(_cycle_pieces(pz, pz.seq_perm(alg.seq), orb))
    for m in pz.frame_moves:
        if pz.moves[m].axis in (pz.moves[alg.seq[0]].axis, pz.moves[alg.seq[1]].axis):
            continue
        cyc = _cycle_pieces(pz, pz.seq_perm([m] + alg.seq + [pz.inverse[m]]), orb)
        if len(cyc) == 3 and sorted(cyc) != ref:
            parts = [("y" if i % 2 else "x", lbl, ms) for i, (lbl, ms) in enumerate(alg.parts)]
            ex = _example_parts(pz, orb, [m], parts, pal)
            ex["title"] = "Avec placement"
            out.append(ex)
            break
    return out


def _pick_ops(pz: Puzzle, lib: Library, orb: Orbit, k: int = 2):
    """Les k séquences les plus simples de l'orbite, de formes différentes si possible."""
    cands = [(X, Y) for X, Y, oid in lib.ops if oid == orb.id]
    buckets: dict[int, list] = {}
    for X, Y in cands:
        buckets.setdefault(len(X), []).append((X, Y))
    scored = []
    for X, Y in (t for b in buckets.values() for t in b[:150]):  # échantillon de chaque forme
        seq = X + Y + pz.invert_seq(X) + pz.invert_seq(Y)
        P = pz.seq_perm(seq)
        cyc = _cycle_pieces(pz, P, orb)
        if len(cyc) != 3:
            continue
        dirty = len(_disturbed(pz, P, orb))
        scored.append(((dirty, len(seq), -_visibility(pz, cyc)), X, Y))
    scored.sort(key=lambda t: t[0])
    cands = scored
    out, shapes = [], set()
    for score, X, Y in cands:
        if len(X) in shapes:
            continue
        shapes.add(len(X))
        out.append((X, Y))
        if len(out) == k:
            break
    return out


def _setup_example(pz: Puzzle, lib: Library, orb: Orbit, base) -> tuple | None:
    """Un exemple de placement : un mouvement amène une pièce dans la position de la séquence apprise."""
    if base is None:
        return None
    X, Y = base
    ref = sorted(_cycle_pieces(pz, pz.seq_perm(X + Y + pz.invert_seq(X) + pz.invert_seq(Y)), orb))
    for s in pz.frame_moves:
        P = pz.seq_perm([s] + X + Y + pz.invert_seq(X) + pz.invert_seq(Y) + [pz.inverse[s]])
        cyc = _cycle_pieces(pz, P, orb)
        if len(cyc) == 3 and sorted(cyc) != ref and pz.moves[s].axis not in (pz.moves[X[0]].axis, pz.moves[Y[0]].axis):
            return [s], X, Y
    return None


def build_cheatsheet(pz: Puzzle, lib: Library) -> dict:
    pal = palette(pz)
    cube = pz.geo.kind == "cube"
    rank = orbit_rank(pz)
    orbs = sorted((o for o in pz.orbits if o.id in rank), key=lambda o: rank[o.id])

    intro = [
        "Toute la résolution repose sur une seule idée : une séquence qui échange trois pièces "
        "en laissant tout le reste en place. Elle se construit toujours en quatre temps :",
        "1. Préparation : quelques coups qui sortent une pièce d'une couche (sans toucher au reste "
        "de cette couche).",
        "2. Tour : on tourne cette couche, ce qui amène une autre pièce à la place libérée.",
        "3. Préparation à l'envers : on rejoue la préparation en sens inverse (dernier coup en premier, "
        "chaque coup dans l'autre sens).",
        "4. Tour à l'envers : on défait le tour.",
        "Si les trois pièces à échanger ne sont pas exactement dans la position de la séquence apprise, "
        "on les y amène d'abord par un ou deux coups de placement, on joue la séquence, puis on défait "
        "le placement.",
    ]
    def _twist(o: Orbit) -> bool:
        return len(o.pieces) == 1 and o.size > 1

    # libellés d'ordre : les orbites d'orientation (coins/pointes du Pyraminx) sont regroupées
    labels, seen_twist = [], set()
    for o in orbs:
        if _twist(o):
            if o.kind in seen_twist:
                continue
            seen_twist.add(o.kind)
            labels.append(_TWIST_TITLE[o.kind])
        else:
            labels.append(o.label)
    order = "Ordre de résolution : " + ", ".join(l[0].lower() + l[1:] for l in labels) + "."

    sections = []
    from .algos import user_algs
    user = user_algs(pz)
    twist_done = set()
    for orb in orbs:
        if _twist(orb):
            if orb.kind in twist_done:
                continue
            twist_done.add(orb.kind)
            sections.append({
                "title": _TWIST_TITLE.get(orb.kind, orb.label),
                "goal": _TWIST_GOAL.get(orb.kind, ""),
                "how": _TWIST_HOW.get(orb.kind, ""),
                "examples": [],
            })
            continue
        if orb.kind in user:
            sections.append({
                "title": orb.label,
                "goal": _GOAL.get(orb.kind, ""),
                "how": "Le guide utilise votre algorithme : il échange trois arêtes du haut. Pour d'autres "
                       "arêtes, des coups de placement (faces extérieures seulement) les amènent en haut, "
                       "puis on les défait après l'algorithme.",
                "examples": _user_examples(pz, orb, user[orb.kind], pal),
            })
            continue
        ops = _pick_ops(pz, lib, orb)
        examples = [_example(pz, orb, [], X, Y, pal) for X, Y in ops]
        setup = _setup_example(pz, lib, orb, ops[0] if ops else None)
        if setup:
            ex = _example(pz, orb, *setup, pal)
            ex["title"] = "Avec placement"
            examples.append(ex)
        for i, ex in enumerate(examples):
            ex.setdefault("title", f"Séquence {i + 1}")
        sections.append({
            "title": orb.label,
            "goal": _GOAL.get(orb.kind, ""),
            "how": ("Chaque séquence place deux pièces : celle qui va à sa place, puis celle qui "
                    "occupait cette place. Enchaînez-les jusqu'à ce que l'étape soit finie.")
            if orb.size > 1 else
            ("Choisissez trois centres dont au moins un ira sur sa face ; avec un peu de choix, "
             "une même séquence en place deux ou trois."),
            "examples": examples,
        })

    tips = []
    if cube:
        tips.append({
            "title": "Deux pièces échangées seules (parité)",
            "text": "Une séquence échange toujours trois pièces : s'il ne reste que deux pièces à "
                    "échanger, faites d'abord un quart de tour d'une tranche qui contient ce type de "
                    "pièce (une face extérieure pour les coins et les arêtes centrales, la tranche "
                    "intérieure correspondante pour les ailes), puis reprenez : les pièces dérangées se "
                    "replacent avec les mêmes séquences. Le guide fait ce quart de tour dès le début.",
        })
    else:
        turn = {3: "tiers", 5: "cinquièmes"}.get(pz.geo.order, "fractions")
        tips.append({
            "title": "Pas de parité",
            "text": f"Toutes les rotations sont des {turn} de tour : il ne reste jamais deux "
                    "pièces échangées seules. Si cela arrive, le puzzle a été mal remonté.",
        })
    tips.append({
        "title": "Pièce à sa place mais tournée",
        "text": "Faites-la participer à un échange : une première séquence l'envoie ailleurs, une "
                "seconde la ramène dans le bon sens. Deux pièces tournées en sens contraire se "
                "corrigent ensemble de cette façon.",
    })
    tips.append({
        "title": "Lire une séquence à l'envers",
        "text": ("Inverser R U' donne U R' : on part du dernier coup et on change le sens de chacun ; "
                 "un demi-tour R2 reste R2." if cube else
                 "Inverser R U' donne U R' : on part du dernier coup et on change le sens de chacun."
                 if pz.geo.order == 3 else
                 "Inverser R U2' donne U2 R' : on part du dernier coup et on change le sens de chacun "
                 "(R devient R', R2 devient R2')."),
    })
    return {"title": f"Aide-mémoire : {pz.label}", "intro": intro, "order": order,
            "sections": sections, "tips": tips}
