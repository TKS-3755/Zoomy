"""the VS Code extension's client (editors/vscode/extension.js), run under node with a stand-in for the 'vscode' and
'vscode-languageclient' modules: it must find tools/zoomy_lsp.py, start it with the right command, and stop it again.
(A real VS Code is not available here; this checks the extension's own code, not the editor.)"""
import os, shutil, subprocess, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0
if not shutil.which("node"):
    print("skipped: node is not installed")
    print("0 failure(s)")
    sys.exit(0)
JS = r'''
const Module = require("module"), path = require("path"), assert = require("assert");
const root = process.argv[1];
const log = {};
const cfg = {serverPath: "", python: "python3"};
const fakeVscode = {
  workspace: {workspaceFolders: [{uri: {fsPath: root}}], getConfiguration: () => ({get: k => cfg[k]})},
};
class FakeClient {
  constructor(id, name, run, opts) { log.id = id; log.run = run; log.opts = opts; }
  start() { log.started = true; return Promise.resolve(); }
  stop() { log.stopped = true; return Promise.resolve(); }
}
const orig = Module._load;
Module._load = function (req, ...rest) {
  if (req === "vscode") return fakeVscode;
  if (req === "vscode-languageclient/node") return {LanguageClient: FakeClient};
  return orig.call(this, req, ...rest);
};
const ext = require(path.join(root, "editors/vscode/extension.js"));
ext.activate({subscriptions: []});
assert(log.started, "client was not started");
assert.strictEqual(log.run.command, "python3");
assert.strictEqual(log.run.args[0], path.join(root, "tools", "zoomy_lsp.py"));
assert.deepStrictEqual(log.opts.documentSelector, [{language: "zoomy"}]);
ext.deactivate().then(() => { assert(log.stopped); console.log(JSON.stringify(log.run)); });
'''
r = subprocess.run(["node", "-e", JS, HERE], capture_output=True, text=True, cwd=HERE)
if r.returncode != 0:
    fails += 1
    print("FAIL extension.js", r.stderr[-400:])
else:
    # the command the extension starts must really be a working server
    import json
    run = json.loads(r.stdout.strip().splitlines()[-1])
    p = subprocess.Popen([sys.executable] + run["args"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    body = b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
    p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body); p.stdin.flush()
    head = p.stdout.readline()
    p.kill()
    if not head.lower().startswith(b"content-length"):
        fails += 1
        print("FAIL server did not answer", head)
for f in ("syntaxes/zoomy.tmLanguage.json",):
    import json
    g = json.load(open(os.path.join(HERE, "editors/vscode", f)))
    kinds = {x.get("name") for x in g["patterns"]}
    for want in ("comment.line.zoomy", "string.quoted.double.zoomy", "keyword.control.zoomy", "constant.numeric.zoomy"):
        if want not in kinds:
            fails += 1
            print("FAIL grammar lacks", want)
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
