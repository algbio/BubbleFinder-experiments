# BubbleFinder experiments

Experiment pipelines for [BubbleFinder](https://github.com/algbio/BubbleFinder), a tool for computing bubble-like structures (snarls, superbubbles, ultrabubbles) in pangenomic graphs.

## Benchmarks

| Paper | Entry point | README |
|---|---|---|
| [Identifying all snarls and superbubbles in linear-time, via a unified SPQR-tree framework](https://arxiv.org/abs/2511.21919) | `Snakefile` + `datasets.yaml` | [snarls-superbubbles/](snarls-superbubbles/README.md) |
| Scalable computation of ultrabubbles in pangenomes by orienting bidirected graphs (preprint forthcoming) | `run_benchmarks.sh` | [ultrabubbles/](ultrabubbles/README.md) |

Both benchmarks share parts of the codebase (Snakemake modules, helper scripts, conda environments).