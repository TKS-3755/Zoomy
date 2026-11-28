"""the language server and the editor files"""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0
def check(name, ok, info=""):
    global fails
    if not ok:
        fails += 1
        print("FAIL", name, info)
for f in ("package.json", "language-configuration.json", "syntaxes/zoomy.tmLanguage.json"):
    try:
        json.load(open(os.path.join(HERE, "editors/vscode", f)))
    except Exception as e:
        check("valid json " + f, False, e)
p = subprocess.Popen([sys.executable, os.path.join(HERE, "tools/zoomy_lsp.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=HERE)
def snd(o):
    b = json.dumps(o).encode(); p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(b) + b); p.stdin.flush()
def rcv():
    n = 0
    while True:
        l = p.stdout.readline().strip()
        if not l: break
        if l.lower().startswith(b"content-length"): n = int(l.split(b":")[1])
    return json.loads(p.stdout.read(n))
U = "file:///a.zmy"
snd({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
caps = rcv()["result"]["capabilities"]
check("capabilities", caps.get("hoverProvider") and caps.get("documentFormattingProvider") and caps.get("codeActionProvider"))
t = "Let a number be called x\nset x to 5\nrepeat 3 time:\n    print x\nprnt x\nKindly set x to 6 and then print x.\n"
snd({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {"uri": U, "text": t}}})
ds = rcv()["params"]["diagnostics"]
check("two errors at once", [d["range"]["start"]["line"] for d in ds] == [2, 4], ds)
check("suggestions in diagnostics", ds and "repeat 3 times:" in ds[0]["message"])
snd({"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover", "params": {"textDocument": {"uri": U}, "position": {"line": 5, "character": 2}}})
h = rcv()["result"]["contents"]["value"]
check("hover explains", "set x to 6" in h and "print x" in h, h)
snd({"jsonrpc": "2.0", "id": 3, "method": "textDocument/codeAction", "params": {"textDocument": {"uri": U}, "context": {"diagnostics": ds[:1]}}})
acts = rcv()["result"]
check("quick fix", acts and acts[0]["edit"]["changes"][U][0]["newText"] == "repeat 3 times:", acts)
good = "Let a number be called x\nKindly set x to 6 and then print x.\n"
snd({"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {"textDocument": {"uri": U}, "contentChanges": [{"text": good}]}})
check("no errors in a good program", rcv()["params"]["diagnostics"] == [])
snd({"jsonrpc": "2.0", "id": 4, "method": "textDocument/formatting", "params": {"textDocument": {"uri": U}}})
e = rcv()["result"]
check("formatting", e and e[0]["newText"] == "Let a number be called x\nset x to 6\nprint x\n", e)
snd({"jsonrpc": "2.0", "id": 5, "method": "shutdown"}); rcv(); snd({"jsonrpc": "2.0", "method": "exit"})
check("clean exit", p.wait(timeout=10) == 0)
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
