"""Reuse already computed Billi overlaps only after checking their inputs."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from check_admitted_input import admitted_inputs_by_name, identity
from toolchain_provenance import check_measurement, load_lock


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def bubbles(path):
    previous = None
    with path.open('rb') as stream:
        for line in stream:
            if line.startswith(b'#') or line == b'x\ty\n':
                continue
            fields = line.rstrip(b'\n').split(b'\t')
            require(line.endswith(b'\n') and len(fields) == 2 and
                    all(len(field) > 1 and field[-1:] in (b'+', b'-') for field in fields) and
                    fields[0] < fields[1] and (previous is None or previous < line),
                    'Malformed or unordered bubble catalogue')
            previous = line
            yield line


def subset_count(subset, full):
    source = iter(bubbles(full))
    current = next(source, None)
    count = 0
    for wanted in bubbles(subset):
        while current is not None and current < wanted:
            current = next(source, None)
        require(current == wanted, 'Filtered Billi bubble is absent from its catalogue')
        count += 1
    return count


def prior_overlap(dataset, source, graph_sha, lock, lock_sha, physical, tmpdir):
    """Return verified atoms, or None if a prior overlap cannot be established."""
    try:
        results = Path(source['results'])
        admission_path = Path(source['admission'])
        old_lock = Path(source['toolchain_lock'])
        old_inputs = admitted_inputs_by_name(json.loads(admission_path.read_text()))
        graph = old_inputs[dataset + '.gfa']
        require(graph['sha256'] == graph_sha and load_lock(old_lock)[1] == lock_sha,
                'Prior graph or toolchain differs')
        graph_path = Path(graph['path'])
        timing = results / (dataset + '.billi.time')
        require(check_measurement(timing, 'billi', lock, lock_sha,
                                  expected_graph_sha256=graph_sha,
                                  expected_operation='decompose'),
                'Prior Billi measurement is unavailable')
        paper = results / 'paper'
        raw = results / (dataset + '.billi.txt')
        raw_counts = results / (dataset + '.billi.counts')
        normalized = paper / (dataset + '.billi.pairs.tsv')
        status_path = paper / (dataset + '.billi.pairs.json')
        billi = paper / (dataset + '.billi.nontrivial.tsv')
        billi_summary = paper / (dataset + '.billi.physical.tsv')
        d = paper / (dataset + '.d.nontrivial.tsv')
        vg = paper / (dataset + '.vg.nontrivial.tsv')
        ub = paper / (dataset + '.vg-ub.pairs.tsv')
        prior_physical = paper / (dataset + '.physical.tsv')
        old_overlap = paper / (dataset + '.overlaps.tsv')
        files = (raw, raw_counts, timing, Path(str(timing) + '.toolchain.json'), admission_path, old_lock,
                 normalized, status_path, billi, billi_summary, d, vg, ub, prior_physical, old_overlap)
        before = {path: identity(path) for path in files}
        require(identity(graph_path) == graph['identity'], 'Prior graph changed')
        status = json.loads(status_path.read_text())
        require(status.get('status') == 'ok' and status.get('method') == 'billi',
                'Prior Billi catalogue is unavailable')
        newest_input = max(normalized.stat().st_mtime_ns, vg.stat().st_mtime_ns)
        require(billi.stat().st_mtime_ns >= newest_input and
                billi_summary.stat().st_mtime_ns >= newest_input, 'Prior Billi filtering is stale')
        scripts = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(prefix='paper-prior-overlaps-', dir=tmpdir) as folder:
            scratch = Path(folder)
            normalized_check, normalized_status = scratch / 'billi.tsv', scratch / 'billi.json'
            subprocess.run([sys.executable, str(scripts / 'paper_catalogues.py'), 'billi',
                            '--input', str(raw), '--time', str(timing), '--toolchain-lock', str(old_lock),
                            '--admission', str(admission_path), '--graph', str(graph_path),
                            '--output', str(normalized_check), '--status', str(normalized_status),
                            '--tmpdir', str(scratch)], check=True, capture_output=True)
            require(file_sha256(normalized_check) == file_sha256(normalized) and
                    json.loads(normalized_status.read_text()) == status,
                    'Prior normalized Billi catalogue differs')
            raw_total = {'BB': 0, 'HP': 0}
            with raw.open(encoding='utf-8') as stream:
                for line in stream:
                    fields = line.rstrip('\n').split('\t')
                    require(fields[0] in raw_total and
                            len(fields) >= (7 if fields[0] == 'BB' else 5),
                            'Malformed Billi row')
                    raw_total[fields[0]] += 1
            recorded = dict(line.rstrip('\n').split('\t') for line in raw_counts.read_text().splitlines())
            require(recorded.get('n_panbubbles') == str(raw_total['BB']) and
                    recorded.get('n_hairpins') == str(raw_total['HP']) and
                    int(status['rows']) <= raw_total['BB'], 'Prior Billi raw count differs')
            with billi_summary.open() as stream:
                next(stream)
                summary = dict(line.rstrip('\n').split('\t') for line in stream)
            count = subset_count(billi, normalized_check)
            require(count == int(summary['nontrivial_pairs']), 'Prior Billi physical count differs')
            overlap_check = scratch / 'overlaps.tsv'
            subprocess.run([sys.executable, str(scripts / 'paper_venn.py'),
                            '--d', str(d), '--vg', str(vg), '--vg-ultrabubbles', str(ub),
                            '--billi', str(billi), '--billi-status', str(status_path),
                            '--physical-summary', str(prior_physical), '--output', str(overlap_check)],
                           check=True, capture_output=True)
            require(file_sha256(overlap_check) == file_sha256(old_overlap), 'Prior overlap differs')
            atoms = {str(i): 0 for i in range(1, 8)}
            with overlap_check.open() as stream:
                for row in csv.DictReader(stream, delimiter='\t'):
                    bits = int(row['d']) + 2 * int(row['vg']) + 4 * int(row['billi'])
                    if bits:
                        atoms[str(bits)] += int(row['pairs'])
            require(sum(atoms[str(i)] for i in (1, 3, 5, 7)) == int(physical['nontrivial_d']) and
                    sum(atoms[str(i)] for i in (2, 3, 6, 7)) == int(physical['nontrivial_vg']) and
                    sum(atoms[str(i)] for i in (3, 7)) == int(physical['nontrivial_common']) and
                    sum(atoms[str(i)] for i in (4, 5, 6, 7)) == count,
                    'Prior overlap marginals differ')
        require(all(identity(path) == before[path] for path in files) and
                identity(graph_path) == graph['identity'], 'Prior files changed during checking')
        return {'status': 'reused_verified', 'atoms': atoms, 'billi_records': raw_total['BB']}
    except (OSError, KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError,
            subprocess.CalledProcessError):
        return None
