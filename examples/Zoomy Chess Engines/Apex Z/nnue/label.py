#!/usr/bin/env python3
"""label.py ENGINE IN.txt OUT.txt : adds the engine's hand-written static evaluation (white's view) as a 4th field"""
import subprocess, sys, os
eng, fin, fout = sys.argv[1:4]
p = subprocess.Popen([eng], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, cwd=os.path.dirname(os.path.abspath(eng)))
p.stdin.write("uci\n"); p.stdin.flush()
while p.stdout.readline().strip() != "uciok": pass
lines = [l.rstrip("\n") for l in open(fin)]
out = open(fout, "w")
B = 1000
for i in range(0, len(lines), B):
    chunk = lines[i:i + B]
    cmd = "".join(f"position fen {l.split('|')[0]}\nhceval\n" for l in chunk)
    p.stdin.write(cmd); p.stdin.flush()
    for l in chunk:
        r = p.stdout.readline().split()
        while r[0] != "hceval": r = p.stdout.readline().split()
        v = int(r[1]); w = l.split("|")[0].split()[1] == "w"
        out.write(f"{l}|{v if w else -v}\n")
p.stdin.write("quit\n"); p.stdin.flush()
