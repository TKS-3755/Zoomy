#!/usr/bin/env python3
"""feat.py IN OUT.npz START COUNT : candidate evaluation terms (white minus black) for positions of IN (fen|score|result|hce)."""
import sys, numpy as np
N_KN=[[] for _ in range(64)]; N_KG=[[] for _ in range(64)]
for s in range(64):
    r,f=divmod(s,8)
    for dr,df in ((1,2),(2,1),(-1,2),(-2,1),(1,-2),(2,-1),(-1,-2),(-2,-1)):
        if 0<=r+dr<8 and 0<=f+df<8: N_KN[s].append((r+dr)*8+f+df)
    for dr in (-1,0,1):
        for df in (-1,0,1):
            if (dr or df) and 0<=r+dr<8 and 0<=f+df<8: N_KG[s].append((r+dr)*8+f+df)
DIAG=((1,1),(1,-1),(-1,1),(-1,-1)); ORTH=((1,0),(-1,0),(0,1),(0,-1))
def rays(b,s,dirs):
    r,f=divmod(s,8); out=[]
    for dr,df in dirs:
        rr,ff=r+dr,f+df
        while 0<=rr<8 and 0<=ff<8:
            q=rr*8+ff; out.append(q)
            if b[q]: break
            rr+=dr; ff+=df
    return out
NF=35
def feats(fen):
    parts=fen.split(); rows=parts[0].split('/'); b=[None]*64
    for i,rk in enumerate(rows):
        r=7-i; f=0
        for ch in rk:
            if ch.isdigit(): f+=int(ch)
            else: b[r*8+f]=ch; f+=1
    wtm = parts[1]=='w'
    pcs={'w':{'P':[],'N':[],'B':[],'R':[],'Q':[],'K':[]},'b':{'P':[],'N':[],'B':[],'R':[],'Q':[],'K':[]}}
    for s in range(64):
        c=b[s]
        if c: pcs['w' if c.isupper() else 'b'][c.upper()].append(s)
    nb=len(pcs['w']['N'])+len(pcs['w']['B'])+len(pcs['b']['N'])+len(pcs['b']['B'])
    nr=len(pcs['w']['R'])+len(pcs['b']['R']); nq=len(pcs['w']['Q'])+len(pcs['b']['Q'])
    ph=min(24,nb+2*nr+4*nq)
    npw=len(pcs['w']['P'])+len(pcs['b']['P'])
    # attack maps
    att={'w':set(),'b':set()}; patt={'w':set(),'b':set()}; cnt={'w':{},'b':{}}
    def add(col,sq):
        att[col].add(sq); cnt[col][sq]=cnt[col].get(sq,0)+1
    for col,sg in (('w',1),('b',-1)):
        for s in pcs[col]['P']:
            r,f=divmod(s,8)
            for df in (-1,1):
                if 0<=f+df<8 and 0<=r+sg<8: q=(r+sg)*8+f+df; patt[col].add(q); add(col,q)
        for s in pcs[col]['N']:
            for q in N_KN[s]: add(col,q)
        for s in pcs[col]['B']:
            for q in rays(b,s,DIAG): add(col,q)
        for s in pcs[col]['R']:
            for q in rays(b,s,ORTH): add(col,q)
        for s in pcs[col]['Q']:
            for q in rays(b,s,DIAG+ORTH): add(col,q)
        for s in pcs[col]['K']:
            for q in N_KG[s]: add(col,q)
    F=np.zeros(NF)
    for col,sg in (('w',1),('b',-1)):
        opp='b' if col=='w' else 'w'; osg=-sg
        own=pcs[col]; foe=pcs[opp]
        ksq=own['K'][0] if own['K'] else None; oksq=foe['K'][0] if foe['K'] else None
        v=np.zeros(NF)
        mypawns=set(own['P']); foepawns=set(foe['P'])
        pfiles_own=[0]*8; pfiles_foe=[0]*8
        for s in own['P']: pfiles_own[s%8]+=1
        for s in foe['P']: pfiles_foe[s%8]+=1
        def rel(s): return s//8 if col=='w' else 7-s//8
        # minors
        for kind,idx_out in (('N',0),('B',1)):
            for s in own[kind]:
                r,f=divmod(s,8); rr=rel(s)
                supported = any(((r-sg)*8+f+df) in mypawns for df in (-1,1) if 0<=f+df<8 and 0<=r-sg<8)
                if supported: v[3]+=1
                if 3<=rr<=5 and supported:
                    can=False
                    for ps in foe['P']:
                        pr,pf=divmod(ps,8)
                        if abs(pf-f)==1 and ((pr>r) if col=='w' else (pr<r)): can=True;break
                    if not can: v[idx_out]+=1
                if kind=='B':
                    sc=(r+f)%2
                    v[2]+=sum(1 for ps in own['P'] if ((ps//8)+(ps%8))%2==sc)
        # rooks
        rf=[s%8 for s in own['R']]
        if len(rf)==2: v[4]+= (rf[0]==rf[1])
        if len(own['R'])>=2: v[27]+=1
        for s in own['R']:
            f=s%8
            if oksq is not None and oksq%8==f and pfiles_own[f]==0: v[16]+=1
        # passed pawns
        for s in own['P']:
            r,f=divmod(s,8); rr=rel(s)
            passed=True
            for ps in foe['P']:
                pr,pf=divmod(ps,8)
                if abs(pf-f)<=1 and ((pr>r) if col=='w' else (pr<r)): passed=False;break
            if passed:
                stop=(r+sg)*8+f if 0<=r+sg<8 else None
                if stop is not None:
                    if b[stop] is None: v[5]+=rr*rr
                    else: v[6]+=rr*rr
                    if ksq is not None and oksq is not None:
                        dk=max(abs(oksq//8-stop//8),abs(oksq%8-stop%8)); dm=max(abs(ksq//8-stop//8),abs(ksq%8-stop%8))
                        v[7]+=(dk-dm)*rr
                v[28]+=1
            # structure
            neigh=[q for q in ((r*8+f-1) if f>0 else None,(r*8+f+1) if f<7 else None) if q is not None]
            if any(q in mypawns for q in neigh): v[8]+=1
            if any(((r-sg)*8+f+df) in mypawns for df in (-1,1) if 0<=f+df<8 and 0<=r-sg<8): v[9]+=1
            # backward
            stop=(r+sg)*8+f if 0<=r+sg<8 else None
            if stop is not None and stop in patt[opp]:
                behind=False
                for ps in own['P']:
                    pr,pf=divmod(ps,8)
                    if abs(pf-f)==1 and ((pr<=r) if col=='w' else (pr>=r)): behind=True;break
                if not behind: v[10]+=1
        # pawn islands
        isl=0; prev=False
        for f in range(8):
            has=pfiles_own[f]>0
            if has and not prev: isl+=1
            prev=has
        v[11]+=isl
        # king
        if ksq is not None:
            kr,kf=divmod(ksq,8); krr=rel(ksq)
            if krr<=1:
                for df in (-1,0,1):
                    ff=kf+df
                    if 0<=ff<8:
                        for d in (1,2):
                            rr_=kr+sg*d
                            if 0<=rr_<8 and (rr_*8+ff) in mypawns: v[12]+=1
            for ps in foe['P']:
                pr,pf=divmod(ps,8)
                if abs(pf-kf)<=1:
                    dist=(pr-kr)*sg
                    if 0<dist<=4: v[13]+=5-dist
            if pfiles_own[kf]==0: v[14]+=1
            if pfiles_own[kf]==0 and pfiles_foe[kf]==0: v[14]+=1
            for df in (-1,1):
                if 0<=kf+df<8 and pfiles_own[kf+df]==0: v[15]+=1
        # space
        sp=0
        for f in range(2,6):
            for rrr in (1,2,3):
                r=rrr if col=='w' else 7-rrr; s=r*8+f
                if s not in patt[opp] and (b[s] is None or b[s]==('P' if col=='w' else 'p')): sp+=1
        v[17]+=sp
        # threats against opp pieces by me
        for kind,w in (('N',1),('B',1),('R',1),('Q',1)):
            for s in foe[kind]:
                if s in patt[col]: v[18]+=1
                if s in att[col] and s not in att[opp]: v[19]+=1
                if kind in ('R','Q') and s in att[col]:
                    # attacked by minor?
                    pass
        # my pieces hanging attacked by opponent minors/pawns counted from opp side loops; mobility-like extras
        # queen attacked by minor/rook: approximate using attack counts
        for s in foe['Q']:
            if cnt[col].get(s,0)>0 and s not in patt[col]: v[20]+=1
        # imbalance
        v[21]+=len(own['N'])*(npw-8)/8; v[22]+=len(own['R'])*(npw-8)/8; v[23]+=len(own['B'])*(npw-8)/8
        # knight pair, queen with minors
        if len(own['N'])>=2: v[24]+=1
        v[25]+=len(own['Q'])*(len(own['N'])+len(own['B']))
        # king attackers beyond existing: attacked squares near enemy king by my pieces count
        if oksq is not None:
            z=[oksq]+N_KG[oksq]
            v[26]+=sum(cnt[col].get(q,0) for q in z)
            v[34]+=sum(1 for q in z if q in att[col])
        # pawns advanced beyond rank 5 supported
        for s in own['P']:
            if rel(s)>=4 and s in patt[col]: v[29]+=1
        # central control
        for q in (27,28,35,36):
            if q in att[col]: v[30]+=1
        # pieces developed (minors off back rank)
        for kind in ('N','B'):
            for s in own[kind]:
                if rel(s)==0: v[31]+=1
        # king mobility/exposure: squares around king attacked by enemy
        if ksq is not None:
            v[32]+=sum(1 for q in N_KG[ksq] if q in att[opp])
        v[33]+=len(own['P'])
        F+=sg*v
    F[27]*=1  # rook pair
    return F, ph, (1 if wtm else -1)
if __name__=="__main__":
    fin,out,start,count=sys.argv[1],sys.argv[2],int(sys.argv[3]),int(sys.argv[4])
    Fs=[];P=[];S=[];R=[];H=[];T=[];STM=[]
    with open(fin) as fh:
        for i,line in enumerate(fh):
            if i<start: continue
            if i>=start+count: break
            fen,sc,res,hce=line.rstrip().split('|')
            f,ph,stm=feats(fen)
            Fs.append(f);P.append(ph);R.append(float(res));H.append(int(hce));T.append(int(sc));STM.append(stm)
    np.savez(out,F=np.array(Fs),ph=np.array(P),res=np.array(R),hce=np.array(H),sc=np.array(T),stm=np.array(STM))
    print("done",len(Fs))
