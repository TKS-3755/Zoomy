#!/usr/bin/env python3
"""Assemble runtime/zoomy_rt.asm with NASM and embed the bytes into zoomy.py.

Only needed when you change the runtime. Users of the compiler never need NASM:
the bytes live inside zoomy.py.

    python3 tools/build_runtime.py            rebuild and embed
    python3 tools/build_runtime.py --check    fail if zoomy.py is out of date
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASM = os.path.join(ROOT, "runtime", "zoomy_rt.asm")
TARGET = os.path.join(ROOT, "zoomy.py")
BEGIN, END = "# --- BEGIN RUNTIME BLOB ---", "# --- END RUNTIME BLOB ---"


def assemble():
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "rt.bin")
        subprocess.run(["nasm", "-f", "bin", ASM, "-o", out], check=True)
        with open(out, "rb") as f:
            return f.read()


def render(blob):
    hexstr = blob.hex()
    rows = [hexstr[i:i + 96] for i in range(0, len(hexstr), 96)]
    body = "\n".join(f'    "{r}"' for r in rows)
    return f"{BEGIN}\nRT_BLOB_HEX = (\n{body}\n)\n{END}"


def main():
    blob = assemble()
    with open(TARGET, encoding="utf-8") as f:
        src = f.read()
    new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda m: render(blob), src, flags=re.S)
    if "--check" in sys.argv:
        if new != src:
            print("zoomy.py's embedded runtime is out of date; run tools/build_runtime.py")
            return 1
        print(f"runtime up to date ({len(blob)} bytes)")
        return 0
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(new)
    print(f"embedded {len(blob)} runtime bytes into zoomy.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
