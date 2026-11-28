"""HalfKAv2 features, the integer reference evaluation and the file format of apexz.nnue (shared by trainer and tests)."""
import numpy as np, struct
NF = 64 * 704
KIND = {"p": 0, "n": 1, "b": 2, "r": 3, "q": 4, "k": 5}
def fen_pieces(fen, mirror=False):
    parts = fen.split()
    out = []; r = 7; f = 0
    for ch in parts[0]:
        if ch == "/": r -= 1; f = 0
        elif ch.isdigit(): f += int(ch)
        else: out.append((ch, r * 8 + (f ^ 7 if mirror else f))); f += 1
    return out, parts[1] == "w"
def feat_index(persp, ksq_o, ch, sq):
    """HalfKAv2 index. persp 0 = white, 1 = black (board flipped vertically). ksq_o is the oriented own king square."""
    white = ch.isupper(); k = KIND[ch.lower()]
    plane = 10 if k == 5 else 2 * k + (0 if white == (persp == 0) else 1)
    so = sq if persp == 0 else sq ^ 56
    return ksq_o * 704 + plane * 64 + so
def features(fen, mirror=False):
    """([white-perspective indices], [black-perspective indices], white_to_move)"""
    pcs, w = fen_pieces(fen, mirror)
    wk = next(s for c, s in pcs if c == "K"); bk = next(s for c, s in pcs if c == "k")
    fw = [feat_index(0, wk, c, s) for c, s in pcs]
    fb = [feat_index(1, bk ^ 56, c, s) for c, s in pcs]
    return fw, fb, w
MAGIC = b"APXN"
class Net:
    """integer network. ft_b[H], ft_w[NF][H] (int16); l1_w[L1][2H] int16, l1_b int32; l2_w[L2][L1], l2_b; o_w[L2], o_b (dense weights int16, scale 1024; ft scale 254, so layer 1 divides by 2048)."""
    def __init__(s, ft_b, ft_w, l1_w, l1_b, l2_w, l2_b, o_w, o_b, K=400):
        s.K = K; s.ft_b, s.ft_w, s.l1_w, s.l1_b, s.l2_w, s.l2_b, s.o_w, s.o_b = ft_b, ft_w, l1_w, l1_b, l2_w, l2_b, o_w, o_b
        s.H = len(ft_b); s.L1 = len(l1_b); s.L2 = len(l2_b)
    def evaluate(s, fen):
        """centipawns from the side to move"""
        fw, fb, white = features(fen)
        aw = s.ft_b.astype(np.int64) + s.ft_w[fw].astype(np.int64).sum(0)
        ab = s.ft_b.astype(np.int64) + s.ft_w[fb].astype(np.int64).sum(0)
        x = np.concatenate([aw, ab] if white else [ab, aw])
        x = np.clip(x, 0, 254)
        a1 = (np.clip(s.l1_b.astype(np.int64) + s.l1_w.astype(np.int64) @ x, 0, None) + 1024) // 2048
        a1 = np.minimum(a1, 127)
        a2 = np.minimum((np.clip(s.l2_b.astype(np.int64) + s.l2_w.astype(np.int64) @ a1, 0, None) + 512) // 1024, 127)
        out = int(s.o_b) + int(s.o_w.astype(np.int64) @ a2)
        return int(out * s.K / (1024 * 127)) if out >= 0 else -int((-out) * s.K / (1024 * 127))
    def save(s, path):
        with open(path, "wb") as f:
            f.write(MAGIC + struct.pack(">HHHH", s.H, s.L1, s.L2, s.K))
            f.write(s.ft_b.astype(">i2").tobytes()); f.write(s.ft_w.astype(">i2").tobytes())
            f.write(s.l1_w.astype(">i2").tobytes()); f.write(s.l1_b.astype(">i4").tobytes())
            f.write(s.l2_w.astype(">i2").tobytes()); f.write(s.l2_b.astype(">i4").tobytes())
            f.write(s.o_w.astype(">i2").tobytes()); f.write(np.array([s.o_b]).astype(">i4").tobytes())
    @staticmethod
    def load(path):
        d = open(path, "rb").read(); assert d[:4] == MAGIC
        H, L1, L2, K = struct.unpack(">HHHH", d[4:12]); p = 12
        def take(n, dt):
            nonlocal p
            a = np.frombuffer(d, dtype=dt, count=n, offset=p).astype(np.int64 if dt != "i1" else np.int64); p += n * np.dtype(dt).itemsize; return a
        ft_b = take(H, ">i2"); ft_w = take(NF * H, ">i2").reshape(NF, H)
        l1_w = take(L1 * 2 * H, ">i2").reshape(L1, 2 * H); l1_b = take(L1, ">i4")
        l2_w = take(L2 * L1, ">i2").reshape(L2, L1); l2_b = take(L2, ">i4")
        o_w = take(L2, ">i2"); o_b = int(take(1, ">i4")[0])
        return Net(ft_b, ft_w, l1_w, l1_b, l2_w, l2_b, o_w, o_b, K)
