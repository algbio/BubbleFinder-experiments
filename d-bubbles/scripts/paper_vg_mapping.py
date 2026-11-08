"""Validate vg's numeric node IDs before comparing named GFA boundaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def identity(path):
    s = Path(path).stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def records(path, numeric=False):
    nodes, edges = {}, set()
    with Path(path).open(encoding='ascii', newline='') as stream:
        for line in stream:
            if not line.endswith('\n') or line.endswith('\r\n'):
                raise ValueError('Truncated or CRLF GFA line')
            fields = line[:-1].split('\t')
            if fields[0] == 'S':
                if len(fields) < 3 or not fields[1] or fields[1] in nodes:
                    raise ValueError('Invalid or duplicate GFA segment')
                if numeric and (not fields[1].isdecimal() or str(int(fields[1])) != fields[1]
                                or int(fields[1]) <= 0):
                    raise ValueError('Invalid converted numeric segment ID')
                nodes[fields[1]] = fields[2]
            elif fields[0] == 'L':
                if len(fields) < 6 or fields[2] not in ('+', '-') or fields[4] not in ('+', '-') or fields[5] not in ('0M', '*'):
                    raise ValueError('Invalid or non-blunt GFA link')
                edges.add(tuple(sorted(((fields[1], fields[2]),
                                        (fields[3], '+' if fields[4] == '-' else '-')))))
            elif fields[0] not in ('H', 'P', 'W'):
                raise ValueError('Unsupported GFA record ' + fields[0])
    if not nodes or any(a not in nodes or b not in nodes for (a, _), (b, _) in edges):
        raise ValueError('Missing GFA segments or dangling link')
    return nodes, edges


def validate(source, translation, explicit, direct):
    nodes, edges = records(source)
    mapping = {}
    with Path(translation).open(encoding='ascii') as stream:
        for line in stream:
            fields = line.rstrip('\n').split('\t')
            if (len(fields) != 3 or fields[0] != 'T' or fields[1] not in nodes
                    or fields[1] in mapping or not fields[2].isdecimal()
                    or str(int(fields[2])) != fields[2] or int(fields[2]) <= 0):
                raise ValueError('Invalid vg translation')
            mapping[fields[1]] = fields[2]
    if set(mapping) != set(nodes) or len(set(mapping.values())) != len(nodes):
        raise ValueError('vg name map must match every node exactly once')
    exp_nodes, exp_edges = records(explicit, numeric=True)
    dir_nodes, dir_edges = records(direct, numeric=True)
    norm_nodes = {mapping[k]: ''.join(c if c in 'ACGTN' else 'N' for c in v.upper())
                  for k, v in nodes.items()}
    norm_edges = {tuple(sorted(((mapping[a], x), (mapping[b], y))))
                  for (a, x), (b, y) in edges}
    if (exp_nodes, exp_edges) != (dir_nodes, dir_edges) or (exp_nodes, exp_edges) != (norm_nodes, norm_edges):
        raise ValueError('Graph read by vg differs from the original graph')
    return {'nodes': len(nodes), 'unique_physical_links': len(edges)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--graph', required=True)
    p.add_argument('--stats', required=True)
    p.add_argument('--vg', required=True)
    p.add_argument('--translation', required=True)
    p.add_argument('--report', required=True)
    p.add_argument('--tmpdir', default='/dev/shm')
    a = p.parse_args()
    positive = 'Positive canonical numeric IDs: 1' in Path(a.stats).read_text()
    before = identity(a.graph)
    report = {'graph_sha256': sha(a.graph), 'vg_sha256': sha(a.vg),
              'canonical_numeric_ids': positive,
              'conversion_length_tags_compared': False,
              'bubble_length_source': 'original_gfa'}
    if positive:
        Path(a.translation).write_text('')
        report['method'] = 'identity_numeric_ids'
    else:
        with tempfile.TemporaryDirectory(prefix='vg-map-', dir=a.tmpdir) as tmp:
            tmp = Path(tmp)
            mapping, explicit, direct = tmp/'mapping.tsv', tmp/'explicit.gfa', tmp/'direct.gfa'
            with explicit.open('wb') as out:
                subprocess.run([a.vg, 'convert', '-g', '-r', '9223372036854775807',
                                '-T', str(mapping), '-f', '--vg-algorithm', '-t', '1', a.graph],
                               stdout=out, check=True)
            with direct.open('wb') as out:
                subprocess.run([a.vg, 'convert', '-f', '--vg-algorithm', '-t', '1', a.graph],
                               stdout=out, check=True)
            report.update(validate(a.graph, mapping, explicit, direct))
            report['method'] = 'validated_full_graph_translation'
            shutil.copyfile(mapping, a.translation)
    report['translation_sha256'] = sha(a.translation)
    if before != identity(a.graph):
        raise RuntimeError('Graph changed while checking the vg name map')
    report['graph_identity'] = before
    Path(a.report).write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
