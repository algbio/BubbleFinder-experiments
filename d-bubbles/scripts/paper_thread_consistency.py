"""Check that thread counts produce the same d-bubble catalogue."""
import argparse
import hashlib
import json
from pathlib import Path


def keyed(values):
    result = {}
    for value in values:
        key, separator, path = value.partition('=')
        if not separator or not key.isdecimal() or int(key) < 1 or not path:
            raise ValueError('Expected a positive thread count and a path')
        count = int(key)
        if count in result:
            raise ValueError('Duplicate thread count')
        result[count] = Path(path)
    return result


def digest(path):
    before = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            h.update(block)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise RuntimeError('D-bubble output changed during comparison: ' + str(path))
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', required=True)
    p.add_argument('--sample', action='append', required=True)
    p.add_argument('--receipt', action='append', required=True)
    p.add_argument('--reference', required=True, type=Path)
    p.add_argument('--reference-receipt', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    samples, receipts = keyed(a.sample), keyed(a.receipt)
    if 1 not in samples or set(samples) != set(receipts):
        raise ValueError('Need a one thread result and matching run records')
    baseline = None
    for threads in sorted(samples):
        r = json.loads(receipts[threads].read_text())
        if (r.get('execution_status') != 'ok' or r.get('threads') != threads or
                r.get('coverage', {}).get('status') not in ('full', 'partial') or
                r.get('includes_trivial') is not True or r.get('ultrabubbles_only') is not False):
            raise ValueError('Invalid d-bubble run record for %d threads' % threads)
        signature = {'graph_sha256': r['graph_sha256'], 'binary_sha256': r['binary_sha256'],
                     'root_policy': r['root_policy'], 'coverage': r['coverage']['status'],
                     'pairs': int(r['metrics']['pairs']), 'output_sha256': digest(samples[threads])}
        if baseline is None:
            baseline = signature
        elif signature != baseline:
            raise RuntimeError('D-bubble results or run settings differ between thread counts')
    reference = json.loads(a.reference_receipt.read_text())
    if (reference.get('execution_status') != 'ok' or
            reference.get('coverage', {}).get('status') not in ('full', 'partial') or
            reference.get('includes_trivial') is not True or
            reference.get('ultrabubbles_only') is not False):
        raise ValueError('Invalid d-bubble analysis run record')
    reference_hash = (baseline['output_sha256'] if a.reference.resolve() == samples[1].resolve()
                      else digest(a.reference))
    if (reference_hash != baseline['output_sha256'] or
            reference['binary_sha256'] != baseline['binary_sha256'] or
            reference['root_policy'] != baseline['root_policy'] or
            reference['coverage']['status'] != baseline['coverage'] or
            int(reference['metrics']['pairs']) != baseline['pairs']):
        raise RuntimeError('Thread benchmark and analysis bubble files differ')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps({'status': 'PASS', 'dataset': a.dataset,
        'threads': sorted(samples), 'analysis_graph_sha256': reference['graph_sha256'],
        **baseline}, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
