"""the browser playground, driven in a real (headless) browser.
Needs a local copy of Pyodide (the 'core' release, pyodide.js + pyodide.asm.*) in $ZOOMY_PYODIDE, plus Playwright;
without them this test says so and skips (the page itself loads Pyodide from a CDN)."""
import os, sys, tempfile, threading, functools, http.server, shutil
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
fails = 0
def check(name, ok, info=""):
    global fails
    if not ok:
        fails += 1
        print("FAIL", name, info)
pyo = os.environ.get("ZOOMY_PYODIDE", "")
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
if not (pyo and os.path.isfile(os.path.join(pyo, "pyodide.js"))) or sync_playwright is None:
    print("skipped: set ZOOMY_PYODIDE to a Pyodide folder (and install playwright) to test the playground in a browser")
    print("0 failure(s)")
    sys.exit(0)
import build_playground
with tempfile.TemporaryDirectory() as d:
    os.symlink(os.path.abspath(pyo), os.path.join(d, "pyodide"))
    build_playground.build(os.path.join(d, "index.html"), "/pyodide")
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=d))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        pg.on("console", lambda m: print("console:", m.text[:200]) if os.environ.get("ZOOMY_DEBUG") else None)
        pg.on("pageerror", lambda e: print("pageerror:", str(e)[:300]))
        pg.goto(url)
        pg.wait_for_function("!document.getElementById('run').disabled", timeout=120000)
        pg.wait_for_function("document.getElementById('status').textContent.startsWith('Reads fine')", timeout=60000)
        check("starts and the example reads", True)
        pg.click("#run")
        pg.wait_for_function("document.getElementById('status').textContent.startsWith('Finished')", timeout=60000)
        check("hello runs", "Hello" in pg.inner_text("#view"), pg.inner_text("#view"))
        # a mistake: plain-English error and a one-click fix
        pg.fill("#src", "Let a number be called x\nset x to 5\nrepeat 3 time:\n    print x\n")
        pg.wait_for_function("document.getElementById('status').className=='bad'", timeout=30000)
        st = pg.inner_text("#status")
        check("error shown", "line 3" in st and "times" in st, st)
        check("fix offered", "Change to: repeat 3 times:" in st, st)
        pg.click("#fix")
        pg.wait_for_function("document.getElementById('status').className=='good'", timeout=30000)
        check("fix applied", "repeat 3 times:" in pg.input_value("#src"))
        pg.click("#run")
        pg.wait_for_function("document.getElementById('status').textContent.startsWith('Finished')", timeout=60000)
        check("fixed program runs", pg.inner_text("#view").split() == ["5", "5", "5"], pg.inner_text("#view"))
        # how it was read, the Python, format
        pg.fill("#src", "Let a number be called x\nKindly set x to 6 and then print x.\n")
        pg.click("button[data-t=explain]")
        pg.wait_for_function("document.getElementById('view').textContent.includes('only a polite')", timeout=30000)
        check("explain tab", True)
        pg.click("button[data-t=python]")
        pg.wait_for_function("document.getElementById('view').textContent.includes('z_x')", timeout=30000)
        check("python tab", True)
        pg.click("#fmt")
        pg.wait_for_function("document.getElementById('src').value.includes('set x to 6\\nprint x')", timeout=30000)
        check("format", True)
        # input and a program that never ends can be stopped
        pg.fill("#src", "Let a number be called x\nset x to 1\nwhile x is more than 0:\n    add 1 to x\n")
        pg.wait_for_function("document.getElementById('status').className!='bad'", timeout=30000)
        pg.click("#run")
        pg.wait_for_function("!document.getElementById('stop').disabled", timeout=10000)
        pg.click("#stop")
        pg.wait_for_function("!document.getElementById('run').disabled", timeout=120000)
        check("stop works", "(stopped)" in pg.inner_text("#view"), pg.inner_text("#view"))
        b.close()
    srv.shutdown()
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
