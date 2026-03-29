import os
from pathlib import Path

configfile: "config/benchmarks.yaml"

RESULTS_DIR = config.get("results_dir", "results")
TIME_BIN = config.get("time_bin", "/usr/bin/time")
BF_STACK = config.get("bf_stack", 483183820800)
ZENODO_RECORD = config.get("zenodo_record", "19209715")
DATA_DIR = config.get("data_dir", "data")
TABLES_DIR = config.get("tables_dir", "tables")

_TIMEOUT_DEFAULT_H = float(config.get("timeout_default_hours",
                            config.get("timeout_hours", 2)))
_TIMEOUT_PER_PROG  = config.get("timeout_per_program", {}) or {}

def timeout_sec(program):
    h = float(_TIMEOUT_PER_PROG.get(program, _TIMEOUT_DEFAULT_H))
    return int(h * 3600)

TIMEOUT_H   = _TIMEOUT_DEFAULT_H
TIMEOUT_SEC = int(TIMEOUT_H * 3600)
BENCH_WRAPPER = "scripts/run_bench.sh"

localrules: download_zenodo, download_hprc, download_all, tables_only, generate_tables, clone_bubblefinder, clone_billi, install_vg, install_bubblegun

GFA_DIRS = config.get("gfa_dirs", [DATA_DIR, "GFAs", "zenodo_gfas"])

HPRC_FILES = {
    "hprc-v1.1-mc-chm13.gfa.gz":
        "https://s3-us-west-2.amazonaws.com/human-pangenomics/pangenomes/freeze/freeze1/minigraph-cactus/hprc-v1.1-mc-chm13/hprc-v1.1-mc-chm13.gfa.gz",
    "hprc-v1.1-mc-chm13.gbz":
        "https://s3-us-west-2.amazonaws.com/human-pangenomics/pangenomes/freeze/freeze1/minigraph-cactus/hprc-v1.1-mc-chm13/hprc-v1.1-mc-chm13.gbz",
    "hprc-v2.0-mc-chm13.gfa.gz":
        "https://s3-us-west-2.amazonaws.com/human-pangenomics/pangenomes/scratch/2025_02_28_minigraph_cactus/hprc-v2.0-mc-chm13/hprc-v2.0-mc-chm13.gfa.gz",
    "hprc-v2.0-mc-chm13.gbz":
        "https://s3-us-west-2.amazonaws.com/human-pangenomics/pangenomes/scratch/2025_02_28_minigraph_cactus/hprc-v2.0-mc-chm13/hprc-v2.0-mc-chm13.gbz",
}


TOOLS_DIR = config.get("tools_dir", "tools")

BF_REPO = "https://github.com/algbio/BubbleFinder.git"
BF_COMMIT = "1b11e9b"
BILLI_REPO = "https://github.com/at-cg/billi.git"
BILLI_COMMIT = "a77892e"
VG_VERSION = "1.72.0"
BUBBLEGUN_REPO = "https://github.com/fawaz-dabbaghieh/bubble_gun.git"
BUBBLEGUN_VERSION = "1.2.0"

BF_BIN = os.path.join(TOOLS_DIR, "BubbleFinder", "build", "BubbleFinder")
VG_BIN = os.path.join(TOOLS_DIR, "vg")
BILLI_BIN = os.path.join(TOOLS_DIR, "billi", "billi")
GFA_STATS_BIN = os.path.join(TOOLS_DIR, "gfa_stats")


DATASETS = config.get("datasets", [
    "ecoli50.cleaned",
    "Ecoli-v1.1-p0g30r5",
    "GCA.cleaned",
    "Mtb152m-v1.1-p0a1",
    "Mtb152m-v1.1-p1a2",
    "Mtb152p-v1.1-p0a1",
    "mouse17_chr19.cleaned",
    "tomato23_chr2.cleaned",
    "primates_chr6.cleaned",
    "Ultrabubble_dataset_chr1.cleaned",
    "Ultrabubble_dataset_chr10.cleaned",
    "Ultrabubble_dataset_chr22.cleaned",
    "hprc-v1.1-mc-chm13",
    "hprc-v2.0-mc-chm13",
    "human100-v1.1-a1",
    "human100p10-v1.1-a1",
    "human472-1.1a2",
    "human472p10-1.1a2",
])

TOOL_VARIANTS = [
    "vg_gfa_T", "vg_gfa_noT",
    "bf_gfa_T", "bf_gfa_noT",
    "bf_sb_gfa_T", "bf_sb_gfa_noT",
    "bubblegun", "billi", "gfa_stats", "vg_stats",
    "vg_gbz_T", "vg_gbz_noT",
    "bf_gbz_T", "bf_gbz_noT",
]


def find_gfa(ds):
    for d in GFA_DIRS:
        p = os.path.join(d, ds + ".gfa")
        if os.path.isfile(p):
            return p
    # If only .gfa.gz exists, return the expected .gfa path
    for d in GFA_DIRS:
        gz = os.path.join(d, ds + ".gfa.gz")
        if os.path.isfile(gz):
            return gz[:-3]  # strip .gz → will exist after decompression
    return None

def find_gbz(ds):
    for d in GFA_DIRS:
        p = os.path.join(d, ds + ".gbz")
        if os.path.isfile(p):
            return p
    return None

def gfa_fmt(_path):
    return "gfa"

def result_files_for(ds, tool):
    R = RESULTS_DIR
    if tool in ("vg_gbz_T", "vg_gbz_noT", "bf_gbz_T", "bf_gbz_noT"):
        if find_gbz(ds) is None:
            return []
        return {
            "vg_gbz_T":   [f"{R}/{ds}.vg_gbz.time"],
            "vg_gbz_noT": [f"{R}/{ds}.vg_gbz_noT.time"],
            "bf_gbz_T":   [f"{R}/{ds}.bf_gbz.time"],
            "bf_gbz_noT": [f"{R}/{ds}.bf_gbz_noT.time"],
        }.get(tool, [])
    gfa = find_gfa(ds)
    if gfa is None:
        return []
    fmt = gfa_fmt(gfa)
    R = RESULTS_DIR
    mapping = {
        "vg_gfa_T":   [f"{R}/{ds}.vg_gfa.{fmt}.time"],
        "vg_gfa_noT":  [f"{R}/{ds}.vg_gfa_noT.{fmt}.time"],
        "bf_gfa_T":   [f"{R}/{ds}.bf_gfa.{fmt}.time"],
        "bf_gfa_noT":  [f"{R}/{ds}.bf_gfa_noT.{fmt}.time"],
        "bf_sb_gfa_T": [f"{R}/{ds}.bf_sb_gfa.{fmt}.time"],
        "bf_sb_gfa_noT": [f"{R}/{ds}.bf_sb_gfa_noT.{fmt}.time"],
        "bubblegun":   [f"{R}/{ds}.bubblegun.time"],
        "billi":     [f"{R}/{ds}.billi.time"],
        "gfa_stats":  [f"{R}/{ds}.gfa_stats"],
        "vg_stats":   [f"{R}/{ds}.vg_stats"],
    }
    return mapping.get(tool, [])

def all_result_files():
    files = []
    for ds in DATASETS:
        for tool in TOOL_VARIANTS:
            files.extend(result_files_for(ds, tool))
    return [f for f in files if f]


rule clone_bubblefinder:
    output:
        stamp=os.path.join(TOOLS_DIR, "BubbleFinder", ".cloned"),
    params:
        repo=BF_REPO,
        commit=BF_COMMIT,
        srcdir=os.path.join(TOOLS_DIR, "BubbleFinder"),
    shell:
        """
        set -euo pipefail
        mkdir -p {TOOLS_DIR}
        if [ ! -d "{params.srcdir}/.git" ]; then
            rm -rf {params.srcdir}
            git clone {params.repo} {params.srcdir}
        fi
        cd {params.srcdir}
        git fetch origin
        git checkout {params.commit}
        git submodule update --init --recursive
        touch {output.stamp}
        echo "BubbleFinder cloned at commit {params.commit}"
        """

rule build_bubblefinder:
    input:
        stamp=os.path.join(TOOLS_DIR, "BubbleFinder", ".cloned"),
    output:
        bin=BF_BIN,
    params:
        srcdir=os.path.join(TOOLS_DIR, "BubbleFinder"),
    shell:
        """
        set -euo pipefail
        cd {params.srcdir}
        mkdir -p build && cd build
        CMAKE_EXTRA=""
        if [ -n "${{CONDA_PREFIX:-}}" ] && [ -f "$CONDA_PREFIX/include/zstd.h" ]; then
            CMAKE_EXTRA="-DCMAKE_PREFIX_PATH=$CONDA_PREFIX"
        fi
        cmake .. -DCMAKE_BUILD_TYPE=Release -DBUBBLEFINDER_HAS_GBZ=OFF \
            -DSB_NATIVE_OPTIMIZATIONS=OFF $CMAKE_EXTRA
        make -j$(nproc)
        echo "BubbleFinder built at commit $(git -C .. rev-parse --short HEAD)"
        """

rule build_gfa_stats:
    input:
        src="scripts/gfa_stats.cpp",
    output:
        bin=GFA_STATS_BIN,
    shell:
        """
        set -euo pipefail
        mkdir -p $(dirname {output.bin})
        g++ -O3 -std=c++17 -o {output.bin} {input.src}
        echo "gfa_stats compiled"
        """

rule install_vg:
    output:
        bin=VG_BIN,
    params:
        version=VG_VERSION,
    shell:
        """
        set -euo pipefail
        mkdir -p {TOOLS_DIR}
        echo "Downloading vg v{params.version} static binary from GitHub Releases..."
        curl -L -o {output.bin} \
            "https://github.com/vgteam/vg/releases/download/v{params.version}/vg"
        chmod +x {output.bin}
        echo "vg v{params.version} installed"
        {output.bin} version 2>&1 | head -1 || true
        """

rule install_bubblegun:
    output:
        stamp=os.path.join(TOOLS_DIR, ".bubblegun.installed"),
    params:
        repo=BUBBLEGUN_REPO,
        srcdir=os.path.join(TOOLS_DIR, "bubble_gun"),
    shell:
        """
        set -euo pipefail
        mkdir -p {TOOLS_DIR}
        if [ ! -d "{params.srcdir}/.git" ]; then
            rm -rf {params.srcdir}
            git clone {params.repo} {params.srcdir}
        fi
        cd {params.srcdir} && git fetch origin && git checkout master && git pull origin master && cd -
        pip install {params.srcdir}
        echo "BubbleGun installed from source"
        BubbleGun --version 2>&1 || true
        touch {output.stamp}
        """

rule clone_billi:
    output:
        stamp=os.path.join(TOOLS_DIR, "billi", ".cloned"),
    params:
        repo=BILLI_REPO,
        commit=BILLI_COMMIT,
        srcdir=os.path.join(TOOLS_DIR, "billi"),
    shell:
        """
        set -euo pipefail
        mkdir -p {TOOLS_DIR}
        if [ ! -d "{params.srcdir}/.git" ]; then
            rm -rf {params.srcdir}
            git clone {params.repo} {params.srcdir}
        fi
        cd {params.srcdir}
        git fetch origin
        git checkout {params.commit}
        touch {output.stamp}
        echo "Billi cloned at commit {params.commit}"
        """

rule build_billi:
    input:
        stamp=os.path.join(TOOLS_DIR, "billi", ".cloned"),
    output:
        bin=BILLI_BIN,
    params:
        srcdir=os.path.join(TOOLS_DIR, "billi"),
    shell:
        """
        set -euo pipefail
        cd {params.srcdir}
        make clean || true
        make -j$(nproc)
        echo "Billi built at commit $(git rev-parse --short HEAD)"
        """


rule download_zenodo:
    output:
        stamp=os.path.join(DATA_DIR, ".zenodo_{record}.done".format(record=ZENODO_RECORD)),
    params:
        record=ZENODO_RECORD,
        data_dir=DATA_DIR,
        jobs=config.get("download_jobs", 4),
    shell:
        """
        set -euo pipefail
        mkdir -p {params.data_dir}

        echo "Fetching file list from Zenodo record {params.record}..."
        FILE_LIST=$(curl -s "https://zenodo.org/api/records/{params.record}" \
            | python3 -c "
import sys, json
data = json.load(sys.stdin)
for f in data.get('files', []):
    print(f['key'])
")

        if [ -z "$FILE_LIST" ]; then
            echo "Trying draft API..."
            FILE_LIST=$(curl -s "https://zenodo.org/api/records/{params.record}/draft/files" \
                | python3 -c "
import sys, json
data = json.load(sys.stdin)
entries = data.get('entries', data) if isinstance(data, dict) else data
for f in entries:
    print(f['key'])
" 2>/dev/null || true)
        fi

        if [ -z "$FILE_LIST" ]; then
            echo "ERROR: Could not list files from Zenodo record {params.record}" >&2
            exit 1
        fi

        N_FILES=$(echo "$FILE_LIST" | wc -l)
        echo "Found $N_FILES files — downloading with {params.jobs} parallel jobs"

        echo "$FILE_LIST" | xargs -P {params.jobs} -I {{}} bash -c '
            dest="{params.data_dir}/{{}}"
            if [ -f "$dest" ]; then
                echo "  SKIP (exists): {{}}"
            else
                echo "  Downloading: {{}}"
                curl -sL -o "$dest" "https://zenodo.org/records/{params.record}/files/{{}}?download=1"
            fi
        '

        echo "All $N_FILES files downloaded to {params.data_dir}/"
        touch {output.stamp}
        """

rule download_hprc:
    output:
        stamp=os.path.join(DATA_DIR, ".hprc.done"),
    params:
        data_dir=DATA_DIR,
        jobs=config.get("download_jobs", 4),
    run:
        import subprocess, os
        os.makedirs(params.data_dir, exist_ok=True)
        # Build list of (url, dest) pairs to download
        to_download = []
        for fname, url in HPRC_FILES.items():
            dest = os.path.join(params.data_dir, fname)
            if os.path.isfile(dest):
                print(f"  SKIP (exists): {fname}")
            else:
                to_download.append((url, dest, fname))
        if to_download:
            print(f"Downloading {len(to_download)} HPRC files ({params.jobs} parallel)...")
            # Write URL list and use xargs
            url_lines = "\n".join(f"{url} {dest}" for url, dest, _ in to_download)
            subprocess.run(
                f"echo '{url_lines}' | xargs -P {params.jobs} -L1 bash -c "
                "'curl -sL -o \"$1\" \"$0\"'",
                shell=True, check=True)
        with open(output.stamp, "w") as f:
            f.write("done\n")

rule download_all:
    input:
        zenodo=os.path.join(DATA_DIR, ".zenodo_{record}.done".format(record=ZENODO_RECORD)),
        hprc=os.path.join(DATA_DIR, ".hprc.done"),
    output:
        touch(os.path.join(DATA_DIR, ".download_all.done")),
    params:
        data_dir=DATA_DIR,
        jobs=config.get("download_jobs", 4),
    shell:
        """
        set -euo pipefail
        echo "Decompressing .gfa.gz files in {params.data_dir}/ ({params.jobs} parallel)..."
        ls {params.data_dir}/*.gfa.gz 2>/dev/null | while read gz; do
            out="${{gz%.gz}}"
            if [ -f "$out" ]; then
                echo "  SKIP: $(basename $out)" >&2
            else
                echo "$gz"
            fi
        done | xargs -r -P {params.jobs} -I {{}} bash -c 'echo "  Decompressing: $(basename {{}})" && gunzip -k "{{}}"'
        echo "All files ready."
        """


rule generate_tables:
    input:
        zenodo=os.path.join(DATA_DIR, ".zenodo_{record}.done".format(record=ZENODO_RECORD)),
        hprc=os.path.join(DATA_DIR, ".hprc.done"),
        results=all_result_files(),
        script="scripts/make_table.py",
    output:
        bubble=os.path.join(TABLES_DIR, "bubble_table.tex"),
        gfa=os.path.join(TABLES_DIR, "gfa_table.tex"),
        stats=os.path.join(TABLES_DIR, "graph_stats_table.tex"),
        bench=os.path.join(TABLES_DIR, "bench_table.tex"),
        tsv=os.path.join(TABLES_DIR, "bench_summary.tsv"),
    shell:
        "mkdir -p {TABLES_DIR} && python3 {input.script} {RESULTS_DIR} {TABLES_DIR}"

rule tables_only:
    """Regenerate tables from existing results (no benchmarks, no download)."""
    input:
        script="scripts/make_table.py",
    output:
        touch(os.path.join(TABLES_DIR, ".tables_only.done")),
    shell:
        "mkdir -p {TABLES_DIR} && python3 {input.script} {RESULTS_DIR} {TABLES_DIR}"


rule run_vg_gfa_T:
    input:
        bin=VG_BIN,
    output:
        time=os.path.join(RESULTS_DIR, "{ds}.vg_gfa.{fmt}.time"),
    params:
        gfa=lambda wc: find_gfa(wc.ds),
        R=RESULTS_DIR,
        tsec=lambda wc: timeout_sec("vg_gfa_T"),
    shell:
        """
        set -euo pipefail
        [ ! -f "{params.gfa}" ] && [ -f "{params.gfa}.gz" ] && gunzip -k "{params.gfa}.gz" || true
        ds="{wildcards.ds}"; fmt="{wildcards.fmt}"; R="{params.R}"
        bash {BENCH_WRAPPER} {TIME_BIN} {params.tsec} {output.time} \
            "{input.bin} snarls -T -A integrated -t 1 {params.gfa} > $R/$ds.vg_gfa.$fmt.snarls.pb 2> $R/$ds.vg_gfa.$fmt.log"
        if [ -s "$R/$ds.vg_gfa.$fmt.snarls.pb" ]; then
            {input.bin} view -R -j "$R/$ds.vg_gfa.$fmt.snarls.pb" 2>/dev/null | python3 -c "
import sys, json
n_snarls = n_ub = 0
for line in sys.stdin:
    obj = json.loads(line)
    n_snarls += 1
    if obj.get('type') == 1: n_ub += 1
print(f'n_snarls\t{{n_snarls}}')
print(f'n_ub\t{{n_ub}}')
print(f'n_diff\t{{n_snarls - n_ub}}')
" > "$R/$ds.vg_gfa.$fmt.snarl_counts" 2>/dev/null || true
            grep 'n_ub' "$R/$ds.vg_gfa.$fmt.snarl_counts" > "$R/$ds.vg_gfa.$fmt.ub" 2>/dev/null || true
        fi
        """

rule run_vg_gfa_noT:
    input:
        bin=VG_BIN,
    output:
        time=os.path.join(RESULTS_DIR, "{ds}.vg_gfa_noT.{fmt}.time"),
    params:
        gfa=lambda wc: find_gfa(wc.ds),
        R=RESULTS_DIR,
        tsec=lambda wc: timeout_sec("vg_gfa_noT"),
    shell:
        """
        set -euo pipefail
        [ ! -f "{params.gfa}" ] && [ -f "{params.gfa}.gz" ] && gunzip -k "{params.gfa}.gz" || true
        ds="{wildcards.ds}"; fmt="{wildcards.fmt}"; R="{params.R}"
        bash {BENCH_WRAPPER} {TIME_BIN} {params.tsec} {output.time} \
            "{input.bin} snarls -A integrated -t 1 {params.gfa} > $R/$ds.vg_gfa_noT.$fmt.snarls.pb 2> $R/$ds.vg_gfa_noT.$fmt.log"
        if [ -s "$R/$ds.vg_gfa_noT.$fmt.snarls.pb" ]; then
            {input.bin} view -R -j "$R/$ds.vg_gfa_noT.$fmt.snarls.pb" 2>/dev/null | python3 -c "
import sys, json
n_snarls = n_ub = 0
for line in sys.stdin:
    obj = json.loads(line)
    n_snarls += 1
    if obj.get('type') == 1: n_ub += 1
print(f'n_snarls\t{{n_snarls}}')
print(f'n_ub\t{{n_ub}}')
print(f'n_diff\t{{n_snarls - n_ub}}')
" > "$R/$ds.vg_gfa_noT.$fmt.snarl_counts" 2>/dev/null || true
            grep 'n_ub' "$R/$ds.vg_gfa_noT.$fmt.snarl_counts" > "$R/$ds.vg_gfa_noT.$fmt.ub" 2>/dev/null || true
        fi
        """

rule run_bf_gfa_T:
    input:
        bin=BF_BIN,
    output:
        time=os.path.join(RESULTS_DIR, "{ds}.bf_gfa.{fmt}.time"),
    params:
        gfa=lambda wc: find_gfa(wc.ds),
        R=RESULTS_DIR,
        tsec=lambda wc: timeout_sec("bf_gfa_T"),
    shell:
        """
        set -euo pipefail
        [ ! -f "{params.gfa}" ] && [ -f "{params.gfa}.gz" ] && gunzip -k "{params.gfa}.gz" || true
        ds="{wildcards.ds}"; fmt="{wildcards.fmt}"; R="{params.R}"
        bash {BENCH_WRAPPER} {TIME_BIN} {params.tsec} {output.time} \
            "{input.bin} ultrabubbles -T -g {params.gfa} -o $R/$ds.bf_gfa.$fmt.txt -j 1 -m {BF_STACK} > $R/$ds.bf_gfa.$fmt.log 2>&1"
        """

rule run_bf_gfa_noT:
    input:
        bin=BF_BIN,
    output:
        time=os.path.join(RESULTS_DIR, "{ds}.bf_gfa_noT.{fmt}.time"),
    params:
        gfa=lambda wc: find_gfa(wc.ds),
        R=RESULTS_DIR,
        tsec=lambda wc: timeout_sec("bf_gfa_noT"),
    shell:
        """
        set -euo pipefail
        [ ! -f "{params.gfa}" ] && [ -f "{params.gfa}.gz" ] && gunzip -k "{params.gfa}.gz" || true
        ds="{wildcards.ds}"; fmt="{wildcards.fmt}"; R="{params.R}"
        bash {BENCH_WRAPPER} {TIME_BIN} {params.tsec} {output.time} \
            "{input.bin} ultrabubbles -g {params.gfa} -o $R/$ds.bf_gfa_noT.$fmt.txt -j 1 -m {BF_STACK} > $R/$ds.bf_gfa_noT.$fmt.log 2>&1"
        """

rule run_bf_sb_gfa_T:
    input:
        bin=BF_BIN,
    output:
        time=os.path.join(RESULTS_DIR, "{ds}.bf_sb_gfa.{fmt}.time"),
    params:
        gfa=lambda wc: find_gfa(wc.ds),
        R=RESULTS_DIR,
        tsec=lambda wc: timeout_sec("bf_sb_gfa_T"),
    shell:
        """
        set -euo pipefail
        [ ! -f "{params.gfa}" ] && [ -f "{params.gfa}.gz" ] && gunzip -k "{params.gfa}.gz" || true
        ds="{wildcards.ds}"; fmt="{wildcards.fmt}"; R="{params.R}"
        bash {BENCH_WRAPPER} {TIME_BIN} {params.tsec} {output.time} \
            "{input.bin} ultrabubbles --doubled -T -g {params.gfa} -o $R/$ds.bf_sb_gfa.$fmt.txt -j 1 -m {BF_STACK} > $R/$ds.bf_sb_gfa.$fmt.log 2>&1"
        """

rule run_bf_sb_gfa_noT:
    input:
        bin=BF_BIN,
    output:
        time=os.path.join(RESULTS_DIR, "{ds}.bf_sb_gfa_noT.{fmt}.time"),
    params:
        gfa=lambda wc: find_gfa(wc.ds),
        R=RESULTS_DIR,
        tsec=lambda wc: timeout_sec("bf_sb_gfa_noT"),
    shell:
        """
        set -euo pipefail
        [ ! -f "{params.gfa}" ] && [ -f "{params.gfa}.gz" ] && gunzip -k "{params.gfa}.gz" || true
        ds="{wildcards.ds}"; fmt="{wildcards.fmt}"; R="{params.R}"
        bash {BENCH_WRAPPER} {TIME_BIN} {params.tsec} {output.time} \
            "{input.bin} ultrabubbles --doubled -g {params.gfa} -o $R/$ds.bf_sb_gfa_noT.$fmt.txt -j 1 -m {BF_STACK} > $R/$ds.bf_sb_gfa_noT.$fmt.log 2>&1"
        """

rule run_bubblegun:
    input:
        stamp=os.path.join(TOOLS_DIR, ".bubblegun.installed"),
    output:
        time=os.path.join(RESULTS_DIR, "{ds}.bubblegun.time"),
    params:
        gfa=lambda wc: find_gfa(wc.ds),
        R=RESULTS_DIR,
        tsec=lambda wc: timeout_sec("bubblegun"),
    shell:
        """
        set -euo pipefail
        [ ! -f "{params.gfa}" ] && [ -f "{params.gfa}.gz" ] && gunzip -k "{params.gfa}.gz" || true
        ds="{wildcards.ds}"; R="{params.R}"
        bash {BENCH_WRAPPER} {TIME_BIN} {params.tsec} {output.time} \
            "BubbleGun -g {params.gfa} bchains --bubble_json $R/$ds.bubblegun.json > $R/$ds.bubblegun.log 2>&1"
        if [ -s "$R/$ds.bubblegun.json" ]; then
            python3 -c "
import json
with open('$R/$ds.bubblegun.json') as f: data = json.load(f)
ns = nt = 0
items = data if isinstance(data, list) else data.values() if isinstance(data, dict) else []
for ch in items:
    for b in (ch.get('bubbles',[]) if isinstance(ch,dict) else []):
        if isinstance(b,dict) and b.get('type')=='simple': nt+=1
        else: ns+=1
print(f'n_super\t{{ns}}')
print(f'n_simple\t{{nt}}')
print(f'n_total\t{{ns+nt}}')
" > "$R/$ds.bubblegun.counts" 2>/dev/null || true
        fi
        """

rule run_billi:
    input:
        bin=BILLI_BIN,
    output:
        time=os.path.join(RESULTS_DIR, "{ds}.billi.time"),
    params:
        gfa=lambda wc: find_gfa(wc.ds),
        R=RESULTS_DIR,
        tsec=lambda wc: timeout_sec("billi"),
    shell:
        """
        set -euo pipefail
        [ ! -f "{params.gfa}" ] && [ -f "{params.gfa}.gz" ] && gunzip -k "{params.gfa}.gz" || true
        ds="{wildcards.ds}"; R="{params.R}"
        bash {BENCH_WRAPPER} {TIME_BIN} {params.tsec} {output.time} \
            "{input.bin} decompose -i {params.gfa} > $R/$ds.billi.log 2>&1"
        grep '^[PH] ' "$R/$ds.billi.log" > "$R/$ds.billi.txt" 2>/dev/null || true
        n=$(grep -oP 'Total panbubbles found: \\K\\d+' "$R/$ds.billi.log" 2>/dev/null || echo "")
        [ -n "$n" ] && echo -e "n_panbubbles\t$n" > "$R/$ds.billi.counts" || true
        """

rule run_gfa_stats:
    input:
        bin=GFA_STATS_BIN,
    output:
        stats=os.path.join(RESULTS_DIR, "{ds}.gfa_stats"),
    params:
        gfa=lambda wc: find_gfa(wc.ds),
        tsec=lambda wc: timeout_sec("gfa_stats"),
    shell:
        """
        set -euo pipefail
        [ ! -f "{params.gfa}" ] && [ -f "{params.gfa}.gz" ] && gunzip -k "{params.gfa}.gz" || true
        TMP="{output.stats}.tmp"
        rm -f "$TMP"
        timeout {params.tsec}s {input.bin} "{params.gfa}" > "$TMP" 2>/dev/null
        mv "$TMP" {output.stats}
        """

rule compute_vg_stats:
    input:
        bin=VG_BIN,
    output:
        stats=os.path.join(RESULTS_DIR, "{ds}.vg_stats"),
    params:
        gfa=lambda wc: find_gfa(wc.ds),
        tsec=lambda wc: timeout_sec("gfa_stats"),
    shell:
        """
        set -euo pipefail
        [ ! -f "{params.gfa}" ] && [ -f "{params.gfa}.gz" ] && gunzip -k "{params.gfa}.gz" || true
        TMP="{output.stats}.tmp"
        rm -f "$TMP"
        timeout {params.tsec}s {input.bin} stats -N -E "{params.gfa}" 2>/dev/null \
            | paste <(printf "nodes\\nedges") - > "$TMP"
        mv "$TMP" {output.stats}
        """

rule run_vg_gbz_T:
    input:
        bin=VG_BIN,
    output:
        time=os.path.join(RESULTS_DIR, "{ds}.vg_gbz.time"),
    params:
        gbz=lambda wc: find_gbz(wc.ds),
        R=RESULTS_DIR,
        tsec=lambda wc: timeout_sec("vg_gbz_T"),
    shell:
        """
        set -euo pipefail
        ds="{wildcards.ds}"; R="{params.R}"
        bash {BENCH_WRAPPER} {TIME_BIN} {params.tsec} {output.time} \
            "{input.bin} snarls -T -A integrated -t 1 {params.gbz} > $R/$ds.vg_gbz.snarls.pb 2> $R/$ds.vg_gbz.log"
        if [ -s "$R/$ds.vg_gbz.snarls.pb" ]; then
            {input.bin} view -R -j "$R/$ds.vg_gbz.snarls.pb" 2>/dev/null | python3 -c "
import sys, json
n_snarls = n_ub = 0
for line in sys.stdin:
    obj = json.loads(line)
    n_snarls += 1
    if obj.get('type') == 1: n_ub += 1
print(f'n_snarls\t{{n_snarls}}')
print(f'n_ub\t{{n_ub}}')
print(f'n_diff\t{{n_snarls - n_ub}}')
" > "$R/$ds.vg_gbz.snarl_counts" 2>/dev/null || true
            grep 'n_ub' "$R/$ds.vg_gbz.snarl_counts" > "$R/$ds.vg_gbz.ub" 2>/dev/null || true
        fi
        """

rule run_vg_gbz_noT:
    input:
        bin=VG_BIN,
    output:
        time=os.path.join(RESULTS_DIR, "{ds}.vg_gbz_noT.time"),
    params:
        gbz=lambda wc: find_gbz(wc.ds),
        R=RESULTS_DIR,
        tsec=lambda wc: timeout_sec("vg_gbz_noT"),
    shell:
        """
        set -euo pipefail
        ds="{wildcards.ds}"; R="{params.R}"
        bash {BENCH_WRAPPER} {TIME_BIN} {params.tsec} {output.time} \
            "{input.bin} snarls -A integrated -t 1 {params.gbz} > $R/$ds.vg_gbz_noT.snarls.pb 2> $R/$ds.vg_gbz_noT.log"
        if [ -s "$R/$ds.vg_gbz_noT.snarls.pb" ]; then
            {input.bin} view -R -j "$R/$ds.vg_gbz_noT.snarls.pb" 2>/dev/null | python3 -c "
import sys, json
n_snarls = n_ub = 0
for line in sys.stdin:
    obj = json.loads(line)
    n_snarls += 1
    if obj.get('type') == 1: n_ub += 1
print(f'n_snarls\t{{n_snarls}}')
print(f'n_ub\t{{n_ub}}')
print(f'n_diff\t{{n_snarls - n_ub}}')
" > "$R/$ds.vg_gbz_noT.snarl_counts" 2>/dev/null || true
            grep 'n_ub' "$R/$ds.vg_gbz_noT.snarl_counts" > "$R/$ds.vg_gbz_noT.ub" 2>/dev/null || true
        fi
        """

rule run_bf_gbz_T:
    input:
        bin=BF_BIN,
    output:
        time=os.path.join(RESULTS_DIR, "{ds}.bf_gbz.time"),
    params:
        gbz=lambda wc: find_gbz(wc.ds),
        R=RESULTS_DIR,
        tsec=lambda wc: timeout_sec("bf_gbz_T"),
    shell:
        """
        set -euo pipefail
        ds="{wildcards.ds}"; R="{params.R}"
        bash {BENCH_WRAPPER} {TIME_BIN} {params.tsec} {output.time} \
            "{input.bin} ultrabubbles -T -g {params.gbz} -o $R/$ds.bf_gbz.txt -j 1 -m {BF_STACK} > $R/$ds.bf_gbz.log 2>&1"
        """

rule run_bf_gbz_noT:
    input:
        bin=BF_BIN,
    output:
        time=os.path.join(RESULTS_DIR, "{ds}.bf_gbz_noT.time"),
    params:
        gbz=lambda wc: find_gbz(wc.ds),
        R=RESULTS_DIR,
        tsec=lambda wc: timeout_sec("bf_gbz_noT"),
    shell:
        """
        set -euo pipefail
        ds="{wildcards.ds}"; R="{params.R}"
        bash {BENCH_WRAPPER} {TIME_BIN} {params.tsec} {output.time} \
            "{input.bin} ultrabubbles -g {params.gbz} -o $R/$ds.bf_gbz_noT.txt -j 1 -m {BF_STACK} > $R/$ds.bf_gbz_noT.log 2>&1"
        """