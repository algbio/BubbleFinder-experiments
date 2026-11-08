#!/usr/bin/env bash
set -euo pipefail

# Preserve the ISMB /usr/bin/time command and redirections, without sending
# signals. SLURM runtime is the authoritative per-job wall limit when used.
TIME_BIN="$1"
NOMINAL_SECONDS="$2"
TIME_OUT="$3"
shift 3

if [ "$#" -ne 1 ]; then
    echo "One recorded shell command required" >&2
    exit 1
fi

mkdir -p "$(dirname "$TIME_OUT")"
if [ -e "$TIME_OUT" ] || [ -e "$TIME_OUT.failed" ]; then
    echo "Existing measurement retained; choose a fresh result directory" >&2
    exit 1
fi

PROVENANCE="$(dirname "${BASH_SOURCE[0]}")/toolchain_provenance.py"
PYTHON="${BENCH_PYTHON:-/usr/bin/python3.11}"
"$PYTHON" "$PROVENANCE" prepare "$TIME_OUT" "$1"

rc=0
"$TIME_BIN" -v -o "$TIME_OUT.tmp" bash -c "$1" || rc=$?
if [ "$rc" -eq 0 ]; then
    mv "$TIME_OUT.tmp" "$TIME_OUT"
else
    {
        echo "EXIT_CODE=$rc"
        echo "REASON=ERROR"
        echo '---'
        cat "$TIME_OUT.tmp"
    } > "$TIME_OUT.failed"
fi

# A successful wrapper records even a failed method; consumers inspect EXIT_CODE.
# Partial biological output is never decoded after a failed command.
if [ "$rc" -ne 0 ]; then
    cp "$TIME_OUT.failed" "$TIME_OUT"
fi
hostname > "$TIME_OUT.host"
"$PYTHON" "$PROVENANCE" finish "$TIME_OUT" "$rc"
exit 0
