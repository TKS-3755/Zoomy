APEX-Z 6.2 - everything in one zip

1_zoomy_compiler/   Zoomy 6.2, the language and compiler (zoomy.py; docs in README.md; tests/; examples/)
2_apexz_engine/     the chess engine
    apexz           ready-to-run Linux x86-64 program (keep apexz_book.txt next to it)
    Apex-Z.zmy      its source in Zoomy. Rebuild: python3 ../1_zoomy_compiler/zoomy.py Apex-Z.zmy -o apexz
    apexz_book.txt  opening book
3_tablebase_dev/    for developers only: the Syzygy prober source (tb_*.zmy), the patch that added it
                    to the engine, and the Python reference and scripts that checked it against python-chess

Tablebases (UCI mode: type "uci" at the first prompt):
    setoption name SyzygyPath value /path/to/syzygy
Tested with 3- and 4-man tables only. 7-man is untested.
