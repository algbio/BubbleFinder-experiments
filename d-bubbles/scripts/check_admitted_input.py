"""Check that a graph is the original file admitted before the benchmark."""
import argparse
import hashlib
import json
from pathlib import Path


def identity(path):
    s = path.stat()
    return [s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def admitted_input(admission, graph):
    graph = Path(graph).resolve(strict=True)
    if admission.get('checks') != 'PASS':
        raise RuntimeError('Input checks failed')
    matches = [row['input'] for row in admission['inputs']
               if Path(row['input']['path']).resolve() == graph]
    if len(matches) != 1 or identity(graph) != matches[0]['identity']:
        raise RuntimeError('Graph differs from the checked input')
    return matches[0]


def admitted_inputs_by_name(admission):
    """Find checked inputs by file name."""
    result = {}
    for row in admission['inputs']:
        name = row.get('source', {}).get('name')
        if (not isinstance(name, str) or not name or Path(name).name != name or
                '\\' in name):
            raise RuntimeError('Invalid input file name')
        name = name.removesuffix('.gz')
        if not name.endswith(('.gfa', '.gbz')) or name in result:
            raise RuntimeError('Invalid or repeated input name: ' + name)
        result[name] = admitted_input(admission, row['input']['path'])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--admission', required=True, type=Path)
    parser.add_argument('--graph', required=True, type=Path)
    parser.add_argument('--d-receipt', type=Path)
    parser.add_argument('--d-graph', type=Path)
    parser.add_argument('--verify-sha256', action='store_true')
    parser.add_argument('--print-sha256', action='store_true')
    args = parser.parse_args()
    graph = args.graph.resolve(strict=True)
    admission_bytes = args.admission.read_bytes()
    admission = json.loads(admission_bytes)
    admitted = admitted_input(admission, graph)
    if args.verify_sha256:
        h = hashlib.sha256()
        with graph.open('rb') as stream:
            for chunk in iter(lambda: stream.read(8 << 20), b''):
                h.update(chunk)
        if identity(graph) != admitted['identity'] or h.hexdigest() != admitted['sha256']:
            raise RuntimeError('Graph contents changed since the input check')
    if args.d_graph and not args.d_receipt:
        parser.error('--d-graph requires --d-receipt')
    if args.d_receipt:
        receipt = json.loads(args.d_receipt.read_text())
        d_graph = args.d_graph.resolve(strict=True) if args.d_graph else graph
        d_admitted = admitted_input(admission, d_graph)
        if (receipt.get('execution_status') != 'ok' or
                Path(receipt.get('graph', '')).resolve() != d_graph or
                receipt.get('graph_sha256') != d_admitted['sha256'] or
                receipt.get('graph_identity_before') != d_admitted['identity'] or
                receipt.get('graph_identity_after') != d_admitted['identity'] or
                receipt.get('admission_sha256') != hashlib.sha256(admission_bytes).hexdigest()):
            raise RuntimeError('D-bubble run used a different graph')
    if args.print_sha256:
        print(admitted['sha256'])


if __name__ == '__main__':
    main()
