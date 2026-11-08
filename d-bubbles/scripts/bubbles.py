"""Strict streaming signed-pole adapters, outside measured tool time."""
import argparse
import json
import os
import subprocess
from pathlib import Path


def canonical(x, y):
    for v in (x, y):
        if len(v) < 2 or v[-1] not in '+-' or any(c.isspace() for c in v):
            raise ValueError('Bubble end needs a node name and + or -')
    return tuple(sorted((x, y)))


def vg(stream, out, ub_out=None):
    n = u = unary = 0
    for line in stream:
        d = json.loads(line)
        a = d['start']
        b = d['end']
        x = str(a['node_id'])
        y = str(b['node_id'])
        if not x.isdigit() or not y.isdigit() or str(int(x)) != x or str(int(y)) != y or min(int(x), int(y)) <= 0:
            raise ValueError('vg output must use positive numeric node IDs')
        x += '-' if a.get('backward', False) else '+'
        y += '+' if b.get('backward', False) else '-'
        x, y = canonical(x, y)
        out.write(x+'\t'+y+'\n')
        n += 1
        is_ub = d.get('type') in (1, '1', 'ULTRABUBBLE')
        u += is_ub
        unary += a['node_id'] == b['node_id']
        if is_ub and ub_out is not None:
            ub_out.write(x+'\t'+y+'\n')
    return dict(n_snarls=n, n_ub=u, n_diff=n-u, n_unary=unary)


def d_bubbles(source, out):
    n = 0
    schema = None
    expected = None
    for line in source:
        if line.startswith('#'):
            continue
        if schema is None:
            header = line.rstrip('\n')
            if header.isdigit():
                schema = 'standard'
                expected = int(header)
            elif header == 'component\tx\ty':
                schema = 'component-tsv'
            else:
                raise ValueError('Unexpected d-bubble columns')
            continue
        if schema == 'standard':
            f = line.rstrip('\n').split(' ')
            if len(f) != 2:
                raise ValueError('Malformed d-bubbles row')
            x, y = canonical(*f)
        else:
            f = line.rstrip('\n').split('\t')
            if len(f) != 3 or not f[0].isdigit():
                raise ValueError('Malformed d-bubbles row')
            x, y = canonical(f[1], f[2])
        out.write(x+'\t'+y+'\n')
        n += 1
    if schema is None:
        raise ValueError('Missing d-bubbles TSV header')
    if expected is not None and n != expected:
        raise ValueError('D-bubble output count differs from its header')
    return n


def sorted_bubbles(source, dest, tmp):
    partial = Path(str(dest)+'.partial-sort')
    if partial.exists():
        raise FileExistsError('Incomplete sort exists. Use a new result directory')
    env = dict(os.environ, LC_ALL='C')
    args = ['/usr/bin/sort', '-u', '--parallel=1', '-S', '64M', '-T', str(tmp), str(source), '-o', str(partial)]
    p = subprocess.Popen(args, env=env)
    pid, status, usage = os.wait4(p.pid, 0)
    p.returncode = os.waitstatus_to_exitcode(status)
    if status != 0 or pid != p.pid or (Path('/proc')/str(p.pid)).exists():
        raise RuntimeError('Bubble sort failed')
    partial.rename(dest)


def main():
    import sys
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['vg'])
    p.add_argument('--bubbles', required=True)
    p.add_argument('--counts', required=True)
    p.add_argument('--ub-bubbles')
    a = p.parse_args()
    with Path(a.bubbles).open('x') as out:
        if a.ub_bubbles:
            with Path(a.ub_bubbles).open('x') as ub_out:
                counts = vg(sys.stdin, out, ub_out)
        else:
            counts = vg(sys.stdin, out)
    with Path(a.counts).open('x') as out:
        for k, v in counts.items():
            out.write(k+'\t'+str(v)+'\n')


if __name__ == '__main__':
    main()
