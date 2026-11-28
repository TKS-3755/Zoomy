# APEX-Z benchmark results (all runs from the v2.1 -> v3.1 work)

Scripts (scripts/): each splices the engine source (everything before "MAIN GAME ENTRY") with a driver, builds it
natively with ../zoomy5/zoomy.py and runs it. Paths assume they sit in a folder next to zoomy5/.
- perft.py v30.zmy            move generator vs published perft counts
- selfplay.py ENGINE D SEEDS  pruning on/off at the same depth: node ratio, same move/score, illegal moves
- tactics.py ENGINE           mates and a knight fork, pruned and plain
- match.py ENGINE DA DB GAMES PLIES MASK OFFSET   pruned engine (depth DA, pruning mask) vs plain depth DB
- match2.py ENGINE DEPTH GAMES PLIES FEAT_A FEAT_B [OFFSET]   two feat settings at the same depth (v31.zmy)
- dev.py ENGINE D SEEDS       root score of each pruning technique alone vs plain search
- sym.py ENGINE               evaluation symmetry on mirrored positions

## Results
v2.1 (hand rewrite, one recursive search) vs the original unrolled v2.0: identical output over ~1,000 engine moves in 100+
scripted games (castling, promotion, mate); about 1.3x slower in time (0.65 s vs 0.52 s on one test game).

Perft (v3.0 and v3.1): start 20/400/8902/197281, kiwipete 48/2039/97862, position 3 14/191/2812/43238,
kiwipete-black 43/2053/86656, ep-black 30/865/25743: all match the published numbers.

selfplay depth 4, 4 seeds: 216 positions, 0 illegal moves, node ratio plain/pruned = 36x, same best move 57%, same score 45%,
score within 60 cp 82%.

dev.py depth 4, 56 positions: full pruning gives the same score as plain on every position; only late-move pruning (32)
(2 positions differ by >150) and quiescence pruning (256, mean abs diff 11) change anything.

Matches, pruned (A, mask 511) vs plain depth 4 (B); adv = average advantage for A in centipawns:
- depth 5, 6 games: A 1, B 3, 2 draws; nodes A 0.39M vs B 4.8M (first run)
- depth 5, 14 games: A 3, B 9, 2 draws, adv -666 (nodes 1.1M vs 15.9M)
- depth 6, 14 games: A 3, B 6, 5 draws, adv -180
- depth 7, 14 games: A 3, B 5, 6 draws, adv -356
- depth 8,  6 games: A 2, B 2, 2 draws, adv +142 (nodes 4.6M vs 7.3M)
- depth 9,  6 games: A 3, B 1, 2 draws, adv +496 (nodes 12.2M vs 8.0M)
- plain depth 5 (mask 0) vs plain depth 4, 14 games: A 8, B 3, 3 draws, adv +741
One technique alone (mask) at depth 5, 6 games each (A wins/B wins/draws): TT 5/0/1, reverse futility 5/1/0, razoring 3/1/2,
null move 3/1/2, futility 3/1/2, late-move pruning 1/2/3, late-move reductions 1/2/3, aspiration 5/0/1, quiescence pruning 4/0/2.
Conclusion: pruning loses at 5-7 plies and wins from 8, so the default became 8.

v3.1 (feat bit mask: 1 new evaluation, 2 mate distance pruning, 4 internal iterative reduction), same depth 6:
- feat 7 vs feat 0, 12 games: A 7, B 1, 4 draws, adv +361
- feat 1 vs feat 0, 12 games: A 8, B 0, 4 draws, adv +476
- feat 7 vs feat 1, 14 games: A 6, B 6, 2 draws, adv +194; feat 5 vs feat 1: identical
Evaluation symmetry: 8 mirrored positions all exactly opposite.
Tactics (depth 6): back-rank mate, scholar's mate, rook ladder mate, black mate in 1 all found (score 79998); knight fork found;
the queen is not hung.

## v3.2 (feat bits 8 repetition draws, 16 counter moves, 32 history-aware reductions; incremental hash)
perft counts unchanged and the incrementally updated hash equals a full scan after every move in the perft trees (0 mismatches).
Speed: no change (about 195k positions/s before and after). Strength at equal depth, A vs B = feat 7 (v3.1):
- depth 6, 14 games: feat 63: 5-6-3 (adv -95); feat 15: 4-6-4 (adv -232)
- depth 8, 10 games: feat 63: 1-7-2 (adv -398); feat 47 (no counter moves): 3-3-4 (adv -35)
Conclusion: none of the three helped (counter moves looked harmful); repetition draws kept as a correctness feature (default feat 15
= v3.1 plus repetition draws), counter moves and history reductions left off.

## Time per move by depth (timing.py, one core, v3.2)
| depth | opening | middlegame | tactical (kiwipete) | endgame |
|---|---|---|---|---|
| 8  | 0.5 s (63k) | 0.1 s (19k) | 0.5 s (77k) | 0.0 s (10k) |
| 10 | 0.8 s (142k) | 0.6 s (106k) | 1.7 s (280k) | 0.1 s (24k) |
| 11 | 1.3 s (255k) | 0.9 s (171k) | 2.9 s (457k) | 0.2 s (69k) |
| 12 | 2.2 s (408k) | 2.4 s (413k) | 5.7 s (931k) | 0.3 s (103k) |
| 13 | 3.7 s (683k) | 3.8 s (677k) | 8.2 s (1.4M) | 0.5 s (157k) |
| 14 | 9.8 s (1.9M) | 6.2 s (1.1M) | 11.3 s (1.9M) | 0.8 s (240k) |

## Automatic depth (v3.2)
auto_depth counts knights, bishops, rooks and queens of both sides (start = 6400): >= 5600 -> 11 plies, <= 3200 -> 14, else 10.
Game "0 / e2e4 / g1f3 / d2d4 / b1c3": 4 engine moves in 4.9 s total at 11 plies (0.09-0.38M positions each).
