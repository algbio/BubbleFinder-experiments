"""Validate paper tables without starting vg or Billi."""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

from check_admitted_input import admitted_inputs_by_name, identity
from bubbles import d_bubbles
from paper_summary import check_d_receipt, gbz_speedups, metrics, ratio, receipt, timing, topology
from paper_prior_overlaps import prior_overlap
from paper_tables import ALL, render
from datasets import length_unit
from toolchain_provenance import check_measurement, load_lock

FIELDS = (
    'dataset', 'length_unit', 'format', 'nodes', 'links', 'components', 'tips', 'cut_vertices',
    'components_without_tips', 'components_without_cut_vertices', 'orientation_conflict_vertices',
    'd_nontrivial', 'd_all_1', 'd_all_8', 'd_main_scope', 'd_scope_1', 'd_scope_8',
    'd_main_seconds', 'd_main_gib', 'd_seconds_1', 'd_seconds_8', 'd_gib_1', 'd_gib_8',
    'd_read_seconds_1', 'd_thread_speedup', 'u_via_d_seconds', 'u_via_d_gib', 'u_via_d_scope',
    'bf_ultrabubbles_seconds', 'bf_ultrabubbles_gib', 'bf_ultrabubbles_all',
    'bf_ultrabubbles_nontrivial', 'nonsnarl_d_nontrivial', 'q1', 'median', 'q3', 'maximum',
    'vg_seconds_1', 'vg_seconds_8', 'vg_gib_1', 'vg_gib_8', 'vg_gfa_seconds', 'vg_gfa_gib',
    'vg_over_d_total_1', 'vg_over_d_subtract_d_read_1', 'vg_thread_speedup', 'vg_over_d_at_8',
    'vg_records_all', 'vg_records_nontrivial_native', 'vg_ultrabubble_records_all',
    'vg_ultrabubble_records_nontrivial_native', 'vg_non_ultrabubble_records',
    'vg_nontrivial', 'common', 'd_only', 'vg_only', 'billi_seconds', 'billi_gib', 'billi_records',
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_nontrivial(path, graph, admission_sha, binary_sha):
    result = json.loads(path.read_text())
    run = result.get('run', {})
    args = run.get('argv')
    if result.get('schema') == 2:
        tail = ['-j', '1', '--output-format', 'tsv']
        valid_command = (isinstance(args, list) and len(args) == 8 + len(tail) and
                         args[1:3] == ['d-bubbles', '-g'] and args[4] == '-o' and
                         args[6] == '--metrics' and args[8:] == tail)
    else:
        valid_command = (result.get('schema') in (3, 4) and isinstance(args, list) and len(args) == 8 and
                         args[1:3] == ['d-bubbles', '-g'] and args[4] == '-o' and
                         args[6:] == ['-j', '1'] and result.get('engine') == 'bubblefinder' and
                         result.get('engine_sha256') == binary_sha and
                         result.get('output_format') == 'standard')
    require(result.get('schema') in (2, 3, 4) and result.get('execution_status') == 'ok' and
            Path(result.get('graph', '')).resolve() == Path(graph['path']).resolve() and
            result.get('graph_sha256') == graph['sha256'] and
            result.get('graph_identity_before') == graph['identity'] and
            result.get('graph_identity_after') == graph['identity'] and
            result.get('admission_sha256') == admission_sha and result.get('binary_sha256') == binary_sha and
            result.get('threads') == 1 and result.get('root_policy') == 'all-zero-indegree-state-exits' and
            result.get('includes_trivial') is False and result.get('ultrabubbles_only') is False and
            result.get('allow_partial_corridor') is False and
            result.get('coverage', {}).get('status') in ('full', 'partial') and
            run.get('returncode') == 0 and run.get('reaped') is True and run.get('absence') is True and
            valid_command,
            'Invalid nontrivial d-bubble receipt: ' + str(path))
    return result


def existing_measurement(path, tool, lock, lock_sha, graph_sha, operation, threads=None, trivial=None):
    if not path.is_file() or not Path(str(path) + '.toolchain.json').is_file():
        return None
    try:
        ok = check_measurement(path, tool, lock, lock_sha, expected_graph_sha256=graph_sha,
                               expected_operation=operation, expected_threads=threads,
                               expected_include_trivial=trivial)
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError):
        return None
    return timing(path) if ok else ('failed', 'failed')


def existing_counts(path):
    if not path.is_file():
        return None
    try:
        values = dict(line.rstrip('\n').split('\t') for line in path.read_text().splitlines())
        require(all(re.fullmatch(r'\d+', values[key]) for key in ('n_snarls', 'n_ub')),
                'Invalid vg counts')
        require(int(values['n_snarls']) >= int(values['n_ub']), 'Invalid vg count partition')
        return values
    except (OSError, KeyError, ValueError):
        return None


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def d_catalogue_digest(path):
    """Compare bubbles from the current and previous output formats."""
    digest = hashlib.sha256()

    class Sink:
        def write(self, value):
            digest.update(value.encode())

    with path.open() as stream:
        count = d_bubbles(stream, Sink())
    return count, digest.hexdigest()


def sorted_bubble_counts(left, right):
    def advance(stream, previous):
        line = stream.readline()
        if not line:
            return None
        fields = line.rstrip(b'\n').split(b'\t')
        require(line.endswith(b'\n') and len(fields) == 2 and
                all(len(field) > 1 and field[-1:] in (b'+', b'-') for field in fields) and
                fields[0] <= fields[1] and (previous is None or previous < line),
                'Invalid or unsorted physical bubble catalogue')
        return line

    a_count = b_count = common = 0
    with left.open('rb') as a, right.open('rb') as b:
        x, y = advance(a, None), advance(b, None)
        while x is not None or y is not None:
            if y is None or (x is not None and x < y):
                a_count += 1
                x = advance(a, x)
            elif x is None or y < x:
                b_count += 1
                y = advance(b, y)
            else:
                a_count += 1
                b_count += 1
                common += 1
                x, y = advance(a, x), advance(b, y)
    return a_count, b_count, common


def existing_physical(ds, existing, reference, main_graph, admission_sha, main_d, nontrivial):
    """Reuse a comparison only when its old D output matches the new one."""
    paper = existing / 'paper'
    old_d = (paper / (ds + '.d.1.receipt.json') if ds == 'hprc-v2.1-mc-chm13'
             else existing / (ds + '.d_bc_gfa.receipt.json'))
    old_bubbles = Path(str(old_d).removesuffix('.receipt.json') + '.tsv')
    new_bubbles = Path(str(reference).removesuffix('.receipt.json') + '.tsv')
    vg_catalogue = paper / (ds + '.vg.pairs.tsv')
    vg_status = paper / (ds + '.vg.pairs.json')
    physical = paper / (ds + '.physical.tsv')
    d_nontrivial = paper / (ds + '.d.nontrivial.tsv')
    vg_nontrivial = paper / (ds + '.vg.nontrivial.tsv')
    files = (old_d, old_bubbles, new_bubbles, vg_catalogue, vg_status, physical, d_nontrivial, vg_nontrivial)
    if not all(path.is_file() for path in files):
        return None
    try:
        before = {path: identity(path) for path in files}
        old_binary_sha = json.loads(old_d.read_text())['binary_sha256']
        require(re.fullmatch(r'[0-9a-f]{64}', old_binary_sha) is not None, 'Invalid old binary pin')
        check_d_receipt(old_d, main_graph, admission_sha, old_binary_sha, 1)
        require(d_catalogue_digest(old_bubbles) == d_catalogue_digest(new_bubbles), 'D bubble outputs differ')
        newest_input = max(old_bubbles.stat().st_mtime_ns, vg_catalogue.stat().st_mtime_ns)
        require(all(path.stat().st_mtime_ns >= newest_input for path in
                    (physical, d_nontrivial, vg_nontrivial)), 'Physical comparison is stale')
        status = json.loads(vg_status.read_text())
        values = metrics(physical)
        a_count, b_count, common = sorted_bubble_counts(d_nontrivial, vg_nontrivial)
        require(status.get('status') == 'ok' and status.get('method') == 'vg' and
                int(status['unique_nonunary_pairs']) == int(values['raw_vg']) and
                int(values['raw_d']) == int(main_d['metrics']['pairs']) and
                a_count == int(nontrivial) == int(values['nontrivial_d']) and
                b_count == int(values['nontrivial_vg']) and common == int(values['nontrivial_common']) and
                a_count - common == int(values['nontrivial_d_only']) and
                b_count - common == int(values['nontrivial_vg_only']),
                'Existing physical comparison is inconsistent')
        require(all(identity(path) == before[path] for path in files), 'Existing comparison changed')
        return values
    except (OSError, KeyError, ValueError, RuntimeError, json.JSONDecodeError):
        return None


def prior_physical(ds, source, reference, graph, main_d, nontrivial, lock, lock_sha):
    """Reuse structural comparisons made on another admitted copy of a graph."""
    try:
        existing = Path(source['results'])
        admission_path = Path(source['admission'])
        prior_lock = Path(source['toolchain_lock'])
        before = {path: identity(path) for path in (admission_path, prior_lock)}
        admission_bytes = admission_path.read_bytes()
        old_inputs = admitted_inputs_by_name(json.loads(admission_bytes))
        old_graph = old_inputs[ds + '.gfa']
        _, old_lock_sha = load_lock(prior_lock)
        require(old_graph['sha256'] == graph['sha256'] and old_lock_sha == lock_sha,
                'Previous graph or toolchain differs')
        measurement = existing_measurement(existing / (ds + '.vg_gfa.gfa.time'),
                                           'vg', lock, lock_sha, graph['sha256'],
                                           'snarls', 1, True)
        require(measurement and measurement[0] != 'failed' and
                existing_counts(existing / (ds + '.vg_gfa.gfa.snarl_counts')),
                'Previous vg measurement or counts unavailable')
        admission_sha = hashlib.sha256(admission_bytes).hexdigest()
        values = existing_physical(ds, existing, reference, old_graph, admission_sha,
                                   main_d, nontrivial)
        require(values is not None, 'Previous physical comparison unavailable')
        require(identity(Path(old_graph['path'])) == old_graph['identity'] and
                identity(Path(graph['path'])) == graph['identity'] and
                all(identity(path) == before[path] for path in before),
                'Previous comparison inputs changed')
        return values
    except (OSError, KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError):
        return None


def load_prior_comparisons(path):
    if path is None:
        return {}
    records = json.loads(path.read_text())
    require(isinstance(records, dict) and set(records) <= set(ALL),
            'Invalid prior comparison dataset names')
    for record in records.values():
        require(isinstance(record, dict) and set(record) == {'results', 'admission', 'toolchain_lock'} and
                all(isinstance(value, str) and value for value in record.values()),
                'Invalid prior comparison source')
    return {ds: {key: str((path.parent / value).resolve()) for key, value in record.items()}
            for ds, record in records.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--paper', required=True, type=Path)
    parser.add_argument('--existing-results', required=True, type=Path)
    parser.add_argument('--prior-comparisons', type=Path)
    parser.add_argument('--tmpdir')
    parser.add_argument('--admission', required=True, type=Path)
    parser.add_argument('--toolchain-lock', required=True, type=Path)
    parser.add_argument('--binary-sha', required=True, type=Path)
    parser.add_argument('--template', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--latex', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--dataset', action='append', required=True)
    args = parser.parse_args()
    binary_sha = args.binary_sha.read_text().strip()
    require(re.fullmatch(r'[0-9a-f]{64}', binary_sha) is not None, 'Invalid BubbleFinder pin')
    lock, lock_sha = load_lock(args.toolchain_lock)
    admission_bytes = args.admission.read_bytes()
    admission = json.loads(admission_bytes)
    admission_sha = hashlib.sha256(admission_bytes).hexdigest()
    inputs = admitted_inputs_by_name(admission)
    prior = load_prior_comparisons(args.prior_comparisons)
    rows, checks = [], []
    for ds in args.dataset:
        gfa = inputs[ds + '.gfa']
        thread_graph = inputs[ds + '.gbz'] if ds.startswith('hprc-') else gfa
        main_graph = thread_graph if ds == 'hprc-v2.1-mc-chm13' else gfa
        row = dict.fromkeys(FIELDS, '-')
        row.update(dataset=ds, length_unit=length_unit(ds),
                   format='GBZ' if ds.startswith('hprc-') else 'GFA')
        for threads in (1, 8):
            path = args.paper / f'{ds}.d.{threads}.receipt.json'
            check_d_receipt(path, thread_graph, admission_sha, binary_sha, threads)
            seconds, memory, scope, count = receipt(path)
            row.update({f'd_seconds_{threads}': seconds, f'd_gib_{threads}': memory,
                        f'd_scope_{threads}': scope, f'd_all_{threads}': count})
        reference = (args.paper / (ds + '.d.1.receipt.json') if ds == 'hprc-v2.1-mc-chm13'
                     else args.results / (ds + '.d_bc_gfa.receipt.json'))
        main_d = check_d_receipt(reference, main_graph, admission_sha, binary_sha, 1)
        row['d_main_seconds'], row['d_main_gib'], row['d_main_scope'], _ = receipt(reference)
        d1 = json.loads((args.paper / (ds + '.d.1.receipt.json')).read_text())
        row['d_read_seconds_1'] = d1.get('metrics', {}).get('read_seconds', '-')
        row['d_thread_speedup'] = ratio(row['d_seconds_1'], row['d_seconds_8']) or '-'
        nontrivial = check_nontrivial(args.paper / (ds + '.validation-nontrivial.receipt.json'),
                                      main_graph, admission_sha, binary_sha)
        row['d_nontrivial'] = nontrivial['metrics']['pairs']
        u_path = args.paper / (ds + '.u.1.receipt.json')
        check_d_receipt(u_path, main_graph, admission_sha, binary_sha, 1, ultra=True)
        row['u_via_d_seconds'], row['u_via_d_gib'], row['u_via_d_scope'], _ = receipt(u_path)
        size = metrics(args.paper / (ds + '.quartiles.tsv'))
        require(int(size['raw_d']) == int(main_d['metrics']['pairs']), 'D size census differs: ' + ds)
        row.update(nonsnarl_d_nontrivial=size['nonsnarl_nontrivial_d'], q1=size.get('Q1_bp', '-'),
                   median=size.get('Q2_bp', '-'), q3=size.get('Q3_bp', '-'),
                   maximum=size.get('Q4_bp', '-'))
        row.update(topology(args.results / (ds + '.gfa_stats')))
        suffix = '.bf_gbz' if ds == 'hprc-v2.1-mc-chm13' else '.bf_gfa.gfa'
        suffix_nt = '.bf_gbz_noT' if ds == 'hprc-v2.1-mc-chm13' else '.bf_gfa_noT.gfa'
        for stem, trivial in ((ds + suffix, True), (ds + suffix_nt, False)):
            path = args.results / (stem + '.time')
            require(check_measurement(path, 'bubblefinder', lock, lock_sha,
                                      expected_binary_sha256=binary_sha,
                                      expected_graph_sha256=main_graph['sha256'],
                                      expected_operation='ultrabubbles', expected_threads=1,
                                      expected_include_trivial=trivial),
                    'Missing BubbleFinder ultrabubble measurement: ' + ds)
            with (args.results / (stem + '.txt')).open() as stream:
                count = stream.readline().strip()
            require(count.isdigit(), 'Invalid BubbleFinder ultrabubble count: ' + ds)
            row['bf_ultrabubbles_all' if trivial else 'bf_ultrabubbles_nontrivial'] = count
        row['bf_ultrabubbles_seconds'], row['bf_ultrabubbles_gib'] = timing(args.results / (ds + suffix + '.time'))
        log = (args.results / (ds + suffix + '.log')).read_text(errors='replace')
        match = re.search(r'Conflict vertices:\s+(\d+)', log)
        if match:
            row['orientation_conflict_vertices'] = match.group(1)

        existing = args.existing_results
        vg_gfa = existing_measurement(existing / (ds + '.vg_gfa.gfa.time'), 'vg', lock, lock_sha,
                                      gfa['sha256'], 'snarls', 1, True)
        if vg_gfa and vg_gfa[0] != 'failed':
            row['vg_gfa_seconds'], row['vg_gfa_gib'] = vg_gfa
        for threads in (1, 8):
            value = existing_measurement(existing / 'paper' / f'{ds}.vg.{threads}.time', 'vg',
                                         lock, lock_sha, thread_graph['sha256'], 'snarls', threads, True)
            if value and value[0] != 'failed':
                row[f'vg_seconds_{threads}'], row[f'vg_gib_{threads}'] = value
        stem = ds + ('.vg_gbz' if ds == 'hprc-v2.1-mc-chm13' else '.vg_gfa.gfa')
        stem_nt = ds + ('.vg_gbz_noT' if ds == 'hprc-v2.1-mc-chm13' else '.vg_gfa_noT.gfa')
        vg = existing_measurement(existing / (stem + '.time'), 'vg', lock, lock_sha,
                                  main_graph['sha256'], 'snarls', 1, True)
        vg_nt = existing_measurement(existing / (stem_nt + '.time'), 'vg', lock, lock_sha,
                                     main_graph['sha256'], 'snarls', 1, False)
        vg_counts = existing_counts(existing / (stem + '.snarl_counts')) if vg and vg[0] != 'failed' else None
        vg_nt_counts = existing_counts(existing / (stem_nt + '.snarl_counts')) if vg_nt and vg_nt[0] != 'failed' else None
        if vg_counts:
            row.update(vg_records_all=vg_counts['n_snarls'], vg_ultrabubble_records_all=vg_counts['n_ub'],
                       vg_non_ultrabubble_records=str(int(vg_counts['n_snarls']) - int(vg_counts['n_ub'])))
        if vg_nt_counts:
            row.update(vg_records_nontrivial_native=vg_nt_counts['n_snarls'],
                       vg_ultrabubble_records_nontrivial_native=vg_nt_counts['n_ub'])
        billi = existing_measurement(existing / (ds + '.billi.time'), 'billi', lock, lock_sha,
                                     gfa['sha256'], 'decompose')
        if billi:
            if billi[0] == 'failed':
                row.update(billi_seconds='failed', billi_gib='failed', billi_records='failed')
            else:
                row['billi_seconds'], row['billi_gib'] = billi
                path = existing / (ds + '.billi.counts')
                if path.is_file():
                    values = dict(line.rstrip('\n').split('\t') for line in path.read_text().splitlines())
                    count = values.get('n_panbubbles')
                    if count and count.isdigit():
                        row['billi_records'] = count
        row['vg_over_d_total_1'], row['vg_over_d_subtract_d_read_1'] = gbz_speedups(
            row['vg_seconds_1'], row['d_seconds_1'], row['d_read_seconds_1'])
        row['vg_thread_speedup'] = ratio(row['vg_seconds_1'], row['vg_seconds_8']) or '-'
        row['vg_over_d_at_8'] = ratio(row['vg_seconds_8'], row['d_seconds_8']) or '-'
        row['vg_over_d_total_1'] = row['vg_over_d_total_1'] or '-'
        row['vg_over_d_subtract_d_read_1'] = row['vg_over_d_subtract_d_read_1'] or '-'

        values = (existing_physical(ds, existing, reference, main_graph, admission_sha,
                                    main_d, row['d_nontrivial']) if vg_counts else None)
        overlap_source = ({'results': str(existing), 'admission': str(args.admission),
                           'toolchain_lock': str(args.toolchain_lock)} if values else None)
        prior_status = None
        if values is None and ds in prior:
            values = prior_physical(ds, prior[ds], reference, main_graph, main_d,
                                    row['d_nontrivial'], lock, lock_sha)
            prior_status = 'reused_verified' if values is not None else 'unavailable'
            overlap_source = prior[ds] if values is not None else None
        if values:
            row.update(vg_nontrivial=values['nontrivial_vg'], common=values['nontrivial_common'],
                       d_only=values['nontrivial_d_only'], vg_only=values['nontrivial_vg_only'])
        overlap = None
        reused_billi_count = False
        if overlap_source:
            overlap = prior_overlap(ds, overlap_source, gfa['sha256'], lock, lock_sha,
                                    values, args.tmpdir)
            if overlap:
                prior_count = str(overlap['billi_records'])
                if row['billi_records'] == '-':
                    row['billi_records'] = prior_count
                    reused_billi_count = True
                elif row['billi_records'] != prior_count:
                    overlap = None
        rows.append(row)
        check = {'dataset': ds,
                 'physical_comparison': 'reused_verified' if values else 'unavailable',
                 'missing_fields': [key for key, value in row.items() if value == '-']}
        if prior_status:
            check['prior_admission_comparison'] = prior_status
        if overlap:
            check['billi_overlap'] = overlap
        if reused_billi_count:
            check['prior_billi_count'] = 'reused_verified'
        checks.append(check)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    args.latex.write_text('% Validation only: missing results are -, not zero.\n' +
                          render(rows, args.template.read_text(), allow_missing=True))
    args.report.write_text(json.dumps({'status': 'PASS', 'datasets_checked': len(rows),
                                                                            'new_vg_or_billi_runs': False,
                                      'missing_representation': '-', 'rows': checks}, indent=2) + '\n')


if __name__ == '__main__':
    main()
