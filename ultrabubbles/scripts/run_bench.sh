set -euo pipefail

if [ $# -lt 4 ]; then
    echo "Usage: run_bench.sh <time_bin> <timeout_sec> <time_output> <command>" >&2
    exit 1
fi

TIME_BIN="$1"
TIMEOUT_SEC="$2"
TIME_OUT="$3"
shift 3
CMD="$*"

TMP="${TIME_OUT}.tmp"
FAILED="${TIME_OUT}.failed"

rm -f "$FAILED" "$TMP" "${TIME_OUT}"
mkdir -p "$(dirname "$TIME_OUT")"

rc=0
if [ "$TIMEOUT_SEC" -gt 0 ] 2>/dev/null; then
    "$TIME_BIN" -v -o "$TMP" timeout -k 10s "${TIMEOUT_SEC}s" bash -c "$CMD" || rc=$?
else
    "$TIME_BIN" -v -o "$TMP" bash -c "$CMD" || rc=$?
fi

if [ $rc -eq 0 ]; then
    mv "$TMP" "$TIME_OUT"
    exit 0
fi

(
    echo "EXIT_CODE=$rc"
    if [ $rc -eq 124 ]; then
        echo "REASON=TIMEOUT"
        echo "TIMEOUT_SECONDS=$TIMEOUT_SEC"
    elif [ $rc -eq 137 ]; then
        echo "REASON=KILLED_OR_OOM"
    elif [ $rc -eq 139 ]; then
        echo "REASON=SEGFAULT"
    else
        echo "REASON=ERROR"
    fi
    echo "TIMESTAMP=$(date -Iseconds 2>/dev/null || date)"
    echo "---"
    cat "$TMP" 2>/dev/null || echo "(no time output captured)"
) > "$FAILED"

rm -f "$TMP"

exit $rc