# BubbleFinder experiments

Experiment pipelines for [BubbleFinder](https://github.com/algbio/BubbleFinder), a tool for computing bubble-like structures (snarls, superbubbles, ultrabubbles, d-bubbles) in pangenomic graphs.

## Benchmarks

| Paper | Entry point | README |
|---|---|---|
| [Identifying all snarls and superbubbles in linear-time, via a unified SPQR-tree framework](https://arxiv.org/abs/2511.21919) | `Snakefile` + `datasets.yaml` | [snarls-superbubbles/](snarls-superbubbles/README.md) |
| [Scalable computation of ultrabubbles in pangenomes by orienting bidirected graphs](https://doi.org/10.64898/2026.03.28.714704) | `run_benchmarks.sh` | [ultrabubbles/](ultrabubbles/README.md) |
| Dominator-bubbles: variation structures beyond separability in pangenome graphs | `run_benchmarks.sh` | [d-bubbles/](d-bubbles/README.md) |

The benchmarks share parts of the codebase (Snakemake modules, helper scripts, conda environments).
The [d-bubble experiments](d-bubbles/README.md) include automatic downloads, result tables and Venn diagrams.
