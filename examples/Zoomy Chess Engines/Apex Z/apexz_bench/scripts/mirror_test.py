import subprocess,sys
eng=sys.argv[1]; feat=sys.argv[2]
FENS=["r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1","8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1","rnbqkb1r/pp2pppp/3p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R b KQkq - 0 1","r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 8","6k1/5p2/6p1/8/7P/6P1/5PK1/8 w - - 0 1"]
def mirror(f):
    p=f.split(); rows=p[0].split("/")[::-1]; rows=[r.swapcase() for r in rows]
    c=p[2]; c2="".join(sorted(((x.swapcase()) for x in c), key=lambda x:"KQkq".index(x))) if c!="-" else "-"
    return " ".join([ "/".join(rows), "b" if p[1]=="w" else "w", c2, "-", p[4],p[5]])
def score(fen):
    pr=subprocess.Popen([eng],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    out=pr.communicate(f"uci\nsetoption name Threads value 1\nsetoption name OwnBook value false\nsetoption name Features value {feat}\nposition fen {fen}\ngo depth 1\nquit\n")[0]
    return [l for l in out.splitlines() if l.startswith("info depth 1 ")][0].split("score ")[1].split()[1]
bad=0
for f in FENS:
    a,b=score(f),score(mirror(f)); print(a,b,"OK" if a==b else "DIFF"); bad+=a!=b
print("bad",bad)
