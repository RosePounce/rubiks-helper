"""Pont navigateur (Pyodide) : enveloppe `api.py` et renvoie des chaînes JSON.

Chaque fonction renvoie du JSON avec un contrat uniforme :
  { "ok": true,  "data": <charge utile> }
  { "ok": false, "status": <code>, "error": <message>,
                 "stickers": [...], "repairs": [...] }
Le JavaScript (`boot.js`) décode et, si ok vaut faux, lève une erreur portant
« stickers » et « repairs », exactement comme le ferait la couche HTTP.
"""

from __future__ import annotations

import json

from . import api
from .solver import SolveError


def _ok(data) -> str:
    return json.dumps({"ok": True, "data": data})


def _err(status: int, message: str, stickers=None, repairs=None) -> str:
    return json.dumps({"ok": False, "status": status, "error": message,
                       "stickers": stickers or [], "repairs": repairs or []})


def catalog() -> str:
    return _ok(api.catalog())


def ensure_library(pid: str) -> str:
    try:
        api.ensure_library(pid)
        return _ok(True)
    except KeyError as e:
        return _err(404, str(e))


def info(pid: str) -> str:
    try:
        return _ok(api.info(pid))
    except KeyError as e:
        return _err(404, str(e))


def cheatsheet(pid: str) -> str:
    try:
        return _ok(api.cheatsheet(pid))
    except KeyError as e:
        return _err(404, str(e))


def scramble(pid: str, seed=None) -> str:
    try:
        return _ok(api.scramble(pid, seed))
    except KeyError as e:
        return _err(404, str(e))


def formula(pid: str, text: str, colors=None) -> str:
    try:
        return _ok(api.formula(pid, text, colors))
    except KeyError as e:
        return _err(404, str(e))
    except ValueError as e:
        return _err(422, str(e))


def solve(pid: str, colors) -> str:
    try:
        return _ok(api.solve(pid, colors))
    except KeyError as e:
        return _err(404, str(e))
    except ValueError as e:
        return _err(400, str(e))
    except SolveError as e:
        return _err(422, str(e), e.stickers, e.repairs)
