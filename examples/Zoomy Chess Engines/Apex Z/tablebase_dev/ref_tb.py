# Reference Syzygy table-level prober (clean Python port of Fathom's algorithm), mirrors the planned Zoomy code.
import os, struct
OffDiag=[0 if r==c else (1 if r>c else -1) for r in range(8) for c in range(8)]
Triangle=[6,0,1,2,2,1,0,6, 0,7,3,4,4,3,7,0, 1,3,8,5,5,8,3,1, 2,4,5,9,9,5,4,2, 2,4,5,9,9,5,4,2, 1,3,8,5,5,8,3,1, 0,7,3,4,4,3,7,0, 6,0,1,2,2,1,0,6]
FlipDiag=[(s%8)*8+s//8 for s in range(64)]
Lower=[28,0,1,2,3,4,5,6, 0,29,7,8,9,10,11,12, 1,7,30,13,14,15,16,17, 2,8,13,31,18,19,20,21, 3,9,14,18,32,22,23,24, 4,10,15,19,22,33,25,26, 5,11,16,20,23,25,34,27, 6,12,17,21,24,26,27,35]
Diag=[0,0,0,0,0,0,0,8, 0,1,0,0,0,0,9,0, 0,0,2,0,0,10,0,0, 0,0,0,3,11,0,0,0, 0,0,0,12,4,0,0,0, 0,0,13,0,0,5,0,0, 0,14,0,0,0,0,6,0, 15,0,0,0,0,0,0,7]
Flap=[[0,0,0,0,0,0,0,0, 0,6,12,18,18,12,6,0, 1,7,13,19,19,13,7,1, 2,8,14,20,20,14,8,2, 3,9,15,21,21,15,9,3, 4,10,16,22,22,16,10,4, 5,11,17,23,23,17,11,5, 0,0,0,0,0,0,0,0],
      [0,0,0,0,0,0,0,0, 0,1,2,3,3,2,1,0, 4,5,6,7,7,6,5,4, 8,9,10,11,11,10,9,8, 12,13,14,15,15,14,13,12, 16,17,18,19,19,18,17,16, 20,21,22,23,23,22,21,20, 0,0,0,0,0,0,0,0]]
PawnTwist=[[0,0,0,0,0,0,0,0, 47,35,23,11,10,22,34,46, 45,33,21,9,8,20,32,44, 43,31,19,7,6,18,30,42, 41,29,17,5,4,16,28,40, 39,27,15,3,2,14,26,38, 37,25,13,1,0,12,24,36, 0,0,0,0,0,0,0,0],
           [0,0,0,0,0,0,0,0, 47,45,43,41,40,42,44,46, 39,37,35,33,32,34,36,38, 31,29,27,25,24,26,28,30, 23,21,19,17,16,18,20,22, 15,13,11,9,8,10,12,14, 7,5,3,1,0,2,4,6, 0,0,0,0,0,0,0,0]]
FileToFile=[0,1,2,3,3,2,1,0]
WdlToMap=[1,3,0,2,0]; PAFlags=[8,0,0,0,4]
# KKIdx: generated like Fathom's table
def make_kkidx():
    # table rows indexed by Triangle value of the first king (0..9); entry = index of 2nd king square, -1 if illegal
    # derive: enumerate legal (k1 in triangle rep, k2) pairs in order. Use Fathom's explicit table instead (extracted below).
    return None
Binomial=[[0]*64 for _ in range(7)]
for i in range(7):
    for j in range(64):
        f=1;l=1
        for k in range(i): f*=(j-k); l*=(k+1)
        Binomial[i][j]=f//l
PawnIdx=[[[0]*24 for _ in range(6)] for _ in range(2)]
PawnFactorFile=[[0]*4 for _ in range(6)]
PawnFactorRank=[[0]*6 for _ in range(6)]
for i in range(6):
    s=0
    for j in range(24):
        PawnIdx[0][i][j]=s
        s+=Binomial[i][PawnTwist[0][(1+(j%6))*8+(j//6)]]
        if (j+1)%6==0: PawnFactorFile[i][j//6]=s; s=0
for i in range(6):
    s=0
    for j in range(24):
        PawnIdx[1][i][j]=s
        s+=Binomial[i][PawnTwist[1][(1+(j//4))*8+(j%4)]]
        if (j+1)%4==0: PawnFactorRank[i][j//4]=s; s=0
from kkidx import KKIdx_flat
KKIdx=[KKIdx_flat[i*64:(i+1)*64] for i in range(10)]
MAGIC=[0x5d23e871,0x88ac504b,0xa50c66d7]
WDL,DTM,DTZ=0,1,2
PIECE_ENC,FILE_ENC,RANK_ENC=0,1,2
def u16(b,o): return b[o]|(b[o+1]<<8)
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
def subfactor(k,n):
    f=n;l=1
    for i in range(1,k): f*=n-i; l*=i+1
    return f//l
class Pairs: pass
class EI:
    def __init__(s): s.pieces=[0]*7; s.norm=[0]*7; s.factor=[0]*7; s.pre=None
class Table:
    def __init__(s,path,name,typ):
        s.name=name; s.typ=typ
        s.data=open(path,'rb').read()
        w,b=name.split('v'); s.w=w; s.b=b
        s.pcs=[0]*16
        code={'P':1,'N':2,'B':3,'R':4,'Q':5,'K':6}
        for ch in w: s.pcs[code[ch]]+=1
        for ch in b: s.pcs[8+code[ch]]+=1
        s.num=sum(s.pcs); s.hasPawns=bool(s.pcs[1] or s.pcs[9])
        s.symmetric=(w==b)
        if not s.hasPawns:
            s.kk_enc=sum(1 for c in s.pcs if c==1)==2
        else:
            s.pawns=[s.pcs[1],s.pcs[9]]
            if s.pcs[9] and (not s.pcs[1] or s.pcs[1]>s.pcs[9]): s.pawns.reverse()
        self_init(s)
def init_enc_info(ei,be,d,pos,shift,t,enc):
    more = 1 if (enc!=PIECE_ENC and be.pawns[1]>0) else 0
    for i in range(be.num):
        ei.pieces[i]=(d[pos+i+1+more]>>shift)&15; ei.norm[i]=0
    order=(d[pos]>>shift)&15
    order2=((d[pos+1]>>shift)&15) if more else 15
    k = be.pawns[0] if enc!=PIECE_ENC else (2 if be.kk_enc else 3)
    ei.norm[0]=k
    if more: ei.norm[k]=be.pawns[1]; k+=ei.norm[k]
    i=k
    while i<be.num:
        j=i
        while j<be.num and ei.pieces[j]==ei.pieces[i]: ei.norm[i]+=1; j+=1
        i+=ei.norm[i]
    n=64-k; f=1; i=0
    while k<be.num or i==order or i==order2:
        if i==order:
            ei.factor[0]=f
            f*= PawnFactorFile[ei.norm[0]-1][t] if enc==FILE_ENC else PawnFactorRank[ei.norm[0]-1][t] if enc==RANK_ENC else (462 if be.kk_enc else 31332)
        elif i==order2:
            ei.factor[ei.norm[0]]=f; f*=subfactor(ei.norm[ei.norm[0]],48-ei.norm[0])
        else:
            ei.factor[k]=f; f*=subfactor(ei.norm[k],n); n-=ei.norm[k]; k+=ei.norm[k]
        i+=1
    return f
def setup_pairs(d,pos,tb_size,typ):
    p=Pairs(); p.flags=d[pos]
    if d[pos]&0x80:
        p.idxBits=0; p.const=d[pos+1] if typ==WDL else 0
        return p,pos+2,(0,0,0)
    blockSize=d[pos+1]; idxBits=d[pos+2]; real=u32(d,pos+4); numBlocks=real+d[pos+3]
    maxLen=d[pos+8]; minLen=d[pos+9]; h=maxLen-minLen+1
    numSyms=u16(d,pos+10+2*h)
    p.blockSize=blockSize; p.idxBits=idxBits; p.minLen=minLen; p.h=h
    p.offset=[u16(d,pos+10+2*i) for i in range(h)]
    p.symPat=pos+12+2*h; p.numSyms=numSyms
    newpos=pos+12+2*h+3*numSyms+(numSyms&1)
    nidx=(tb_size+(1<<idxBits)-1)>>idxBits
    size=(6*nidx,2*numBlocks,real<<blockSize)
    p.symLen=[None]*numSyms
    import sys; sys.setrecursionlimit(10000)
    def calc(s):
        w=p.symPat+3*s
        s2=(d[w+2]<<4)|(d[w+1]>>4)
        if s2==0xfff: p.symLen[s]=0
        else:
            s1=((d[w+1]&15)<<8)|d[w]
            if p.symLen[s1] is None: calc(s1)
            if p.symLen[s2] is None: calc(s2)
            p.symLen[s]=p.symLen[s1]+p.symLen[s2]+1
    for s in range(numSyms):
        if p.symLen[s] is None: calc(s)
    base=[0]*h
    for i in range(h-2,-1,-1):
        base[i]=(base[i+1]+p.offset[i]-p.offset[i+1])//2
    p.base=[base[i]<<(64-(p.minLen+i)) for i in range(h)]
    return p,newpos,size
def self_init(be):
    d=be.data; typ=be.typ
    assert u32(d,0)==MAGIC[typ]
    split = typ!=DTZ and (d[4]&1)
    pos=5
    num = 4 if be.hasPawns else 1
    be.num_t=num
    be.ei=[EI() for _ in range(num*2)]
    enc = PIECE_ENC if not be.hasPawns else (FILE_ENC if typ!=DTM else RANK_ENC)
    tb_size=[[0,0] for _ in range(num)]
    for t in range(num):
        tb_size[t][0]=init_enc_info(be.ei[t],be,d,pos,0,t,enc)
        if split: tb_size[t][1]=init_enc_info(be.ei[num+t],be,d,pos,4,t,enc)
        pos+=be.num+1+(1 if (be.hasPawns and be.pawns[1]) else 0)
    pos+=pos&1
    sizes=[[None,None] for _ in range(num)]
    be.dtzFlags=[0]*num
    for t in range(num):
        p,pos,sz=setup_pairs(d,pos,tb_size[t][0],typ); be.ei[t].pre=p; sizes[t][0]=sz
        if typ==DTZ: be.dtzFlags[t]=p.flags
        if split:
            p,pos,sz=setup_pairs(d,pos,tb_size[t][1],typ); be.ei[num+t].pre=p; sizes[t][1]=sz
    be.dtzMapIdx=[[0]*4 for _ in range(num)]
    be.mapbase=0
    if typ==DTZ:
        be.mapbase=pos
        for t in range(num):
            fl=be.dtzFlags[t]
            if fl&2:
                if not fl&16:
                    for i in range(4):
                        be.dtzMapIdx[t][i]=pos+1-be.mapbase; pos+=1+d[pos]
                else:
                    pos+=pos&1
                    for i in range(4):
                        be.dtzMapIdx[t][i]=(pos+2-be.mapbase)//2; pos+=2+2*u16(d,pos)
        pos+=pos&1
    for t in range(num):
        be.ei[t].pre.indexTable=pos; pos+=sizes[t][0][0]
        if split: be.ei[num+t].pre.indexTable=pos; pos+=sizes[t][1][0]
    for t in range(num):
        be.ei[t].pre.sizeTable=pos; pos+=sizes[t][0][1]
        if split: be.ei[num+t].pre.sizeTable=pos; pos+=sizes[t][1][1]
    for t in range(num):
        pos=(pos+0x3f)&~0x3f; be.ei[t].pre.data=pos; pos+=sizes[t][0][2]
        if split:
            pos=(pos+0x3f)&~0x3f; be.ei[num+t].pre.data=pos; pos+=sizes[t][1][2]
def encode(p,ei,be,enc):
    n=be.num
    if p[0]&4:
        for i in range(n): p[i]^=7
    if enc==PIECE_ENC:
        if p[0]&0x20:
            for i in range(n): p[i]^=0x38
        for i in range(n):
            if OffDiag[p[i]]:
                if OffDiag[p[i]]>0 and i<(2 if be.kk_enc else 3):
                    for j in range(n): p[j]=FlipDiag[p[j]]
                break
        if be.kk_enc:
            idx=KKIdx[Triangle[p[0]]][p[1]]; k=2
        else:
            s1=1 if p[1]>p[0] else 0
            s2=(p[2]>p[0])+(p[2]>p[1])
            if OffDiag[p[0]]: idx=Triangle[p[0]]*63*62+(p[1]-s1)*62+(p[2]-s2)
            elif OffDiag[p[1]]: idx=6*63*62+Diag[p[0]]*28*62+Lower[p[1]]*62+p[2]-s2
            elif OffDiag[p[2]]: idx=6*63*62+4*28*62+Diag[p[0]]*7*28+(Diag[p[1]]-s1)*28+Lower[p[2]]
            else: idx=6*63*62+4*28*62+4*7*28+Diag[p[0]]*7*6+(Diag[p[1]]-s1)*6+(Diag[p[2]]-s2)
            k=3
        idx*=ei.factor[0]
    else:
        for i in range(1,be.pawns[0]):
            for j in range(i+1,be.pawns[0]):
                if PawnTwist[enc-1][p[i]]<PawnTwist[enc-1][p[j]]: p[i],p[j]=p[j],p[i]
        k=be.pawns[0]
        idx=PawnIdx[enc-1][k-1][Flap[enc-1][p[0]]]
        for i in range(1,k): idx+=Binomial[k-i][PawnTwist[enc-1][p[i]]]
        idx*=ei.factor[0]
        if be.pawns[1]:
            t=k+be.pawns[1]
            for i in range(k,t):
                for j in range(i+1,t):
                    if p[i]>p[j]: p[i],p[j]=p[j],p[i]
            s=0
            for i in range(k,t):
                sq=p[i]; skips=0
                for j in range(k): skips+=(sq>p[j])
                s+=Binomial[i-k+1][sq-skips-8]
            idx+=s*ei.factor[k]; k=t
    while k<n:
        t=k+ei.norm[k]
        for i in range(k,t):
            for j in range(i+1,t):
                if p[i]>p[j]: p[i],p[j]=p[j],p[i]
        s=0
        for i in range(k,t):
            sq=p[i]; skips=0
            for j in range(k): skips+=(sq>p[j])
            s+=Binomial[i-k+1][sq-skips]
        idx+=s*ei.factor[k]; k=t
    return idx
def decompress(be,d,idx):
    data=be.data
    if not d.idxBits: return d.const,0
    mainIdx=idx>>d.idxBits
    litIdx=(idx&((1<<d.idxBits)-1))-(1<<(d.idxBits-1))
    block=u32(data,d.indexTable+6*mainIdx)
    litIdx+=u16(data,d.indexTable+6*mainIdx+4)
    if litIdx<0:
        while litIdx<0:
            block-=1; litIdx+=u16(data,d.sizeTable+2*block)+1
    else:
        while litIdx>u16(data,d.sizeTable+2*block):
            litIdx-=u16(data,d.sizeTable+2*block)+1; block+=1
    ptr=d.data+(block<<d.blockSize)
    m=d.minLen
    code=int.from_bytes(data[ptr:ptr+8],'big'); ptr+=8
    bitCnt=0; M=(1<<64)-1
    while True:
        l=m
        while code<d.base[l-m]: l+=1
        sym=d.offset[l-m]+((code-d.base[l-m])>>(64-l))
        if litIdx<d.symLen[sym]+1: break
        litIdx-=d.symLen[sym]+1
        code=(code<<l)&M
        bitCnt+=l
        if bitCnt>=32:
            bitCnt-=32
            tmp=int.from_bytes(data[ptr:ptr+4],'big'); ptr+=4
            code|=tmp<<bitCnt
    while d.symLen[sym]!=0:
        w=d.symPat+3*sym
        s1=((data[w+1]&15)<<8)|data[w]
        if litIdx<d.symLen[s1]+1: sym=s1
        else:
            litIdx-=d.symLen[s1]+1
            sym=(data[w+2]<<4)|(data[w+1]>>4)
    w=d.symPat+3*sym
    return data[w],data[w+1]
def probe_table(be,sqs,turn,s=0):
    """sqs: piececode(1..6 white, 9..14 black) -> squares in position's own colours. returns raw value or None"""
    typ=be.typ
    if not be.symmetric:
        same=all(len(sqs.get(c,[]))==be.pcs[c] for c in list(range(1,7))+list(range(9,15)))
        flip=not same
        bside=((turn==0)==flip)
    else:
        flip=(turn!=0); bside=False
    p=[0]*7
    def fill_sq(ei,mirror,i):
        pc=ei.pieces[i]; col=(pc>>3)^(1 if flip else 0); key=(pc&7)|(col<<3)
        for sq in sorted(sqs.get(key,[])):
            p[i]=sq^mirror; i+=1
        return i
    flags=0; t=0
    if not be.hasPawns:
        if typ==DTZ:
            flags=be.dtzFlags[0]
            if (flags&1)!=bside and not be.symmetric: return None
        ei=be.ei[bside] if typ!=DTZ else be.ei[0]
        i=0
        while i<be.num: i=fill_sq(ei,0,i)
        idx=encode(p,ei,be,PIECE_ENC)
    else:
        ei0=be.ei[0]
        i=fill_sq(ei0,0x38 if flip else 0,0)
        for k in range(1,be.pawns[0]):
            if Flap[0][p[0]]>Flap[0][p[k]]: p[0],p[k]=p[k],p[0]
        t=FileToFile[p[0]&7]
        if typ==DTZ:
            flags=be.dtzFlags[t]
            if (flags&1)!=bside and not be.symmetric: return None
        ei=be.ei[t+4*bside] if typ==WDL else be.ei[t]
        while i<be.num: i=fill_sq(ei,0x38 if flip else 0,i)
        idx=encode(p,ei,be,FILE_ENC)
    w0,w1=decompress(be,ei.pre,idx)
    if typ==WDL: return w0-2
    v=w0+((w1&15)<<8)
    if flags&2:
        m=WdlToMap[s+2]; mp=be.data
        if not flags&16: v=mp[be.mapbase+be.dtzMapIdx[t][m]+v]
        else: v=u16(mp,be.mapbase+2*(be.dtzMapIdx[t][m]+v))
    if not (flags&PAFlags[s+2]) or (s&1): v*=2
    return v
