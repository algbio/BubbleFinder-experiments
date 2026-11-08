"""Normalize vg and Billi boundaries for the paper's set comparisons."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from toolchain_provenance import check_measurement, load_lock
from check_admitted_input import admitted_input


def canonical(a, b):
    if not a or not b or a[-1] not in '+-' or b[-1] not in '+-':
        raise ValueError('Bubble end needs a node name and sign')
    if any(c.isspace() for c in a + b):
        raise ValueError('Bubble end name contains whitespace')
    return tuple(sorted((a, b)))


def reverse_mapping(path):
    mapping = {}
    with Path(path).open() as stream:
        for line in stream:
            fields = line.rstrip('\n').split('\t')
            if len(fields) != 3 or fields[0] != 'T' or fields[2] in mapping:
                raise ValueError('Invalid row or repeated ID in the vg name map')
            mapping[fields[2]] = fields[1]
    if not mapping or len(set(mapping.values())) != len(mapping):
        raise ValueError('Empty vg name map or repeated node name')
    return mapping


def vg_bubbles(stream, mapping):
    for line in stream:
        fields = line.rstrip('\n').split('\t')
        if len(fields) != 2:
            raise ValueError('vg bubble row needs two signed node names')
        if mapping is not None:
            fields = [mapping[value[:-1]] + value[-1] for value in fields]
        a, b = canonical(*fields)
        if a[:-1] != b[:-1]:
            yield a, b


def billi_bubbles(stream):
    for line in stream:
        fields = line.rstrip('\n').split('\t')
        if fields[0] != 'BB':
            continue
        if len(fields) < 7 or any(not x or x[0] not in '<>' for x in fields[4:6]):
            raise ValueError('Invalid Billi bubble ends')
        a = fields[4][1:] + ('-' if fields[4][0] == '<' else '+')
        b = fields[5][1:] + ('-' if fields[5][0] == '>' else '+')
        a, b = canonical(a, b)
        if a[:-1] != b[:-1]:
            yield a, b


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('vg', 'billi'))
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--time', required=True, type=Path)
    parser.add_argument('--toolchain-lock', type=Path)
    parser.add_argument('--admission', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--status', required=True, type=Path)
    parser.add_argument('--stats', type=Path)
    parser.add_argument('--translation', type=Path)
    parser.add_argument('--mapping-report', type=Path)
    parser.add_argument('--graph', type=Path)
    parser.add_argument('--measurement-graph', type=Path)
    parser.add_argument('--version', default='1.78.0')
    parser.add_argument('--algorithm', choices=('integrated', 'cactus', 'default'), default='integrated')
    parser.add_argument('--record-filter', choices=('include_trivial', 'exclude_trivial'), default='include_trivial')
    parser.add_argument('--vg-argv', default='vg snarls -T -A integrated -t 1')
    parser.add_argument('--tmpdir', default='/dev/shm')
    args = parser.parse_args()
    if args.toolchain_lock:
        measurement_graph = args.measurement_graph or args.graph
        if not args.admission or not measurement_graph:
            raise RuntimeError('Tool checks need the checked graph')
        lock, lock_sha = load_lock(args.toolchain_lock)
        admitted = admitted_input(json.loads(args.admission.read_text()), measurement_graph)
        check_measurement(args.time, args.mode, lock, lock_sha,
                          expected_graph_sha256=admitted['sha256'],
                          expected_operation='snarls' if args.mode == 'vg' else 'decompose',
                          expected_threads=1 if args.mode == 'vg' else None,
                          expected_include_trivial=True if args.mode == 'vg' else None)
    failed = args.time.read_text().startswith('EXIT_CODE=')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if failed:
        if args.mode != 'billi':
            raise RuntimeError('vg run failed. No bubble file is available')
        args.output.write_text('')
        args.status.write_text(json.dumps({'status': 'failed', 'method': args.mode}) + '\n')
        return
    if not args.input.is_file():
        raise FileNotFoundError('Run succeeded but its bubble file is missing: ' + str(args.input))
    if args.mapping_report:
        if not args.translation or not args.graph:
            raise ValueError('Name map checks need the graph and mapping file')
        report = json.loads(args.mapping_report.read_text())
        st = args.graph.stat()
        current = [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]
        digest = hashlib.sha256(args.translation.read_bytes()).hexdigest()
        if current != report['graph_identity'] or digest != report['translation_sha256']:
            raise RuntimeError('Graph or vg name map changed after the check')
    mapping = (reverse_mapping(args.translation)
               if args.translation and args.translation.stat().st_size else None)
    if args.mode == 'vg' and mapping is None:
        if args.stats is None or 'Positive canonical numeric IDs: 1' not in args.stats.read_text():
            raise RuntimeError('GFA names need a checked vg name map')
    with tempfile.TemporaryDirectory(prefix='paper-catalogue-', dir=args.tmpdir) as folder:
        raw = Path(folder) / 'bubbles'
        ordered = Path(folder) / 'sorted'
        count = 0
        with args.input.open() as source, raw.open('w') as output:
            bubbles = vg_bubbles(source, mapping) if args.mode == 'vg' else billi_bubbles(source)
            for a, b in bubbles:
                output.write(a + '\t' + b + '\n')
                count += 1
        env = dict(os.environ, LC_ALL='C')
        subprocess.run(['/usr/bin/sort', '-u', '-S', '64M', '-T', folder,
                        '-o', str(ordered), str(raw)], check=True, env=env)
        unique = 0
        with args.output.open('w') as out, ordered.open() as source:
            if args.mode == 'vg':
                out.write('# BubbleFinder vg-snarls catalogue 1\n')
                for key, value in [('vg_version', args.version), ('vg_algorithm', args.algorithm),
                        ('vg_argv', args.vg_argv),
                        ('coordinate_space', 'original_GFA_inward_poles'),
                        ('record_filter', args.record_filter),
                        ('catalogue_scope', 'complete_selected_vg_output')]:
                    out.write('# ' + key + '\t' + value + '\n')
                out.write('x\ty\n')
            for line in source:
                out.write(line)
                unique += 1
    args.status.write_text(json.dumps({'status': 'ok', 'method': args.mode,
                                      'rows': count, 'unique_nonunary_pairs': unique,
                                      'translation': str(args.translation) if args.translation else None}) + '\n')


if __name__ == '__main__':
    main()
