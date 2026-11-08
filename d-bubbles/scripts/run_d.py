"""Run BubbleFinder and save the result."""

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path



def result_summary(output, log):
    with output.open() as stream:
        count = stream.readline().strip()

    if not count.isdigit():
        raise ValueError('Missing bubble count')

    times = re.findall(r'^\[timer\] Graph read : (\d+) ms$', log, re.MULTILINE)
    if len(times) != 1:
        raise ValueError('Missing graph reading time')

    partial = '[d-bubbles] warning: partial tip coverage' in log
    coverage = dict(status='partial' if partial else 'full',
                    full_graph_eligible=not partial,
                    root_policy='all-zero-indegree-state-exits')
    return dict(pairs=count, read_seconds=str(int(times[0]) / 1000)), coverage


def whole(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def identity(p):
    s = Path(p).stat()
    return [s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--binary', required=True)
    p.add_argument('--graph', required=True)
    p.add_argument('--prefix', required=True)
    p.add_argument('--expected-sha256', required=True)
    p.add_argument('--threads', type=int, default=1)
    p.add_argument('--nontrivial', action='store_true')
    p.add_argument('--ultrabubbles-only', action='store_true')
    p.add_argument('--tmpfs')
    p.add_argument('--admission', type=Path)
    a = p.parse_args()

    if a.threads < 1:
        raise ValueError('Thread count must be positive')

    prefix = Path(a.prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    receipt = Path(str(prefix) + '.receipt.json')
    if any(Path(str(prefix) + suffix).exists() for suffix in
           ('.receipt.json', '.tsv', '.stdout', '.stderr')):
        raise FileExistsError('Run already exists. Use a new result directory')

    sha = whole(a.binary)
    if len(a.expected_sha256) != 64 or sha != a.expected_sha256:
        raise RuntimeError('BubbleFinder checksum differs from the expected version')

    graph = Path(a.graph)
    before = identity(graph)
    graph_sha = whole(graph)
    if identity(graph) != before:
        raise RuntimeError('Input changed during hashing')

    admission_identity = admission_sha = None
    if a.admission:
        admission_identity = identity(a.admission)
        payload = a.admission.read_bytes()
        if identity(a.admission) != admission_identity:
            raise RuntimeError('Input check record changed while reading')
        admission = json.loads(payload)
        matches = [row['input'] for row in admission['inputs']
                   if Path(row['input']['path']).resolve() == graph.resolve()]
        if (admission.get('checks') != 'PASS' or len(matches) != 1 or
                matches[0]['identity'] != before or matches[0]['sha256'] != graph_sha):
            raise RuntimeError('Graph differs from the checked input')
        admission_sha = hashlib.sha256(payload).hexdigest()

    env = dict(os.environ, OMP_NUM_THREADS=str(a.threads), OPENBLAS_NUM_THREADS='1', LC_ALL='C')
    counts = {}
    coverage = dict(status='not_applicable', full_graph_eligible=False, root_policy='legacy_unknown')
    with tempfile.TemporaryDirectory(prefix='d-bubbles-', dir=a.tmpfs) as scratch:
        scratch = Path(scratch)
        if a.tmpfs:
            work_graph = scratch / ('graph' + ''.join(graph.suffixes))
            shutil.copyfile(graph, work_graph)
            if graph_sha != whole(work_graph) or identity(graph) != before:
                raise RuntimeError('Copied graph differs from the source')
            work_prefix = scratch / 'output'
        else:
            work_graph = graph
            work_prefix = prefix
        command = 'ultrabubbles' if a.ultrabubbles_only else 'd-bubbles'
        args = [a.binary, command, '-g', str(work_graph), '-o',
                str(work_prefix) + '.tsv', '-j', str(a.threads)]
        if not a.nontrivial:
            args.append('-T')
        if a.ultrabubbles_only:
            args.append('--d-bubbles')

        started = time.monotonic()
        with Path(str(work_prefix) + '.stdout').open('xb') as so, \
                Path(str(work_prefix) + '.stderr').open('xb') as se:
            child = subprocess.Popen(args, stdout=so, stderr=se, env=env)
            pid, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
        run = dict(argv=args, pid=child.pid, wait4_pid=pid, returncode=child.returncode,
                   raw_wait4=status, reaped=pid == child.pid,
                   absence=not (Path('/proc') / str(child.pid)).exists(),
                   wall_seconds=time.monotonic() - started, maxrss_kib=usage.ru_maxrss,
                   user_seconds=usage.ru_utime, system_seconds=usage.ru_stime)
        if child.returncode == 0:
            counts, coverage = result_summary(Path(str(work_prefix) + '.tsv'),
                                              Path(str(work_prefix) + '.stderr').read_text(errors='replace'))
        if a.tmpfs:
            for suffix in ('.tsv', '.stdout', '.stderr'):
                source = Path(str(work_prefix) + suffix)
                if source.exists():
                    shutil.copyfile(source, Path(str(prefix) + suffix))

    log = Path(str(prefix) + '.stderr').read_text(errors='replace')
    state = 'ok' if status == 0 else 'error'
    if child.returncode == 1 and ('tips; the paper' in log or
                                  'requires full selected S--T corridor coverage' in log or
                                  'some oriented states are unreachable from the two tip exits' in log or
                                  'ultrabubble filtering requires full tip coverage' in log):
        state = 'unsupported'

    execution_status = state
    if state == 'ok' and not coverage['full_graph_eligible']:
        state = {'partial': 'partial_coverage', 'legacy_unknown': 'coverage_unknown',
                 'invalid': 'invalid_coverage'}[coverage['status']]

    result = dict(
        schema=5 if a.ultrabubbles_only else 4, execution_status=execution_status, coverage=coverage,
        root_policy=coverage['root_policy'], status=state, host=socket.gethostname(),
        slurm_job=os.environ.get('SLURM_JOB_ID'), binary_sha256=sha,
        graph=str(graph.resolve()), graph_sha256=graph_sha, graph_identity_before=before,
        graph_identity_after=identity(graph), admission_sha256=admission_sha,
        definition='idom_S(y)=x AND idom_T(x)=y', includes_trivial=not a.nontrivial,
        ultrabubbles_only=a.ultrabubbles_only, allow_partial_corridor=a.ultrabubbles_only,
        tmpfs=bool(a.tmpfs), threads=a.threads, backend='bc', run=run, metrics=counts,
        engine='bubblefinder', engine_sha256=sha,
        output_format='standard')
    if before != result['graph_identity_after']:
        raise RuntimeError('Graph changed during the run')
    if whole(a.binary) != sha:
        raise RuntimeError('BubbleFinder changed during the run')
    if not run['reaped'] or not run['absence']:
        raise RuntimeError('Could not confirm that the process ended')
    if a.admission and identity(a.admission) != admission_identity:
        raise RuntimeError('Input check record changed during the run')
    receipt.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    # Record a failed run without reporting zero bubbles.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
