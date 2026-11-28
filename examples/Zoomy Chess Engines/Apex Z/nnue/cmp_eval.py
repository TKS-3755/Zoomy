import sys, subprocess, random, os
sys.path.insert(0, "/tmp/zt/nn")
import nnue
net = nnue.Net.load(sys.argv[2])
lines = [l.split("|")[0] for l in open(sys.argv[3])][:int(sys.argv[4])]
p = subprocess.Popen([sys.argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, cwd=os.path.dirname(os.path.abspath(sys.argv[1])))
def send(s): p.stdin.write(s + "\n"); p.stdin.flush()
send("uci")
while p.stdout.readline().strip() != "uciok": pass
bad = 0
for fen in lines:
    send("position fen " + fen); send("nneval")
    l = p.stdout.readline().split()
    want = net.evaluate(fen)
    if int(l[1]) != want: bad += 1; print("MISMATCH", fen, l, want)
print("checked", len(lines), "mismatches", bad)
send("quit")
