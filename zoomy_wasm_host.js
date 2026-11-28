// Runs a Zoomy .wasm program under Node.js (WASI preview 1):  node zoomy_wasm_host.js program.wasm
// The program's standard input, output and error are this process's; files it opens are looked up in the current directory.
// It runs in a worker thread with a large stack, so deeply recursive programs get the Zoomy error instead of a crash.
const fs = require("fs");
const { Worker, isMainThread, workerData, parentPort } = require("node:worker_threads");

if (isMainThread) {
  const file = process.argv[2];
  if (!file) { console.error("usage: node zoomy_wasm_host.js program.wasm"); process.exit(2); }
  const w = new Worker(__filename, { workerData: { file }, resourceLimits: { stackSizeMb: 512 }, stdin: false, env: { ...process.env, NODE_NO_WARNINGS: "1" } });
  w.on("message", (code) => { process.exitCode = code; });
  w.on("error", (e) => { console.error("zoomy: " + e.message); process.exitCode = 1; });
} else {
  const { WASI } = require("node:wasi");
  const { file } = workerData;
  const wasi = new WASI({ version: "preview1", args: [file], env: {}, preopens: { ".": "." }, returnOnExit: true });
  // standard input and output are done here (not by node:wasi): a full or empty pipe must make us wait, not lose data
  const imports = wasi.getImportObject();
  const w = imports.wasi_snapshot_preview1;
  const { fd_write, fd_read } = w;
  let mem = null;
  const nap = new Int32Array(new SharedArrayBuffer(4));
  const retry = (f) => { for (;;) { try { return f(); } catch (e) { if (e.code !== "EAGAIN") throw e; Atomics.wait(nap, 0, 0, 2); } } };
  w.fd_write = (fd, iovs, n, nw) => {
    if (fd !== 1 && fd !== 2) return fd_write(fd, iovs, n, nw);
    const d = new DataView(mem.buffer);
    let total = 0;
    for (let i = 0; i < n; i++) {
      const p = d.getUint32(iovs + 8 * i, true), l = d.getUint32(iovs + 8 * i + 4, true);
      const buf = Buffer.from(mem.buffer, p, l);
      let off = 0;
      try { while (off < l) off += retry(() => fs.writeSync(fd, buf, off, l - off)); } catch (e) { return 29; }
      total += l;
    }
    d.setUint32(nw, total, true);
    return 0;
  };
  w.fd_read = (fd, iovs, n, nr) => {
    if (fd !== 0) return fd_read(fd, iovs, n, nr);
    const d = new DataView(mem.buffer);
    const p = d.getUint32(iovs, true), l = d.getUint32(iovs + 4, true);
    let got = 0;
    try { got = retry(() => fs.readSync(0, Buffer.from(mem.buffer, p, l), 0, l, null)); } catch (e) { if (e.code !== "EOF") return 29; }
    d.setUint32(nr, got, true);
    return 0;
  };
  WebAssembly.compile(fs.readFileSync(file)).then((m) => WebAssembly.instantiate(m, imports)).then((inst) => {
    mem = inst.exports.memory;
    try {
      parentPort.postMessage(wasi.start(inst));
    } catch (e) {
      if (e instanceof RangeError) {
        fs.writeSync(2, "zoomy: runtime error: too many nested calls (a function calls itself without stopping?)\n");
        parentPort.postMessage(255);
      } else throw e;
    }
  }).catch((e) => { fs.writeSync(2, "zoomy: " + e.message + "\n"); parentPort.postMessage(1); });
}
