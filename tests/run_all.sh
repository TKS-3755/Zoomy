#!/bin/sh
# One command to run every check:  sh tests/run_all.sh            (the full suite, in parallel)
#                                  sh tests/run_all.sh --quick    (the everyday tier)
# See tests/run.py for the options.
cd "$(dirname "$0")/.." || exit 1
exec python3 tests/run.py "$@"
