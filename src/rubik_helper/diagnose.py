"""Diagnostic d'un puzzle mal remonté.

Après un démontage (pièces tombées), un coin peut être remis tourné, ou deux
pièces échangées. L'état n'est alors plus atteignable par des mouvements :
le solveur doit dire quelles pièces posent problème et comment les remettre.

Deux invariants sont contrôlés pour chaque orbite à pièces distinctes :
  - torsion : la somme des orientations doit être nulle (modulo 3 pour les
    coins, modulo 2 pour les arêtes) ;
  - parité : la permutation des pièces doit pouvoir être atteinte par les
    mouvements (sur un Megaminx ou un Gigaminx, toutes les permutations
    doivent être paires).

Une seule pièce tournée ne se repère pas toujours de façon certaine :
tourner n'importe quel coin d'un tiers de tour rend l'état valable. On
privilégie donc les pièces « suspectes » : à leur place mais tournées.
"""

from __future__ import annotations

import math

import numpy as np

from .extras import palette
from .puzzle import Orbit, Puzzle
from .solver import SolveError, State, _parity, _piece_perm, read_state

# mot, pluriel, article défini, accord féminin, verbe de correction
_KIND_NAMES = {
    "corner": ("coin", "coins", "Le coin", False, "tournez-le sur place"),
    "midge": ("arête", "arêtes", "L'arête", True, "retournez-la"),
    "wing": ("aile", "ailes", "L'aile", True, "retournez-la"),
}
_PREFERENCE = {"corner": 0, "midge": 1, "wing": 2}


def _names(kind: str) -> tuple[str, str, str, bool, str]:
    return _KIND_NAMES.get(kind, ("pièce", "pièces", "La pièce", True, "tournez-la"))


def _agree(word: str, fem: bool, plural: bool) -> str:
    """Accorde un participe : tourné, tournée, tournés, tournées."""
    return word + ("e" if fem else "") + ("s" if plural else "")


def _twist_modulus(pz: Puzzle, orb: Orbit) -> int:
    """Les mouvements ne changent la torsion totale que par multiples de ce nombre."""
    k = orb.size
    h = k
    for mi in pz.frame_moves:
        perm = pz.moves[mi].perm
        tot = sum(int(pz.sticker_index[perm[pz.pieces[p][0]]]) for p in orb.pieces)
        h = math.gcd(h, tot % k)
    return h or k


def _piece_text(pz: Puzzle, p: int, colors, pal) -> str:
    faces = "-".join(pz.geo.face_names[pz.sticker_face[s]] for s in pz.pieces[p])
    cols = "-".join(pal[colors[s]]["name"].lower() for s in pz.pieces[p])
    return f"{faces} ({cols})"


def _color_name(pal, c) -> str:
    return pal[c]["name"].lower()


def _where(pz: Puzzle, st: State, p: int, pal, fixed_centers: bool) -> str:
    """Emplacement d'une pièce décrit par les couleurs des faces qui l'entourent."""
    faces = [int(pz.sticker_face[s]) for s in pz.pieces[p]]
    names = [_color_name(pal, st.face_color[f]) for f in faces]
    if len(names) == 1:
        txt = f"sur la face {names[0]}"
    else:
        liste = ", ".join(names[:-1]) + " et " + names[-1]
        txt = (f"entre les centres {liste}" if fixed_centers else f"à la jonction des faces {liste}")
    orb = pz.orbits[pz.orbit_of_piece[p]]
    same = [q for q in orb.pieces
            if sorted(int(pz.sticker_face[s]) for s in pz.pieces[q]) == sorted(faces)]
    if len(same) > 1:
        # plusieurs pièces entre les mêmes faces (ailes) : préciser le côté
        c = sum(pz.geo.stickers[s].center for s in pz.pieces[p])
        others = [g for g in range(len(pz.geo.normals)) if g not in faces]
        g = max(others, key=lambda g: float(pz.geo.normals[g] @ c))
        txt += f", côté {_color_name(pal, st.face_color[g])}"
    return txt


def _item(pz: Puzzle, st: State, p: int, now: list[int], target: list[int], piece_colors: list[int],
          instruction: str) -> dict:
    """Description concrète d'une pièce à corriger, pour l'affichage."""
    pal = palette(pz)
    fixed = any(o.fixed and not o.ignored for o in pz.orbits)
    orb = pz.orbits[pz.orbit_of_piece[p]]
    one = _names(orb.kind)[0]
    label = f"{one.capitalize()} " + " / ".join(_color_name(pal, c) for c in piece_colors)
    faces = [{"face": int(st.face_color[pz.sticker_face[s]]), "now": int(now[s]), "target": int(target[s])}
             for s in pz.pieces[p]]
    focus = sum(pz.geo.stickers[s].center for s in pz.pieces[p])
    focus = (focus / np.linalg.norm(focus)).round(4).tolist()
    where = _where(pz, st, p, pal, fixed)
    text = f"{label}, {where} : {instruction[0].lower()}{instruction[1:]}"
    return {"label": label, "where": where, "instruction": instruction, "faces": faces,
            "stickers": list(pz.pieces[p]), "focus": focus, "text": text}


def _rank_pieces(pz: Puzzle, pieces: list[int]) -> list[int]:
    """Pièces les plus faciles à atteindre d'abord (côté face U et avant)."""
    v = np.array([0.35, 1.0, 0.6])

    def score(p):
        c = sum(pz.geo.stickers[s].center for s in pz.pieces[p])
        return -float(c @ v)

    return sorted(pieces, key=score)


# ---------------------------------------------------------------------------
# Torsion
# ---------------------------------------------------------------------------

def _twist_problem(pz: Puzzle, st: State, colors: list[int], orb: Orbit) -> dict | None:
    k = orb.size
    if k == 1:
        return None
    h = _twist_modulus(pz, orb)
    if h == 1:
        return None
    r = {}
    home = {}
    for p in orb.pieces:
        c = int(st.cont[pz.pieces[p][0]])
        r[p] = int(pz.sticker_index[c]) % k
        home[p] = int(pz.piece_of[c])
    tot = sum(r.values()) % h
    if tot == 0:
        return None

    # pièces à leur place mais tournées : coupables les plus probables
    suspects = [p for p in orb.pieces if home[p] == p and r[p] != 0]
    fix: dict[int, int] = {}
    certain = False
    if suspects and sum(r[p] for p in suspects) % h == tot:
        fix = {p: r[p] for p in suspects}
        certain = True
    else:
        single = [p for p in suspects if r[p] % h == tot]
        if single:
            fix = {single[0]: r[single[0]]}
            certain = True
        else:
            pool = suspects or orb.pieces
            p = _rank_pieces(pz, pool)[0]
            fix = {p: tot}

    pal = palette(pz)
    one, many, article, fem, verb = _names(orb.kind)
    new = list(colors)
    for p, d in fix.items():
        st_ = pz.pieces[p]
        for j, s in enumerate(st_):
            new[s] = colors[st_[(j - d) % k]]
    items = [_item(pz, st, p, colors, new, [colors[s] for s in pz.pieces[p]],
                   f"{verb[0].upper()}{verb[1:]} jusqu'à ce que chaque face montre la couleur attendue.")
             for p in fix]
    un = "une" if fem else "un"
    amount = "d'un tiers de tour" if k == 3 else ""
    quel = "quelle" if fem else "quel"
    if certain:
        pl = len(fix) > 1
        head = (f"{orb.label} : {len(fix)} {many if pl else one} {_agree('remonté', fem, pl)} de travers "
                f"({'à leur place mais ' + _agree('tourné', fem, True) if pl else 'à sa place mais ' + _agree('tourné', fem, False)}).")
    else:
        head = (f"{orb.label} : {un} {one} a été {_agree('remonté', fem, False)} "
                f"{_agree('tourné' if k == 3 else 'retourné', fem, False)}, ce qui rend le puzzle insoluble. "
                f"Impossible de savoir {'laquelle' if fem else 'lequel'} : "
                f"{'tourner' if k == 3 else 'retourner'} n'importe {quel} {one} "
                f"{amount} corrige l'état. Le plus simple : « Résoudre quand même », "
                f"la pièce à corriger apparaîtra d'elle-même à la fin. Sinon, proposition :").replace("  ", " ")
    stickers = [s for p in fix for s in pz.pieces[p]]
    suspects_st = [s for p in suspects for s in pz.pieces[p]]
    return {"kind": "twist", "orbit": orb.label, "title": head, "items": items,
            "actions": [it["text"] for it in items],
            "stickers": stickers, "suspects": suspects_st if not certain else stickers,
            "changes": [[s, new[s]] for s in stickers if new[s] != colors[s]], "colors": new}


# ---------------------------------------------------------------------------
# Parité
# ---------------------------------------------------------------------------

def _span(vectors: list[int]) -> set[int]:
    span = {0}
    for v in vectors:
        span |= {x ^ v for x in span}
    return span


def _parity_problem(pz: Puzzle, st: State, colors: list[int]) -> dict | None:
    orbs = [o for o in pz.orbits if not (o.fixed or o.ignored or o.id in st.color_mode)]
    if not orbs:
        return None
    ident = np.arange(pz.n)
    vecs = []
    for mi in pz.frame_moves:
        m = pz.moves[mi]
        if m.amount != 1:
            continue
        cont = pz.apply(ident, m.perm)
        v = 0
        for i, o in enumerate(orbs):
            v |= _parity(_piece_perm(pz, o, cont)) << i
        vecs.append(v)
    span = _span(vecs)
    target = 0
    for i, o in enumerate(orbs):
        target |= _parity(_piece_perm(pz, o, st.cont)) << i
    if target in span:
        return None
    odd = [i for i in range(len(orbs)) if target >> i & 1]
    odd.sort(key=lambda i: (_PREFERENCE.get(orbs[i].kind, 9), i))
    pick = next((i for i in odd if (target ^ (1 << i)) in span), odd[0])
    orb = orbs[pick]
    mapping = _piece_perm(pz, orb, st.cont)    # position -> pièce d'origine
    # échange idéal : deux pièces chacune à la place de l'autre
    pair = next(((p, mapping[p]) for p in orb.pieces
                 if mapping[p] != p and mapping[mapping[p]] == p), None)
    certain = pair is not None
    if pair is None:
        p = next((p for p in _rank_pieces(pz, orb.pieces) if mapping[p] != p), orb.pieces[0])
        pair = (p, mapping[p]) if mapping[p] != p else (orb.pieces[0], orb.pieces[1])
    a, b = pair
    pal = palette(pz)
    one, many, article, fem, _ = _names(orb.kind)
    new = list(colors)
    for sa, sb in zip(pz.pieces[a], pz.pieces[b]):
        new[sa], new[sb] = colors[sb], colors[sa]
    items = []
    for src, dst in ((a, b), (b, a)):
        dest = _where(pz, st, dst, pal, any(o.fixed and not o.ignored for o in pz.orbits))
        it = _item(pz, st, src, colors, colors, [colors[s] for s in pz.pieces[src]],
                   f"Placez-{'la' if fem else 'le'} {dest}, dans l'orientation ci-dessous.")
        # les pastilles décrivent la destination : couleur attendue après l'échange
        it["faces"] = [{"face": int(st.face_color[pz.sticker_face[sd]]), "now": int(colors[sd]),
                        "target": int(new[sd])} for sd in pz.pieces[dst]]
        items.append(it)
    if certain:
        head = f"{orb.label} : deux {many} ont été {_agree('interverti', fem, True)} au remontage."
    else:
        head = (f"{orb.label} : deux {many} sont {_agree('interverti', fem, True)} (parité impossible). "
                f"Impossible de savoir {'lesquelles' if fem else 'lesquels'} : échanger n'importe quelle "
                f"paire corrige l'état. Le plus simple : « Résoudre quand même », les deux pièces "
                f"apparaîtront d'elles-mêmes à la fin. Sinon, proposition :")
    stickers = pz.pieces[a] + pz.pieces[b]
    return {"kind": "swap", "orbit": orb.label, "title": head, "items": items,
            "actions": [it["text"] for it in items],
            "stickers": stickers, "suspects": stickers,
            "changes": [[s, new[s]] for s in stickers if new[s] != colors[s]], "colors": new}


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def diagnose(pz: Puzzle, colors: list[int], face_color: list[int]) -> list[dict]:
    """Liste des corrections physiques nécessaires (vide si l'état est valable).

    Les corrections sont cumulatives : chacune est calculée sur l'état obtenu
    après les précédentes.
    """
    colors = [int(c) for c in colors]
    repairs: list[dict] = []
    for _ in range(10):
        st = read_state(pz, colors, face_color)
        rep = None
        orbs = sorted((o for o in pz.orbits if not (o.fixed or o.ignored or o.id in st.color_mode)),
                      key=lambda o: (_PREFERENCE.get(o.kind, 9), o.id))
        for orb in orbs:
            rep = _twist_problem(pz, st, colors, orb)
            if rep:
                break
        if rep is None:
            rep = _parity_problem(pz, st, colors)
        if rep is None:
            return repairs
        repairs.append(rep)
        colors = rep.pop("colors")
    raise SolveError("État trop incohérent pour proposer une correction : vérifiez la saisie.")


def repairs_error(repairs: list[dict]) -> SolveError:
    n = len(repairs)
    msg = ("Le puzzle a été mal remonté : il ne peut pas être résolu en l'état. "
           + ("Une correction physique est nécessaire." if n == 1 else f"{n} corrections physiques sont nécessaires."))
    err = SolveError(msg, sorted({s for r in repairs for s in r["suspects"]}))
    err.repairs = repairs
    return err
