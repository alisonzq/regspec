"""Project commands. Works the same on Windows, macOS and Linux.

    python tasks.py              same as "check"
    python tasks.py validate     check spec/timer0.json
    python tasks.py gen          validate + write build/timer0.h
    python tasks.py ctest        gen + compile and run tests/test_reset.c
    python tasks.py pytest       run the Python tests (validator, generator, API)
    python tasks.py check        gen + ctest + pytest
    python tasks.py serve        start the API on http://127.0.0.1:8000
    python tasks.py clean        delete build/

The C compiler is taken from the CC environment variable if set, otherwise the
first of gcc, clang, cc, cl (MSVC) found on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Paths are relative to ROOT (commands run there) so generated files don't embed your folder path.
SPEC = Path("spec", "timer0.json")
BUILD = Path("build")
HEADER = BUILD / "timer0.h"
C_TEST = Path("tests", "test_reset.c")
EXE = BUILD / ("test_reset.exe" if os.name == "nt" else "test_reset")


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    result = subprocess.run([str(c) for c in cmd], cwd=ROOT)
    if result.returncode:
        sys.exit(result.returncode)


def find_compiler() -> str:
    cc = os.environ.get("CC")
    if cc:
        return cc
    for name in ("gcc", "clang", "cc", "cl"):
        if shutil.which(name):
            return name
    sys.exit("No C compiler found. Install gcc (e.g. via MSYS2 on Windows) or set CC.")


def validate() -> None:
    run([sys.executable, "-m", "regspec.validate", SPEC])


def gen() -> None:
    run([sys.executable, "-m", "regspec.gen_header", SPEC, "-o", HEADER])


def ctest() -> None:
    gen()
    cc = find_compiler()
    if Path(cc).stem.lower() == "cl":
        run([cc, "/nologo", "/std:c11", "/W3", f"/I{BUILD}", C_TEST,
             f"/Fe:{EXE}", f"/Fo:{BUILD}{os.sep}"])
    else:
        run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
             f"-I{BUILD}", C_TEST, "-o", EXE])
    run([ROOT / EXE])


def pytest() -> None:
    run([sys.executable, "-m", "pytest", "-q"])


def check() -> None:
    ctest()
    pytest()
    print("\nAll checks passed.")


def serve() -> None:
    validate()
    run([sys.executable, "-m", "uvicorn", "api.app:app", "--reload", "--port", "8000"])


def clean() -> None:
    shutil.rmtree(ROOT / BUILD, ignore_errors=True)
    print(f"removed {BUILD}/")


TASKS = {f.__name__: f for f in (validate, gen, ctest, pytest, check, serve, clean)}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "check"
    if name not in TASKS:
        sys.exit(f"unknown task '{name}'. Choose from: {', '.join(TASKS)}")
    TASKS[name]()
