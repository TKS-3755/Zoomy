"""The Python side of the browser playground (runs inside Pyodide, but works anywhere).
zoomy_playground(text, mode, stdin) -> JSON text {"ok", "out", "error", "line", "fix"}
modes: check (compile only), run, python (show generated code), explain, fmt"""
import io
import json
import re
import sys

import zoomy_py
import zoomy_suggest
import zoomy_fmt

NAME = "program.zmy"


def _error(e, text):
    line = e.line if getattr(e, "line", None) else None
    msg = re.sub(r"^[^:]*:\d+:\s*", "", str(e))
    msg = re.sub(r"^program\.zmy:\s*", "", msg)
    fix = zoomy_suggest.suggest(text, NAME, e) if line else None
    return {"ok": False, "out": "", "error": msg, "line": line, "fix": fix}


def zoomy_playground(text, mode="check", stdin=""):
    if not text.endswith("\n"):
        text += "\n"
    try:
        if mode == "explain":
            return json.dumps({"ok": True, "out": zoomy_py.explain(text, NAME)})
        if mode == "fmt":
            new = zoomy_fmt.format_text(text, NAME)
            if zoomy_fmt._compile(new, NAME) != zoomy_fmt._compile(text, NAME):
                new = text
            return json.dumps({"ok": True, "out": new})
        prog = zoomy_py.Program(NAME)
        prog.load_text(text, NAME)
        warnings = []
        src, _ = zoomy_py.compile_python(prog, warnings.append)
        if prog.uses_extern:
            return json.dumps({"ok": False, "out": "", "error": "'extern' (C libraries) needs the native compiler; it cannot run in the browser", "line": None, "fix": None})
        if mode == "check":
            return json.dumps({"ok": True, "out": "".join("Warning: " + w + "\n" for w in warnings)})
        if mode == "python":
            return json.dumps({"ok": True, "out": src})
        # run
        raw = io.BytesIO()
        out = io.TextIOWrapper(raw, encoding="utf-8", write_through=True)
        old = sys.stdout, sys.stdin, sys.argv
        sys.stdout = out
        sys.stdin = io.TextIOWrapper(io.BytesIO(stdin.encode("utf-8")), encoding="utf-8")
        sys.argv = [NAME]
        err = None
        try:
            exec(compile(src, NAME + ".py", "exec"), {"__name__": "__main__"})
        except SystemExit:
            pass
        except Exception as e:                      # a run-time stop (division by zero, a failed check, ...)
            err = f"{type(e).__name__}: {e}"
        finally:
            sys.stdout, sys.stdin, sys.argv = old
        out.flush()
        r = {"ok": err is None, "out": raw.getvalue().decode("utf-8", "replace")}
        if err:
            r["error"], r["line"], r["fix"] = err, None, None
        return json.dumps(r)
    except zoomy_py.ZoomyError as e:
        return json.dumps(_error(e, text))
    except Exception as e:
        return json.dumps({"ok": False, "out": "", "error": f"{type(e).__name__}: {e}", "line": None, "fix": None})
