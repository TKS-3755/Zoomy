#!/usr/bin/env python3
"""Train the HalfKAv2 net on self-play data.  train.py OUT.nnue EPOCHS H [data files...]
Float model: FT(45056 -> H, with a 704-entry factorizer shared over king squares) -> clip[0,1] on [stm, other] -> L1 -> clip -> L2 -> clip -> 1.
Quantised for the integer evaluation in nnue.py / Apex-Z.zmy."""
import sys, time, numpy as np, scipy.sparse as sp, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nnue
out_path, EPOCHS, H = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
files = sys.argv[4:]
L1, L2, NF, K = int(os.environ.get('L1', '16')), int(os.environ.get('L2', '16')), nnue.NF, float(os.environ.get('K', '1000'))
LAM = float(os.environ.get('LAM', '0.9'))
RESID = int(os.environ.get('RESID', '0'))      # learn what the search finds beyond the hand-written evaluation: score - hce
RCLIP = float(os.environ.get('RCLIP', '2'))
MIRROR = int(os.environ.get('MIRROR', '1'))
rng = np.random.default_rng(1)
# ---- data
cache = out_path + ".cache.npz"
rows_s, rows_n, tgt = [], [], []
t0 = time.time(); n = 0
S = []; N = []; T = []
Sidx = []; Scnt = []; Nidx = []; Ncnt = []; Tarr = []
def flush():
    """turn the lists collected so far into compact arrays (millions of Python lists would not fit in memory)"""
    global S, N, T
    if not T: return
    Scnt.append(np.fromiter((len(l) for l in S), dtype=np.int64, count=len(S)))
    Sidx.append(np.fromiter((i for l in S for i in l), dtype=np.int32))
    Ncnt.append(np.fromiter((len(l) for l in N), dtype=np.int64, count=len(N)))
    Nidx.append(np.fromiter((i for l in N for i in l), dtype=np.int32))
    Tarr.append(np.array(T, dtype=np.float64))
    S = []; N = []; T = []
for fn in files:
    for line in open(fn):
        try:
            fld = line.rstrip("\n").split("|")
            fen, sc, res = fld[:3]
            sc = int(sc); res = float(res)
            if abs(sc) > 2500: continue
            hce = int(fld[3]) if RESID else 0
            fw, fb, white = nnue.features(fen)
            mw, mb, _ = nnue.features(fen, True)
        except Exception:
            continue
        if not white: sc = -sc; res = 1 - res; hce = -hce
        S.append(fw if white else fb); N.append(fb if white else fw)
        T.append((sc, res, hce))
        if MIRROR:                                   # the board turned left to right: same score
            S.append(mw if white else mb); N.append(mb if white else mw)
            T.append((sc, res, hce))
        if len(T) >= 200000: flush()
flush()
T = np.concatenate(Tarr); n = len(T)
print("positions", n, "load %.0fs" % (time.time() - t0), flush=True)
def csr(cnts, idxs):
    c = np.concatenate(cnts); indptr = np.zeros(len(c) + 1, dtype=np.int64); indptr[1:] = np.cumsum(c)
    return np.concatenate(idxs), indptr
Si, Sp = csr(Scnt, Sidx); Ni, Np = csr(Ncnt, Nidx)
del Sidx, Nidx, Tarr
G = 2 if MIRROR else 1                               # a position and its mirror image stay on the same side of the split
gperm = rng.permutation(n // G); ngv = max(1000, n // G // 40)
expand = lambda g: (g[:, None] * G + np.arange(G)[None, :]).ravel()
val, trn = expand(gperm[:ngv]), expand(gperm[ngv:])
def batch(ids):
    def build(idx, ptr):
        cnt = ptr[ids + 1] - ptr[ids]
        ind = np.concatenate([idx[ptr[i]:ptr[i + 1]] for i in ids])
        pp = np.zeros(len(ids) + 1, dtype=np.int64); pp[1:] = np.cumsum(cnt)
        m = sp.csr_matrix((np.ones(len(ind), dtype=np.float32), ind, pp), shape=(len(ids), NF))
        mv = sp.csr_matrix((np.ones(len(ind), dtype=np.float32), ind % 704, pp), shape=(len(ids), 704))
        return m, mv
    xs, xsv = build(Si, Sp); xn, xnv = build(Ni, Np)
    sc, res = T[ids, 0], T[ids, 1]
    if RESID:
        y = np.clip((sc - T[ids, 2]) / K, -RCLIP, RCLIP)
    else:
        y = LAM * (1 / (1 + np.exp(-sc / K))) + (1 - LAM) * res
    return xs, xsv, xn, xnv, y.astype(np.float32)
# ---- model
def init(shape, fan): return (rng.standard_normal(shape) * np.sqrt(1.0 / fan)).astype(np.float32)
P = {"W": np.zeros((NF, H), np.float32), "V": (rng.standard_normal((704, H)) * 0.05).astype(np.float32) + 0.0, "fb": np.zeros(H, np.float32) + 0.1,
     "W1": init((2 * H, L1), 2 * H), "b1": np.zeros(L1, np.float32), "W2": init((L1, L2), L1), "b2": np.zeros(L2, np.float32),
     "W3": init((L2, 1), L2), "b3": np.zeros(1, np.float32)}
Mo = {k: np.zeros_like(v) for k, v in P.items()}; Vo = {k: np.zeros_like(v) for k, v in P.items()}
def forward(xs, xsv, xn, xnv):
    a_s = xs @ P["W"] + xsv @ P["V"] + P["fb"]; a_n = xn @ P["W"] + xnv @ P["V"] + P["fb"]
    cs, cn = np.clip(a_s, 0, 1), np.clip(a_n, 0, 1)
    x = np.concatenate([cs, cn], 1)
    z1 = x @ P["W1"] + P["b1"]; h1 = np.clip(z1, 0, 1)
    z2 = h1 @ P["W2"] + P["b2"]; h2 = np.clip(z2, 0, 1)
    o = (h2 @ P["W3"] + P["b3"])[:, 0]
    return o, (a_s, a_n, x, z1, h1, z2, h2)
def loss_grad(batchd):
    xs, xsv, xn, xnv, y = batchd
    o, (a_s, a_n, x, z1, h1, z2, h2) = forward(xs, xsv, xn, xnv)
    B = len(y)
    if RESID:
        p = o; L = float(np.mean((p - y) ** 2)); do = (2 * (p - y) / B).astype(np.float32)[:, None]
    else:
        p = 1 / (1 + np.exp(-o))
        L = float(np.mean((p - y) ** 2))
        do = (2 * (p - y) * p * (1 - p) / B).astype(np.float32)[:, None]
    g = {}
    g["W3"] = h2.T @ do; g["b3"] = do.sum(0)
    dh2 = do @ P["W3"].T; dz2 = dh2 * ((z2 > 0) & (z2 < 1))
    g["W2"] = h1.T @ dz2; g["b2"] = dz2.sum(0)
    dh1 = dz2 @ P["W2"].T; dz1 = dh1 * ((z1 > 0) & (z1 < 1))
    g["W1"] = x.T @ dz1; g["b1"] = dz1.sum(0)
    dx = dz1 @ P["W1"].T
    ds = dx[:, :H] * ((a_s > 0) & (a_s < 1)); dn = dx[:, H:] * ((a_n > 0) & (a_n < 1))
    g["W"] = np.asarray(xs.T @ ds + xn.T @ dn); g["V"] = np.asarray(xsv.T @ ds + xnv.T @ dn)
    g["fb"] = ds.sum(0) + dn.sum(0)
    return L, g
step = 0
def adam(g, lr):
    global step
    step += 1
    b1, b2 = 0.9, 0.999
    for k in P:
        Mo[k] = b1 * Mo[k] + (1 - b1) * g[k]; Vo[k] = b2 * Vo[k] + (1 - b2) * g[k] ** 2
        mh = Mo[k] / (1 - b1 ** step); vh = Vo[k] / (1 - b2 ** step)
        P[k] -= (lr * mh / (np.sqrt(vh) + 1e-8)).astype(np.float32)
    for k in ("W1", "W2", "W3"): np.clip(P[k], -8, 8, out=P[k])
BS = 4096
def val_loss():
    ids = val[:20000]
    tot = 0; c = 0
    for i in range(0, len(ids), 8192):
        b = batch(ids[i:i + 8192]); o, _ = forward(*b[:4]); p = o if RESID else 1 / (1 + np.exp(-o)); tot += ((p - b[4]) ** 2).sum(); c += len(b[4])
    return tot / c
print("baseline loss (predict 0.5): %.5f" % float(np.mean((0.5 - batch(val[:5000])[4]) ** 2)), flush=True)
t0 = time.time()
for ep in range(EPOCHS):
    lr = 0.004 * (0.5 * (1 + np.cos(np.pi * ep / EPOCHS)) * 0.97 + 0.03)
    rng.shuffle(trn); tl = 0; nb = 0
    for i in range(0, len(trn) - BS + 1, BS):
        L, g = loss_grad(batch(trn[i:i + BS])); adam(g, lr); tl += L; nb += 1
    print("epoch %d train %.5f val %.5f lr %.5f  %.0fs" % (ep, tl / nb, val_loss(), lr, time.time() - t0), flush=True)
    if ep % 5 == 4 or ep == EPOCHS - 1: np.savez(out_path + ".float.npz", **P)
# ---- quantise
def q(a, s, lo, hi): return np.clip(np.round(a * s), lo, hi).astype(np.int64)
Wm = P["W"] + np.tile(P["V"], (64, 1))                       # merge the factorizer: feature f uses V[f % 704]
net = nnue.Net(q(P["fb"], 254, -32768, 32767), q(Wm, 254, -32768, 32767),
               q(P["W1"].T, 1024, -32767, 32767), q(P["b1"], 1024 * 254, -2**31, 2**31 - 1),
               q(P["W2"].T, 1024, -32767, 32767), q(P["b2"], 1024 * 127, -2**31, 2**31 - 1),
               q(P["W3"][:, 0], 1024, -32767, 32767), int(np.round(P["b3"][0] * 1024 * 127)), int(K))
net.save(out_path)
# integer vs float agreement on validation positions
import itertools
err = []
lines = []
for fn in files[:1]:
    for line in itertools.islice(open(fn), 3000): lines.append(line)
for line in lines[:300]:
    fen, sc, res = line.strip().split("|")[:3]
    fw, fb, white = nnue.features(fen)
    xs = sp.csr_matrix((np.ones(len(fw), np.float32), fw, [0, len(fw)]), shape=(1, NF)); xsv = sp.csr_matrix((np.ones(len(fw), np.float32), np.array(fw) % 704, [0, len(fw)]), shape=(1, 704))
    xn = sp.csr_matrix((np.ones(len(fb), np.float32), fb, [0, len(fb)]), shape=(1, NF)); xnv = sp.csr_matrix((np.ones(len(fb), np.float32), np.array(fb) % 704, [0, len(fb)]), shape=(1, 704))
    if not white: xs, xsv, xn, xnv = xn, xnv, xs, xsv
    o, _ = forward(xs, xsv, xn, xnv)
    err.append(abs(o[0] * K - net.evaluate(fen)))
print("float vs integer net, mean |diff| %.1f cp, max %.0f" % (np.mean(err), np.max(err)))
