# Snakemake Pipeline for BubbleFinder

This repository contains a Snakemake pipeline that **can** (depending on the requested Snakemake targets and on the configuration in `datasets.yaml`):

- Build graphs (GFA) from FASTA, FASTQ (ggcat+Lighter), VCF (vg), or pre‑existing GFAs.
- Clean and "bluntify" the graphs.
- Prepare unidirectional graph representations (sgraph / edgelist), when required by the selected benchmark programs / inputs.
- Run benchmarks on several programs (BubbleGun, BubbleFinder (superbubbles / snarls / ultrabubbles), vg snarls, clsd).
- Aggregate results in a single table and produce plots (time / memory).

Running the default target `all` (`snakemake all ...`) triggers the workflow needed to produce the aggregated table and plots for all enabled datasets and selected benchmark programs.

**Note:** steps (build / clean / conversions / benchmarks) run only if required by the requested Snakemake targets and by `datasets.yaml`. In particular, any benchmark/aggregation target (e.g. `results/benchmarks.tsv` or `all`) will build `data/<dataset>/<dataset>.cleaned.gfa` for the datasets being benchmarked.

> [!IMPORTANT]
> **Reproduce the ultrabubbles experiments**
>
> Our script downloads all datasets from [Zenodo (record 19209715)](https://zenodo.org/records/19209715),
> builds five tools, runs all benchmarks, and generates LaTeX tables.
> See [Section 8](#8-ultrabubble-benchmarks-run_benchmarkssh) for details.
>
> ```bash
> # On a SLURM cluster:
> nohup bash run_benchmarks.sh --slurm -j 20 > run_benchmarks.log 2>&1 &
>
> # On a single machine (no SLURM):
> nohup bash run_benchmarks.sh > run_benchmarks.log 2>&1 &
> ```

---

## Table of contents

- [1. Requirements](#1-requirements)
- [2. Setup](#2-setup)
- [3. Dataset configuration (`datasets.yaml`)](#3-dataset-configuration-datasetsyaml)
  - [3.1 Available builders](#31-available-builders)
  - [3.2 Enable / disable a dataset](#32-enable--disable-a-dataset)
  - [3.3 Choosing benchmark programs](#33-choosing-benchmark-programs)
  - [3.4 BubbleFinder: modes and inputs (including ultrabubbles)](#34-bubblefinder-modes-and-inputs-including-ultrabubbles)
  - [3.5 When are sgraph / edgelist produced?](#35-when-are-sgraph--edgelist-produced)
  - [3.6 Threads configuration (build + benchmarks)](#36-threads-configuration-build--benchmarks)
- [4. Running the pipeline](#4-running-the-pipeline)
- [5. Output structure](#5-output-structure)
- [6. Customizing tool binaries](#6-customizing-tool-binaries)
- [7. Quick troubleshooting](#7-quick-troubleshooting)
- [8. Ultrabubble benchmarks (`run_benchmarks.sh`)](#8-ultrabubble-benchmarks-run_benchmarkssh)

---

## 1. Requirements

- Unix‑like OS (Linux, macOS).
- *Snakemake* (recommended via conda/mamba).
- *conda* or *mamba* available in `$PATH`.  
  (The pipeline uses `conda:` directives in the rules.)
- Internet access (to download data and binaries).

The following tools are managed automatically by the Snakefile if no binary is specified in `datasets.yaml`:

- [BubbleFinder](https://github.com/algbio/BubbleFinder/tree/302de4f06c60fe96856a0da46439152a99c8d053), cloned and built from GitHub (commit `302de4f0`).
- [GetBlunted](https://github.com/vgteam/GetBlunted/releases/tag/v1.0.0), precompiled binary downloaded (release `v1.0.0`).
- [clsd](https://github.com/Fabianexe/clsd/tree/c49598fcb149b2c224a4625e0bf4b870f27ec166), cloned and built (commit `c49598fc`).
- [Lighter](https://github.com/mourisl/Lighter/tree/d8621db12352895662404b38a4b61862eaf60f6a), cloned and built (commit `d8621db1`).

---

## 2. Setup

```bash
# 1) Clone the repository
git clone https://github.com/algbio/BubbleFinder-experiments.git
cd BubbleFinder-experiments

# 2) (Optional) Create a conda/mamba env with Snakemake version 9
mamba env create -f environment.yml
conda activate bench
```

Make sure `conda` *or* `mamba` is in `$PATH` when you run Snakemake.

---

## 3. Dataset configuration (`datasets.yaml`)

The `datasets.yaml` file describes:

- datasets (`datasets:`),
- builders (how to produce raw GFAs),
- tools and conda environments,
- benchmark programs and their parameters.

### 3.1 Available builders

Each dataset has a `builder` field:

- `ggcat_from_fasta`  
  - Input: FASTA/FNA (or `.tar.gz` archive containing FASTA files).
- `ggcat_from_reads_lighter`  
  - Input: FASTQ(.gz) → Lighter correction → ggcat.
- `vg_from_vcf`  
  - Input: `fa_gz` (reference) + `vcf_gz` → `vg construct` → GFA.
- `gfa_from_url`  
  - Input: pre‑built GFA downloaded from a URL.
- `vg_from_url`  
  - Input: a `.vg` file downloaded from a URL → `vg convert -g` → GFA.
- `gbz_from_url`  
  - Input: a `.gbz` file downloaded from a URL → `vg convert -g` → GFA.
- `pggb_from_fasta`  
  - Input: FASTA, graph built with [pggb](https://github.com/pangenome/pggb).

### 3.2 Enable / disable a dataset

Under `datasets:`:

```yaml
- name: coli3682
  enabled: true
  builder: ggcat_from_fasta
  ...
```

- `enabled: true` → used.
- `enabled: false` → ignored.
- `enabled: auto` → enabled only if input files can be detected (useful for datasets discovered from an index page).

### 3.3 Choosing benchmark programs

Benchmark programs are selected:

- globally via `defaults.bench.programs`, and/or
- per dataset via `datasets: ... bench_programs:`

Global example:

```yaml
defaults:
  bench:
    reps: 2
    programs:
      - BubbleGun_gfa
      - BubbleFinder
      - vg_snarls_gfa
      - clsd_sb
```

Per dataset override example:

```yaml
- name: ecoli50
  ...
  bench_programs:
    - BubbleFinder
    - vg_snarls_gfa
```

#### Repetitions (`reps`)

The number of benchmark repetitions is controlled by `defaults.bench.reps`.  
For each dataset, for each selected program (and for each configured thread count), the pipeline runs `rep = 1..reps` and writes one TSV per repetition.

A TSV file is a plain-text **T**ab-**S**eparated **V**alues file (fields separated by tab characters); in this pipeline, benchmark TSVs are small key/value tables storing time/memory/exit status and some metadata (program, threads, etc.).

Example:

```yaml
defaults:
  bench:
    reps: 2
```

### 3.4 BubbleFinder: modes and inputs

The pipeline benchmarks BubbleFinder via the program name `BubbleFinder`. BubbleFinder runs in one or more **modes**, configured in `datasets.yaml`.

Modes supported here (BubbleFinder commands):

- `superbubbles`
- `snarls`
- `ultrabubbles`

Mode selection is controlled by:

- `defaults.bench.program_opts.BubbleFinder.modes` (global), and/or
- per-dataset overrides under `datasets: ... bench: program_opts: BubbleFinder: ...`

Global example (run multiple modes):

```yaml
defaults:
  bench:
    program_opts:
      BubbleFinder:
        modes: ["superbubbles", "snarls", "ultrabubbles"]
```

Per-dataset example (run only ultrabubbles on one dataset):

```yaml
- name: ecoli50
  ...
  bench_programs:
    - BubbleFinder
  bench:
    program_opts:
      BubbleFinder:
        modes: ["ultrabubbles"]
```

BubbleFinder input type is configured per mode with `input:`:

- `input: "gfa"` → BubbleFinder reads `data/<dataset>/<dataset>.cleaned.gfa`
- `input: "sgraph"` → BubbleFinder reads `data/<dataset>/<dataset>.sbspqr.sgraph` (built from a cleaned GFA)

Example (run BubbleFinder ultrabubbles, using GFA input):

```yaml
defaults:
  bench:
    program_opts:
      BubbleFinder:
        modes: ["ultrabubbles"]
        default:
          input: "gfa"
```

Note: dataset names do not control BubbleFinder modes; only the `modes:` field does.  
Also, BubbleFinder's `ultrabubbles` mode requires **at least one tip per connected component** in the input graph (BubbleFinder requirement).

### 3.5 When are sgraph / edgelist produced?

These derived representations are built only if required by the selected benchmark programs / inputs:

- **clsd (`clsd_sb`)** uses an **edgelist**: `data/<dataset>/<dataset>.clsd.edgelist` (generated from a cleaned GFA).
- **BubbleFinder** uses **sgraph** only when `BubbleFinder` is configured with `input: "sgraph"`.

### 3.6 Threads configuration (build + benchmarks)

There are two distinct "thread" concepts:

- `snakemake -j <N>` controls **how many rules run in parallel** (workflow-level parallelism).
- Program-specific thread counts control **how many threads a tool uses** inside one rule.

#### Builder threads (graph construction)

Builder thread defaults are set under `defaults.threads`, e.g.:

```yaml
defaults:
  threads:
    ggcat: 8
    vg: 16
    lighter: 8
    pggb: 4
```

#### Benchmark threads (per program)

For benchmarks, thread values can be configured:

- globally per program via `defaults.bench.threads_by_program`, and/or
- per dataset via `datasets: ... bench_threads:`

Global example:

```yaml
defaults:
  bench:
    threads_by_program:
      BubbleFinder: [1, 4, 8, 16]
      vg_snarls_gfa: [1, 4, 8, 16]
```

Per-dataset override example:

```yaml
- name: ecoli50
  ...
  bench_threads:
    vg_snarls_gfa: [1, 8]
```

BubbleFinder thread values can also be set per mode via `program_opts`:

```yaml
defaults:
  bench:
    program_opts:
      BubbleFinder:
        modes: ["superbubbles", "ultrabubbles"]
        by_mode:
          superbubbles:
            threads: [1, 2, 4, 8]
          ultrabubbles:
            threads: [1, 4, 8, 16]
```

---

## 4. Running the pipeline

### Dry‑run (no execution)

```bash
snakemake -n -p
```

### Full run (all enabled datasets)

```bash
snakemake all --use-conda -j 8
```

- `--use-conda`: required to create/use the environments defined in `config/*.yml`.
- `-j 8`: number of parallel jobs.

### Targeted examples

- Build and clean only the GFA of `coli3682`:

```bash
snakemake --use-conda -j 4 data/coli3682/coli3682.cleaned.gfa
```

- Run benchmarks + aggregation (this also produces the plots because they are generated by the same rule in this workflow):

```bash
snakemake --use-conda -j 8 results/benchmarks.tsv
```

---

## 5. Output structure

### `data/` directory

For each dataset `<name>`:

- `data/<name>/<name>.*.gfa`  
  - Raw GFA (builder-dependent), e.g.:
    - `...ggcat.fasta.gfa`
    - `...vg.gfa`
    - `...pggb.gfa`
    - `...raw.gfa`       (builder: `gfa_from_url`)
    - `...vg.url.gfa`    (builder: `vg_from_url`)
    - `...gbz.url.gfa`   (builder: `gbz_from_url`)
- `data/<name>/<name>.bluntified.gfa` (temporary).
- `data/<name>/<name>.cleaned.gfa`  
  - Cleaned GFA (no H‑lines, bluntified).
- `data/<name>/<name>.sb.cleaned.gfa`  
  - Cleaned GFA produced by the optional ggcat `-f` rebuild (when enabled for SB programs on ggcat-based datasets).
- `data/<name>/<name>.sbspqr.sgraph`  
  - sgraph for BubbleFinder when configured with `input: "sgraph"`.
- `data/<name>/<name>.clsd.edgelist`  
  - Edgelist for `clsd`.

### `results/` directory

- `results/.prechecks.ok`  
  - Marker indicating that prechecks have run.
- `results/bench/`  
  - Per‑program, per‑dataset, per‑rep benchmark TSV files.
  - For BubbleFinder, file names include the mode:
    - `BubbleFinder/<dataset>.<mode>.t<threads>.rep<rep>.tsv`
- `results/prog_out/`  
  - Raw program outputs (BubbleFinder outputs + BubbleFinder JSON report, etc.).
- `results/logs/`  
  - Detailed logs per step.
- `results/benchmarks.tsv`  
  - Aggregated benchmark table.
- `results/plots/`  
  - `time_by_dataset_program.png`
  - `rss_by_dataset_program.png`
- `results/summary/reruns_planned.tsv`  
  - Information used for automatic reruns (timeouts, failures).

---

## 6. Customizing tool binaries

In `datasets.yaml`, under `defaults.tools`, you can point to pre‑installed binaries to avoid automatic cloning/building:

```yaml
defaults:
  tools:
    spqr_bin: /path/to/BubbleFinder
    get_blunted: /path/to/get_blunted
    lighter_bin: /path/to/lighter
    clsd_bin: /path/to/clsd
```

If these paths are not set, the Snakefile will:

- clone/build `BubbleFinder`, `clsd`, and `Lighter` under `build/`,
- download `get_blunted` into `bin/`.

---

## 7. Quick troubleshooting

- Error in prechecks (`prechecks`):
  - Check `results/logs/*` (especially `results/logs/bench`, `results/logs/ggcat`, `results/logs/vg`).
  - Ensure `conda` or `mamba` is available.
- Frequent timeouts:
  - Adjust `defaults.tools.timeout.seconds` in `datasets.yaml`.
- Problem with a specific dataset:
  - Run a single target, e.g.  
    `snakemake --use-conda -j 4 data/coli3682/coli3682.cleaned.gfa`
- Bluntification issues:
  - A WARN about `get_blunted` means the pipeline falls back to "naive bluntify" (overlap fields forced to `*`).
  - Install GetBlunted and set `defaults.tools.get_blunted` to use it.

---

## 8. Ultrabubble benchmarks (`run_benchmarks.sh`)

This script reproduces the ultrabubble experiments. Downloads 18 datasets from
[Zenodo (record 19209715)](https://zenodo.org/records/19209715) and HPRC S3,
builds five tools (BubbleFinder, vg, BubbleGun, Billi, gfa\_stats), runs all
benchmarks, and generates LaTeX tables in `tables/`.

```bash
# SLURM cluster
nohup bash run_benchmarks.sh --slurm -j 20 > run_benchmarks.log 2>&1 &

# Single machine:
bash run_benchmarks.sh
```

### Commands

| Command | Description |
|---|---|
| `--slurm -j N` | Full pipeline via SLURM |
| *(no flag)* | Full pipeline, local |
| `--stop` | Kill all jobs, generate tables from partial results |
| `--cancel <JOBID>` | Cancel one SLURM job; pipeline restarts automatically |
| `--tables-only` | Regenerate `.tex` from existing `results/` |
| `--download-only` | Download and decompress datasets only |
| `--dry-run` | Show plan, no execution |

After `--stop`, re-running `--slurm` only re-executes what is missing.
`--cancel` is needed because the Snakemake SLURM plugin (v2.5.x) does not
detect `scancel`ed jobs.

### SLURM configuration

Edit `profiles/slurm/config.yaml` to adjust per-rule memory and time limits.
Set `slurm_account` to your cluster's account (default: `cs`).