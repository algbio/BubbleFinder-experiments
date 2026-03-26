import os
import re
import sys
import glob
import json
import subprocess
from collections import defaultdict
from pathlib import Path
STATUS_OK = "ok"
STATUS_TIMEOUT = "timeout"
STATUS_OOM = "oom"
STATUS_KILLED = "killed"
STATUS_CRASHED = "crashed"
STATUS_NO_DATA = "no_data"
STATUS_NA = "na" 

TIMEOUT_HOURS = 3
TIMEOUT_SEC = TIMEOUT_HOURS * 3600

def _build_status_labels():
    global STATUS_LABELS, STATUS_LABELS_TEX
    STATUS_LABELS = {
        STATUS_TIMEOUT: f"TO ({TIMEOUT_HOURS}h)",
        STATUS_OOM: "OOM",
        STATUS_KILLED: "KILL",
        STATUS_CRASHED: "ERR",
        STATUS_NO_DATA: "--",
        STATUS_NA: "N/A",
    }
    STATUS_LABELS_TEX = {
        STATUS_TIMEOUT: f"TO ({TIMEOUT_HOURS}\\,h)",
        STATUS_OOM: "OOM",
        STATUS_KILLED: "KILL",
        STATUS_CRASHED: "ERR",
        STATUS_NO_DATA: "--",
        STATUS_NA: "N/A",
    }

STATUS_LABELS = {}
STATUS_LABELS_TEX = {}
_build_status_labels()

def infer_timeout(results_dir):
    import math
    max_wall = 0
    for f in glob.glob(os.path.join(results_dir, "*.time")):
        try:
            text = Path(f).read_text()
        except Exception:
            continue
        if not re.search(r"Exit status:\s+124", text):
            continue
        m = re.search(r"Elapsed \(wall clock\).*:\s+(.+)", text)
        if not m:
            continue
        parts = m.group(1).strip().split(":")
        try:
            if len(parts) == 3:
                wall = float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
            elif len(parts) == 2:
                wall = float(parts[0])*60 + float(parts[1])
            else:
                wall = float(parts[0])
            max_wall = max(max_wall, wall)
        except ValueError:
            pass
    if max_wall > 0:
        return math.ceil(max_wall / 3600)
    return 3

def load_config_timeouts(results_dir):
    for base in [os.path.dirname(results_dir), "."]:
        path = os.path.join(base, "config", "benchmarks.yaml")
        if os.path.isfile(path):
            try:
                text = Path(path).read_text()
                default = None
                m = re.search(r"timeout_default_hours:\s+([\d.]+)", text)
                if m:
                    val = float(m.group(1))
                    default = int(val) if val == int(val) else val
                per_program = {}
                in_section = False
                for line in text.split("\n"):
                    if line.startswith("timeout_per_program:"):
                        in_section = True
                        continue
                    if in_section:
                        pm = re.match(r"\s+(\S+):\s+([\d.]+)", line)
                        if pm:
                            val = float(pm.group(2))
                            per_program[pm.group(1)] = int(val) if val == int(val) else val
                        elif line.strip() and not line.startswith(" "):
                            in_section = False
                return default, per_program
            except Exception:
                pass
    return None, {}

TIMEOUT_PER_PROGRAM = {}

def get_tool_timeout(tool):
    if tool in TIMEOUT_PER_PROGRAM:
        return TIMEOUT_PER_PROGRAM[tool]
    key_T = tool + "_T"
    if key_T in TIMEOUT_PER_PROGRAM:
        return TIMEOUT_PER_PROGRAM[key_T]
    return TIMEOUT_HOURS

def set_timeout(hours):
    global TIMEOUT_HOURS, TIMEOUT_SEC
    TIMEOUT_HOURS = hours
    TIMEOUT_SEC = hours * 3600
    _build_status_labels()

def parse_time_file(path):
    info = {}
    try:
        text = Path(path).read_text()
    except Exception:
        return info
    if not text.strip():
        info["run_status"] = STATUS_KILLED
        info["_diag"] = ".time file empty"
        return info
    if text.startswith("EXIT_CODE="):
        meta, _, time_text = text.partition("---\n")
        for line in meta.strip().split("\n"):
            if line.startswith("REASON=TIMEOUT"):
                info["run_status"] = STATUS_TIMEOUT
                info["timed_out"] = True
            elif line.startswith("REASON=KILLED_OR_OOM"):
                info["run_status"] = STATUS_OOM
            elif line.startswith("REASON=SEGFAULT"):
                info["run_status"] = STATUS_CRASHED
            elif line.startswith("REASON=ERROR"):
                info["run_status"] = STATUS_CRASHED
        text = time_text if time_text.strip() else ""
        if not text:
            return info
    m = re.search(r"Elapsed \(wall clock\).*:\s+(.+)", text)
    if m:
        parts = m.group(1).strip().split(":")
        try:
            if len(parts) == 3:
                info["wall_sec"] = float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
            elif len(parts) == 2:
                info["wall_sec"] = float(parts[0])*60 + float(parts[1])
            else:
                info["wall_sec"] = float(parts[0])
        except ValueError:
            pass
    m = re.search(r"User time.*:\s+([\d.]+)", text)
    if m: info["user_sec"] = float(m.group(1))
    m = re.search(r"System time.*:\s+([\d.]+)", text)
    if m: info["sys_sec"] = float(m.group(1))
    m = re.search(r"Maximum resident.*:\s+(\d+)", text)
    if m: info["rss_kb"] = int(m.group(1))
    m_signal = re.search(r"Command terminated by signal (\d+)", text)
    if m_signal:
        info["killed_signal"] = int(m_signal.group(1))
    m_exit = re.search(r"Exit status:\s+(\d+)", text)
    exit_code = int(m_exit.group(1)) if m_exit else None
    if exit_code is not None:
        info["exit_code"] = exit_code
    if exit_code == 124:
        info["run_status"] = STATUS_TIMEOUT
        info["timed_out"] = True
    elif m_signal:
        sig = info["killed_signal"]
        if sig in (6, 11):
            info["run_status"] = STATUS_CRASHED
        elif sig == 9:
            info["run_status"] = STATUS_OOM
        else:
            info["run_status"] = STATUS_KILLED
    elif "wall_sec" in info and info["wall_sec"] >= TIMEOUT_SEC * 0.99:
        info["run_status"] = STATUS_TIMEOUT
        info["timed_out"] = True
    elif exit_code is not None and exit_code != 0:
        info["run_status"] = STATUS_CRASHED
    return info


def parse_bf_stderr(path):
    info = {}
    try:
        text = Path(path).read_text()
    except Exception:
        return info
    def ts_to_sec(match):
        h, m, s, ms = match
        return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000
    lines = text.split("\n")
    t_parse_start = t_parse_end = t_end = None
    for line in lines:
        ts_match = re.match(r"\[(\d+):(\d+):(\d+)\.(\d+)\]", line)
        if not ts_match:
            continue
        t = ts_to_sec(ts_match.groups())
        if "parsing input" in line or "parsing GFA" in line or "Starting to read graph" in line:
            t_parse_start = t
        elif "segments," in line and "links" in line:
            t_parse_end = t
        elif "Process PeakRSS" in line:
            t_end = t
    if t_parse_start is not None and t_parse_end is not None:
        diff = t_parse_end - t_parse_start
        if diff < 0: diff += 86400
        info["parse_sec"] = round(diff, 1)
    if t_parse_end is not None and t_end is not None:
        diff = t_end - t_parse_end
        if diff < 0: diff += 86400
        info["algo_sec"] = round(diff, 1)
    if t_parse_start is not None and t_end is not None:
        diff = t_end - t_parse_start
        if diff < 0: diff += 86400
        info["total_from_log"] = round(diff, 1)
    m = re.search(r"(\d+\.\d+)s\s*\|.*\|\s*io/read_graph", text)
    if m: info["io_read_graph_sec"] = float(m.group(1))
    m = re.search(r"ULTRABUBBLES found:\s+(\d+)", text)
    if m: info["n_ub_log"] = int(m.group(1))
    tipless = re.findall(r"\[WARNING\] Skipping tipless connected component", text)
    if tipless:
        info["n_tipless_cc"] = len(tipless)
    if "n_ub_log" not in info:
        if "terminate called" in text or "orientation failed" in text:
            info["crashed"] = True
    m = re.search(r"(\d+)\s+segments,\s+(\d+)\s+links", text)
    if m:
        info["n_segments"] = int(m.group(1))
        info["n_links"] = int(m.group(2))
    m = re.search(r"Conflict vertices:\s+(\d+)", text)
    if m:
        info["n_conflict_vtx"] = int(m.group(1))
    return info


def count_ub_from_output(path):
    try:
        with open(path) as f:
            first = f.readline().strip()
            return int(first)
    except Exception:
        return None


def parse_vg_ub(path):
    info = {}
    try:
        for line in Path(path).read_text().strip().split("\n"):
            parts = line.split("\t")
            if len(parts) == 2:
                info[parts[0]] = int(parts[1])
    except Exception:
        pass
    return info


def parse_snarl_counts(path):
    info = {}
    try:
        for line in Path(path).read_text().strip().split("\n"):
            parts = line.split("\t")
            if len(parts) == 2:
                info[parts[0]] = int(parts[1])
    except Exception:
        pass
    return info


def count_bf_superbubbles(path):
    try:
        with open(path) as f:
            return int(f.readline().strip())
    except Exception:
        return None


def parse_gfa_stats(path):
    info = {}
    try:
        text = Path(path).read_text()
    except Exception:
        return info
    for key, pat in [
        ("nodes_raw", r"Nodes:\s+(\d+)"), ("edges", r"Edges:\s+(\d+)"),
        ("n_cc_raw", r"Connected components:\s+(\d+)"), ("tips", r"Total tips:\s+(\d+)"),
        ("cuts", r"Total cut vertices:\s+(\d+)"),
        ("trivial_cc", r"Trivial CCs.*:\s+(\d+)"),
        ("tipless_cc", r"(?:Non-triv\. w/o tips|CCs without tips):\s*(\d+)"),
        ("cutless_cc", r"(?:Non-triv\. w/o cut vtx|CCs without cut vtx):\s*(\d+)"),
    ]:
        m = re.search(pat, text)
        if m:
            info[key] = int(m.group(1))
    trivial = info.get("trivial_cc", 0)
    if "nodes_raw" in info:
        info["nodes"] = info["nodes_raw"]
    if "n_cc_raw" in info:
        info["n_cc"] = info["n_cc_raw"] - trivial
    return info


def parse_vg_stats(path):
    info = {}
    try:
        text = Path(path).read_text()
    except Exception:
        return info
    m = re.search(r"nodes\s+(\d+)", text)
    if m: info["nodes"] = int(m.group(1))
    m = re.search(r"edges\s+(\d+)", text)
    if m: info["edges"] = int(m.group(1))
    return info


def parse_kv_counts(path):
    info = {}
    try:
        for line in Path(path).read_text().strip().split("\n"):
            parts = line.split("\t")
            if len(parts) == 2:
                try: info[parts[0]] = int(parts[1])
                except ValueError: info[parts[0]] = parts[1]
    except Exception:
        pass
    return info


def parse_bubblegun_json(path):
    try:
        with open(path) as f:
            data = json.load(f)
        n_super = n_simple = 0
        items = data if isinstance(data, list) else data.values() if isinstance(data, dict) else []
        for chain in items:
            bubbles = chain.get("bubbles", []) if isinstance(chain, dict) else []
            for b in bubbles:
                btype = b.get("type", "") if isinstance(b, dict) else ""
                if btype == "simple": n_simple += 1
                else: n_super += 1
        return {"bg_n_super": n_super, "bg_n_simple": n_simple, "bg_n_total": n_super + n_simple}
    except Exception:
        return {}


def count_billi_output(path):
    try:
        text = Path(path).read_text()
    except Exception:
        return None
    if not text.strip():
        return None
    m = re.search(r"Total panbubbles found:\s+(\d+)", text)
    if m:
        return int(m.group(1))
    n = sum(1 for line in text.split("\n") if line.startswith("P\t") or line.startswith("P "))
    return n if n > 0 else None


def check_billi_log_crash(path):
    try:
        text = Path(path).read_text()
    except Exception:
        return None
    if "component with zero tips!" in text or "terminate called" in text:
        return "tipless"
    if "Segmentation fault" in text or "core dumped" in text:
        return "segfault"
    if "std::bad_alloc" in text:
        return "oom"
    return None

def get_status(row):
    return row.get("run_status", STATUS_OK)

def is_failed(row):
    return get_status(row) in (STATUS_TIMEOUT, STATUS_OOM, STATUS_KILLED, STATUS_CRASHED, STATUS_NA)

def status_label_tex(row):
    s = get_status(row)
    if s == STATUS_OK: return None
    if s == STATUS_TIMEOUT:
        th = row.get("timeout_hours", TIMEOUT_HOURS)
        if isinstance(th, float) and th == int(th):
            th = int(th)
        return f"TO ({th}\\,h)"
    return STATUS_LABELS_TEX.get(s, "--")

_MAIN_TOOLS = ["vg_gbz_noT", "bf_gbz_noT", "vg_gbz", "bf_gbz",
               "vg_noT", "bf_noT", "vg", "bf"]
_GFA_TOOLS = [
    "bf_gfa_noT", "bf_gfa",
    "vg_gfa_noT", "vg_gfa",
    "bf_sb_gfa_noT", "bf_sb_gfa",
]

def discover_results(results_dir):
    entries = defaultdict(dict)
    all_time = {}
    for f in glob.glob(os.path.join(results_dir, "*.time")):
        all_time[os.path.basename(f)] = f
    for f in glob.glob(os.path.join(results_dir, "*.time.failed")):
        key = os.path.basename(f)[:-len(".failed")]
        if key not in all_time:
            all_time[key] = f
    for base, f in sorted(all_time.items()):
        parts = base.rsplit(".", 1)[0]
        tf = os.path.join(results_dir, base)
        if ".bubblegun." in base or ".billi." in base:
            continue
        is_gfa_tool = any(f".{gt}." in base for gt in _GFA_TOOLS)
        if is_gfa_tool:
            continue
        for tool in _MAIN_TOOLS:
            marker = f".{tool}."
            idx = parts.find(marker)
            if idx < 0 and parts.endswith(f".{tool}"):
                idx = len(parts) - len(tool) - 1
            if idx >= 0:
                name = parts[:idx]
                fmt = parts[idx + len(marker):]
                key = (name, tool, fmt)
                entries[key]["time_file"] = f
                for ext in [".log", ".stderr"]:
                    lf = tf.replace(".time", ext)
                    if os.path.isfile(lf):
                        entries[key]["log_file"] = lf
                        break
                if tool in ("vg", "vg_noT", "vg_gbz", "vg_gbz_noT"):
                    ub_file = tf.replace(".time", ".ub")
                    if os.path.isfile(ub_file):
                        entries[key]["ub_file"] = ub_file
                    sc_file = tf.replace(".time", ".snarl_counts").replace(".snarls.pb", "")
                    sc_file2 = tf.replace(".time", "").replace(".time", "") 
                    for candidate in [tf.replace(".time", ".snarl_counts"),
                                      tf.replace(".time", "").rsplit(".", 1)[0] + ".snarl_counts"]:
                        if os.path.isfile(candidate):
                            entries[key]["snarl_counts_file"] = candidate
                            break
                else:
                    out = tf.replace(".time", ".txt")
                    if os.path.isfile(out):
                        entries[key]["output_file"] = out
                break
    for gt in _GFA_TOOLS:
        is_vg_tool = gt.startswith("vg_")
        gfa_time = {}
        for f in glob.glob(os.path.join(results_dir, f"*.{gt}.*.time")):
            gfa_time[os.path.basename(f)] = f
        for f in glob.glob(os.path.join(results_dir, f"*.{gt}.*.time.failed")):
            k = os.path.basename(f)[:-len(".failed")]
            if k not in gfa_time:
                gfa_time[k] = f
        for base, f in sorted(gfa_time.items()):
            tf = os.path.join(results_dir, base)
            idx = base.find(f".{gt}.")
            if idx >= 0:
                name = base[:idx]
                rest = base[idx + len(f".{gt}."):]
                fmt = rest.rsplit(".", 1)[0]
                key = (name, gt, fmt)
                entries[key]["time_file"] = f
                log_f = tf.replace(".time", ".log")
                if os.path.isfile(log_f):
                    entries[key]["log_file"] = log_f
                if is_vg_tool:
                    for candidate in [tf.replace(".time", ".snarl_counts")]:
                        if os.path.isfile(candidate):
                            entries[key]["snarl_counts_file"] = candidate
                    ub_f = tf.replace(".time", ".ub")
                    if os.path.isfile(ub_f):
                        entries[key]["ub_file"] = ub_f
                else:
                    out_f = tf.replace(".time", ".txt")
                    if os.path.isfile(out_f):
                        entries[key]["output_file"] = out_f
    gfa_stats = {}
    for f in sorted(glob.glob(os.path.join(results_dir, "*.gfa_stats"))):
        name = os.path.basename(f).rsplit(".", 1)[0]
        gfa_stats[name] = parse_gfa_stats(f)
    vg_stats = {}
    for f in sorted(glob.glob(os.path.join(results_dir, "*.vg_stats"))):
        name = os.path.basename(f).rsplit(".", 1)[0]
        vg_stats[name] = parse_vg_stats(f)
    conflict_vtx = {}
    for f in sorted(glob.glob(os.path.join(results_dir, "*.conflict_vertices"))):
        name = os.path.basename(f).rsplit(".", 1)[0]
        try:
            val = int(Path(f).read_text().strip())
            conflict_vtx[name] = val
            conflict_vtx[name + ".cleaned"] = val
        except (ValueError, OSError):
            pass
    return entries, gfa_stats, vg_stats, conflict_vtx


def discover_extra_tools(results_dir):
    bg_data = {}
    billi_data = {}
    # BubbleGun
    bg_names = set()
    for pattern in ("*.bubblegun.time", "*.bubblegun.time.failed",
                    "*.bubblegun.counts", "*.bubblegun.json"):
        for f in glob.glob(os.path.join(results_dir, pattern)):
            name = os.path.basename(f).split(".bubblegun.")[0]
            bg_names.add(name)
    for name in sorted(bg_names):
        row = {"dataset": name, "tool": "bubblegun"}
        time_f = os.path.join(results_dir, f"{name}.bubblegun.time")
        failed_f = time_f + ".failed"
        if os.path.isfile(time_f):
            if os.path.getsize(time_f) > 0:
                row.update(parse_time_file(time_f))
            else:
                row["run_status"] = STATUS_KILLED
        elif os.path.isfile(failed_f):
            row.update(parse_time_file(failed_f))
        counts_f = os.path.join(results_dir, f"{name}.bubblegun.counts")
        if os.path.isfile(counts_f) and os.path.getsize(counts_f) > 0:
            counts = parse_kv_counts(counts_f)
            for k in ("n_super", "n_simple", "n_total"):
                if k in counts: row[f"bg_{k}"] = counts[k]
        if "bg_n_super" not in row:
            json_f = os.path.join(results_dir, f"{name}.bubblegun.json")
            if os.path.isfile(json_f) and os.path.getsize(json_f) > 0:
                row.update(parse_bubblegun_json(json_f))
        if "run_status" not in row and "bg_n_super" not in row and not os.path.isfile(time_f) and not os.path.isfile(failed_f):
            row["run_status"] = STATUS_NO_DATA
        bg_data[name] = row
    # Billi
    billi_names = set()
    for pattern in ("*.billi.time", "*.billi.time.failed",
                    "*.billi.counts", "*.billi.txt", "*.billi.log"):
        for f in glob.glob(os.path.join(results_dir, pattern)):
            name = os.path.basename(f).split(".billi.")[0]
            billi_names.add(name)
    for name in sorted(billi_names):
        row = {"dataset": name, "tool": "billi"}
        time_f = os.path.join(results_dir, f"{name}.billi.time")
        failed_f = time_f + ".failed"
        if os.path.isfile(time_f):
            if os.path.getsize(time_f) > 0:
                row.update(parse_time_file(time_f))
            else:
                row["run_status"] = STATUS_KILLED
        elif os.path.isfile(failed_f):
            row.update(parse_time_file(failed_f))
        log_f = os.path.join(results_dir, f"{name}.billi.log")
        if os.path.isfile(log_f):
            crash_type = check_billi_log_crash(log_f)
            if crash_type == "tipless":
                row["run_status"] = STATUS_NA
                row["_diag"] = "Billi crashed: component with zero tips"
                billi_data[name] = row
                continue
            elif crash_type:
                row["run_status"] = STATUS_CRASHED
                billi_data[name] = row
                continue
        counts_f = os.path.join(results_dir, f"{name}.billi.counts")
        if os.path.isfile(counts_f) and os.path.getsize(counts_f) > 0:
            counts = parse_kv_counts(counts_f)
            if "n_panbubbles" in counts:
                row["n_panbubbles"] = counts["n_panbubbles"]
        if "n_panbubbles" not in row:
            for candidate in [os.path.join(results_dir, f"{name}.billi.txt"), log_f]:
                if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                    n = count_billi_output(candidate)
                    if n is not None:
                        row["n_panbubbles"] = n
                        break
        if "run_status" not in row and "n_panbubbles" not in row and not os.path.isfile(time_f) and not os.path.isfile(failed_f):
            row["run_status"] = STATUS_NO_DATA
        billi_data[name] = row
    return bg_data, billi_data

def _fmt_hms(sec):
    sec = float(sec)
    if sec < 1: return r"$<$\,1s"
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    if h > 0: return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def _fmt_gib(kb):
    gib = int(kb) / 1048576
    return f"{gib:.1f}" if gib >= 1 else f"{gib:.2f}"

def fmt_hms(sec, row=None):
    if row and is_failed(row): return status_label_tex(row)
    if sec is None or sec == "": return "--"
    return _fmt_hms(sec)

def fmt_mem(kb, row=None):
    if kb is not None and kb != "": return _fmt_gib(kb)
    if row and is_failed(row): return status_label_tex(row)
    return "--"

def fmt_count(n, row=None):
    if n is not None and n != "": return f"{int(n):,}"
    if row and is_failed(row): return status_label_tex(row)
    return "--"

def fmt_speedup(vg_wall, bf_wall, parse_sec):
    if vg_wall is None or bf_wall is None or parse_sec is None: return "--"
    try:
        v, b, p = float(vg_wall), float(bf_wall), float(parse_sec)
        algo_vg = v - p; algo_bf = b - p
        if algo_bf <= 0 or algo_vg <= 0: return "--"
        return f"{algo_vg/algo_bf:.2f}$\\times$"
    except (ValueError, TypeError): return "--"

def bold(s):
    if s == "--" or s.startswith("TO") or s.startswith("N/A") or s.startswith("ERR") or s.startswith("OOM"):
        return s
    return r"\textbf{" + s + "}"



DATASET_META = {
    "chrX":  ("MC",      r"\textsf{HPRC v1.1 Chr.~X}"),
    "chrY": ("MC",      r"\textsf{HPRC v1.1 Chr.~Y}"),
    "hprc-v1.1-mc-chm13": ("MC",      r"\textsf{HPRC v1.1 CHM13 (47 indiv.)}"),
    "hprc-v2.0-mc-chm13":      ("MC",      r"\textsf{HPRC v2.0 CHM13 (232 indiv.)}"),
    "ecoli50.cleaned":                   ("pggb",    r"\textsf{E.~coli (50 indiv.)}"),
    "mouse17_chr19.cleaned":     ("pggb",    r"\textsf{Mouse Chr.~19 (17 indiv.)}"),
    "primates_chr6.cleaned":             ("pggb",    r"\textsf{Primate Chr.~6 (14 indiv.)}"),
    "tomato23_chr2.cleaned":   ("pggb",    r"\textsf{Tomato Chr.~2 (23 indiv.)}"),
    "GCA.cleaned":     ("dbg",     r"\textsf{M.~xanthus (10 indiv.)}"),
    "Ultrabubble_dataset_chr1.cleaned":  ("vg",      r"\textsf{1000GP Chr.~1}"),
    "Ultrabubble_dataset_chr10.cleaned": ("vg",      r"\textsf{1000GP Chr.~10}"),
    "Ultrabubble_dataset_chr22.cleaned": ("vg",      r"\textsf{1000GP Chr.~22}"),
    "Ecoli-v1.1-p0g30r5":    ("Pangene", r"\textsf{E.~coli v1.1}"),
    "Mtb152m-v1.1-p0a1":       ("Pangene", r"\textsf{M.~tb 152m p0}"),
    "Mtb152m-v1.1-p1a2" :  ("Pangene", r"\textsf{M.~tb 152m p1}"),
    "Mtb152p-v1.1-p0a1" :                ("Pangene", r"\textsf{M.~tb 152p}"),
    "human100-v1.1-a1" :       ("Pangene", r"\textsf{Human 100}"),
    "human100p10-v1.1-a1" :    ("Pangene", r"\textsf{Human 100+10\%}"),
    "human472-1.1a2":                    ("Pangene", r"\textsf{Human 472}"),
    "human472p10-1.1a2":                 ("Pangene", r"\textsf{Human 472+10\%}"),
}

TYPE_ORDER = ["MC", "pggb", "dbg", "vg", "Pangene"]
TYPE_TEX = {
    "MC" : r"\textsf{MC}",
    "pggb": r"\textsf{pggb}",
    "dbg": r"\textsf{dbg}",
    "vg": r"\textsf{vg}",
    "Pangene": r"\textsf{Pangene}",
}

def ds_display(ds):
    meta = DATASET_META.get(ds)
    return meta[1] if meta else ds.replace("_", r"\_")

def type_col(i, n_rows, type_name):
    tex = TYPE_TEX.get(type_name, f"\\textsf{{{type_name}}}")
    if i == 0 and n_rows > 1:
        return f"\\multirow{{{n_rows}}}{{*}}{{{tex}}}"
    elif i == 0:
        return f"\\multirow{{1}}{{*}}{{{tex}}}"
    return ""

def main():
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "results"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else results_dir
    if not os.path.isdir(results_dir):
        print(f"Error: directory '{results_dir}' not found", file=sys.stderr)
        sys.exit(1)
    os.makedirs(out_dir, exist_ok=True)

    inferred_hours = infer_timeout(results_dir)
    cfg_default, cfg_per_program = load_config_timeouts(results_dir)
    global TIMEOUT_PER_PROGRAM
    TIMEOUT_PER_PROGRAM = cfg_per_program
    if cfg_default is not None:
        set_timeout(cfg_default)
        print(f"Timeout limit from config : {TIMEOUT_HOURS}h")
    else:
        set_timeout(inferred_hours)
        print(f"Inferred timeout limit : {TIMEOUT_HOURS}h")
    if cfg_per_program:
        vals = sorted(set(cfg_per_program.values()))
        print(f"Per program timeouts : {', '.join(f'{v}h' for v in vals)}")

    entries, gfa_stats_data, vg_stats_data, conflict_vtx = discover_results(results_dir)
    bg_data, billi_data = discover_extra_tools(results_dir)
    for row in bg_data.values():
        row["timeout_hours"] = get_tool_timeout("bubblegun")
    for row in billi_data.values():
        row.setdefault("timeout_hours", get_tool_timeout("billi"))

    rows = []
    for (name, tool, fmt), files in sorted(entries.items()):
        row = {"dataset": name, "tool": tool, "format": fmt}
        if "time_file" in files:
            row.update(parse_time_file(files["time_file"]))
        if tool in ("bf", "bf_noT", "bf_gbz", "bf_gbz_noT", "bf_gfa", "bf_gfa_noT",
                     "bf_sb", "bf_sb_noT", "bf_sb_gfa", "bf_sb_gfa_noT") and "log_file" in files:
            row.update(parse_bf_stderr(files["log_file"]))
        if tool in ("bf", "bf_noT", "bf_gbz", "bf_gbz_noT", "bf_gfa", "bf_gfa_noT") and "output_file" in files:
            n = count_ub_from_output(files["output_file"])
            if n is not None: row["n_ub"] = n
        if tool in ("vg", "vg_noT", "vg_gbz", "vg_gbz_noT", "vg_gfa", "vg_gfa_noT"):
            if "ub_file" in files:
                vg_ub = parse_vg_ub(files["ub_file"])
                if "n_ub" in vg_ub: row["n_ub"] = vg_ub["n_ub"]
                if "n_snarls" in vg_ub: row["n_snarls"] = vg_ub["n_snarls"]
            if "snarl_counts_file" in files:
                sc = parse_snarl_counts(files["snarl_counts_file"])
                if "n_ub" in sc: row["n_ub"] = sc["n_ub"]
                if "n_total" in sc: row["n_snarls"] = sc["n_total"]
                elif "n_snarls" in sc: row["n_snarls"] = sc["n_snarls"]
                if "n_diff" in sc: row["n_diff"] = sc["n_diff"]
            if "n_snarls" in row and "n_ub" in row and "n_diff" not in row:
                row["n_diff"] = row["n_snarls"] - row["n_ub"]
        if tool in ("bf_sb", "bf_sb_gfa", "bf_sb_noT", "bf_sb_gfa_noT") and "output_file" in files:
            n = count_bf_superbubbles(files["output_file"])
            if n is not None: row["n_sb"] = n
        row["timeout_hours"] = get_tool_timeout(tool)
        rows.append(row)

    datasets = sorted(set(r["dataset"] for r in rows) | set(bg_data.keys()) | set(billi_data.keys()))

    def index_tool(tool_name):
        return {r["dataset"]: r for r in rows if r["tool"] == tool_name}

    vg_data= index_tool("vg_gbz")
    vg_noT_data= index_tool("vg_gbz_noT")
    bf_data= index_tool("bf_gbz")
    vg_gfa_data= index_tool("vg_gfa")
    vg_gfa_noT_data= index_tool("vg_gfa_noT")
    bf_gfa_data= index_tool("bf_gfa")
    bf_gfa_noT_data= index_tool("bf_gfa_noT")
    bf_sb_gfa_data = index_tool("bf_sb_gfa")
    bf_sb_gfa_noT_data = index_tool("bf_sb_gfa_noT")

    grouped = {t: [] for t in TYPE_ORDER}
    ungrouped = []
    for ds in datasets:
        meta = DATASET_META.get(ds)
        if meta and meta[0] in grouped:
            grouped[meta[0]].append(ds)
        else:
            ungrouped.append(ds)

    def write_grouped_rows(f, row_func):
        first_group = True
        for type_name in TYPE_ORDER:
            ds_list = grouped[type_name]
            if not ds_list: continue
            if not first_group: f.write("\\hline\n")
            first_group = False
            for i, ds in enumerate(ds_list):
                tc = type_col(i, len(ds_list), type_name)
                f.write(row_func(ds, tc) + "\n")

    tsv_path = os.path.join(out_dir, "bench_summary.tsv")
    cols = ["dataset", "tool", "format", "wall_sec", "user_sec", "sys_sec",
            "rss_kb", "parse_sec", "algo_sec", "n_ub", "run_status"]
    with open(tsv_path, "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")) for c in cols) + "\n")
    print(f"TSV {tsv_path}")

    bubble_path = os.path.join(out_dir, "bubble_table.tex")
    with open(bubble_path, "w") as f:
        f.write(r"""\begin{table*}[ht]
\centering
\definecolor{famBiSB}{HTML}{F9E0E0}
\definecolor{famBiSBLight}{HTML}{FAE5E5}
\definecolor{famSnarl}{HTML}{E0F4E5}
\definecolor{famSnarlLight}{HTML}{E5F6EA}
\caption{Number of bubbles reported by each tool.
  All counts are based on GFA input, except for HPRC v2.0 with \texttt{vg snarls}, which was run on GBZ input because the GFA run timed out after 24\,h.
  Ultrabubble counts are shown both including and excluding trivial bubbles, as controlled by the \texttt{-T} flag in \texttt{vg snarls} and BubbleFinder.
  For \texttt{vg snarls}, the \emph{snarls} and \emph{diff} columns correspond to runs with trivial bubbles included; \emph{diff} denotes the number of snarls that are not ultrabubbles.
  BubbleGun reports nontrivial superbubbles, and Billi-heuristic reports nontrivial panbubbles.
  TO = exceeded the time limit; N/A = tool does not run on graphs with tipless connected components. We mark in \textbf{bold} the values equal to the corresponding number of non-trivial ultrabubbles reported by \vg.}
\label{tab:bubbles}
\renewcommand{\arraystretch}{1.15}
\setlength{\tabcolsep}{3.5pt}
\begin{adjustbox}{max width=\linewidth}
\begin{tabular}{l l r r r r r r r r r r}
\toprule
\multirow{3}{*}{Type} & \multirow{3}{*}{Dataset} &
\multicolumn{4}{>{\columncolor{famSnarl}}c}{\texttt{vg snarls}} &
\multicolumn{4}{>{\columncolor{famBiSB}}c}{BubbleFinder (ultrabubbles)} &
\multirow{3}{*}{\makecell{BubbleGun \\ {\scriptsize superbubbles}}} &
\multirow{3}{*}{\makecell{Billi-heuristic \\ {\scriptsize panbubbles}}} \\
& &
\multicolumn{1}{>{\columncolor{famSnarl}}c}{} &
\multicolumn{1}{>{\columncolor{famSnarl}}c}{} &
\multicolumn{1}{>{\columncolor{famSnarl}}c}{} &
\multicolumn{1}{>{\columncolor{famSnarl}}c}{} &
\multicolumn{2}{>{\columncolor{famBiSB}}c}{\scriptsize orientation} &
\multicolumn{2}{>{\columncolor{famBiSB}}c}{\scriptsize doubled} &
& \\
& &
\multicolumn{1}{>{\columncolor{famSnarl}}c}{\multirow{-2}{*}{\scriptsize \makecell{ultrabubbles\\incl.\ trivial}}} &
\multicolumn{1}{>{\columncolor{famSnarl}}c}{\multirow{-2}{*}{\scriptsize \makecell{snarls\\incl.\ trivial}}} &
\multicolumn{1}{>{\columncolor{famSnarl}}c}{\multirow{-2}{*}{\scriptsize diff}} &
\multicolumn{1}{>{\columncolor{famSnarl}}c}{\multirow{-2}{*}{\scriptsize \makecell{ultrabubbles\\excl.\ trivial}}} &
\multicolumn{1}{>{\columncolor{famBiSB}}c}{\scriptsize incl.\ triv.} &
\multicolumn{1}{>{\columncolor{famBiSB}}c}{\scriptsize excl.\ triv.} &
\multicolumn{1}{>{\columncolor{famBiSB}}c}{\scriptsize incl.\ triv.} &
\multicolumn{1}{>{\columncolor{famBiSB}}c}{\scriptsize excl.\ triv.} &
& \\
\midrule
""")
        def bubble_row(ds, tc):
            vg_g= vg_gfa_data.get(ds, {})
            vgN_g = vg_gfa_noT_data.get(ds, {})
            if not vg_g or is_failed(vg_g):
                vg_gbz = vg_data.get(ds, {})
                if vg_gbz and not is_failed(vg_gbz):
                    vg_g = vg_gbz
            if not vgN_g or is_failed(vgN_g):
                vgN_gbz = vg_noT_data.get(ds, {})
                if vgN_gbz and not is_failed(vgN_gbz):
                    vgN_g = vgN_gbz
            bf_g= bf_gfa_data.get(ds, {})
            bfN_g = bf_gfa_noT_data.get(ds, {})
            sb_g= bf_sb_gfa_data.get(ds, {})
            sbN_g = bf_sb_gfa_noT_data.get(ds, {})
            bg= bg_data.get(ds, {})
            bil = billi_data.get(ds, {})
            vg_noT_val = vgN_g.get("n_ub")

            def fmt_bold(n, row=None):
                """Format count, bold if matches vg_noT_val."""
                s = fmt_count(n, row)
                if vg_noT_val is not None and n is not None and n != "" and int(n) == int(vg_noT_val):
                    return bold(s)
                return s

            bf_ub = bf_g.get("n_ub", bf_g.get("n_ub_log"))
            bfN_ub= bfN_g.get("n_ub", bfN_g.get("n_ub_log"))

            return f"{tc} & {ds_display(ds)} & {fmt_count(vg_g.get('n_ub'), vg_g if vg_g else None)} & {fmt_count(vg_g.get('n_snarls'), vg_g if vg_g else None)} & {fmt_count(vg_g.get('n_diff'), vg_g if vg_g else None)} & {fmt_bold(vgN_g.get('n_ub'), vgN_g if vgN_g else None)} & {fmt_count(bf_ub, bf_g if bf_g else None)} & {fmt_bold(bfN_ub, bfN_g if bfN_g else None)} & {fmt_count(sb_g.get('n_sb'), sb_g if sb_g else None)} & {fmt_bold(sbN_g.get('n_sb'), sbN_g if sbN_g else None)} & {fmt_bold(bg.get('bg_n_total', bg.get('bg_n_super')), bg)} & {fmt_bold(bil.get('n_panbubbles'), bil)} \\\\"
            
        write_grouped_rows(f, bubble_row)
        f.write("\\bottomrule\n\\end{tabular}\n\\end{adjustbox}\n\\end{table*}\n")
    print(f"bubble_table.tex written to {bubble_path}")

    stats_path = os.path.join(out_dir, "graph_stats_table.tex")
    with open(stats_path, "w") as f:
        f.write(r"""\begin{table*}[ht]
\centering
\caption{Graph topology statistics.
  $n$ =number of segments (nodes), $m$=number of links (edges).
  Tips and cut vertices are counted on the bidirected graph.
  A connected component (CC) without tips has no degree-1 node. ``without cut vertices'' has no node whose removal disconnects the CC. Conflict vertices are those introduced by the orientation algorithm (Algorithm~1 in the main paper).}
\label{tab:graph_stats}
\renewcommand{\arraystretch}{1.15}
\setlength{\tabcolsep}{4pt}
\begin{adjustbox}{max width=\linewidth}
\begin{tabular}{l l r r r r r r r r}
\toprule
Type & Dataset & $n$ & $m$ &
\makecell{\#\,CCs} &
\makecell{\#\,tips} &
\makecell{\#\,cut\\vertices} &
\makecell{CCs w/o\\tips} &
\makecell{CCs w/o\\cut vtx} &
\makecell{\#\,conflict\\vertices} \\
\midrule
""")
        def stats_row(ds, tc):
            gs = gfa_stats_data.get(ds, {}); vs = vg_stats_data.get(ds, {})
            bf_g = bf_gfa_data.get(ds, {}); bf = bf_data.get(ds, {})
            n_val = vs.get("nodes") or bf_g.get("n_segments") or bf.get("n_segments") or gs.get("nodes")
            m_val = vs.get("edges") or bf_g.get("n_links") or bf.get("n_links") or gs.get("edges")
            z_val = conflict_vtx.get(ds) or bf_g.get("n_conflict_vtx")
            return (f"{tc} & {ds_display(ds)} & "
                    f"{fmt_count(n_val)} & {fmt_count(m_val)} & "
                    f"{fmt_count(gs.get('n_cc'))} & {fmt_count(gs.get('tips'))} & "
                    f"{fmt_count(gs.get('cuts'))} & "
                    f"{fmt_count(gs.get('tipless_cc'))} & {fmt_count(gs.get('cutless_cc'))} & "
                    f"{fmt_count(z_val)} \\\\")
        write_grouped_rows(f, stats_row)
        f.write("\\bottomrule\n\\end{tabular}\n\\end{adjustbox}\n\\end{table*}\n")
    print(f"graph_stats_table.tex written to {stats_path}")

    tex_path = os.path.join(out_dir, "bench_table.tex")
    with open(tex_path, "w") as f:
        f.write(r"""\begin{table*}[ht]
\centering
\definecolor{famBiSB}{HTML}{F9E0E0}
\definecolor{famBiSBLight}{HTML}{FAE5E5}
\definecolor{famSnarl}{HTML}{E0F4E5}
\definecolor{famSnarlLight}{HTML}{E5F6EA}

\caption{Performance comparison of \texttt{vg snarls} and BubbleFinder, on HPRC graphs in GBZ format.
  Times are wall-clock (single-threaded), formatted as h:mm:ss or m:ss.
  Memory is peak RSS in GiB.
  Both tools use the same GBZ parsing library (\texttt{gbwtgraph}). Speedup is computed excluding shared GBZ parsing time.}
\label{tab:gbz}
\renewcommand{\arraystretch}{1.15}
\setlength{\tabcolsep}{4pt}
\begin{adjustbox}{max width=\linewidth}
\begin{tabular}{l l c c c c c c}
\toprule
\multirow{2}{*}{Type} & \multirow{2}{*}{Dataset} &
\multicolumn{2}{c}{\cellcolor{famSnarl}\texttt{vg snarls}} &
\multicolumn{2}{c}{\cellcolor{famBiSB}BubbleFinder} &
\makecell{Parsing} &
\makecell{Speedup} \\
 & &
\cellcolor{famSnarl}{\scriptsize Time} & \cellcolor{famSnarl}{\scriptsize Mem (GiB)} &
\cellcolor{famBiSB}{\scriptsize Time} & \cellcolor{famBiSB}{\scriptsize Mem (GiB)} &
\scriptsize (GBZ, s) &
{\scriptsize excl.\ parsing} \\
\midrule
""")
        def bench_row(ds, tc):
            vg = vg_data.get(ds, {}); bf = bf_data.get(ds, {})
            return (f"{tc} & {ds_display(ds)} & "
                    f"{fmt_hms(vg.get('wall_sec'), vg)} & {fmt_mem(vg.get('rss_kb'), vg)} & "
                    f"{fmt_hms(bf.get('wall_sec'), bf)} & {fmt_mem(bf.get('rss_kb'), bf)} & "
                    f"{fmt_hms(bf.get('parse_sec'))} & "
                    f"{fmt_speedup(vg.get('wall_sec'), bf.get('wall_sec'), bf.get('parse_sec'))} \\\\")
        first_group = True
        for type_name in TYPE_ORDER:
            ds_list = [ds for ds in grouped[type_name] if ds in vg_data or ds in bf_data]
            if not ds_list: continue
            if not first_group: f.write("\\hline\n")
            first_group = False
            for i, ds in enumerate(ds_list):
                tc = type_col(i, len(ds_list), type_name)
                f.write(bench_row(ds, tc) + "\n")
        f.write("\\bottomrule\n\\end{tabular}\n\\end{adjustbox}\n\\end{table*}\n")
    print(f"bench_table.tex written to {tex_path}")
    gfa_path = os.path.join(out_dir, "gfa_table.tex")
    with open(gfa_path, "w") as f:
        f.write(r"""\begin{table*}[ht]
\centering
\definecolor{famBiSB}{HTML}{F9E0E0}
\definecolor{famBiSBLight}{HTML}{FAE5E5}
\definecolor{famSnarl}{HTML}{E0F4E5}
\definecolor{famSnarlLight}{HTML}{E5F6EA}
\caption{Performance comparison on GFA graphs across five tools computing bubble-like structures.
  Times are wall-clock (single-threaded), formatted as h:mm:ss or m:ss.
  Memory is peak RSS in GiB. For BubbleFinder and BubbleFinder (doubled), the Parsing column reports the parsing part of the runtime (including on-the-fly construction of the internal graph representation) and is included in the Time column. For the doubled mode, this involves building a graph with twice as many vertices.
  BubbleFinder (doubled) uses the doubled-graph method for ultrabubble detection.
  Best time and memory per dataset are in \textbf{bold} (excluding parsing-only columns and datasets where all tools take under one second).
  TO~=~exceeded time limit; N/A~=~tool does not run because the graph is tipless.}
\label{tab:gfa}
\renewcommand{\arraystretch}{1.15}
\setlength{\tabcolsep}{4pt}
\begin{adjustbox}{max width=\linewidth}
\begin{tabular}{l l c c c c c c c c c c c c}
\toprule
\multirow{2}{*}{Type} & \multirow{2}{*}{Dataset} &
\multicolumn{2}{c}{\cellcolor{famSnarl}\texttt{vg snarls}} &
\multicolumn{3}{c}{\cellcolor{famBiSB}BubbleFinder} &
\multicolumn{3}{c}{\cellcolor{famBiSB}BubbleFinder (doubled)} &
\multicolumn{2}{c}{BubbleGun} &
\multicolumn{2}{c}{Billi-heuristic} \\
 & &
\cellcolor{famSnarl}{\scriptsize Time} & \cellcolor{famSnarl}{\scriptsize Mem} &
\cellcolor{famBiSB}{\scriptsize Parsing} &
\cellcolor{famBiSB}{\scriptsize Time} & \cellcolor{famBiSB}{\scriptsize Mem} &
\cellcolor{famBiSB}{\scriptsize Parsing} &
\cellcolor{famBiSB}{\scriptsize Time} & \cellcolor{famBiSB}{\scriptsize Mem} &
{\scriptsize Time} & {\scriptsize Mem} &
{\scriptsize Time} & {\scriptsize Mem} \\
\midrule
""")
        def gfa_row(ds, tc):
            vg_g = vg_gfa_data.get(ds, {})
            bf_g = bf_gfa_data.get(ds, {})
            sb_g = bf_sb_gfa_data.get(ds, {})
            bg = bg_data.get(ds, {})
            bil = billi_data.get(ds, {})

            bf_parse = bf_g.get("parse_sec") or bf_g.get("io_read_graph_sec")
            sb_parse = sb_g.get("parse_sec") or sb_g.get("io_read_graph_sec")

            times = []
            for r in [vg_g, bf_g, sb_g]:
                w = r.get("wall_sec")
                if w is not None and not is_failed(r):
                    times.append(w)
            mems = []
            for r in [vg_g, bf_g, sb_g]:
                m = r.get("rss_kb")
                if m is not None and not is_failed(r):
                    mems.append(m)

            all_under_1s = all(t < 1 for t in times) if times else True
            best_time = min(times) if times and not all_under_1s else None
            best_mem = min(mems) if mems and not all_under_1s else None

            def fmt_t(sec, row):
                s = fmt_hms(sec, row)
                if best_time is not None and sec is not None and not is_failed(row) and abs(float(sec) - best_time) < 0.5:
                    return bold(s)
                return s

            def fmt_m(kb, row):
                s = fmt_mem(kb, row)
                if best_mem is not None and kb is not None and not is_failed(row) and int(kb) == int(best_mem):
                    return bold(s)
                return s

            return (f"{tc} & {ds_display(ds)} & "
                    f"{fmt_t(vg_g.get('wall_sec'), vg_g)} & {fmt_m(vg_g.get('rss_kb'), vg_g)} & "
                    f"{fmt_hms(bf_parse)} & "
                    f"{fmt_t(bf_g.get('wall_sec'), bf_g)} & {fmt_m(bf_g.get('rss_kb'), bf_g)} & "
                    f"{fmt_hms(sb_parse)} & "
                    f"{fmt_t(sb_g.get('wall_sec'), sb_g)} & {fmt_m(sb_g.get('rss_kb'), sb_g)} & "
                    f"{fmt_hms(bg.get('wall_sec'), bg)} & {fmt_mem(bg.get('rss_kb'), bg)} & "
                    f"{fmt_hms(bil.get('wall_sec'), bil)} & {fmt_mem(bil.get('rss_kb'), bil)} \\\\")
        write_grouped_rows(f, gfa_row)
        f.write("\\hline\n\\end{tabular}\n\\end{adjustbox}\n\\end{table*}\n")
    print(f"gfa_table.tex written to {gfa_path}")

    print("\nDone. 4 tables generated.")


if __name__ == "__main__":
    main()