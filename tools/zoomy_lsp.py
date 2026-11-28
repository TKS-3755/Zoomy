#!/usr/bin/env python3
"""A small Zoomy language server (stdio, no dependencies).
Gives any editor that speaks LSP: error squiggles (several at once), 'Did you mean this sentence' quick fixes,
hover that says how a line was read (the --explain text), and whole-document formatting (zoomy fmt).
Run:  python3 tools/zoomy_lsp.py"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import zoomy_py       # noqa: E402
import zoomy_fmt      # noqa: E402
import zoomy_suggest  # noqa: E402

MAX_ERRORS = 10
docs = {}


def _try(text, name):
    try:
        prog = zoomy_py.Program(name)
        prog.load_text(text, name)
        zoomy_py.compile_python(prog)
        return None
    except zoomy_py.ZoomyError as e:
        return e
    except Exception:
        return None


def _blank(lines, n):
    """blank line n (1-based); for a block header also blank its body, so one broken header gives one error"""
    ind = lambda s: len(s) - len(s.lstrip())
    base = ind(lines[n - 1])
    head = lines[n - 1].rstrip().endswith(":")
    lines[n - 1] = ""
    if head:
        k = n
        while k < len(lines) and (not lines[k].strip() or ind(lines[k]) > base):
            lines[k] = ""
            k += 1


def diagnostics(text, name="program.zmy"):
    lines = text.splitlines()
    out, seen = [], set()
    cur = list(lines)
    for _ in range(MAX_ERRORS):
        e = _try("\n".join(cur) + "\n", name)
        if e is None:
            break
        n = e.line if e.line and 1 <= e.line <= len(cur) else None
        msg = str(e)
        msg = re.sub(r"^[^:]*:\d+:\s*", "", msg)
        if n is None:
            out.append({"line": 0, "msg": msg, "fix": None})
            break
        if n in seen:
            break
        seen.add(n)
        s = zoomy_suggest.suggest("\n".join(lines) + "\n", name, e) if cur[n - 1] == lines[n - 1] else None
        out.append({"line": n - 1, "msg": msg, "fix": s})
        _blank(cur, n)
    return out


def _range(lines, ln):
    t = lines[ln] if ln < len(lines) else ""
    start = len(t) - len(t.lstrip())
    return {"start": {"line": ln, "character": start}, "end": {"line": ln, "character": max(len(t.rstrip()), start)}}


def publish(uri):
    text = docs[uri]
    lines = text.splitlines()
    ds = []
    for d in diagnostics(text, _name(uri)):
        m = d["msg"] + (f"\nDid you mean this sentence: {d['fix']}" if d["fix"] else "")
        ds.append({"range": _range(lines, d["line"]), "severity": 1, "source": "zoomy", "message": m,
                   "data": {"fix": d["fix"]}})
    send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": uri, "diagnostics": ds}})


def _name(uri):
    return os.path.basename(uri) if uri else "program.zmy"


def hover(uri, pos):
    text = docs.get(uri, "")
    lines = text.splitlines()
    if pos["line"] >= len(lines) or not lines[pos["line"]].strip():
        return None
    try:
        note = zoomy_py.explain(lines[pos["line"]].strip() + "\n", "line")
    except Exception:
        return None
    note = "\n".join(l for l in note.splitlines() if "statement line(s)" not in l).strip()
    return {"contents": {"kind": "markdown", "value": "```\n" + note + "\n```"}, "range": _range(lines, pos["line"])}


def formatting(uri):
    text = docs.get(uri, "")
    try:
        new = zoomy_fmt.format_text(text, _name(uri))
    except Exception:
        return []
    if zoomy_fmt._compile(new, _name(uri)) != zoomy_fmt._compile(text, _name(uri)):
        return []                                      # never change what the program does
    lines = text.splitlines()
    return [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": len(lines), "character": 0}}, "newText": new}]


def code_actions(uri, params):
    out = []
    lines = docs.get(uri, "").splitlines()
    for d in params.get("context", {}).get("diagnostics", []):
        fix = (d.get("data") or {}).get("fix")
        if fix:
            ln = d["range"]["start"]["line"]
            t = lines[ln]
            ind = t[:len(t) - len(t.lstrip())]
            out.append({"title": f"Change to: {fix}", "kind": "quickfix", "diagnostics": [d], "isPreferred": True,
                        "edit": {"changes": {uri: [{"range": {"start": {"line": ln, "character": 0},
                                                            "end": {"line": ln, "character": len(t)}}, "newText": ind + fix}]}}})
    return out


def send(msg):
    body = json.dumps(msg).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    sys.stdout.buffer.flush()


def read():
    n = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        if line.lower().startswith(b"content-length:"):
            n = int(line.split(b":")[1])
    return json.loads(sys.stdin.buffer.read(n).decode("utf-8")) if n else None


def main():
    shutdown = False
    while True:
        m = read()
        if m is None:
            return 0
        method, params, mid = m.get("method"), m.get("params") or {}, m.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {"capabilities": {
                "textDocumentSync": 1, "hoverProvider": True, "documentFormattingProvider": True,
                "codeActionProvider": True}, "serverInfo": {"name": "zoomy-lsp"}}})
        elif method == "textDocument/didOpen":
            td = params["textDocument"]
            docs[td["uri"]] = td["text"]
            publish(td["uri"])
        elif method == "textDocument/didChange":
            uri = params["textDocument"]["uri"]
            docs[uri] = params["contentChanges"][-1]["text"]
            publish(uri)
        elif method == "textDocument/didClose":
            docs.pop(params["textDocument"]["uri"], None)
        elif method == "textDocument/hover":
            send({"jsonrpc": "2.0", "id": mid, "result": hover(params["textDocument"]["uri"], params["position"])})
        elif method == "textDocument/formatting":
            send({"jsonrpc": "2.0", "id": mid, "result": formatting(params["textDocument"]["uri"])})
        elif method == "textDocument/codeAction":
            send({"jsonrpc": "2.0", "id": mid, "result": code_actions(params["textDocument"]["uri"], params)})
        elif method == "shutdown":
            shutdown = True
            send({"jsonrpc": "2.0", "id": mid, "result": None})
        elif method == "exit":
            return 0 if shutdown else 1
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "not supported"}})


if __name__ == "__main__":
    sys.exit(main())
