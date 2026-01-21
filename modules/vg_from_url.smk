import os
import shutil
import subprocess
import gzip
from urllib.request import urlopen, Request
from snakemake.exceptions import WorkflowError
from snakemake.shell import shell
from pathlib import Path

shell.executable("/bin/bash")

_VGURL_BASEDIR = Path(workflow.basedir) if "workflow" in globals() else Path(os.getcwd())
def _vgurl_resolve_env(p):
    p = str(p)
    return p if os.path.isabs(p) else str(_VGURL_BASEDIR / p)

_VGURL_DEFAULTS = config.get("defaults", {}) or {}
_VGURL_DATA_DIR = _VGURL_DEFAULTS.get("data_dir", "data")
_VGURL_OUT_DIR = _VGURL_DEFAULTS.get("out_dir", "results")
_VGURL_VG_ENV = _vgurl_resolve_env((_VGURL_DEFAULTS.get("envs", {}) or {}).get("vg", "config/vg.yml"))

def _vgurl_ds(name):
    for d in config.get("datasets", []):
        if d.get("name") == name:
            return d
    raise WorkflowError(f"Dataset not found in config: {name}")

def _vgurl_primary_url(name):
    ucfg = _vgurl_ds(name).get("urls", {}) or {}
    if ucfg.get("url"):
        return ucfg.get("url")
    files = ucfg.get("files") or []
    for f in files:
        if f:
            return f
    raise WorkflowError(f"{name}: urls.url or urls.files must be set for vg_from_url builder")

def _vgurl_path_of(obj):
    if isinstance(obj, (list, tuple)):
        obj = obj[0] if len(obj) > 0 else obj
    try:
        return os.fspath(obj)
    except Exception:
        if hasattr(obj, "path"):
            return str(obj.path)
        return str(obj)

def _vgurl_download(url, part, logp):
    def log_text(msg):
        with open(logp, "a", encoding="utf-8") as lf:
            lf.write(msg + "\n")

    os.makedirs(os.path.dirname(part), exist_ok=True)
    os.makedirs(os.path.dirname(logp), exist_ok=True)

    log_text(f"[INFO] Starting download: {url} -> {part}")
    downloaded = False
    try:
        req = Request(url, headers={"User-Agent": "snakemake/1.0"})
        with urlopen(req, timeout=120) as r, open(part, "wb") as fh:
            shutil.copyfileobj(r, fh)
        if os.path.exists(part) and os.path.getsize(part) > 0:
            downloaded = True
            log_text(f"[INFO] Python download succeeded, size={os.path.getsize(part)}")
        else:
            log_text("[WARN] Python download produced empty or missing file")
    except Exception as e:
        log_text(f"[WARN] Python download failed: {e}")

    if not downloaded:
        wget = shutil.which("wget")
        curl = shutil.which("curl")
        if wget:
            log_text("[INFO] Trying wget fallback")
            with open(logp, "ab") as logb:
                rc = subprocess.run([wget, "-q", "-O", part, url], stdout=logb, stderr=logb)
            if rc.returncode == 0 and os.path.exists(part) and os.path.getsize(part) > 0:
                downloaded = True
                log_text(f"[INFO] wget succeeded, size={os.path.getsize(part)}")
            else:
                log_text(f"[WARN] wget failed (rc={rc.returncode})")
        if not downloaded and curl:
            log_text("[INFO] Trying curl fallback")
            with open(logp, "ab") as logb:
                rc = subprocess.run([curl, "-fL", "-o", part, url], stdout=logb, stderr=logb)
            if rc.returncode == 0 and os.path.exists(part) and os.path.getsize(part) > 0:
                downloaded = True
                log_text(f"[INFO] curl succeeded, size={os.path.getsize(part)}")
            else:
                log_text(f"[WARN] curl failed (rc={rc.returncode})")

    if not downloaded:
        raise WorkflowError(f"Failed to download {url} (tried urllib, wget, curl). See {logp}")

def _vgurl_decompress_or_move(url, src, dst, logp):
    def log_text(msg):
        with open(logp, "a", encoding="utf-8") as lf:
            lf.write(msg + "\n")

    ubase = url.split("?", 1)[0].lower()
    if ubase.endswith(".zst"):
        zstd_bin = shutil.which("zstd") or shutil.which("zstdcat")
        if not zstd_bin:
            raise WorkflowError("zstd not found on PATH; please install zstd or pre-decompress the file.")
        log_text(f"[INFO] Decompressing .zst with {zstd_bin}")
        with open(logp, "ab") as logb:
            if os.path.basename(zstd_bin).endswith("zstdcat"):
                with open(dst, "wb") as out:
                    rc = subprocess.run([zstd_bin, src], stdout=out, stderr=logb)
                    if rc.returncode != 0:
                        raise WorkflowError(f"zstdcat failed (rc={rc.returncode}); see {logp}")
            else:
                with open(dst, "wb") as out:
                    rc = subprocess.run([zstd_bin, "-d", "-c", src], stdout=out, stderr=logb)
                    if rc.returncode != 0:
                        raise WorkflowError(f"zstd -d failed (rc={rc.returncode}); see {logp}")
    elif ubase.endswith(".gz") or ubase.endswith(".tgz"):
        log_text("[INFO] Decompressing .gz with gzip module")
        with gzip.open(src, "rb") as fin, open(dst, "wb") as fout:
            shutil.copyfileobj(fin, fout)
    else:
        log_text("[INFO] Moving downloaded file to final destination")
        shutil.move(src, dst)

rule vg_from_url_download:
    message: "Download + convert .vg to raw GFA for {wildcards.dataset}"
    output:
        raw=os.path.join(_VGURL_DATA_DIR, "{dataset}", "{dataset}.vg.url.gfa")
    log:
        os.path.join(_VGURL_OUT_DIR, "logs", "vg_from_url", "{dataset}.download.log")
    conda:
        _VGURL_VG_ENV
    run:
        dataset = wildcards.dataset
        url = _vgurl_primary_url(dataset)

        dest = _vgurl_path_of(output.raw)
        logp = _vgurl_path_of(log)

        os.makedirs(os.path.dirname(dest), exist_ok=True)
        os.makedirs(os.path.dirname(logp), exist_ok=True)

        part = os.path.join(_VGURL_DATA_DIR, dataset, f"{dataset}.vg.part")
        tmp_in = os.path.join(_VGURL_DATA_DIR, dataset, f"{dataset}.raw.vg")
        tmp_out = dest + ".part"

        def log_text(msg):
            with open(logp, "a", encoding="utf-8") as lf:
                lf.write(msg + "\n")

        try:
            _vgurl_download(url, part, logp)

            if os.path.exists(tmp_in):
                os.remove(tmp_in)
            _vgurl_decompress_or_move(url, part, tmp_in, logp)

            if not os.path.exists(tmp_in) or os.path.getsize(tmp_in) == 0:
                raise WorkflowError(f"Downloaded/decoded input {tmp_in} missing or empty; check {logp}")

            if os.path.exists(tmp_out):
                os.remove(tmp_out)

            log_text("[INFO] Converting VG -> GFA via vg convert -g")
            shell(f"vg convert -g {tmp_in} > {tmp_out} 2>> {logp}")

            if not os.path.exists(tmp_out) or os.path.getsize(tmp_out) == 0:
                raise WorkflowError(f"Produced file {tmp_out} missing or empty; check {logp}")

            os.replace(tmp_out, dest)
            log_text(f"[INFO] Produced {dest} (size={os.path.getsize(dest)})")
        finally:
            for p in [part, tmp_in, tmp_out]:
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass