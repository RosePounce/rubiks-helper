"""Cœur applicatif, sans dépendance web.

Mêmes opérations que les routes JSON du serveur, mais sous forme de fonctions
pures renvoyant des structures Python. Partagé par le serveur FastAPI
(`server.py`) et par le build navigateur Pyodide (`webglue.py`) : aucun import
de FastAPI ici, pour que le moteur soit chargeable tel quel dans le navigateur.
"""

from __future__ import annotations

import random

import numpy as np

from .cheatsheet import build_cheatsheet
from .extras import kociemba_solution, net_layout, palette, random_scramble
from .puzzle import CATALOG, get_puzzle
from .solver import get_library, solve_colors


def _puzzle(pid: str):
    if pid not in CATALOG:
        raise KeyError(f"Puzzle inconnu : {pid}")
    return get_puzzle(pid)


def catalog() -> list[dict]:
    return [{"id": pid, "label": lbl} for pid, (lbl, _, _) in CATALOG.items()]


def ensure_library(pid: str) -> None:
    """Prépare (et met en cache) la bibliothèque de commutateurs du puzzle."""
    get_library(_puzzle(pid))


def info(pid: str) -> dict:
    """Description complète d'un puzzle : faces, facettes (3D + patron), palette, état résolu."""
    pz = _puzzle(pid)
    data = pz.to_json()
    net = net_layout(pz)
    for s in data["stickers"]:
        s["net"] = net[s["id"]]
    data["palette"] = palette(pz)
    data["solved"] = [int(f) for f in pz.sticker_face]
    return data


def cheatsheet(pid: str) -> dict:
    pz = _puzzle(pid)
    return build_cheatsheet(pz, get_library(pz))


def _anim_tokens(toks):
    return [{"name": t["name"], "face": t["face"], "angle": t["angle"], "members": t["members"],
             "perm": t["perm"].tolist()} for t in toks]


def formula(pid: str, text: str, colors: list[int] | None = None) -> dict:
    """Analyse une formule : jetons animables et couleurs finales. Lève ValueError."""
    pz = _puzzle(pid)
    toks = pz.parse(text)
    cur = np.asarray(colors if colors is not None else pz.sticker_face, dtype=int)
    for t in toks:
        out = np.empty_like(cur)
        out[t["perm"]] = cur
        cur = out
    return {"tokens": _anim_tokens(toks), "colors": cur.tolist()}


def scramble(pid: str, seed: int | None = None) -> dict:
    pz = _puzzle(pid)
    rng = random.Random(seed)
    text = random_scramble(pz, rng)
    cur = np.asarray(pz.sticker_face, dtype=int)
    for t in pz.parse(text):
        out = np.empty_like(cur)
        out[t["perm"]] = cur
        cur = out
    return {"formula": text, "colors": cur.tolist()}


def solve(pid: str, colors: list[int]) -> dict:
    """Résout un état décrit par ses couleurs. Lève ValueError (saisie) ou SolveError (état)."""
    pz = _puzzle(pid)
    if len(colors) != pz.n:
        raise ValueError(f"{pz.n} facettes attendues, {len(colors)} reçues.")
    get_library(pz)
    res = solve_colors(pz, colors)
    short = kociemba_solution(pz, colors, res["face_colors"])
    if short is not None:
        res["short"] = {"moves": short, "move_count": len(short)}
    return res
