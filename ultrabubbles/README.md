# Ultrabubble Benchmark

Experiments for:

> J. Harviainen, F. Sena, C. Moumard, A. Politov, S. Schmidt, A. I. Tomescu.
> *Scalable computation of ultrabubbles in pangenomes by orienting bidirected graphs.*
> Preprint forthcoming (link to be added).

---

## Overview

The script `run_benchmarks.sh` downloads datasets, builds the required tools, runs all benchmarks, and generates LaTeX tables. It wraps a dedicated Snakemake workflow (`Snakefile`).

Datasets: 18 pangenomic graphs from [Zenodo (record 19209715)](https://zenodo.org/records/19209715) and HPRC S3.

Tools benchmarked: BubbleFinder, vg, BubbleGun, Billi (heuristic).

---

## Quick start

```bash
# On a SLURM cluster:
nohup bash run_benchmarks.sh --slurm -j <JOBS> > run_benchmarks.log 2>&1 &

# On a single machine:
nohup bash run_benchmarks.sh > run_benchmarks.log 2>&1 &
```

---

## Commands

| Flag | Description |
|---|---|
| *(none)* | Full pipeline, local execution |
| `--slurm -j N` | Full pipeline via SLURM |
| `--stop` | Kill all jobs, generate tables from partial results |
| `--cancel <JOBID>` | Cancel one SLURM job; pipeline continues |
| `--tables-only` | Regenerate `.tex` from existing `results/` |
| `--download-only` | Download and decompress datasets only |
| `--dry-run` | Show plan, no execution |

After `--stop`, re-running `--slurm` only re-executes missing steps. `--cancel` is needed because the Snakemake SLURM plugin (v2.5.x) does not detect `scancel`-ed jobs.

---

## Configuration

### Timeouts (`config/benchmarks.yaml`)

Controls the maximum wall-clock time (in hours) allocated to each benchmark run. If a tool exceeds its timeout, the run is recorded as failed.

```yaml
timeout_default_hours: 2

timeout_per_program:
  vg_gfa_T: 2
  vg_gfa_noT: 2
  bf_gfa_T: 2
  bf_gfa_noT: 2
  bf_sb_gfa_T: 2
  bf_sb_gfa_noT: 2
  bubblegun: 2
  billi: 2
  gfa_stats: 1
  vg_gbz_T: 2
  vg_gbz_noT: 2
  bf_gbz_T: 2
  bf_gbz_noT: 2  
```

Program name conventions: `bf` = BubbleFinder, `vg` = vg snarls, `bf_sb` = BubbleFinder (doubled graph mode). Suffix `_T` = with trivial ultrabubbles (`-T` flag), `_noT` = without. Suffix `_gfa` / `_gbz` = input format.

### Tool versions (`Snakefile`)

Pinned at the top of the `Snakefile`:

```python
BF_COMMIT = "1b11e9b"            
BILLI_COMMIT = "a77892e"         
VG_VERSION = "1.72.0"            
BUBBLEGUN_VERSION = "1.2.0"      
```

Other adjustable constants:

```python
BF_STACK = 483183820800          
ZENODO_RECORD = "19209715" # Zenodo record ID for dataset downloads
DATASETS = [...] # list of dataset names to benchmark
```

### SLURM resources (`profiles/slurm/config.yaml`)

Controls SLURM job resources per Snakemake rule. Runtimes are in minutes, memory in MB.

```yaml
executor: slurm
latency-wait: 60
default-resources:
  slurm_account: cs # autodetected by run_benchmarks.sh
  runtime: 120
  mem_mb: 8000
  cpus_per_task: 2

set-resources:
  build_bubblefinder:
    runtime: 120
    mem_mb: 8000
    cpus_per_task: 4

  run_vg_gfa_T:
    runtime: 135
    mem_mb: 180000
    cpus_per_task: 2
  run_bf_gfa_T:
    runtime: 135
    mem_mb: 180000
    cpus_per_task: 2
  run_bubblegun:
    runtime: 135
    mem_mb: 180000
    cpus_per_task: 2
  run_billi:
    runtime: 135
    mem_mb: 100000
    cpus_per_task: 2
  run_gfa_stats:
    runtime: 45
    mem_mb: 500000
    cpus_per_task: 1

  # ...
```

`slurm_account` is auto-detected by `run_benchmarks.sh` from your cluster configuration. To override it, edit the file directly.

---

## Output

LaTeX tables and TSV summaries are written to `tables/`.