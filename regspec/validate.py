"""Load and validate a peripheral register spec.

Check a spec from the command line:

    python -m regspec.validate spec/timer0.json

Rules enforced (all errors are collected and reported together):
  * names are valid C identifiers; register names are unique, field names are
    unique within their register
  * register offsets are 4-byte aligned and no two registers share an offset
  * access is one of ro, rw, wo, w1c; a field in a read-only register must be ro
  * every field lies inside bits 31..0 and has msb >= lsb
  * no two fields in a register overlap
  * the reset value fits in 32 bits and sets no bits outside the defined fields
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REG_WIDTH = 32
REG_BYTES = REG_WIDTH // 8
REG_MAX = (1 << REG_WIDTH) - 1
ACCESS_TYPES = ("ro", "rw", "wo", "w1c")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
BITS = re.compile(r"^\s*(\d+)\s*(?::\s*(\d+)\s*)?$")


class SpecError(Exception):
    """Raised when a spec is invalid. ``errors`` lists every problem found."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("invalid spec:\n" + "\n".join(f"  - {e}" for e in errors))


@dataclass(frozen=True)
class Field:
    name: str
    msb: int
    lsb: int
    access: str
    description: str = ""

    @property
    def width(self) -> int:
        return self.msb - self.lsb + 1

    @property
    def mask(self) -> int:
        return ((1 << self.width) - 1) << self.lsb

    @property
    def bits(self) -> str:
        return str(self.lsb) if self.msb == self.lsb else f"{self.msb}:{self.lsb}"


@dataclass(frozen=True)
class Register:
    name: str
    offset: int
    access: str
    reset: int
    description: str
    fields: tuple[Field, ...]

    def field_reset(self, f: Field) -> int:
        return (self.reset & f.mask) >> f.lsb


@dataclass(frozen=True)
class Peripheral:
    name: str
    base_address: int
    description: str
    registers: tuple[Register, ...]  # sorted by offset

    @property
    def size(self) -> int:
        """Bytes spanned by the register block (last offset + one register)."""
        return max(r.offset for r in self.registers) + REG_BYTES


# --------------------------------------------------------------------------- helpers

def _int(value: Any, where: str, errors: list[str]) -> int | None:
    """Accept a JSON integer or a string like "0x1F" / "31"."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip(), 0)
        except ValueError:
            pass
    errors.append(f'{where}: expected an integer or hex string like "0x1F", got {value!r}')
    return None


def _bits(value: Any, where: str, errors: list[str]) -> tuple[int, int] | None:
    """Accept "msb:lsb", a single bit "n", or an integer bit number."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value, value
    if isinstance(value, str):
        m = BITS.match(value)
        if m:
            msb = int(m.group(1))
            lsb = int(m.group(2)) if m.group(2) is not None else msb
            return msb, lsb
    errors.append(f'{where}: bits must look like "15:8" or "3", got {value!r}')
    return None


def _name(value: Any, where: str, errors: list[str]) -> str | None:
    if isinstance(value, str) and IDENT.match(value):
        return value
    errors.append(f"{where}: name must be a C identifier (letters, digits, _), got {value!r}")
    return None


def _bit_list(mask: int) -> str:
    """Describe the set bits of a mask as ranges, e.g. 0b1101_1100 -> "7:6, 4:2"."""
    runs: list[str] = []
    bit = REG_WIDTH - 1
    while bit >= 0:
        if mask >> bit & 1:
            hi = bit
            while bit > 0 and mask >> (bit - 1) & 1:
                bit -= 1
            runs.append(str(hi) if hi == bit else f"{hi}:{bit}")
        bit -= 1
    return ", ".join(runs)


# --------------------------------------------------------------------------- validation

def _validate_field(raw: Any, reg_name: str, reg_access: str, idx: int,
                    errors: list[str]) -> Field | None:
    where = f"register '{reg_name}' fields[{idx}]"
    if not isinstance(raw, dict):
        errors.append(f"{where}: must be an object")
        return None
    name = _name(raw.get("name"), where, errors)
    if name:
        where = f"field '{reg_name}.{name}'"

    bits = _bits(raw.get("bits"), where, errors) if "bits" in raw else None
    if "bits" not in raw:
        errors.append(f"{where}: missing 'bits'")

    access = raw.get("access", reg_access)
    if access not in ACCESS_TYPES:
        errors.append(f"{where}: access must be one of {', '.join(ACCESS_TYPES)}, got {access!r}")
    elif reg_access == "ro" and access != "ro":
        errors.append(f"{where}: register is read-only, so field access must be 'ro', got {access!r}")

    if bits is None or name is None:
        return None
    msb, lsb = bits
    ok = True
    if msb < lsb:
        errors.append(f"{where}: bits {msb}:{lsb} have msb < lsb (write them as high:low)")
        ok = False
    if msb > REG_WIDTH - 1:
        errors.append(f"{where}: bits {msb}:{lsb} extend past bit {REG_WIDTH - 1}")
        ok = False
    if not ok or access not in ACCESS_TYPES:
        return None
    return Field(name, msb, lsb, access, str(raw.get("description", "")))


def _validate_register(raw: Any, idx: int, errors: list[str]) -> Register | None:
    where = f"registers[{idx}]"
    if not isinstance(raw, dict):
        errors.append(f"{where}: must be an object")
        return None
    name = _name(raw.get("name"), where, errors)
    if name:
        where = f"register '{name}'"

    for key in ("offset", "access", "reset", "fields"):
        if key not in raw:
            errors.append(f"{where}: missing '{key}'")

    offset = _int(raw["offset"], f"{where} offset", errors) if "offset" in raw else None
    if offset is not None:
        if offset < 0:
            errors.append(f"{where}: offset must not be negative, got {offset}")
        elif offset % REG_BYTES:
            errors.append(f"{where}: offset 0x{offset:02X} is not aligned to {REG_BYTES} bytes")

    access = raw.get("access")
    if "access" in raw and access not in ACCESS_TYPES:
        errors.append(f"{where}: access must be one of {', '.join(ACCESS_TYPES)}, got {access!r}")

    reset = _int(raw["reset"], f"{where} reset", errors) if "reset" in raw else None
    if reset is not None and not 0 <= reset <= REG_MAX:
        errors.append(f"{where}: reset value {reset:#x} does not fit in {REG_WIDTH} bits")
        reset = None

    raw_fields = raw.get("fields")
    if "fields" in raw and (not isinstance(raw_fields, list) or not raw_fields):
        errors.append(f"{where}: 'fields' must be a non-empty list "
                      f"(use one field with bits \"31:0\" for a plain 32-bit value)")
        raw_fields = []

    fields: list[Field] = []
    seen: set[str] = set()
    for i, rf in enumerate(raw_fields or []):
        f = _validate_field(rf, name or f"#{idx}", access if access in ACCESS_TYPES else "rw", i, errors)
        if f is None:
            continue
        if f.name.upper() in seen:
            errors.append(f"{where}: duplicate field name '{f.name}'")
            continue
        seen.add(f.name.upper())
        fields.append(f)

    # Overlap check: compare every pair so each clash is reported once, by name.
    for i, a in enumerate(fields):
        for b in fields[i + 1:]:
            clash = a.mask & b.mask
            if clash:
                errors.append(f"{where}: fields '{a.name}' (bits {a.bits}) and '{b.name}' "
                              f"(bits {b.bits}) overlap at bit(s) {_bit_list(clash)}")

    if reset is not None and fields:
        covered = 0
        for f in fields:
            covered |= f.mask
        stray = reset & ~covered & REG_MAX
        if stray:
            errors.append(f"{where}: reset value 0x{reset:08X} sets bit(s) {_bit_list(stray)} "
                          f"that no field covers")

    if None in (name, offset, reset) or access not in ACCESS_TYPES:
        return None
    fields.sort(key=lambda f: f.lsb)
    return Register(name, offset, access, reset, str(raw.get("description", "")), tuple(fields))


def validate_spec(data: Any) -> Peripheral:
    """Validate parsed JSON and return a Peripheral, or raise SpecError listing every problem."""
    errors: list[str] = []
    if not isinstance(data, dict):
        raise SpecError(["top level must be a JSON object"])

    name = _name(data.get("name"), "peripheral", errors)
    base = _int(data.get("base_address", 0), "peripheral base_address", errors)
    if base is not None:
        if not 0 <= base <= REG_MAX:
            errors.append(f"peripheral base_address {base:#x} does not fit in 32 bits")
        elif base % REG_BYTES:
            errors.append(f"peripheral base_address 0x{base:08X} is not aligned to {REG_BYTES} bytes")

    raw_regs = data.get("registers")
    if not isinstance(raw_regs, list) or not raw_regs:
        errors.append("'registers' must be a non-empty list")
        raw_regs = []

    regs: list[Register] = []
    by_name: dict[str, str] = {}
    by_offset: dict[int, str] = {}
    for i, rr in enumerate(raw_regs):
        r = _validate_register(rr, i, errors)
        if r is None:
            continue
        if r.name.upper() in by_name:
            errors.append(f"register '{r.name}': duplicate register name")
            continue
        if r.offset in by_offset:
            errors.append(f"register '{r.name}': offset 0x{r.offset:02X} is already used by "
                          f"'{by_offset[r.offset]}'")
            continue
        by_name[r.name.upper()] = r.name
        by_offset[r.offset] = r.name
        regs.append(r)

    if errors:
        raise SpecError(errors)
    regs.sort(key=lambda r: r.offset)
    return Peripheral(name, base, str(data.get("description", "")), tuple(regs))


def load_spec(path: str | Path) -> Peripheral:
    """Read a JSON spec file and validate it."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SpecError([f"{path}: file not found"]) from None
    except json.JSONDecodeError as e:
        raise SpecError([f"{path}: invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}"]) from None
    return validate_spec(data)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = argv[0] if argv else "spec/timer0.json"
    try:
        p = load_spec(path)
    except SpecError as e:
        print(f"{path}: {len(e.errors)} problem(s)", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    n_fields = sum(len(r.fields) for r in p.registers)
    print(f"{path}: OK - {p.name}, {len(p.registers)} registers, {n_fields} fields")
    return 0


if __name__ == "__main__":
    sys.exit(main())
