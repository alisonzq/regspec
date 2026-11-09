"""Generate a C header from a validated peripheral spec.

    python -m regspec.gen_header spec/timer0.json -o build/timer0.h

For every register the header defines <P>_<REG>_OFFSET and <P>_<REG>_RESET, and
for every field <P>_<REG>_<FIELD>_SHIFT, _WIDTH, _MASK and _RESET (the field's
value after reset). It also emits a memory-mapped struct and X-macro lists so
C code can loop over every register and field.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .validate import REG_BYTES, Peripheral, SpecError, load_spec

COL = 40  # column where macro values start


def _define(name: str, value: str, comment: str = "") -> str:
    line = f"#define {name.ljust(COL - 8)} {value}"
    return f"{line}  /* {comment} */" if comment else line


def _h32(v: int) -> str:
    return f"0x{v:08X}u"


def _h(v: int) -> str:
    return f"0x{v:02X}u"


def _comment(text: str) -> str:
    return text.replace("*/", "* /")


def _xmacro(name: str, entries: list[str]) -> list[str]:
    lines = [f"#define {name}(X) \\"]
    lines += [f"    {e} \\" for e in entries[:-1]]
    lines.append(f"    {entries[-1]}")
    return lines


def render_header(p: Peripheral, source: str = "spec/timer0.json") -> str:
    P = p.name.upper()
    guard = f"{P}_REGS_H"
    seen: dict[str, str] = {}

    def define(name: str, value: str, comment: str = "") -> str:
        # Catch names that collide after joining, e.g. reg A_B + field C vs reg A + field B_C.
        if name in seen:
            raise SpecError([f"generated macro {name} is defined twice ({seen[name]} and {comment or value})"])
        seen[name] = comment or value
        return _define(name, value, comment)

    out: list[str] = [
        f"/* {P} register map.",
        f" *",
        f" * GENERATED FILE - DO NOT EDIT.",
        f" * Source:    {source}",
        f" * Generator: regspec/gen_header.py",
    ]
    if p.description:
        out += [" *", f" * {_comment(p.description)}"]
    out += [
        " */",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stdint.h>",
        "",
        define(f"{P}_BASE_ADDR", _h32(p.base_address)),
        define(f"{P}_SIZE", _h(p.size), "bytes spanned by the register block"),
        define(f"{P}_REG_COUNT", f"{len(p.registers)}u"),
        "",
        "/* Field helpers: GET extracts a field from a register value, PREP shifts a",
        " * field value into position (and masks it) ready to OR into a register. */",
        define(f"{P}_FIELD_GET(reg_val, MASK, SHIFT)", "((uint32_t)(((uint32_t)(reg_val) & (MASK)) >> (SHIFT)))"),
        define(f"{P}_FIELD_PREP(val, MASK, SHIFT)", "((uint32_t)(((uint32_t)(val) << (SHIFT)) & (MASK)))"),
    ]

    for r in p.registers:
        R = f"{P}_{r.name.upper()}"
        title = f"{r.name} @ 0x{r.offset:02X} ({r.access})"
        out += ["", "/* " + "-" * 72, f" * {title}" + (f" - {_comment(r.description)}" if r.description else ""), " */"]
        out.append(define(f"{R}_OFFSET", _h(r.offset)))
        out.append(define(f"{R}_RESET", _h32(r.reset)))
        for f in r.fields:
            F = f"{R}_{f.name.upper()}"
            note = ("bit " if f.width == 1 else "bits ") + f.bits +(f", {f.access}" if f.access != r.access else "")
            if f.description:
                note += f" - {_comment(f.description)}"
            out.append("")
            out.append(f"/* {f.name}: {note} */")
            out.append(define(f"{F}_SHIFT", f"{f.lsb}u"))
            out.append(define(f"{F}_WIDTH", f"{f.width}u"))
            out.append(define(f"{F}_MASK", _h32(f.mask)))
            out.append(define(f"{F}_RESET", _h(r.field_reset(f))))

    # Memory-mapped struct with reserved padding for gaps between registers.
    out += ["", "/* " + "-" * 72, " * Memory-mapped layout. Read-only registers are const.", " */",
            "typedef struct {"]
    pos, n_reserved = 0, 0
    for r in p.registers:
        if r.offset > pos:
            words = (r.offset - pos) // REG_BYTES
            out.append(f"    uint32_t RESERVED{n_reserved}[{words}];".ljust(COL + 4)
                       + f"/* 0x{pos:02X}-0x{r.offset - 1:02X} */")
            n_reserved += 1
        qual = "volatile const uint32_t" if r.access == "ro" else "volatile uint32_t"
        out.append(f"    {qual} {r.name.upper()};".ljust(COL + 4) + f"/* 0x{r.offset:02X} {r.access} */")
        pos = r.offset + REG_BYTES
    out += [f"}} {P}_Type;", "", define(P, f"(({P}_Type *){P}_BASE_ADDR)")]

    # X-macros so C code (e.g. the tests) can iterate the map without hand-written tables.
    out += ["", "/* X-macro lists. X(name, offset, reset, access) and X(reg, field). */"]
    out += _xmacro(f"{P}_REGISTER_LIST",
                   [f"X({r.name.upper()}, {P}_{r.name.upper()}_OFFSET, {P}_{r.name.upper()}_RESET, {r.access})"
                    for r in p.registers])
    out.append("")
    out += _xmacro(f"{P}_FIELD_LIST",
                   [f"X({r.name.upper()}, {f.name.upper()})" for r in p.registers for f in r.fields])

    out += ["", f"#endif /* {guard} */", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate a C header from a peripheral JSON spec.")
    ap.add_argument("spec", nargs="?", default="spec/timer0.json", help="path to the JSON spec")
    ap.add_argument("-o", "--output", help="header to write (default: build/<spec name>.h)")
    args = ap.parse_args(argv)

    try:
        p = load_spec(args.spec)
        text = render_header(p, Path(args.spec).as_posix())
    except SpecError as e:
        print(f"{args.spec}: {len(e.errors)} problem(s), header not written", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    out = Path(args.output) if args.output else Path("build", Path(args.spec).stem + ".h")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"wrote {out.as_posix()} ({len(p.registers)} registers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
