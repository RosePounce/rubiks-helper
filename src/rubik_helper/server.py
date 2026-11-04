"""Serveur web : API JSON + interface statique.

Couche HTTP mince au-dessus de `api.py` (qui contient toute la logique, sans
FastAPI). Le serveur ajoute le suivi de « préparation » des bibliothèques et le
service des fichiers statiques.
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import api
from .puzzle import CATALOG
from .solver import SolveError

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Rubik Helper")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_locks: dict[str, threading.Lock] = {pid: threading.Lock() for pid in CATALOG}
_ready: set[str] = set()
_info_cache: dict[str, dict] = {}
_cheat_cache: dict[str, dict] = {}


def _library(pid: str):
    with _locks[pid]:
        api.ensure_library(pid)
        _ready.add(pid)


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
    return [{**p, "ready": p["id"] in _ready} for p in api.catalog()]


@app.get("/api/puzzles/{pid}")
def puzzle_info(pid: str):
    if pid not in CATALOG:
        raise HTTPException(404, f"Puzzle inconnu : {pid}")
    if pid not in _info_cache:
        _info_cache[pid] = api.info(pid)
    return {**_info_cache[pid], "ready": pid in _ready}


@app.get("/api/cheatsheet/{pid}")
def cheatsheet(pid: str):
    if pid not in CATALOG:
        raise HTTPException(404, f"Puzzle inconnu : {pid}")
    if pid not in _cheat_cache:
        _cheat_cache[pid] = api.cheatsheet(pid)
    return _cheat_cache[pid]


class SolveRequest(BaseModel):
    puzzle: str
    colors: list[int]


@app.post("/api/solve")
def solve(req: SolveRequest):
    if req.puzzle not in CATALOG:
        raise HTTPException(404, f"Puzzle inconnu : {req.puzzle}")
    _library(req.puzzle)
    try:
        return api.solve(req.puzzle, req.colors)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except SolveError as e:
        return JSONResponse(status_code=422, content={"error": str(e), "stickers": e.stickers,
                                                      "repairs": e.repairs})


class FormulaRequest(BaseModel):
    puzzle: str
    formula: str
    colors: list[int] | None = None


@app.post("/api/formula")
def formula(req: FormulaRequest):
    if req.puzzle not in CATALOG:
        raise HTTPException(404, f"Puzzle inconnu : {req.puzzle}")
    try:
        return api.formula(req.puzzle, req.formula, req.colors)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"error": str(e)})


class ScrambleRequest(BaseModel):
    puzzle: str
    seed: int | None = None


@app.post("/api/scramble")
def scramble(req: ScrambleRequest):
    if req.puzzle not in CATALOG:
        raise HTTPException(404, f"Puzzle inconnu : {req.puzzle}")
    return api.scramble(req.puzzle, req.seed)


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description="Rubik Helper : solveur de cubes et de Megaminx")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--prepare", action="store_true",
                    help="calcule les bibliothèques de commutateurs puis quitte")
    ap.add_argument("--lan", action="store_true",
                    help="ouvre l'application au réseau local en HTTPS (caméra du téléphone)")
    args = ap.parse_args()
    if args.prepare:
        for pid in CATALOG:
            print(f"Préparation de {pid}...", flush=True)
            _library(pid)
        return
    if not args.lan:
        uvicorn.run(app, host=args.host, port=args.port)
        return

    from .lan import ensure_certificate, local_addresses

    addrs = local_addresses()
    cert, key = ensure_certificate(addrs)
    host = "0.0.0.0" if args.host == "127.0.0.1" else args.host
    print("\nRubik Helper accessible sur le réseau local :")
    for a in addrs or ["<adresse IP de cet ordinateur>"]:
        print(f"    https://{a}:{args.port}")
    print("Le certificat est auto-signé : accepter l'avertissement du navigateur à la première visite.")
    print("Le téléphone doit être sur le même réseau Wi-Fi ; autoriser le port dans le pare-feu si besoin.\n",
          flush=True)
    uvicorn.run(app, host=host, port=args.port, ssl_certfile=str(cert), ssl_keyfile=str(key))
