"""API tests.  Run: python -m pytest"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import app

ROOT = Path(__file__).resolve().parent.parent
SPEC = json.loads((ROOT / "spec" / "timer0.json").read_text(encoding="utf-8"))
client = TestClient(app)


def test_get_register_returns_spec_json():
    r = client.get("/registers/CTRL")
    assert r.status_code == 200
    assert r.json() == next(reg for reg in SPEC["registers"] if reg["name"] == "CTRL")


def test_lookup_is_case_insensitive():
    assert client.get("/registers/int_status").json()["name"] == "INT_STATUS"


def test_unknown_register_is_404():
    r = client.get("/registers/NOPE")
    assert r.status_code == 404
    assert "CTRL" in r.json()["detail"]


def test_list_registers():
    r = client.get("/registers")
    assert r.status_code == 200
    names = [x["name"] for x in r.json()["registers"]]
    assert names == [reg["name"] for reg in SPEC["registers"]]
