"""Write the paper results and tables."""
import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

from toolchain_provenance import check_measurement, load_lock
from check_admitted_input import admitted_inputs_by_name
from paper_tables import render as render_tables
from datasets import length_unit



def check_d_receipt(path, graph, admission_sha, binary_sha, threads, ultra=False,
                    allow_partial=None):
    """Check the input and settings of a run."""
    r = json.loads(Path(path).read_text())
    if allow_partial is None:
        allow_partial = bool(r.get('allow_partial_corridor', False))
    if r.get('schema') not in ((5,) if ultra else (2, 3, 4)):
        raise ValueError('Unsupported d-bubble run record: ' + str(path))
    if r.get('execution_status') != 'ok':
        raise ValueError('D-bubble run failed: ' + str(path))
    if (Path(r.get('graph', '')).resolve() != Path(graph['path']).resolve() or
            r.get('graph_sha256') != graph['sha256'] or
            r.get('graph_identity_before') != graph['identity'] or
            r.get('graph_identity_after') != graph['identity']):
        raise ValueError('D-bubble run used a different graph: ' + str(path))
    if r.get('admission_sha256') != admission_sha:
        raise ValueError('Input check record changed: ' + str(path))
    if r.get('binary_sha256') != binary_sha:
        raise ValueError('D-bubble run used a different executable: ' + str(path))
    if r.get('threads') != threads:
        raise ValueError('D-bubble thread count differs: ' + str(path))
    if r.get('root_policy') != 'all-zero-indegree-state-exits':
        raise ValueError('D-bubble run used different tip connections: ' + str(path))
    if r.get('includes_trivial') is not True:
        raise ValueError('D-bubble run must include trivial bubbles: ' + str(path))
    if r.get('ultrabubbles_only') is not ultra:
        raise ValueError('Wrong ultrabubble filter setting: ' + str(path))
    if r.get('allow_partial_corridor') is not allow_partial:
        raise ValueError('Wrong partial coverage setting: ' + str(path))
    if r.get('coverage', {}).get('status') not in ('full', 'partial'):
        raise ValueError('D-bubble run has no valid coverage result: ' + str(path))
    run = r.get('run', {})
    argv = run.get('argv')
    if ultra:
        valid_command = (isinstance(argv, list) and len(argv) == 10 and
                         argv[1:3] == ['ultrabubbles', '-g'] and argv[4] == '-o' and
                         argv[6:] == ['-j', str(threads), '-T', '--d-bubbles'] and
                         r.get('engine') == 'bubblefinder' and r.get('engine_sha256') == binary_sha and
                         r.get('output_format') == 'standard')
    elif r['schema'] == 2:
        tail = ['-j', str(threads), '--output-format', 'tsv', '-T']
        if allow_partial:
            tail.append('--allow-partial-corridor')
        valid_command = (isinstance(argv, list) and len(argv) == 8 + len(tail) and
                         argv[1:3] == ['d-bubbles', '-g'] and argv[4] == '-o' and
                         argv[6] == '--metrics' and argv[8:] == tail)
    else:
        valid_command = (isinstance(argv, list) and len(argv) == 9 and
                         argv[1:3] == ['d-bubbles', '-g'] and argv[4] == '-o' and
                         argv[6:] == ['-j', str(threads), '-T'] and
                         r.get('engine') == 'bubblefinder' and r.get('engine_sha256') == binary_sha and
                         r.get('output_format') == 'standard')
    if (run.get('returncode') != 0 or run.get('reaped') is not True or
            run.get('absence') is not True or not valid_command or
            not all(isinstance(value, str) and value for value in argv)):
        raise ValueError('D-bubble process did not finish with the expected command: ' + str(path))
    return r


def metrics(path):
    with Path(path).open() as stream:
        rows = list(csv.reader(stream, delimiter='\t'))
    if not rows or rows[0] != ['metric', 'value']:
        raise ValueError('Invalid metrics table: ' + str(path))
    return dict(rows[1:])


def timing(path):
    text = Path(path).read_text()
    if text.startswith('EXIT_CODE='):
        return ('failed', 'failed')
    wall = rss = None
    for line in text.splitlines():
        if 'Elapsed (wall clock) time' in line:
            parts = line.rsplit(': ', 1)[-1].split(':')
            wall = sum(float(value) * 60 ** i for i, value in enumerate(reversed(parts)))
        if 'Maximum resident set size (kbytes):' in line:
            rss = int(line.rsplit(':', 1)[-1].strip()) / (1024 * 1024)
    if wall is None or rss is None:
        raise ValueError('Incomplete time output: ' + str(path))
    return (f"{wall:.3f}", f"{rss:.3f}")


def receipt(path):
    r = json.loads(Path(path).read_text())
    if r['execution_status'] != 'ok':
        return ('failed', 'failed', r['coverage']['status'], '')
    if r['coverage']['status'] not in ('full', 'partial'):
        raise ValueError('Run has no valid coverage result: ' + str(path))
    return (f"{r['run']['wall_seconds']:.3f}",
            f"{r['run']['maxrss_kib'] / (1024 * 1024):.3f}",
            r['coverage']['status'], r['metrics']['pairs'])


def topology(path):
    text = Path(path).read_text()
    fields = {'nodes': 'Nodes', 'links': 'Edges', 'components': 'Connected components',
              'tips': 'Total tips', 'cut_vertices': 'Total cut vertices',
              'components_without_tips': 'Non-triv. w/o tips',
              'components_without_cut_vertices': 'Non-triv. w/o cut vtx'}
    result = {}
    for name, label in fields.items():
        match = re.search(r'^\s*' + re.escape(label) + r':\s*(\d+)', text, re.MULTILINE)
        if not match:
            raise ValueError('Missing topology field ' + label + ' in ' + str(path))
        result[name] = match.group(1)
    return result


def ratio(numerator, denominator):
    try:
        return f"{float(numerator) / float(denominator):.2f}"
    except (ValueError, ZeroDivisionError):
        return ''


def gbz_speedups(vg_seconds, d_seconds, read_seconds):
    """Compare the total times and estimate the ratio after reading."""
    def value(raw):
        try:
            number = float(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) and number >= 0 else None

    def divide(numerator, denominator):
        if numerator is None or denominator is None or denominator <= 0:
            return ''
        quotient = numerator / denominator
        return f"{quotient:.3f}" if math.isfinite(quotient) else ''

    vg, d, read = map(value, (vg_seconds, d_seconds, read_seconds))
    total = divide(vg, d)
    if vg is None or d is None or read is None or vg <= read or d <= read:
        return total, ''
    return total, divide(vg - read, d - read)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--results', required=True, type=Path)
    p.add_argument('--paper', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--latex', required=True, type=Path)
    p.add_argument('--table-template', type=Path,
                   default=Path(__file__).resolve().parent.parent / 'templates/paper-tables.tex')
    p.add_argument('--dataset', action='append', required=True)
    p.add_argument('--threads', action='append', type=int, required=True)
    p.add_argument('--toolchain-lock', required=True, type=Path)
    p.add_argument('--admission', required=True, type=Path)
    a = p.parse_args()
    lock, lock_sha = load_lock(a.toolchain_lock)
    admission_bytes = a.admission.read_bytes()
    admission = json.loads(admission_bytes)
    admission_sha = hashlib.sha256(admission_bytes).hexdigest()
    inputs = admitted_inputs_by_name(admission)
    rows = []
    for ds in a.dataset:
        raw_receipt = json.loads((a.paper / (ds + '.d.1.receipt.json')).read_text())
        binary_sha = raw_receipt['binary_sha256']
        if not re.fullmatch(r'[0-9a-f]{64}', binary_sha):
            raise ValueError('Invalid BubbleFinder binary SHA-256: ' + ds)
        gfa = inputs[ds + '.gfa']
        thread_graph = inputs[ds + '.gbz'] if ds.startswith('hprc-') else gfa
        main_graph = thread_graph if ds == 'hprc-v2.1-mc-chm13' else gfa
        gfa_sha, thread_graph_sha, main_graph_sha = (gfa['sha256'], thread_graph['sha256'],
                                                     main_graph['sha256'])
        for j in a.threads:
            check_d_receipt(a.paper / f"{ds}.d.{j}.receipt.json", thread_graph,
                            admission_sha, binary_sha, j)
        reference_receipt = (a.paper / (ds + '.d.1.receipt.json')
                             if ds == 'hprc-v2.1-mc-chm13' else
                             a.results / (ds + '.d_bc_gfa.receipt.json'))
        check_d_receipt(reference_receipt, main_graph, admission_sha, binary_sha, 1)
        check_d_receipt(a.paper / (ds + '.u.1.receipt.json'), main_graph,
                        admission_sha, binary_sha, 1, ultra=True)
        vg_stem = ds + ('.vg_gbz' if ds == 'hprc-v2.1-mc-chm13' else '.vg_gfa.gfa')
        vg_nontriv_stem = ds + ('.vg_gbz_noT' if ds == 'hprc-v2.1-mc-chm13' else '.vg_gfa_noT.gfa')
        vg_times = {a.results / (vg_stem + '.time'): (main_graph_sha, 1, True),
                    a.results / (vg_nontriv_stem + '.time'): (main_graph_sha, 1, False),
                    a.results / (ds + '.vg_gfa.gfa.time'): (gfa_sha, 1, True)}
        vg_times.update({a.paper / f"{ds}.vg.{j}.time": (thread_graph_sha, j, True)
                         for j in a.threads})
        for path, (graph_sha, threads, trivial) in vg_times.items():
            if not check_measurement(path, 'vg', lock, lock_sha,
                                     expected_graph_sha256=graph_sha, expected_operation='snarls',
                                     expected_threads=threads, expected_include_trivial=trivial):
                raise ValueError('Failed or missing vg measurement: ' + str(path))
        billi_time = a.results / (ds + '.billi.time')
        billi_ok = check_measurement(billi_time, 'billi', lock, lock_sha,
                                     expected_graph_sha256=gfa_sha, expected_operation='decompose')
        ub_stem = ds + ('.bf_gbz' if ds == 'hprc-v2.1-mc-chm13' else '.bf_gfa.gfa')
        ub_nontriv_stem = ds + ('.bf_gbz_noT' if ds == 'hprc-v2.1-mc-chm13' else '.bf_gfa_noT.gfa')
        for stem, trivial in ((ub_stem, True), (ub_nontriv_stem, False)):
            path = a.results / (stem + '.time')
            if not check_measurement(path, 'bubblefinder', lock, lock_sha,
                                     expected_binary_sha256=binary_sha,
                                     expected_graph_sha256=main_graph_sha,
                                     expected_operation='ultrabubbles', expected_threads=1,
                                     expected_include_trivial=trivial):
                raise ValueError('Failed or missing BubbleFinder measurement: ' + str(path))
        physical = metrics(a.paper / (ds + '.physical.tsv'))
        size = metrics(a.paper / (ds + '.quartiles.tsv'))
        with (a.paper / (ds + '.overlaps.tsv')).open() as stream:
            overlap = list(csv.DictReader(stream, delimiter='\t'))
        billi_status = json.loads((a.paper / (ds + '.billi.pairs.json')).read_text())['status']
        if (billi_status == 'ok') != billi_ok:
            raise ValueError('Billi bubble status differs from the run status: ' + ds)
        ub = sum(int(r['pairs']) for r in overlap if r['ultrabubble'] == '1')
        pan = (sum(int(r['pairs']) for r in overlap if r['billi'] == '1')
               if billi_status == 'ok' else 'failed')
        row = {'dataset': ds, 'length_unit': length_unit(ds),
               'd_nontrivial': physical['nontrivial_d'],
               'vg_nontrivial': physical['nontrivial_vg'], 'common': physical['nontrivial_common'],
               'd_only': physical['nontrivial_d_only'], 'vg_only': physical['nontrivial_vg_only'],
               'vg_ultrabubbles_nontrivial': ub, 'billi_nontrivial': pan,
               'nonsnarl_d_nontrivial': size['nonsnarl_nontrivial_d'],
               'unknown_lengths': size['unknown_length_d'],
               'q1': size.get('Q1_bp', ''), 'median': size.get('Q2_bp', ''),
               'q3': size.get('Q3_bp', ''), 'maximum': size.get('Q4_bp', '')}
        classification = json.loads((a.paper / (ds + '.classification.json')).read_text())
        if classification['d_only'] != int(row['d_only']):
            raise ValueError('D-bubble classification differs from the graph comparison')
        row.update(d_only_nonseparable=classification['nonseparable'],
                   d_only_nonminimal=classification['separable_nonminimal'],
                   d_only_snarls=classification['snarl'],
                   billi_outside_vg=classification.get('billi_outside_vg', ''),
                   billi_outside_vg_snarls=classification.get('billi_outside_vg_snarls', ''),
                   billi_outside_vg_also_d=classification.get('billi_outside_vg_also_d', ''))
        row.update(topology(a.results / (ds + '.gfa_stats')))
        vg_stem = ds + ('.vg_gbz' if ds == 'hprc-v2.1-mc-chm13' else '.vg_gfa.gfa')
        vg_nontriv_stem = ds + ('.vg_gbz_noT' if ds == 'hprc-v2.1-mc-chm13' else '.vg_gfa_noT.gfa')
        with (a.results / (vg_stem + '.snarl_counts')).open() as stream:
            vg_counts = dict(line.rstrip('\n').split('\t') for line in stream)
        with (a.results / (vg_nontriv_stem + '.snarl_counts')).open() as stream:
            vg_nontriv_counts = dict(line.rstrip('\n').split('\t') for line in stream)
        row.update(vg_records_all=vg_counts['n_snarls'], vg_ultrabubble_records_all=vg_counts['n_ub'],
                   vg_records_nontrivial_native=vg_nontriv_counts['n_snarls'],
                   vg_ultrabubble_records_nontrivial_native=vg_nontriv_counts['n_ub'],
                   vg_non_ultrabubble_records=str(int(vg_counts['n_snarls'])-int(vg_counts['n_ub'])))
        billi_seconds, billi_mem = timing(a.results / (ds + '.billi.time'))
        vg_gfa_seconds, vg_gfa_mem = timing(a.results / (ds + '.vg_gfa.gfa.time'))
        ub_stem = ds + ('.bf_gbz' if ds == 'hprc-v2.1-mc-chm13' else '.bf_gfa.gfa')
        ub_seconds, ub_mem = timing(a.results / (ub_stem + '.time'))
        log = (a.results / (ub_stem + '.log')).read_text(errors='replace')
        conflict = re.search(r'Conflict vertices:\s+(\d+)', log)
        if ub_seconds == 'failed':
            ub_all = 'failed'
        else:
            with (a.results / (ub_stem + '.txt')).open() as stream:
                ub_all = str(int(stream.readline().strip()))
        ub_nontriv_stem = ds + ('.bf_gbz_noT' if ds == 'hprc-v2.1-mc-chm13' else '.bf_gfa_noT.gfa')
        with (a.results / (ub_nontriv_stem + '.txt')).open() as stream:
            ub_nontriv = str(int(stream.readline().strip()))
        with (a.results / (ds + '.billi.counts')).open() as stream:
            billi_counts = dict(line.rstrip('\n').split('\t') for line in stream)
        row.update(billi_seconds=billi_seconds, billi_gib=billi_mem,
                   vg_gfa_seconds=vg_gfa_seconds, vg_gfa_gib=vg_gfa_mem,
                   billi_records=billi_counts.get('n_panbubbles', 'failed'),
                   bf_ultrabubbles_seconds=ub_seconds, bf_ultrabubbles_gib=ub_mem,
                   bf_ultrabubbles_all=ub_all, bf_ultrabubbles_nontrivial=ub_nontriv,
                   orientation_conflict_vertices=conflict.group(1) if conflict else '')
        if ds == 'hprc-v2.1-mc-chm13':
            gfa_seconds, gfa_mem, gfa_scope, gfa_count = ('', '', '', '')
        else:
            gfa_seconds, gfa_mem, gfa_scope, gfa_count = receipt(a.results / (ds + '.d_bc_gfa.receipt.json'))
        row.update(d_gfa_seconds=gfa_seconds, d_gfa_gib=gfa_mem,
                   d_gfa_scope=gfa_scope, d_gfa_all=gfa_count)
        u_seconds, u_mem, u_scope, u_count = receipt(a.paper / (ds + '.u.1.receipt.json'))
        row.update(u_via_d_seconds=u_seconds, u_via_d_gib=u_mem,
                   u_via_d_scope=u_scope, u_via_d_pairs=u_count)
        for j in a.threads:
            seconds, mem, scope, count = receipt(a.paper / f"{ds}.d.{j}.receipt.json")
            vg_seconds, vg_mem = timing(a.paper / f"{ds}.vg.{j}.time")
            row.update({f'd_seconds_{j}': seconds, f'd_gib_{j}': mem,
                        f'd_scope_{j}': scope, f'd_all_{j}': count,
                        f'vg_seconds_{j}': vg_seconds, f'vg_gib_{j}': vg_mem})
        if 1 in a.threads:
            raw_receipt = json.loads((a.paper / (ds + '.d.1.receipt.json')).read_text())
            read_seconds = raw_receipt.get('metrics', {}).get('read_seconds', '')
            row['d_read_seconds_1'] = read_seconds
            row['vg_over_d_total_1'], row['vg_over_d_subtract_d_read_1'] = gbz_speedups(
                row['vg_seconds_1'], row['d_seconds_1'], read_seconds)
        if ds == 'hprc-v2.1-mc-chm13':
            row['d_main_seconds'], row['d_main_gib'] = row.get('d_seconds_1', ''), row.get('d_gib_1', '')
            row['d_main_scope'] = row.get('d_scope_1', '')
        else:
            row['d_main_seconds'], row['d_main_gib'] = row['d_gfa_seconds'], row['d_gfa_gib']
            row['d_main_scope'] = row['d_gfa_scope']
        row['format'] = 'GBZ' if ds.startswith('hprc-') else 'GFA'
        if 1 in a.threads and 8 in a.threads:
            row['d_thread_speedup'] = ratio(row['d_seconds_1'], row['d_seconds_8'])
            row['vg_thread_speedup'] = ratio(row['vg_seconds_1'], row['vg_seconds_8'])
            row['vg_over_d_at_8'] = ratio(row['vg_seconds_8'], row['d_seconds_8'])
        rows.append(row)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter='\t', lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    a.latex.write_text(render_tables(rows, a.table_template.read_text()))


if __name__ == '__main__':
    main()
