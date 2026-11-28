"""Version 2 network (file magic APX2): king buckets with the board mirrored left to right, pairwise product of the accumulator halves, clipped and squared layer 1 with a skip to the output, one set of dense layers per piece count bucket.  Integer reference evaluation, file format and features (shared by trainer and tests)."""
import numpy as np, struct
from nnue import fen_pieces, KIND
NF2 = 32 * 704
MAGIC = b"APX2"
def king_bucket(ksq_o):
    f = ksq_o & 7; r = ksq_o >> 3
    return (r * 4 + (7 - f if f >= 4 else f)), f >= 4
def feat_index2(persp, ksq_o, ch, sq):
    b, mir = king_bucket(ksq_o)
    white = ch.isupper(); k = KIND[ch.lower()]
    plane = 10 if k == 5 else 2 * k + (0 if white == (persp == 0) else 1)
    so = sq if persp == 0 else sq ^ 56
    if mir: so ^= 7
    return b * 704 + plane * 64 + so
def features2(fen, mirror=False):
    """([white indices], [black indices], white_to_move, piece_count)"""
    pcs, w = fen_pieces(fen, mirror)
    wk = next(s for c, s in pcs if c == "K"); bk = next(s for c, s in pcs if c == "k")
    return ([feat_index2(0, wk, c, s) for c, s in pcs], [feat_index2(1, bk ^ 56, c, s) for c, s in pcs], w, len(pcs))
def bucket_of(n, nb): return min(nb - 1, max(0, (n - 1) // 4))
class Net2:
    """ft_b[H], ft_w[NF2][H]; per bucket b: l1_w[b][L1][H], l1_b[b][L1], l2_w[b][L2][2*L1], l2_b[b][L2], o_w[b][L2], s_w[b][L1], o_b[b]  (dense weights scale 1024, ft scale 254)"""
    def __init__(s, ft_b, ft_w, l1_w, l1_b, l2_w, l2_b, o_w, s_w, o_b, K=400):
        s.K = K; s.ft_b, s.ft_w, s.l1_w, s.l1_b, s.l2_w, s.l2_b, s.o_w, s.s_w, s.o_b = ft_b, ft_w, l1_w, l1_b, l2_w, l2_b, o_w, s_w, o_b
        s.H = len(ft_b); s.NB = len(l1_b); s.L1 = l1_b.shape[1]; s.L2 = l2_b.shape[1]
    def evaluate(s, fen):
        fw, fb, white, n = features2(fen)
        H = s.H; hh = H // 2
        aw = s.ft_b.astype(np.int64) + s.ft_w[fw].astype(np.int64).sum(0)
        ab = s.ft_b.astype(np.int64) + s.ft_w[fb].astype(np.int64).sum(0)
        a, o = (aw, ab) if white else (ab, aw)
        a = np.clip(a, 0, 254); o = np.clip(o, 0, 254)
        x = np.concatenate([a[:hh] * a[hh:] // 254, o[:hh] * o[hh:] // 254])
        b = bucket_of(n, s.NB)
        v = (s.l1_b[b].astype(np.int64) + s.l1_w[b].astype(np.int64) @ x + 1024) // 2048
        c = np.clip(v, 0, 127); q = c * c // 127
        y = np.concatenate([c, q])
        w = np.clip((s.l2_b[b].astype(np.int64) + s.l2_w[b].astype(np.int64) @ y + 512) // 1024, 0, 127)
        out = int(s.o_b[b]) + int(s.o_w[b].astype(np.int64) @ w) + int(s.s_w[b].astype(np.int64) @ c)
        return int(out * s.K / (1024 * 127)) if out >= 0 else -int((-out) * s.K / (1024 * 127))
    def save(s, path):
        with open(path, "wb") as f:
            f.write(MAGIC + struct.pack(">HHHHH", s.H, s.L1, s.L2, s.K, s.NB))
            f.write(s.ft_b.astype(">i2").tobytes()); f.write(s.ft_w.astype(">i2").tobytes())
            for b in range(s.NB):
                f.write(s.l1_w[b].astype(">i2").tobytes()); f.write(s.l1_b[b].astype(">i4").tobytes())
                f.write(s.l2_w[b].astype(">i2").tobytes()); f.write(s.l2_b[b].astype(">i4").tobytes())
                f.write(s.o_w[b].astype(">i2").tobytes()); f.write(s.s_w[b].astype(">i2").tobytes())
                f.write(np.array([s.o_b[b]]).astype(">i4").tobytes())
    @staticmethod
    def load(path):
        d = open(path, "rb").read(); assert d[:4] == MAGIC
        H, L1, L2, K, NB = struct.unpack(">HHHHH", d[4:14]); p = 14
        def take(n, dt):
            nonlocal p
            a = np.frombuffer(d, dtype=dt, count=n, offset=p).astype(np.int64); p += n * np.dtype(dt).itemsize; return a
        ft_b = take(H, ">i2"); ft_w = take(NF2 * H, ">i2").reshape(NF2, H)
        l1w, l1b, l2w, l2b, ow, sw, ob = [], [], [], [], [], [], []
        for _ in range(NB):
            l1w.append(take(L1 * H, ">i2").reshape(L1, H)); l1b.append(take(L1, ">i4"))
            l2w.append(take(L2 * 2 * L1, ">i2").reshape(L2, 2 * L1)); l2b.append(take(L2, ">i4"))
            ow.append(take(L2, ">i2")); sw.append(take(L1, ">i2")); ob.append(int(take(1, ">i4")[0]))
        return Net2(ft_b, ft_w, np.array(l1w), np.array(l1b), np.array(l2w), np.array(l2b), np.array(ow), np.array(sw), np.array(ob), K)
