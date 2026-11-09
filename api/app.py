"""HTTP API over the register spec.

Run from the project root:

    uvicorn api.app:app --reload

    GET /registers          -> list of register names and offsets
    GET /registers/{name}   -> the JSON for one register, exactly as written in the spec
                               (name match is case-insensitive; unknown names give 404)

The spec is re-read whenever the file changes, and it is validated first, so
the API never serves a spec the generator would reject. Point it at another
spec with the REGSPEC_FILE environment variable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from regspec.validate import SpecError, validate_spec

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = Path(os.environ.get("REGSPEC_FILE", ROOT / "spec" / "timer0.json"))

app = FastAPI(title="regspec register API")

_cache: dict[str, Any] = {"mtime": None, "spec": None}


def load_spec() -> dict[str, Any]:
    """Return the raw spec JSON, re-reading and re-validating it if the file changed."""
    try:
        mtime = SPEC_PATH.stat().st_mtime_ns
    except FileNotFoundError:
        raise HTTPException(500, f"spec file not found: {SPEC_PATH}") from None
    if _cache["mtime"] != mtime:
        try:
            raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            validate_spec(raw)
        except json.JSONDecodeError as e:
            raise HTTPException(500, f"spec is not valid JSON: {e}") from None
        except SpecError as e:
            raise HTTPException(500, {"message": "spec is invalid", "errors": e.errors}) from None
        _cache.update(mtime=mtime, spec=raw)
    return _cache["spec"]


@app.get("/registers")
def list_registers() -> dict[str, Any]:
    spec = load_spec()
    return {
        "peripheral": spec["name"],
        "registers": [{"name": r["name"], "offset": r["offset"]} for r in spec["registers"]],
    }


@app.get("/registers/{name}")
def get_register(name: str) -> dict[str, Any]:
    spec = load_spec()
    for reg in spec["registers"]:
        if reg["name"].upper() == name.upper():
            return reg
    known = ", ".join(r["name"] for r in spec["registers"])
    raise HTTPException(404, f"no register named '{name}'. Known registers: {known}")
