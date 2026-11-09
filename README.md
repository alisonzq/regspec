# regspec

Describe a peripheral's registers once in JSON; regspec validates the spec,
generates a C header from it, and serves it over HTTP. The example spec is a
fake timer peripheral, `TIMER0`.

```
spec/timer0.json          the register map: the only file you edit by hand
regspec/validate.py       loads the spec and checks it (reports every problem at once)
regspec/gen_header.py     writes build/timer0.h from a valid spec
build/timer0.h            GENERATED: offsets, resets, field shifts/masks, struct, X-macros
tests/test_reset.c        C test: layout, field maths and golden reset values
tests/test_validate.py    pytest: good spec passes, each kind of bad spec is rejected
tests/test_api.py         pytest: the HTTP endpoint
api/app.py                FastAPI app: GET /registers and GET /registers/{name}
tasks.py                  one command for everything (works on Windows)
```

## One-time setup (Windows)

1. Install **Python 3.10+** from python.org (tick "Add python.exe to PATH").
2. Install a **C compiler**. The simplest is MSYS2 (https://www.msys2.org), then in
   the "MSYS2 UCRT64" terminal run `pacman -S mingw-w64-ucrt-x86_64-gcc` and add
   `C:\msys64\ucrt64\bin` to your PATH. Visual Studio's `cl` also works if you run from
   a "Developer Command Prompt".
3. In this folder, create a virtual environment and install the Python packages:

```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

(On macOS/Linux: `python3 -m venv .venv`, then `source .venv/bin/activate`.)

## Everyday commands

```
python tasks.py              # validate + generate header + C test + Python tests
python tasks.py gen          # just regenerate build/timer0.h
python tasks.py ctest        # generate, compile and run the C test
python tasks.py pytest       # Python tests only
python tasks.py serve        # API on http://127.0.0.1:8000
```

With the server running, open:

- http://127.0.0.1:8000/registers/CTRL - one register's JSON (name is case-insensitive)
- http://127.0.0.1:8000/registers - every register name and offset
- http://127.0.0.1:8000/docs - interactive API docs

## The spec format

```json
{
  "name": "TIMER0",
  "base_address": "0x40001000",
  "registers": [
    {
      "name": "CTRL", "offset": "0x00", "access": "rw", "reset": "0x00000300",
      "fields": [
        { "name": "EN",       "bits": "0" },
        { "name": "PRESCALE", "bits": "15:8" }
      ]
    }
  ]
}
```

- Numbers can be JSON integers or strings such as `"0x1C"`.
- `bits` is `"msb:lsb"` or a single bit `"3"`.
- `access` is `ro`, `rw`, `wo` or `w1c` (write 1 to clear). A field may set its own
  `access`, which otherwise defaults to the register's.
- `description` is optional on the peripheral, registers and fields, and is copied
  into header comments.

The validator rejects: names that aren't C identifiers, duplicate register or
field names, offsets that aren't 4-byte aligned, two registers at the same
offset, unknown access types, writable fields in a read-only register, fields
outside bits 31..0 or written low:high, overlapping fields, and reset values
that don't fit in 32 bits or set bits that no field covers.

## What the header gives you

For register `CTRL` and field `PRESCALE`:

```c
TIMER0_CTRL_OFFSET            0x00u
TIMER0_CTRL_RESET             0x00000300u
TIMER0_CTRL_PRESCALE_SHIFT    8u
TIMER0_CTRL_PRESCALE_WIDTH    8u
TIMER0_CTRL_PRESCALE_MASK     0x0000FF00u
TIMER0_CTRL_PRESCALE_RESET    0x03u          /* field value after reset */

TIMER0_FIELD_GET(reg_val, MASK, SHIFT)       /* extract a field */
TIMER0_FIELD_PREP(val, MASK, SHIFT)          /* shift a value into place */
TIMER0->CTRL                                 /* memory-mapped struct access */
```

It also emits `TIMER0_REGISTER_LIST(X)` and `TIMER0_FIELD_LIST(X)` X-macros,
which the C test uses to loop over every register and field.

## When you change the spec

Run `python tasks.py`. The generic C checks and the Python tests adapt
automatically. The **golden values** at the bottom of `tests/test_reset.c` are
copied by hand from the spec on purpose, so a changed reset value fails the test
until you update it there too. If you rename the peripheral from `TIMER0`, update
the `TIMER0_` names in `tests/test_reset.c`.
