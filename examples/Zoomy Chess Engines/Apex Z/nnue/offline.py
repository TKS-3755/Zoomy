import sys, numpy as np
sys.path.insert(0,'/tmp/zt/nn'); import nnue2
net = nnue2.Net2.load(sys.argv[1]); rows=[]
for l in open(sys.argv[2]):
    f=l.rstrip().split('|'); fen,sc,res,h=f[0],int(f[1]),float(f[2]),int(f[3])
    if abs(sc)>2500: continue
    w=fen.split()[1]=='w'; nn=net.evaluate(fen); nn = nn if w else -nn   # white view
    rows.append((sc,res,h,nn))
a=np.array(rows,float); sc,res,h,nn=a.T
print("n",len(a)," std score %.0f  std hce-score %.0f  std nn %.0f  std (score-hce) %.0f"%(sc.std(),(h-sc).std(),nn.std(),(sc-h).std()))
print("corr(nn, score-hce) %.3f"%np.corrcoef(nn,sc-h)[0,1])
sg=lambda x:1/(1+np.exp(-x/400))
for s in (0,.25,.5,1,1.5):
    e=h+s*nn
    print("scale %.2f  MSE vs score(cp^2) %.0f   sigmoid-MSE vs score %.5f  vs result %.5f"%(s,((e-sc)**2).mean(),((sg(e)-sg(sc))**2).mean(),((sg(e)-res)**2).mean()))
