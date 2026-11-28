APEX-Z NNUE tools (Zoomy 8)
===========================

The engine (../Apex-Z.zmy, v7.0) can evaluate with a small neural network, an NNUE with HalfKAv2 input features.
Everything in this folder is plain Python (numpy and scipy for training only).

  cm.py        chess rules in Python (legal moves, FEN, UCI moves) - perft-checked
  gen.py       self-play data:   python3 gen.py ENGINE DEPTH SECONDS SEED OUT.txt
               lines "fen|score|result": the engine's score at the given depth (white's view, centipawns),
               quiet positions only (no check, best move is not a capture), and the game result.
  nnue2.py     version 2 network: features, integer reference evaluation, file format APX2
  train2.py    python3 train2.py OUT.nnue EPOCHS H data...     (env NB, L1, L2, MIRROR, K, LAM, RESID) trains version 2
  nnue.py      the feature layout, the integer reference evaluation and the file format (apexz.nnue)
  train.py     python3 train.py OUT.nnue EPOCHS H data1.txt data2.txt ...     (env L1, L2, MIRROR, K, LAM, RESID, RCLIP)
  label.py     python3 label.py ENGINE in.txt out.txt   (adds the static evaluation as a 4th field, for RESID=1)
  match.py     A/B match over UCI with random 8-ply openings: python3 match.py GAMES MOVETIME_MS "A|Opt=v;Opt=v" "B|..."
  cmp_eval.py  compares the engine's `nneval` with nnue.py on many positions

The network
-----------
* Input: HalfKAv2 as in Stockfish 12-13: for each side's point of view, one feature per (own king square, piece plane,
  piece square): 64 x 11 x 64 = 45056 features per side (planes: own/enemy pawn, knight, bishop, rook, queen, and one for both kings;
  the board is turned over for Black).
* Layer 1 (feature transformer): 45056 -> H (H up to 64) per side, whole numbers (254 stands for 1.0), kept in an accumulator for every ply and
  changed by adding and taking away only the features a move changes. A king move rebuilds that side's accumulator.
* The two accumulators (side to move first) are clipped to 0..1 and go through dense layers 2H -> L1 -> L2 -> 1 (L1, L2 up to 16) with clipped
  ReLU; the file also stores the output scale K; weights are 16 bit whole numbers (1024 stands for 1.0). Everything is integer arithmetic, so the Zoomy engine and nnue.py
  give identical numbers (tests/test_apexz_nnue.py).
* Two ways to train: the plain one (net predicts the search score) and RESID=1 (net predicts score minus the engine's own static evaluation; the engine then uses hand-written evaluation + net). label.py adds the static evaluation to a data file. Neither beat the hand-written evaluation with 525k positions (see the main README); no net is shipped.
* Training uses the same layout in floating point, with a "factorizer" (a 704-row table shared by all king squares that is added to
  the king-square-specific rows while training and merged when the file is written), mirrored boards as extra data, Adam, and a loss on
  sigmoid(score / 400) blended with the game result.
* File: "APXN", H, L1, L2 (16 bit each, big endian), then the weights in the order of Net.save() in nnue.py.

Using it
--------
    python3 zoomy.py Apex-Z.zmy --native -o apexz        (apexz.nnue next to the binary is loaded at start)
UCI options: EvalFile (a path), UseNNUE (true/false), NNScale (percent of the net's part, default 100), NNDebug (true: check the accumulators against a rebuild at every node, slow).
`nneval` (UCI) prints the static evaluation for the side to move.

Version 2 network (file "APX2")
-------------------------------
Ideas taken from current Stockfish networks, written from scratch (Stockfish is GPL, no code is copied); off unless an APX2 file is loaded.
* King buckets with mirroring: 32 buckets (the own king square, turned so that the king is always on files a-d, with the board mirrored left to
  right when it is not) x 11 planes x 64 squares = 22528 inputs per side, half of HalfKAv2, so each weight sees twice the data.
* Pairwise product: each accumulator (clipped 0..254) is split in two halves; half 1 times half 2 / 254 gives H/2 values per side.
* Layer 1 -> L1 values c (clipped 0..127); layer 2 gets c and c*c/127 (a squared copy), and the output also gets a skip: c . skip weights.
* Output buckets: one set of layer 1, 2, output and skip weights for each piece count bucket, bucket = min(NB-1, (pieces-1) / 4), NB up to 8.
* File: "APX2", H, L1, L2, K, NB (16 bit each), then the feature transformer, then per bucket l1 weights, l1 bias, l2 weights, l2 bias, output weights, skip weights, output bias (nnue2.py Net2.save()).
* The engine loads APXN (version 1) and APX2 files by the magic; tests/test_apexz_nnue2.py checks the integer evaluation against nnue2.py, the incremental updates and the version 1 loader.
