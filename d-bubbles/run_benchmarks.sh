#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
MODE=""
JOBS=""
LOCAL_MEMORY_MB=""
MEMORY_SET=0
NO_VG_BILLI=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --slurm|--tables-only|--download-only|--dry-run)
            MODE="$1"
            shift ;;
        --no-vg-billi)
            NO_VG_BILLI=1
            shift ;;
        -j)
            [ "$#" -ge 2 ] || {
                echo "-j needs a positive integer" >&2
                exit 1
            }
            JOBS="$2"
            shift 2 ;;
        -j[0-9]*)
            JOBS="${1#-j}"
            shift ;;
        --local-memory-mb)
            [ "$#" -ge 2 ] || {
                echo "--local-memory-mb needs a positive integer" >&2
                exit 1
            }
            LOCAL_MEMORY_MB="$2"
            MEMORY_SET=1
            shift 2 ;;
        -h|--help)
            echo "Usage: bash run_benchmarks.sh [--slurm | --dry-run | --tables-only | --download-only] [--no-vg-billi] [-j N] [--local-memory-mb MB]"
            exit 0 ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1 ;;
    esac
done

if [ -z "$JOBS" ]; then
    case "$MODE" in
        --slurm|--download-only) JOBS=4 ;;
        *) JOBS=8 ;;
    esac
fi
case "$JOBS" in
    ''|*[!0-9]*)
        echo "-j needs a positive integer" >&2
        exit 1 ;;
esac
if ! [ "$JOBS" -gt 0 ] 2>/dev/null; then
    echo "-j needs a positive integer" >&2
    exit 1
fi

MEMORY_ARGS=()
if [ "$MEMORY_SET" -eq 1 ]; then
    case "$LOCAL_MEMORY_MB" in
        ''|*[!0-9]*)
            echo "--local-memory-mb needs a positive integer" >&2
            exit 1 ;;
    esac
    if ! [ "$LOCAL_MEMORY_MB" -gt 0 ] 2>/dev/null; then
        echo "--local-memory-mb needs a positive integer" >&2
        exit 1
    fi
    case "$MODE" in
        ""|--dry-run) ;;
        *)
            echo "--local-memory-mb is for local execution or a dry run." >&2
            exit 1 ;;
    esac
    MEMORY_ARGS=(--resources "mem_mb=$LOCAL_MEMORY_MB")
fi

VALIDATION_RULES=(paper_validation_no_external paper_validation_nontrivial
    paper_bubblefinder_threads paper_thread_consistency paper_bubble_sizes
    run_d_bubbles run_gfa_stats run_bf_gfa_T run_bf_gfa_noT
    run_bf_gbz_T run_bf_gbz_noT build_paper_analysis build_gfa_stats
    pin_bubblefinder build_bubblefinder clone_bubblefinder clone_spdlog
    download_all download_zenodo download_hprc)

case "$MODE" in
    --dry-run)
        if [ "$NO_VG_BILLI" -eq 1 ]; then
            exec snakemake -s Snakefile --cores 8 "${MEMORY_ARGS[@]}" --dry-run \
                --allowed-rules "${VALIDATION_RULES[@]}" -- paper_validation_no_external
        fi
        exec snakemake -s Snakefile --cores 8 "${MEMORY_ARGS[@]}" --dry-run all ;;
    --slurm)
        if [ "$NO_VG_BILLI" -eq 1 ]; then
            exec snakemake -s Snakefile --profile profiles/slurm --jobs "$JOBS" --cores 8 --keep-going \
                --allowed-rules "${VALIDATION_RULES[@]}" -- paper_validation_no_external
        fi
        exec snakemake -s Snakefile --profile profiles/slurm --jobs "$JOBS" --cores 8 --keep-going all ;;
    --tables-only)
        if [ "$NO_VG_BILLI" -eq 1 ]; then
            exec snakemake -s Snakefile --cores 8 --allowed-rules paper_validation_no_external \
                --forcerun paper_validation_no_external -- paper_validation_no_external
        fi
        exec snakemake -s Snakefile --cores 8 --allowed-rules paper_summary --forcerun paper_summary -- paper_summary ;;
    --download-only)
        exec snakemake -s Snakefile --cores "$JOBS" download_all ;;
    *)
        [ "$JOBS" -ge 8 ] || {
            echo "Local execution needs at least 8 cores." >&2
            exit 1
        }
        if [ -n "${SLURM_CPUS_PER_TASK:-}" ] && [ "$SLURM_CPUS_PER_TASK" -lt "$JOBS" ]; then
            echo "The local core limit exceeds SLURM_CPUS_PER_TASK; request a larger allocation." >&2
            exit 1
        fi
        if [ "$NO_VG_BILLI" -eq 1 ]; then
            exec snakemake -s Snakefile --cores "$JOBS" "${MEMORY_ARGS[@]}" --keep-going \
                --allowed-rules "${VALIDATION_RULES[@]}" -- paper_validation_no_external
        fi
        exec snakemake -s Snakefile --cores "$JOBS" "${MEMORY_ARGS[@]}" --keep-going all ;;
esac
