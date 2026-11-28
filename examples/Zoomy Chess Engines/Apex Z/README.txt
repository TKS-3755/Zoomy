APEX-Z v6.0 (written in Zoomy 6.1)
Build:  python3 zoomy.py Apex-Z.zmy --native -o apexz      (zoomy5/ is in zoomy6.1.zip)
Run:    ./apexz            console game; type uci (or uciok) at the first prompt for UCI mode
UCI options: Threads, Hash (1-256 MB), OwnBook, Features (sum of feature bits, see the header of Apex-Z.zmy; default 262095)
Put apexz_book.txt (and optionally book.bin, a Polyglot book) next to the binary.
depth_benchmark.csv / .md : time to reach depth 12..20 in the opening, Kiwipete and an endgame.
source/ : every intermediate version and the patch scripts that produced it from v5.0.
