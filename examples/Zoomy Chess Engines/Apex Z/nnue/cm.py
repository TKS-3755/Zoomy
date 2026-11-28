"""Tiny chess rules in Python (legal moves, FEN, UCI moves) for the NNUE data generator and tests."""
import random
KN=[(1,2),(2,1),(-1,2),(-2,1),(1,-2),(2,-1),(-1,-2),(-2,-1)]
KG=[(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]
RD=KG[:4]; BD=KG[4:]
START="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
def sq(f,r): return r*8+f
def name(s): return "abcdefgh"[s&7]+str((s>>3)+1)
def parse(n): return ord(n[0])-97+8*(int(n[1])-1)
class Board:
    def __init__(s,fen=START):
        p=fen.split(); s.b=[None]*64
        r=7;f=0
        for ch in p[0]:
            if ch=="/": r-=1;f=0
            elif ch.isdigit(): f+=int(ch)
            else: s.b[sq(f,r)]=ch; f+=1
        s.white=p[1]=="w"; s.castle=set(p[2]) - {"-"}
        s.ep=None if p[3]=="-" else parse(p[3])
        s.half=int(p[4]) if len(p)>4 else 0; s.full=int(p[5]) if len(p)>5 else 1
        s.hist=[s.key()]
    def key(s): return (tuple(s.b),s.white,frozenset(s.castle),s.ep if s.ep_ok() else None)
    def ep_ok(s):
        if s.ep is None: return False
        pawn="P" if s.white else "p"; d=-1 if s.white else 1
        for df in (-1,1):
            f=(s.ep&7)+df; r=(s.ep>>3)+d
            if 0<=f<8 and 0<=r<8 and s.b[sq(f,r)]==pawn: return True
        return False
    def fen(s):
        rows=[]
        for r in range(7,-1,-1):
            row="";e=0
            for f in range(8):
                c=s.b[sq(f,r)]
                if c is None: e+=1
                else:
                    if e: row+=str(e);e=0
                    row+=c
            if e: row+=str(e)
            rows.append(row)
        cs="".join(c for c in "KQkq" if c in s.castle) or "-"
        return " ".join(["/".join(rows),"w" if s.white else "b",cs,name(s.ep) if s.ep is not None else "-",str(s.half),str(s.full)])
    def own(s,c): return c is not None and (c.isupper()==s.white)
    def attacked(s,t,by_white):
        f,r=t&7,t>>3
        pawn="P" if by_white else "p"; d=-1 if by_white else 1
        for df in (-1,1):
            ff,rr=f+df,r+d
            if 0<=ff<8 and 0<=rr<8 and s.b[sq(ff,rr)]==pawn: return True
        kn="N" if by_white else "n"
        for df,dr in KN:
            ff,rr=f+df,r+dr
            if 0<=ff<8 and 0<=rr<8 and s.b[sq(ff,rr)]==kn: return True
        kg="K" if by_white else "k"
        for df,dr in KG:
            ff,rr=f+df,r+dr
            if 0<=ff<8 and 0<=rr<8 and s.b[sq(ff,rr)]==kg: return True
        for dirs,pcs in ((RD,"RQ" if by_white else "rq"),(BD,"BQ" if by_white else "bq")):
            for df,dr in dirs:
                ff,rr=f+df,r+dr
                while 0<=ff<8 and 0<=rr<8:
                    c=s.b[sq(ff,rr)]
                    if c is not None:
                        if c in pcs: return True
                        break
                    ff+=df;rr+=dr
        return False
    def king(s,white): return s.b.index("K" if white else "k")
    def in_check(s): return s.attacked(s.king(s.white),not s.white)
    def pseudo(s):
        out=[]; w=s.white
        for t in range(64):
            c=s.b[t]
            if not s.own(c): continue
            k=c.upper(); f,r=t&7,t>>3
            if k=="P":
                d=1 if w else -1; r1=r+d
                promo=(r1==7) if w else (r1==0)
                def add(to,cap=False):
                    if promo:
                        for pc in "qrbn": out.append((t,to,pc))
                    else: out.append((t,to,None))
                if 0<=r1<8 and s.b[sq(f,r1)] is None:
                    add(sq(f,r1))
                    if r==(1 if w else 6) and s.b[sq(f,r+2*d)] is None: out.append((t,sq(f,r+2*d),None))
                for df in (-1,1):
                    ff=f+df
                    if 0<=ff<8 and 0<=r1<8:
                        to=sq(ff,r1); o=s.b[to]
                        if o is not None and not s.own(o): add(to)
                        elif to==s.ep and o is None: out.append((t,to,None))
            elif k in "NK":
                for df,dr in (KN if k=="N" else KG):
                    ff,rr=f+df,r+dr
                    if 0<=ff<8 and 0<=rr<8:
                        o=s.b[sq(ff,rr)]
                        if o is None or not s.own(o): out.append((t,sq(ff,rr),None))
                if k=="K":
                    home=0 if w else 7
                    if t==sq(4,home) and not s.in_check():
                        K,Q=("K","Q") if w else ("k","q")
                        if K in s.castle and s.b[sq(5,home)] is None and s.b[sq(6,home)] is None and s.b[sq(7,home)]==("R" if w else "r") \
                           and not s.attacked(sq(5,home),not w) and not s.attacked(sq(6,home),not w): out.append((t,sq(6,home),None))
                        if Q in s.castle and s.b[sq(3,home)] is None and s.b[sq(2,home)] is None and s.b[sq(1,home)] is None and s.b[sq(0,home)]==("R" if w else "r") \
                           and not s.attacked(sq(3,home),not w) and not s.attacked(sq(2,home),not w): out.append((t,sq(2,home),None))
            else:
                dirs=(RD if k=="R" else BD if k=="B" else KG)
                for df,dr in dirs:
                    ff,rr=f+df,r+dr
                    while 0<=ff<8 and 0<=rr<8:
                        o=s.b[sq(ff,rr)]
                        if o is None: out.append((t,sq(ff,rr),None))
                        else:
                            if not s.own(o): out.append((t,sq(ff,rr),None))
                            break
                        ff+=df;rr+=dr
        return out
    def push(s,m):
        a,t,pr=m; c=s.b[a]; k=c.upper(); cap=s.b[t]
        s.half=0 if (k=="P" or cap is not None) else s.half+1
        if not s.white: s.full+=1
        s.b[a]=None
        if k=="P" and t==s.ep and cap is None:
            s.b[t-8 if s.white else t+8]=None
        s.b[t]=(pr.upper() if s.white else pr) if pr else c
        if k=="K" and abs(t-a)==2:
            home=a-4
            if t>a: s.b[a+3]=None; s.b[a+1]="R" if s.white else "r"
            else: s.b[a-4]=None; s.b[a-1]="R" if s.white else "r"
        s.ep=None
        if k=="P" and abs(t-a)==16: s.ep=(a+t)//2
        for q,cr in ((0,"Q"),(7,"K"),(56,"q"),(63,"k")):
            if a==q or t==q: s.castle.discard(cr)
        if k=="K":
            if s.white: s.castle-={"K","Q"}
            else: s.castle-={"k","q"}
        s.white=not s.white
        s.hist.append(s.key())
    def legal(s):
        out=[]
        for m in s.pseudo():
            n=s.copy(); n.push(m)
            if not n.attacked(n.king(not n.white),n.white): out.append(m)
        return out
    def copy(s):
        n=Board.__new__(Board); n.b=s.b[:]; n.white=s.white; n.castle=set(s.castle); n.ep=s.ep; n.half=s.half; n.full=s.full; n.hist=s.hist[:]
        return n
    def uci(s,m): return name(m[0])+name(m[1])+(m[2] or "")
    def push_uci(s,u):
        for m in s.legal():
            if s.uci(m)==u: s.push(m); return
        raise ValueError("illegal "+u+" in "+s.fen())
    def insufficient(s):
        ps=[c for c in s.b if c and c.upper()!="K"]
        if not ps: return True
        if len(ps)==1 and ps[0].upper() in "NB": return True
        return False
    def rep(s): return s.hist.count(s.hist[-1])>=3
perft_cache=None
def perft(b,d):
    if d==0: return 1
    n=0
    for m in b.legal():
        c=b.copy(); c.push(m); n+=perft(c,d-1)
    return n
if __name__=="__main__":
    print(perft(Board(),3), perft(Board("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),2))
