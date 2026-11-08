# D-bubble experiments

Input graphs are listed in [config/datasets.tsv](config/datasets.tsv).
Missing files are downloaded automatically from Zenodo and HPRC.
Existing local inputs are reused, and GFA archives are decompressed before use.

## Run

Use Python 3.11, Snakemake 9, curl, GNU time, a C++17 compiler, CMake and Cargo.
The SLURM mode also needs the Snakemake SLURM executor plugin.

    bash run_benchmarks.sh --dry-run
    bash run_benchmarks.sh --slurm -j 4

For a local run with eight cores:

    bash run_benchmarks.sh -j 8

Set paths and compiler options in [config/benchmarks.yaml](config/benchmarks.yaml).
For SLURM, set your account and partition in
[profiles/slurm/config.yaml](profiles/slurm/config.yaml) if needed. Adjust
memory and runtime there. The checkout and input/output paths must be visible
from the compute nodes. Downloads run on the machine that launches Snakemake.
The workflow builds the adjacent BubbleFinder checkout, or clones it if absent.
The HPRC GFA runs need a node with enough memory for the graph and tmpfs files.

## Results

The workflow uses `BubbleFinder ultrabubbles --d-bubbles` to find ultrabubbles
from the d-bubble candidates. Both modes support `-j` and `-T`.

The workflow writes measurements and bubble catalogues to results/.
The 14 LaTeX tables and their TSV are tables/paper-results.tex and
tables/paper-results.tsv. Rows come from the current run. Times and memory
depend on the machine used. Input checks verify the downloads and record
the files used for each run.

tables/figures/ contains the LaTeX/TikZ Venn diagrams, including the four set
HPRC v2.1 comparison. Counts come from the tool outputs.

To regenerate tables from existing results:

    bash run_benchmarks.sh --tables-only

To run BubbleFinder and generate tables with '-' for missing vg or Billi results:

    bash run_benchmarks.sh --slurm --no-vg-billi -j 4

Those tables are written to tables/validation-no-vg-billi/.
Use --download-only to fetch and prepare the inputs locally.
