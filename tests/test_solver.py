"""Tests de bout en bout : mélange -> couleurs -> solution -> vérification."""
import random

import numpy as np
import pytest

from rubik_helper.extras import kociemba_solution, random_scramble
from rubik_helper.puzzle import CATALOG, get_puzzle
from rubik_helper.solver import SolveError, solve_colors

FAST = ["3x3", "4x4", "5x5", "megaminx"]
ALL = list(CATALOG)


def scrambled_colors(pz, seed, rotate=True):
    rng = random.Random(seed)
    cont = pz.apply_formula(np.arange(pz.n), random_scramble(pz, rng))
    if rotate:
        cont = pz.apply(cont, pz.symmetries[rng.randrange(len(pz.symmetries))])
    colors = pz.sticker_face[cont].tolist()
    for o in pz.orbits:
        if o.ignored:
            for p in o.pieces:
                for s in pz.pieces[p]:
                    colors[s] = -1
    return colors


def assert_solves(pz, colors, moves, face_colors):
    cur = np.asarray(colors)
    for tok in pz.parse(" ".join(moves)):
        out = np.empty_like(cur)
        out[tok["perm"]] = cur
        cur = out
    for o in pz.orbits:
        if o.ignored:
            continue
        for p in o.pieces:
            for s in pz.pieces[p]:
                assert cur[s] == face_colors[pz.sticker_face[s]]


@pytest.mark.parametrize("pid", FAST)
@pytest.mark.parametrize("seed", [1, 2])
def test_solve_fast(pid, seed):
    pz = get_puzzle(pid)
    colors = scrambled_colors(pz, seed)
    res = solve_colors(pz, colors)
    assert_solves(pz, colors, res["moves"], res["face_colors"])


@pytest.mark.slow
@pytest.mark.parametrize("pid", [p for p in ALL if p not in FAST])
def test_solve_big(pid):
    pz = get_puzzle(pid)
    colors = scrambled_colors(pz, 7)
    res = solve_colors(pz, colors)
    assert_solves(pz, colors, res["moves"], res["face_colors"])


def test_kociemba_short():
    pytest.importorskip("kociemba", reason="optional C extension, not installed")
    pz = get_puzzle("3x3")
    colors = scrambled_colors(pz, 3, rotate=False)
    res = solve_colors(pz, colors)
    short = kociemba_solution(pz, colors, res["face_colors"])
    assert short is not None and len(short) <= 23
    assert_solves(pz, colors, short, res["face_colors"])


def test_twisted_corner_rejected():
    pz = get_puzzle("3x3")
    colors = pz.sticker_face.tolist()
    corner = next(o for o in pz.orbits if o.kind == "corner").pieces[0]
    a, b, c = pz.pieces[corner]
    colors[a], colors[b], colors[c] = colors[b], colors[c], colors[a]
    with pytest.raises(SolveError):
        solve_colors(pz, colors)


def test_swapped_edges_rejected():
    pz = get_puzzle("megaminx")
    colors = pz.sticker_face.tolist()
    edges = next(o for o in pz.orbits if o.kind == "midge").pieces
    p, q = pz.pieces[edges[0]], pz.pieces[edges[5]]
    for s, t in zip(p, q):
        colors[s], colors[t] = colors[t], colors[s]
    with pytest.raises(SolveError):
        solve_colors(pz, colors)


def test_formula_inverse_is_identity():
    for pid in ("4x4", "gigaminx"):
        pz = get_puzzle(pid)
        f = "R U2 Rw' 2R F" if pid == "4x4" else "R 2U2' Fw BL2"
        inv = " ".join(pz.names(pz.invert_seq([i for t in pz.parse(f) for i in t["seq"]])))
        assert (pz.apply_formula(np.arange(pz.n), f + " " + inv) == np.arange(pz.n)).all()


def _twist(pz, colors, p, d):
    st = pz.pieces[p]
    old = list(colors)
    for j, s in enumerate(st):
        colors[s] = old[st[(j - d) % len(st)]]


def _repair_and_solve(pz, colors):
    with pytest.raises(SolveError) as ei:
        solve_colors(pz, colors)
    repairs = ei.value.repairs
    assert repairs, "une correction physique doit être proposée"
    fixed = list(colors)
    for r in repairs:
        for s, c in r["changes"]:
            fixed[s] = c
    res = solve_colors(pz, fixed)
    assert_solves(pz, fixed, res["moves"], res["face_colors"])
    return repairs


@pytest.mark.parametrize("pid", ["3x3", "megaminx", "gigaminx"])
def test_diagnose_twisted_corner_in_place(pid):
    """Puzzle remonté résolu avec un coin tourné : le coin fautif est désigné avec certitude."""
    pz = get_puzzle(pid)
    corner = next(o for o in pz.orbits if o.kind == "corner").pieces[5]
    colors = pz.sticker_face.tolist()
    _twist(pz, colors, corner, 1)
    repairs = _repair_and_solve(pz, colors)
    assert sorted(repairs[0]["stickers"]) == sorted(pz.pieces[corner])


def test_diagnose_swapped_corners_in_place():
    pz = get_puzzle("gigaminx")
    cs = next(o for o in pz.orbits if o.kind == "corner").pieces
    colors = pz.sticker_face.tolist()
    for x, y in zip(pz.pieces[cs[2]], pz.pieces[cs[9]]):
        colors[x], colors[y] = colors[y], colors[x]
    repairs = _repair_and_solve(pz, colors)
    assert sorted(repairs[0]["stickers"]) == sorted(pz.pieces[cs[2]] + pz.pieces[cs[9]])


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_diagnose_scrambled_with_several_faults(seed):
    pz = get_puzzle("gigaminx")
    colors = scrambled_colors(pz, seed, rotate=False)
    cs = next(o for o in pz.orbits if o.kind == "corner").pieces
    ms = next(o for o in pz.orbits if o.kind == "midge").pieces
    _twist(pz, colors, cs[seed], 2)
    _twist(pz, colors, ms[seed], 1)
    _repair_and_solve(pz, colors)


@pytest.mark.parametrize("pid", ["3x3", "4x4", "megaminx", "gigaminx"])
def test_cheatsheet_sequences_cycle_three_pieces(pid):
    from rubik_helper.cheatsheet import build_cheatsheet
    from rubik_helper.solver import get_library

    pz = get_puzzle(pid)
    cs = build_cheatsheet(pz, get_library(pz))
    assert cs["sections"]
    for sec in cs["sections"]:
        assert sec["examples"]
        for ex in sec["examples"]:
            flat = [m for p in ex["parts"] for m in p["moves"]]
            assert flat == ex["moves"]
            assert len(ex["highlight"]) % 3 == 0 and ex["effect"] != "Échange trois pièces."


def test_3x3_edges_use_user_algorithm():
    pz = get_puzzle("3x3")
    rng = random.Random(7)
    cur = np.array(pz.sticker_face)
    for t in pz.parse(random_scramble(pz, rng)):
        out = np.empty_like(cur)
        out[t["perm"]] = cur
        cur = out
    res = solve_colors(pz, cur.tolist())
    edges = [sg for sg in res["stages"] if sg["title"] == "Arêtes"]
    assert edges and edges[0]["steps"]
    for st in edges[0]["steps"]:
        assert "M' U2 M" in " ".join(st["moves"])
