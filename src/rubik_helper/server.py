"""Serveur web : API JSON + interface statique."""

from __future__ import annotations

import random
import threading
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .cheatsheet import build_cheatsheet
from .extras import kociemba_solution, net_layout, palette, random_scramble
from .puzzle import CATALOG, get_puzzle
from .solver import SolveError, get_library, solve_colors

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Rubik Helper")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_locks: dict[str, threading.Lock] = {pid: threading.Lock() for pid in CATALOG}
_ready: set[str] = set()
_json_cache: dict[str, dict] = {}


def _puzzle(pid: str):
    if pid not in CATALOG:
        raise HTTPException(404, f"Puzzle inconnu : {pid}")
    return get_puzzle(pid)


def _library(pid: str):
    with _locks[pid]:
        lib = get_library(get_puzzle(pid))
        _ready.add(pid)
        return lib


def _warmup():
    for pid in CATALOG:
        try:
            _library(pid)
        except Exception as exc:  # pragma: no cover - journalisation seulement
            print(f"[rubik-helper] préparation de {pid} impossible : {exc}")


@app.on_event("startup")
def _start_warmup():
    threading.Thread(target=_warmup, daemon=True).start()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/puzzles")
def list_puzzles():
    return [{"id": pid, "label": lbl, "ready": pid in _ready} for pid, (lbl, _, _) in CATALOG.items()]


@app.get("/api/puzzles/{pid}")
def puzzle_info(pid: str):
    pz = _puzzle(pid)
    if pid not in _json_cache:
        data = pz.to_json()
        net = net_layout(pz)
        for s in data["stickers"]:
            s["net"] = net[s["id"]]
        data["palette"] = palette(pz)
        data["solved"] = [int(f) for f in pz.sticker_face]
        _json_cache[pid] = data
    return {**_json_cache[pid], "ready": pid in _ready}


_cheat_cache: dict[str, dict] = {}


@app.get("/api/cheatsheet/{pid}")
def cheatsheet(pid: str):
    pz = _puzzle(pid)
    if pid not in _cheat_cache:
        _cheat_cache[pid] = build_cheatsheet(pz, _library(pid))
    return _cheat_cache[pid]


class SolveRequest(BaseModel):
    puzzle: str
    colors: list[int]


@app.post("/api/solve")
def solve(req: SolveRequest):
    pz = _puzzle(req.puzzle)
    if len(req.colors) != pz.n:
        raise HTTPException(400, f"{pz.n} facettes attendues, {len(req.colors)} reçues.")
    _library(req.puzzle)
    try:
        res = solve_colors(pz, req.colors)
    except SolveError as e:
        return JSONResponse(status_code=422, content={"error": str(e), "stickers": e.stickers,
                                                      "repairs": e.repairs})
    short = kociemba_solution(pz, req.colors, res["face_colors"])
    if short is not None:
        res["short"] = {"moves": short, "move_count": len(short)}
    return res


class FormulaRequest(BaseModel):
    puzzle: str
    formula: str
    colors: list[int] | None = None


def _anim_tokens(toks):
    return [{"name": t["name"], "face": t["face"], "angle": t["angle"], "members": t["members"],
             "perm": t["perm"].tolist()} for t in toks]


@app.post("/api/formula")
def formula(req: FormulaRequest):
    """Analyse une formule et renvoie les jetons animables et les couleurs finales."""
    pz = _puzzle(req.puzzle)
    try:
        toks = pz.parse(req.formula)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"error": str(e)})
    cur = np.asarray(req.colors if req.colors is not None else pz.sticker_face, dtype=int)
    for t in toks:
        out = np.empty_like(cur)
        out[t["perm"]] = cur
        cur = out
    return {"tokens": _anim_tokens(toks), "colors": cur.tolist()}


class ScrambleRequest(BaseModel):
    puzzle: str
    seed: int | None = None


@app.post("/api/scramble")
def scramble(req: ScrambleRequest):
    pz = _puzzle(req.puzzle)
    rng = random.Random(req.seed)
    text = random_scramble(pz, rng)
    cur = np.asarray(pz.sticker_face, dtype=int)
    for t in pz.parse(text):
        out = np.empty_like(cur)
        out[t["perm"]] = cur
        cur = out
    return {"formula": text, "colors": cur.tolist()}


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description="Rubik Helper : solveur de cubes et de Megaminx")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--prepare", action="store_true",
                    help="calcule les bibliothèques de commutateurs puis quitte")
    args = ap.parse_args()
    if args.prepare:
        for pid in CATALOG:
            print(f"Préparation de {pid}...", flush=True)
            _library(pid)
        return
    uvicorn.run(app, host=args.host, port=args.port)
