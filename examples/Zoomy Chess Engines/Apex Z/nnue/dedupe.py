#!/usr/bin/env python3
"""dedupe.py IN.txt OUT.txt [--exclude OTHER.txt ...] [--average]
Removes duplicate positions from a training file (lines "fen|score|result[|hce]").  Two lines are the same position when board, side to move,
castling rights and en passant square agree (the move counters are ignored).  By default the first line of a position is kept; with --average the
score, result and hce of all copies are averaged into one line (less noisy than any single search).  --exclude removes every position that
occurs in another file, e.g. the held-out test set, so that nothing the net is tested on is also trained on."""
import sys
args = sys.argv[1:]; fin, fout = args[0], args[1]
avg = "--average" in args; excl = [args[i + 1] for i, a in enumerate(args) if a == "--exclude"]
key = lambda fen: " ".join(fen.split()[:4])
banned = set()
for fn in excl:
    for l in open(fn): banned.add(key(l.split("|", 1)[0]))
seen = {}; order = []; total = dropped_ex = 0
for l in open(fin):
    l = l.rstrip("\n"); f = l.split("|")
    if len(f) < 3: continue
    total += 1; k = key(f[0])
    if k in banned: dropped_ex += 1; continue
    if k in seen:
        if avg:
            s = seen[k]; s[0] += 1
            for j in range(1, len(f)): s[j] += float(f[j])
        continue
    seen[k] = [1] + [float(x) for x in f[1:]]; order.append((k, l))
with open(fout, "w") as o:
    for k, fen in order:
        s = seen[k]
        if avg: o.write(fen.split("|")[0] + "|" + "|".join(str(int(round(v / s[0]))) if j != 2 else "%.3f" % (v / s[0]) for j, v in enumerate(s[1:], 1)) + "\n")
        else: o.write(fen + "\n")
print(f"{total} lines, {total - len(order) - dropped_ex} duplicates removed, {dropped_ex} excluded, {len(order)} kept")
