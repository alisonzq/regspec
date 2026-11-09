"""Validator and header-generator tests.  Run: python -m pytest"""

import copy
import json
from pathlib import Path

import pytest

from regspec.gen_header import render_header
from regspec.validate import SpecError, load_spec, validate_spec

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "spec" / "timer0.json"


def base_spec():
    """A minimal valid spec that each bad-spec test tweaks."""
    return {
        "name": "DEV",
        "base_address": "0x1000",
        "registers": [
            {"name": "CTRL", "offset": "0x00", "access": "rw", "reset": "0x00000005",
             "fields": [{"name": "EN", "bits": "0"}, {"name": "MODE", "bits": "3:1"}]},
            {"name": "DATA", "offset": "0x04", "access": "ro", "reset": 0,
             "fields": [{"name": "VALUE", "bits": "31:0"}]},
        ],
    }


def errors_for(spec):
    with pytest.raises(SpecError) as exc:
        validate_spec(spec)
    return "\n".join(exc.value.errors)


def test_sample_spec_is_valid():
    p = load_spec(SPEC)
    assert p.name == "TIMER0"
    assert [r.offset for r in p.registers] == sorted(r.offset for r in p.registers)


def test_base_spec_is_valid():
    p = validate_spec(base_spec())
    ctrl = p.registers[0]
    mode = ctrl.fields[1]
    assert (mode.msb, mode.lsb, mode.width, mode.mask) == (3, 1, 3, 0b1110)
    assert ctrl.field_reset(mode) == 0b010


def tweak(path, value):
    """Return base_spec() with one value replaced. path is a tuple of keys/indexes."""
    spec = copy.deepcopy(base_spec())
    target = spec
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return spec


@pytest.mark.parametrize("path, value, expected", [
    # overlapping fields
    (("registers", 0, "fields", 1, "bits"), "3:0", "overlap at bit(s) 0"),
    # field outside 32 bits
    (("registers", 1, "fields", 0, "bits"), "32:0", "extend past bit 31"),
    (("registers", 0, "fields", 0, "bits"), "40", "extend past bit 31"),
    # msb/lsb written backwards
    (("registers", 0, "fields", 1, "bits"), "1:3", "msb < lsb"),
    # misaligned offset
    (("registers", 1, "offset"), "0x06", "not aligned to 4 bytes"),
    # duplicate offset
    (("registers", 1, "offset"), "0x00", "already used by 'CTRL'"),
    # duplicate register name (case-insensitive)
    (("registers", 1, "name"), "ctrl", "duplicate register name"),
    # bad access type
    (("registers", 0, "access"), "readwrite", "access must be one of"),
    # writable field in a read-only register
    (("registers", 1, "fields", 0, "access"), "rw", "field access must be 'ro'"),
    # reset value too big / sets bits no field covers
    (("registers", 0, "reset"), "0x100000000", "does not fit in 32 bits"),
    (("registers", 0, "reset"), "0x00000010", "bit(s) 4 that no field covers"),
    # malformed values
    (("registers", 0, "offset"), "zero", "expected an integer"),
    (("registers", 0, "fields", 0, "bits"), "a:b", "bits must look like"),
    (("registers", 0, "name"), "2CTRL", "must be a C identifier"),
    (("registers", 0, "fields"), [], "non-empty list"),
    (("base_address",), "0x1002", "base_address 0x00001002 is not aligned"),
])
def test_bad_specs_are_rejected(path, value, expected):
    assert expected in errors_for(tweak(path, value))


def test_all_errors_reported_together():
    spec = tweak(("registers", 1, "offset"), "0x06")
    spec["registers"][0]["fields"][1]["bits"] = "3:0"
    errors = errors_for(spec)
    assert "not aligned" in errors and "overlap" in errors


def test_missing_keys():
    spec = base_spec()
    del spec["registers"][0]["reset"]
    del spec["registers"][0]["fields"][0]["bits"]
    errors = errors_for(spec)
    assert "missing 'reset'" in errors and "missing 'bits'" in errors


def test_invalid_json_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"name": "X",}')
    with pytest.raises(SpecError, match="invalid JSON"):
        load_spec(bad)


def test_header_contents():
    h = render_header(validate_spec(base_spec()))
    assert "#define DEV_CTRL_OFFSET" in h and "0x00u" in h
    assert "#define DEV_CTRL_RESET                   0x00000005u" in h
    assert "#define DEV_CTRL_MODE_SHIFT              1u" in h
    assert "#define DEV_CTRL_MODE_MASK               0x0000000Eu" in h
    assert "#define DEV_CTRL_MODE_RESET              0x02u" in h
    assert "#define DEV_DATA_VALUE_MASK              0xFFFFFFFFu" in h
    assert "volatile const uint32_t DATA;" in h  # ro register is const


def test_header_reserved_gap():
    spec = tweak(("registers", 1, "offset"), "0x10")
    h = render_header(validate_spec(spec))
    assert "uint32_t RESERVED0[3];" in h


def test_header_macro_collision():
    spec = base_spec()
    spec["registers"][0]["fields"] = [{"name": "A_B", "bits": "0"}]
    spec["registers"][0]["reset"] = 0
    spec["registers"][0]["name"] = "X"
    spec["registers"][1]["name"] = "X_A"
    spec["registers"][1]["fields"] = [{"name": "B", "bits": "0"}]
    with pytest.raises(SpecError, match="defined twice"):
        render_header(validate_spec(spec))


def test_sample_spec_round_trips_through_json():
    # The spec file itself must be plain JSON (no comments, trailing commas).
    json.loads(SPEC.read_text(encoding="utf-8"))
