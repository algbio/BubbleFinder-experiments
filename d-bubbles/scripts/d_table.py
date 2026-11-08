"""Compare the bubbles found by BubbleFinder and vg."""
import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path
from bubbles import d_bubbles, sorted_bubbles
from toolchain_provenance import check_results


def kv(p):
    if not p.exists():
        return {}
    return dict(line.split('\t') for line in p.read_text().splitlines() if line and not line.startswith('#'))


def identity(p):
    s = p.stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def normalized(p, kind='plain'):
    target = Path(str(p)+'.sorted')
    source = p
    marker = Path(str(target)+'.json')
    held = identity(p)
    if target.exists():
        m = json.loads(marker.read_text())
        if m['input'] != held or m['output'] != identity(target):
            raise RuntimeError('Sorted bubble cache has changed')
        return target
    if kind == 'd':
        source = Path(str(p)+'.poles')
        with p.open() as f, source.open('w') as out:
            d_bubbles(f, out)
    sorted_bubbles(source, target, p.parent)
    if identity(p) != held:
        raise RuntimeError("Input changed while sorting bubbles")
    marker.write_text(json.dumps(dict(input=held, output=identity(target)))+"\n")
    return target


def difference(a, b, dest=None):
    """Subtract one sorted set of bubbles from another."""
    count = 0
    out = dest.open('w') if dest else None
    try:
        with a.open() as fa, b.open() as fb:
            y = next(fb, None)
            for x in fa:
                while y is not None and y < x:
                    y = next(fb, None)
                if x != y:
                    count += 1
                    if out:
                        out.write(x)
    finally:
        if out:
            out.close()
    return count


def length(p):
    with p.open() as f:
        return sum(1 for _ in f)


def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for x in iter(lambda: f.read(1<<20), b''): h.update(x)
    return h.hexdigest()


def timing(p):
    if not p.exists():
        return ('', '')
    s = p.read_text()
    if s.startswith('EXIT_CODE='):
        return ('', '')
    wall = re.search(r'Elapsed \(wall clock\).*?:\s*([0-9:.]+)', s)
    rss = re.search(r'Maximum resident set size \(kbytes\):\s*(\d+)', s)
    seconds = ''
    if wall:
        seconds = 0.
        for part in wall.group(1).split(':'):
            seconds = 60*seconds+float(part)
    return seconds, int(rss.group(1)) if rss else ''


def receipt_coverage_status(receipt):
    """Check whether the result covers the whole graph."""
    original = receipt['status']
    coverage = receipt.get('coverage', {})
    if original != 'ok':
        return original
    if coverage.get('status') != 'full' or coverage.get('full_graph_eligible') is not True:
        return 'partial_coverage' if coverage.get('status') == 'partial' else 'coverage_unknown'
    if receipt.get('schema') == 4:
        return 'ok'
    metrics = receipt.get('metrics', {})
    try:
        if (int(metrics['corridor_states']) != 2*int(metrics['physical_nodes']) or
            int(metrics['noncorridor_states']) != 0 or
            int(metrics['components_selected']) != int(metrics['components_total'])):
            return 'invalid_coverage'
    except (KeyError, TypeError, ValueError):
        return 'invalid_coverage'
    return 'ok'


def main():
    a = argparse.ArgumentParser()
    a.add_argument('results', type=Path)
    a.add_argument('tables', type=Path)
    a.add_argument('--stem', default='d_bubble_table')
    a.add_argument('--toolchain-lock', type=Path, required=True)
    args = a.parse_args()
    R = args.results
    lock, lock_sha = check_results(R, args.toolchain_lock)
    T = args.tables
    T.mkdir(parents=True, exist_ok=True)
    rows = []
    parity = []
    for receipt in sorted(R.glob('*.d*.receipt.json')):
        match = re.fullmatch(r'(.+)\.(d(?:_bc)?_(?:gfa|gbz))\.receipt\.json', receipt.name)
        if not match:
            continue
        ds, variant = match.groups()
        r = json.loads(receipt.read_text())
        prefix = R/(ds+'.'+variant)
        fmt = variant.rsplit('_', 1)[1]
        scope_status = receipt_coverage_status(r)
        coverage = r.get('coverage', {})
        metrics = r.get('metrics', {})
        row = dict(dataset=ds, format=fmt, backend=r['backend'], status=scope_status,
            receipt_status=r['status'], execution_status=r.get('execution_status', r['status']),
            coverage_status=coverage.get('status', 'legacy_unknown'), root_policy=r.get('root_policy', 'legacy_unknown'),
            corridor_states=metrics.get('corridor_states', ''), selected_oriented_states=coverage.get('selected_oriented_states', ''),
            components_selected=metrics.get('components_selected', ''), components_total=metrics.get('components_total', ''),
            d_observed_pairs=metrics.get('pairs', ''), toolchain_sha256=lock_sha, d_all='', d_nontrivial='', vg_all='', vg_nontrivial='', vg_ultrabubbles_all='', vg_other_all='', d_intersect_vg='', d_not_reported_by_vg='', vg_not_reported_by_d='', d_nontrivial_intersect_vg='', id_join_status='not_checked', wall_seconds=r['run']['wall_seconds'], maxrss_kib=r['run']['maxrss_kib'])
        vg = R/(ds+('.vg_gfa.gfa' if fmt == 'gfa' else '.vg_gbz'))
        vn = R/(ds+('.vg_gfa_noT.gfa' if fmt == 'gfa' else '.vg_gbz_noT'))
        counts = kv(Path(str(vg)+'.snarl_counts'))
        counts0 = kv(Path(str(vn)+'.snarl_counts'))
        row.update(vg_all=counts.get('n_snarls', ''), vg_nontrivial=counts0.get('n_snarls', ''),
                   vg_ultrabubbles_all=counts.get('n_ub', ''), vg_other_all=counts.get('n_diff', ''))
        row['vg_unary_rows'] = counts.get('n_unary', '')
        row['vg_unique_pairs'] = ''
        row['vg_duplicate_rows'] = ''
        row['vg_wall_seconds'], row['vg_maxrss_kib'] = timing(Path(str(vg)+'.time'))
        row['billi_heuristic_reported'] = kv(R/(ds+'.billi.counts')).get('n_panbubbles', '')
        bf = R/(ds+('.bf_gfa.gfa.txt' if fmt == 'gfa' else '.bf_gbz.txt'))
        row['bf_ultrabubbles_reported'] = ''
        if bf.exists() and not (Path(str(bf).removesuffix('.txt')+'.time').exists() and Path(str(bf).removesuffix('.txt')+'.time').read_text().startswith('EXIT_CODE=')):
            with bf.open() as f:
                head = f.readline().strip()
            if head.isdigit():
                row['bf_ultrabubbles_reported'] = int(head)
        if scope_status == 'ok':
            D = normalized(Path(str(prefix)+'.tsv'), 'd')
            n = length(D)
            raw = int(r['metrics']['pairs'])
            if n != raw:
                raise RuntimeError('Repeated d-bubble or incomplete TSV: '+ds)
            row['d_all'] = n
            empty = R/(ds+'.empty.pairs')
            stats = R/(ds+'.gfa_stats')
            verified = stats.exists() and 'Positive canonical numeric IDs: 1' in stats.read_text()
            # Keep the original GFA names and report each format separately.
            if fmt == 'gfa' and empty.exists():
                E = normalized(empty)
                D0 = Path(str(prefix)+'.nontrivial.pairs')
                row['d_nontrivial'] = difference(D, E, D0)
            P = Path(str(vg)+'.pairs')
            if fmt == 'gfa' and verified and P.exists():
                V = normalized(P)
                nv = length(V)
                row['vg_unique_pairs'] = nv
                row['vg_duplicate_rows'] = int(row['vg_all'])-nv
                if row['vg_duplicate_rows'] < 0:
                    raise RuntimeError('vg bubble/count mismatch')
                minus = difference(D, V)
                row.update(d_intersect_vg=n-minus, d_not_reported_by_vg=minus,
                           vg_not_reported_by_d=difference(V, D), id_join_status='positive_numeric_GFA_ids')
                if row['d_nontrivial'] != '':
                    missing = difference(D0, V)
                    row['d_nontrivial_intersect_vg'] = int(row['d_nontrivial'])-missing
            else:
                row['id_join_status'] = 'unverified_GBZ_mapping' if fmt == 'gbz' else 'unverified_or_missing_reference'
        rows.append(row)
        if variant.startswith('d_bc'):
            other = R/(ds+'.d_'+fmt+'.receipt.json')
            if other.exists():
                q = json.loads(other.read_text())
                same = r['status'] == q['status']
                if r['status'] == 'ok':
                    same = same and digest(Path(str(prefix)+'.tsv')) == digest(R/(ds+'.d_'+fmt+'.tsv'))
                parity.append(dict(dataset=ds, format=fmt, exact_LT_BC_TSV_and_status_equal=same))
                if not same:
                    raise RuntimeError('Results differ with and without blocks: '+ds)
    fields = list(rows[0]) if rows else ['dataset', 'format', 'backend', 'status']
    with (T/(args.stem+'.tsv')).open('w', newline='') as f:
        w = csv.DictWriter(f, fields, delimiter='\t', lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    (T/(args.stem+'-parity.json')).write_text(json.dumps(parity, indent=2)+'\n')
    (T/(args.stem+'-toolchain.json')).write_text(json.dumps(dict(toolchain_sha256=lock_sha, lock=lock), indent=2)+'\n')
    def text(v): return str(v).replace('\\', r'\textbackslash{}').replace(
        '_', r'\_').replace('&', r'\&').replace('%', r'\%')
    def number(v): return '--' if v == '' else f'{int(v):,}'
    with (T/(args.stem+'.tex')).open('w') as f:
        f.write('\\begin{tabular}{llrrrrrr}\n\\hline\nGraph / format & Backend & \\shortstack{D-bubbles\\\\all} & \\shortstack{D-bubbles\\\\nontrivial} & \\shortstack{vg snarls\\\\reported} & \\shortstack{vg snarls\\\\nontrivial} & \\shortstack{Found by both\\\\all bubbles} & \\shortstack{D-bubbles not\\\\reported by vg} \\\\\n\\hline\n')
        for r in rows:
            state = r['status']
            d = number(r['d_all']) if state == 'ok' else text(state)
            f.write(' & '.join([text(r['dataset']+' / '+r['format']), text(r['backend']), d, number(r['d_nontrivial']), number(
                r['vg_all']), number(r['vg_nontrivial']), number(r['d_intersect_vg']), number(r['d_not_reported_by_vg'])])+' \\\\\n')
        f.write('\\hline\n\\end{tabular}\n% Counts include trivial bubbles unless stated.\n% A dash marks unavailable results.\n')
    with (T/(args.stem+'-performance.tex')).open('w') as f:
        f.write('\\begin{tabular}{llrrrr}\n\\hline\nGraph / format & Backend & \\shortstack{D-bubble\\\\time (s)} & \\shortstack{vg time\\\\(s)} & \\shortstack{D-bubble\\\\memory (GiB)} & \\shortstack{vg memory\\\\(GiB)} \\\\\n\\hline\n')
        for r in rows:
            v = r['vg_wall_seconds']
            m = r['vg_maxrss_kib']
            f.write(' & '.join([text(r['dataset']+' / '+r['format']), text(r['backend']), f"{r['wall_seconds']:.3f}" if r['status'] == 'ok' else text(
                r['status']), f'{v:.3f}' if v != '' else '--', f"{r['maxrss_kib']/1048576:.3f}" if r['status'] == 'ok' else '--', f'{m/1048576:.3f}' if m != '' else '--'])+' \\\\\n')
        f.write(
            '\\hline\n\\end{tabular}\n% Times include reading and output.\n')


if __name__ == '__main__':
    main()
