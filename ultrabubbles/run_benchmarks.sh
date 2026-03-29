set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

SMK="Snakefile"
PROFILE="$(pwd)/profiles/slurm"
RESULTS_DIR="results"
TABLES_DIR="tables"
PIDFILE=".run_benchmarks.pid"

MODE=""
JOBS=""

CANCEL_JOBID=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --slurm|--tables-only|--download-only|--dry-run|--stop)
            MODE="$1"; shift ;;
        --cancel)
            MODE="--cancel"; CANCEL_JOBID="$2"; shift 2 ;;
        -j)
            JOBS="$2"; shift 2 ;;
        -j[0-9]*)
            JOBS="${1#-j}"; shift ;;
        -h|--help)
            echo "Usage: bash run_benchmarks_ultrabubbles.sh [MODE] [-j N]"
            echo ""
            echo "Modes:"
            echo "  --slurm          Full pipeline via SLURM"
            echo "  (none)           Full pipeline, local"
            echo "  --stop           Kill all jobs + generate tables from partial results"
            echo "  --cancel JOBID   Cancel a single SLURM job (pipeline continues)"
            echo "  --tables-only    Regenerate .tex from existing results/"
            echo "  --download-only  Download + decompress datasets only"
            echo "  --dry-run        Show plan without executing"
            echo ""
            echo "Options:"
            echo "  -j N             Max concurrent jobs (default: nproc for local, 10 for SLURM)"
            exit 0 ;;
        *)
            echo "Unknown argument: $1 (try --help)" >&2; exit 1 ;;
    esac
done

if [[ -z "$JOBS" ]]; then
    if [[ "$MODE" == "--slurm" ]]; then
        JOBS=10
    else
        JOBS=$(nproc)
    fi
fi

mkdir -p slurm_logs


kill_all_snakemake() {
    local KILLED=0

    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "  Killing run_benchmarks_ultrabubbles.sh (PID $PID)..."
            kill -- -"$PID" 2>/dev/null || kill "$PID" 2>/dev/null || true
            KILLED=1
        fi
        rm -f "$PIDFILE"
    fi

    local PIDS
    PIDS=$(pgrep -f "snakemake.*$SMK" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "  Killing orphan snakemake processes: $PIDS"
        echo "$PIDS" | xargs kill 2>/dev/null || true
        KILLED=1
    fi

    if [ "$KILLED" -eq 1 ]; then
        sleep 2
        PIDS=$(pgrep -f "snakemake.*$SMK" 2>/dev/null || true)
        if [ -n "$PIDS" ]; then
            echo "  Force-killing: $PIDS"
            echo "$PIDS" | xargs kill -9 2>/dev/null || true
        fi
    fi
}


ensure_slurm_plugin() {
    if ! python3 -c "import snakemake_executor_plugin_slurm" 2>/dev/null; then
        echo "Installing snakemake-executor-plugin-slurm..."
        pip3 install snakemake-executor-plugin-slurm --quiet
    fi
}

detect_slurm_account() {
    local acct
    acct=$(sacctmgr -n -p show user "$USER" withassoc format=Account 2>/dev/null \
        | head -1 | tr -d '|' | xargs || true)
    [ -n "$acct" ] && echo "$acct" && return
    acct=$(sshare -U -u "$USER" --format=Account --noheader 2>/dev/null \
        | head -1 | xargs || true)
    [ -n "$acct" ] && echo "$acct" && return
    echo ""
}

update_slurm_profile() {
    local profile_cfg="$PROFILE/config.yaml"
    [ ! -f "$profile_cfg" ] && profile_cfg="$PROFILE/config.yaml "
    [ ! -f "$profile_cfg" ] && return
    local current detected
    current=$(grep -oP 'slurm_account:\s*\K\S+' "$profile_cfg" 2>/dev/null | head -1 || true)
    detected=$(detect_slurm_account)
    if [ -z "$detected" ]; then
        return
    fi
    if [ "$current" != "$detected" ]; then
        echo "  Updating SLURM account: $current → $detected"
        sed -i "s/slurm_account: .*/slurm_account: $detected/" "$profile_cfg"
    fi
}

print_run_summary() {
    local R="$1"
    local n_ok=0 n_fail=0
    for f in "$R"/*.time; do
        [ -f "$f" ] && n_ok=$((n_ok + 1))
    done
    for f in "$R"/*.time.failed; do
        [ -f "$f" ] && n_fail=$((n_fail + 1))
    done
    echo ""
    echo " Run summary: $n_ok succeeded, $n_fail failed "
    if [ "$n_fail" -gt 0 ]; then
        for f in "$R"/*.time.failed; do
            [ -f "$f" ] || continue
            local name reason
            name=$(basename "$f" .time.failed)
            reason=$(grep '^REASON=' "$f" 2>/dev/null | head -1 | cut -d= -f2)
            case "$reason" in
                TIMEOUT)       printf "  %-8s %s\n" "TIMEOUT" "$name" ;;
                KILLED_OR_OOM) printf "  %-8s %s\n" "OOM" "$name" ;;
                SEGFAULT)      printf "  %-8s %s\n" "SEGFAULT" "$name" ;;
                ERROR)         printf "  %-8s %s\n" "ERROR" "$name" ;;
                *)             printf "  %-8s %s\n" "UNKNOWN" "$name" ;;
            esac
        done
    fi
}


case "$MODE" in
    --stop)
        echo "=Stopping all running jobs"

        kill_all_snakemake

        echo "Cancelling all SLURM jobs..."
        scancel -u "$USER" 2>/dev/null || true
        sleep 2
        snakemake -s "$SMK" --unlock 2>/dev/null || true
        echo ""
        echo " Cleaning incomplete results"
        N_CLEANED=0
        for f in "$RESULTS_DIR"/*.time "$RESULTS_DIR"/*.gfa_stats; do
            [ -f "$f" ] || continue
            if [ ! -s "$f" ]; then
                echo "  Removing empty: $(basename $f)"
                rm -f "$f"
                N_CLEANED=$((N_CLEANED + 1))
            fi
        done
        echo "  Removed $N_CLEANED incomplete file(s)"

        snakemake -s "$SMK" --cleanup-metadata "$RESULTS_DIR"/*.time 2>/dev/null || true
        echo ""
        echo " Generating tables from partial results"
        mkdir -p "$TABLES_DIR"
        print_run_summary "$RESULTS_DIR"
        python3 scripts/make_table.py "$RESULTS_DIR" "$TABLES_DIR"

        echo ""
        echo " Stopped"
        echo "Incomplete results were removed. Re-run with --slurm to complete them."
        ;;

    --cancel)
        if [ -z "$CANCEL_JOBID" ]; then
            echo "Usage: bash run_benchmarks_ultrabubbles.sh --cancel <SLURM_JOBID>" >&2
            exit 1
        fi
        LOG_FILE="run_benchmarks_ultrabubbles.log"
        OUTPUT_FILE=$(awk -v jid="$CANCEL_JOBID" '
            /^[[:space:]]*output:/ { out=$2 }
            $0 ~ "SLURM jobid " jid { print out; exit }
        ' "$LOG_FILE")

        echo " Cancelling SLURM job $CANCEL_JOBID"

        if [ -n "$OUTPUT_FILE" ]; then
            echo "  Output file: $OUTPUT_FILE"
        else
            echo "  WARNING: Could not find output file for job $CANCEL_JOBID in $LOG_FILE"
        fi
        scancel "$CANCEL_JOBID" 2>/dev/null || true
        echo "  Job cancelled."

        if [ -n "$OUTPUT_FILE" ] && [ -f "$OUTPUT_FILE" ]; then
            rm -f "$OUTPUT_FILE"
            echo "  Removed $OUTPUT_FILE"
        fi
        echo ""
        echo " Restarting Snakemake "
        kill_all_snakemake
        sleep 1
        snakemake -s "$SMK" --unlock 2>/dev/null || true
        JOBS=${JOBS:-20}
        ensure_slurm_plugin
        update_slurm_profile
        nohup bash -c "
            cd '$SCRIPT_DIR'
            echo \$\$ > '$PIDFILE'
            snakemake -s '$SMK' --profile '$PROFILE' -j $JOBS --rerun-incomplete --keep-going generate_tables
            rm -f '$PIDFILE'
        " > "$LOG_FILE" 2>&1 &
        NEWPID=$!
        echo "  Snakemake restarted (PID $NEWPID). Tail with: tail -f $LOG_FILE"
        ;;

    --slurm)
        ensure_slurm_plugin
        update_slurm_profile
        EXISTING=$(pgrep -f "snakemake.*$SMK" 2>/dev/null || true)
        if [ -n "$EXISTING" ]; then
            echo "WARNING: Killing existing snakemake processes: $EXISTING"
            kill_all_snakemake
            echo "  Cancelling orphan SLURM jobs..."
            scancel -u "$USER" 2>/dev/null || true
            sleep 2
            snakemake -s "$SMK" --unlock 2>/dev/null || true
        fi

        echo " Phase 1 : download and we decompress datasets "
        snakemake -s "$SMK" -j 3 download_all
        echo ""
        echo " Phase 2: Build + bench + tables (SLURM, -j $JOBS) "
        echo $$ > "$PIDFILE"
        snakemake -s "$SMK" --profile "$PROFILE" -j "$JOBS" --rerun-incomplete --keep-going generate_tables || true
        rm -f "$PIDFILE"
        print_run_summary "$RESULTS_DIR"
        echo ""
        echo " Generating tables from available results "
        mkdir -p "$TABLES_DIR"
        python3 scripts/make_table.py "$RESULTS_DIR" "$TABLES_DIR"
        ;;

    --tables-only)
        echo " Regenerating tables from existing results "
        mkdir -p "$TABLES_DIR"
        python3 scripts/make_table.py "$RESULTS_DIR" "$TABLES_DIR"
        ;;

    --download-only)
        echo " Downloading + we decompressing datasets "
        snakemake -s "$SMK" -j 3 download_all
        ;;

    --dry-run)
        echo " Dry run "
        snakemake -s "$SMK" -j "$JOBS" -n -p download_all
        echo ""
        snakemake -s "$SMK" -j "$JOBS" -n -p generate_tables
        ;;

    "")
        echo " Phase 1: Download + we decompress datasets "
        snakemake -s "$SMK" -j 3 download_all
        echo ""
        echo " Phase 2: Build + bench + tables (local, -j $JOBS) "
        echo $$ > "$PIDFILE"
        snakemake -s "$SMK" -j "$JOBS" --rerun-incomplete --keep-going generate_tables || true
        rm -f "$PIDFILE"
        print_run_summary "$RESULTS_DIR"
        echo ""
        echo " Generating tables from available results "
        mkdir -p "$TABLES_DIR"
        python3 scripts/make_table.py "$RESULTS_DIR" "$TABLES_DIR"
        ;;
esac

echo ""
echo " Done "
ls -lh "$TABLES_DIR"/*.tex "$TABLES_DIR"/*.tsv 2>/dev/null || echo "(no tables in $TABLES_DIR/)"