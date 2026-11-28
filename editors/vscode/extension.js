// Starts tools/zoomy_lsp.py for .zmy files. Needs `npm install` in this folder (vscode-languageclient).
const path = require("path");
const fs = require("fs");
const vscode = require("vscode");
const { LanguageClient } = require("vscode-languageclient/node");
let client;
function activate(context) {
  const cfg = vscode.workspace.getConfiguration("zoomy");
  let server = cfg.get("serverPath");
  if (!server) {
    for (const f of vscode.workspace.workspaceFolders || []) {
      const c = path.join(f.uri.fsPath, "tools", "zoomy_lsp.py");
      if (fs.existsSync(c)) { server = c; break; }
    }
  }
  if (!server) return;
  const run = { command: cfg.get("python") || "python3", args: [server] };
  client = new LanguageClient("zoomy", "Zoomy", run, { documentSelector: [{ language: "zoomy" }] });
  client.start();
}
function deactivate() { return client ? client.stop() : undefined; }
module.exports = { activate, deactivate };
