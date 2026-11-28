# APEX-Z v6.3 benchmarks (current)

All numbers on this page were measured with APEX-Z v6.3 (Zoomy 6.3) on a **1-core** Linux x86-64 machine, one search thread, hash 64 MB, book off.
They are kept apart from the old benchmarks: `../old_v2.1-v3.2/` (the v2.1 to v3.2 development runs) and `../old_v6.0/` (the v6.0 depth benchmark). Do not mix them.

Two builds of the same engine were measured:

- **plain build**: `python3 zoomy.py Apex-Z.zmy --native -o apexz` (155 KB)
- **optimized build**: `python3 zoomy.py Apex-Z.zmy --native --unroll --regs -o apexz` (about 1.7 MB: `--unroll` writes short loops out as straight-line code, `--regs` keeps the four most used variables in registers)

The optimized build plays exactly the same search: the node counts and scores at depth 20 are identical in all three positions. Only the speed differs.

## Depth benchmark: time to reach depth 12 to 20 (seconds, 1 thread)

Plain build:

| Depth | Opening | Kiwipete | Endgame |
|---|---|---|---|
| 12 | 0.64 s | 2.65 s | 0.33 s |
| 13 | 0.90 s | 3.49 s | 0.62 s |
| 14 | 1.34 s | 6.81 s | 0.92 s |
| 15 | 1.62 s | 11.40 s | 1.03 s |
| 16 | 4.06 s | 14.01 s | 1.81 s |
| 17 | 12.37 s | 26.82 s | 2.69 s |
| 18 | 16.40 s | 32.14 s | 4.87 s |
| 19 | 25.14 s | 42.46 s | 7.00 s |
| 20 | 41.58 s | 78.02 s | 7.34 s |

Optimized build:

| Depth | Opening | Kiwipete | Endgame |
|---|---|---|---|
| 12 | 1.00 s | 2.04 s | 0.16 s |
| 13 | 1.31 s | 2.49 s | 0.30 s |
| 14 | 1.65 s | 4.56 s | 0.46 s |
| 15 | 1.81 s | 7.28 s | 0.50 s |
| 16 | 3.39 s | 9.76 s | 0.88 s |
| 17 | 8.73 s | 18.15 s | 1.48 s |
| 18 | 11.30 s | 21.17 s | 2.60 s |
| 19 | 16.84 s | 27.25 s | 3.76 s |
| 20 | 27.45 s | 48.14 s | 3.94 s |

Speed-up of the optimized build at depth 20: opening 1.51x, kiwipete 1.62x, endgame 1.86x.

## Comparison with the old v6.0 depth benchmark (time to depth, seconds)

| Depth | Opening: v6.0 / v6.3 plain / v6.3 opt | Kiwipete: v6.0 / v6.3 plain / v6.3 opt | Endgame: v6.0 / v6.3 plain / v6.3 opt |
|---|---|---|---|
| 12 | 0.71 / 0.64 / 1.00 s | 2.80 / 2.65 / 2.04 s | 0.28 / 0.33 / 0.16 s |
| 14 | 1.50 / 1.34 / 1.65 s | 7.13 / 6.81 / 4.56 s | 0.91 / 0.92 / 0.46 s |
| 16 | 4.51 / 4.06 / 3.39 s | 14.51 / 14.01 / 9.76 s | 1.78 / 1.81 / 0.88 s |
| 18 | 17.40 / 16.40 / 11.30 s | 33.65 / 32.14 / 21.17 s | 5.08 / 4.87 / 2.60 s |
| 20 | 44.16 / 41.58 / 27.45 s | 82.27 / 78.02 / 48.14 s | 7.69 / 7.34 / 3.94 s |

The v6.0 numbers came from a 2-core machine (1-thread column), the v6.3 numbers from a 1-core machine, so differences of about 10-20% in either direction are not meaningful. The search itself is unchanged since v6.0: the node counts are identical at every depth from 1 to 20 in all three positions, so the time columns compare speed only. The old v6.0 table also showed the older v5.0 engine's times in brackets; they are not repeated here (see the main README).

## Full results, plain build

**Correctness**

- perft (5 positions): 0 failure(s)
- evaluation symmetry (8 mirrored positions): 0 asymmetric
- mirror test at depth 1 (Features 262095): bad 0
- tactics (6 positions, depth 6): 0 failure(s)

**Pruning on vs off, depth 4, 4 seeds (selfplay.py)**

```
{'n': 216, 'same_move': 142, 'same_score': 51, 'off': 7670276.0, 'on': 224880.0, 'illegal': 0, 'close': 206} node ratio off/on = 34.1
```

**Each pruning technique alone (dev.py, depth 4, 4 seeds)**

```
positions 32
mask   0  |diff|>150:   0   mean abs diff 0
mask 511  |diff|>150:   0   mean abs diff 16
mask   1  |diff|>150:   0   mean abs diff 16
mask   8  |diff|>150:   0   mean abs diff 0
mask  64  |diff|>150:   0   mean abs diff 4
mask 128  |diff|>150:   0   mean abs diff 0
```

**Time per move by depth, 1 core (timing.py)**

```
depth 8 | opening 0.1s 33k nodes | middlegame 0.1s 16k nodes | tactical 0.1s 58k nodes | endgame 0.0s 4k nodes
depth 10 | opening 0.2s 113k nodes | middlegame 0.4s 198k nodes | tactical 1.0s 506k nodes | endgame 0.0s 19k nodes
depth 11 | opening 0.4s 191k nodes | middlegame 0.8s 404k nodes | tactical 1.4s 763k nodes | endgame 0.1s 28k nodes
depth 12 | opening 0.6s 325k nodes | middlegame 1.2s 574k nodes | tactical 2.8s 1554k nodes | endgame 0.1s 49k nodes
depth 13 | opening 1.2s 568k nodes | middlegame 1.4s 749k nodes | tactical 3.8s 2031k nodes | endgame 0.3s 195k nodes
depth 14 | opening 1.7s 956k nodes | middlegame 2.4s 1390k nodes | tactical 7.4s 3957k nodes | endgame 0.4s 296k nodes
```

**Matches at equal depth**

- pruned depth 5 vs plain depth 4, 14 games (match.py): `{'A': 2, 'B': 8, 'draw': 4, 'nodesA': 1000660.0, 'nodesB': 12475375.0, 'adv': -231}`
- Features 262095 vs 15, depth 5, 14 games (match2.py): `A=feat 262095 B=feat 15 depth 5 {'A': 4, 'B': 4, 'draw': 6, 'adv': 200}`

**UCI matches, 100 ms a move, 24 games, A = Features 262095 (the default)**

- vs Features 15 (the v3.2 default): `FINAL {'A': 20, 'B': 2, 'D': 2} A score 21.0/24`
- vs Features 261839 (default without singular extensions): `FINAL {'A': 11, 'B': 7, 'D': 6} A score 14.0/24`
- vs Features 261583 (default without the tapered evaluation): `FINAL {'A': 19, 'B': 2, 'D': 3} A score 20.5/24`

**UCI self-play, 100 ms a move, 4 games, 120 plies (uci_selfplay.py)**

```
game 1: maxplies; 120 plies; slowest move 104 ms vs 100 ms asked
game 2: game over (no legal move) at ply 102; 102 plies; slowest move 106 ms vs 100 ms asked
game 3: maxplies; 120 plies; slowest move 109 ms vs 100 ms asked
game 4: maxplies; 120 plies; slowest move 118 ms vs 100 ms asked
```

## Full results, optimized build

**Correctness**

- perft (5 positions): 0 failure(s)
- evaluation symmetry (8 mirrored positions): 0 asymmetric
- mirror test at depth 1 (Features 262095): bad 0
- tactics (6 positions, depth 6): 0 failure(s)

**Pruning on vs off, depth 4, 4 seeds (selfplay.py)**

```
{'n': 216, 'same_move': 142, 'same_score': 51, 'off': 7670276.0, 'on': 224880.0, 'illegal': 0, 'close': 206} node ratio off/on = 34.1
```

**Each pruning technique alone (dev.py, depth 4, 4 seeds)**

```
positions 32
mask   0  |diff|>150:   0   mean abs diff 0
mask 511  |diff|>150:   0   mean abs diff 16
mask   1  |diff|>150:   0   mean abs diff 16
mask   8  |diff|>150:   0   mean abs diff 0
mask  64  |diff|>150:   0   mean abs diff 4
mask 128  |diff|>150:   0   mean abs diff 0
```

**Time per move by depth, 1 core (timing.py)**

```
depth 8 | opening 0.0s 33k nodes | middlegame 0.0s 16k nodes | tactical 0.1s 58k nodes | endgame 0.0s 4k nodes
depth 10 | opening 0.2s 113k nodes | middlegame 0.2s 198k nodes | tactical 0.7s 506k nodes | endgame 0.0s 19k nodes
depth 11 | opening 0.2s 191k nodes | middlegame 0.4s 404k nodes | tactical 0.8s 763k nodes | endgame 0.0s 28k nodes
depth 12 | opening 0.4s 325k nodes | middlegame 0.6s 574k nodes | tactical 1.6s 1554k nodes | endgame 0.0s 49k nodes
depth 13 | opening 0.7s 568k nodes | middlegame 0.9s 749k nodes | tactical 2.5s 2031k nodes | endgame 0.2s 195k nodes
depth 14 | opening 0.9s 956k nodes | middlegame 1.4s 1390k nodes | tactical 4.1s 3957k nodes | endgame 0.2s 296k nodes
```

**Matches at equal depth**

- pruned depth 5 vs plain depth 4, 14 games (match.py): `{'A': 2, 'B': 8, 'draw': 4, 'nodesA': 1000660.0, 'nodesB': 12475375.0, 'adv': -231}`
- Features 262095 vs 15, depth 5, 14 games (match2.py): `A=feat 262095 B=feat 15 depth 5 {'A': 4, 'B': 4, 'draw': 6, 'adv': 200}`

**UCI matches, 100 ms a move, 24 games, A = Features 262095 (the default)**

- vs Features 15 (the v3.2 default): `FINAL {'A': 20, 'B': 1, 'D': 3} A score 21.5/24`
- vs Features 261839 (default without singular extensions): `FINAL {'A': 13, 'B': 5, 'D': 6} A score 16.0/24`
- vs Features 261583 (default without the tapered evaluation): `FINAL {'A': 15, 'B': 0, 'D': 9} A score 19.5/24`

**UCI self-play, 100 ms a move, 4 games, 120 plies (uci_selfplay.py)**

```
game 1: maxplies; 120 plies; slowest move 98 ms vs 100 ms asked
game 2: maxplies; 120 plies; slowest move 106 ms vs 100 ms asked
game 3: maxplies; 120 plies; slowest move 110 ms vs 100 ms asked
game 4: game over (no legal move) at ply 119; 119 plies; slowest move 99 ms vs 100 ms asked
```

## Notes

- The correctness checks, the fixed-depth matches and the pruning experiments (perft, symmetry, mirror, tactics, selfplay, dev, match, match2) give byte-identical results on both builds. Only the 100 ms UCI matches differ between builds, because there the clock decides how deep each move is searched.
- In the opening position the optimized build is slower than the plain one at depths 12 to 15 (for example 1.00 s against 0.64 s at depth 12) and faster from depth 16 on; I did not investigate why. In the other two positions it is faster at every depth shown.
- The matches are small samples (14 to 24 games): read them as direction, not as an Elo measurement.
- The old driver scripts (`tactics.py`, `selfplay.py`, `dev.py`, `match.py`, `match2.py`, `timing.py`) were written for the v3.x engine. For v6.3 they were adapted in two ways: they initialise the engine the way v6.3's `action start` does (bitboards, evaluation masks, tablebase tables, hash, one thread), and they synchronise the bitboards after setting up a FEN. `ZOOMY` and `ZFLAGS` environment variables choose the compiler path and flags.
- `match.py` and `selfplay.py` use the engine's internal `pruning` variable, which is not a UCI option; `dev.py` and `match.py` therefore still splice the engine source with a driver, as they always did.
- `uci_match2.py` compares two engine files; it is not repeated because there is only one v6.3 engine file to compare (the plain and optimized builds play identically).
- Re-run everything with `sh run_all.sh` (plain build) or `sh run_all.sh opt` (optimized build) from this folder; results go to `rerun_plain/` or `rerun_opt/`.
