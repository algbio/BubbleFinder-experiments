"""Write LaTeX tables from the run results."""
import argparse
import csv
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


from datasets import DATASETS, ordered


ALL = tuple(ordered(DATASETS))
HPRC = tuple(ds for ds in ALL if DATASETS[ds]['group'] == 'MC')
PANGENE = tuple(ds for ds in ALL if DATASETS[ds]['group'] == 'Pangene')
MAIN = tuple(ds for ds in ALL if ds not in PANGENE)
DISPLAY = {ds: (row['label'], row['short_label']) for ds, row in DATASETS.items()}

SLOTS = {
    'tab:supervisor-gbz': (HPRC,),
    'tab:supervisor-gfa': (MAIN,),
    'tab:supervisor-comparison': (MAIN,),
    'tab:supervisor-sizes': (MAIN,),
    'tab:app-pangene-perf': (PANGENE,),
    'tab:app-ub-via-d': (ALL,),
    'tab:app-pangene-comparison': (PANGENE,),
    'tab:app-pangene-sizes': (PANGENE,),
    'tab:threads-main-1-8': (MAIN,),
    'tab:threads-extra-1-8': (PANGENE,),
    'tab:threads-memory-1-8': (ALL,),
    'tab:app-topology': (ALL, ALL),
    'tab:app-native-counts': (ALL,),
    'tab:app-reference-counts': (ALL, ALL),
}
MARKER = re.compile(r'^%% TABLE_ROWS:(tab:[a-z0-9-]+):(\d+) %%$', re.MULTILINE)


def missing(row, key):
    return row.get('_allow_missing') is True and str(row.get(key, '')) in ('', '-', '--')


def number(row, key):
    value = str(row.get(key, ''))
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Missing or invalid {key} for {row['dataset']}: {value!r}") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"Invalid {key} for {row['dataset']}: {value!r}")
    return result


def count(row, key):
    if missing(row, key):
        return '-'
    value = number(row, key)
    if value != value.to_integral_value():
        raise ValueError(f"Non-integral {key} for {row['dataset']}")
    return format(int(value), ',')


def quartile(row, key):
    if missing(row, key):
        return '-'
    value = number(row, key)
    return format(value, ',f').rstrip('0').rstrip('.') if '.' in format(value, 'f') else format(value, ',f')


def duration(row, key):
    if missing(row, key):
        return '-'
    value = number(row, key)
    if value < 1:
        return r'$<1$\,s'
    seconds = int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def memory(row, key, *, threads=False):
    if missing(row, key):
        return '-'
    value = number(row, key)
    if not threads and value < Decimal('0.01'):
        return r'$<0.01$' if value else '0.00'
    places = 3 if threads and value < 1 else (2 if threads or value < 10 else 1)
    return f"{float(value):.{places}f}"


def seconds(row, key):
    if missing(row, key):
        return '-'
    value = number(row, key)
    places = 3 if value < 1 else (2 if value < 10 else 1)
    return format(value, f",.{places}f")


def speed(row, key, *, bold=False):
    if missing(row, key):
        return '-'
    value = str(row.get(key, ''))
    if not value:
        return '--'
    result = f"{float(number(row, key)):.2f}" + r'$\times$'
    return r'\textbf{' + result + '}' if bold else result


def dataset(row, *, short=False, scope=None, gbz=False):
    name = row['dataset']
    value = DISPLAY.get(name, (name, name))[1 if short else 0]
    if gbz and name == HPRC[2]:
        value = 'HPRC v2.1 CHM13 (231 indiv.; GBZ)'
    value = value.replace('_', r'\_').replace('%', r'\%')
    if not short:
        value = r'\textsf{' + value + '}'
    if scope and any(row.get(key) == 'partial' for key in scope):
        value += r'$^\dagger$'
    return value


def graph_type(name):
    return r'\textsf{' + DATASETS[name]['group'] + '}'


def fields(row, keys, formatter=count):
    return [formatter(row, key) for key in keys]


def render_row(label, subtable, row, group_start=True):
    name = row['dataset']
    group = graph_type(name) if group_start else r'\textsf{}'
    if label == 'tab:supervisor-gbz':
        result = [group, dataset(row), duration(row, 'vg_seconds_1'), memory(row, 'vg_gib_1'),
                  duration(row, 'd_seconds_1'), memory(row, 'd_gib_1'),
                  (f"{float(number(row, 'd_read_seconds_1')):.3f}"
                   if row.get('d_read_seconds_1') and not missing(row, 'd_read_seconds_1')
                   else '-' if row.get('_allow_missing') else '--'),
                  speed(row, 'vg_over_d_total_1'),
                  speed(row, 'vg_over_d_subtract_d_read_1')]
    elif label in ('tab:supervisor-gfa', 'tab:app-pangene-perf'):
        result = [group, dataset(row, scope=('d_main_scope',)),
                  duration(row, 'vg_gfa_seconds'), memory(row, 'vg_gfa_gib')]
        if row.get('billi_seconds') == 'failed':
            result.append(r'\multicolumn{2}{c}{Failed}')
        else:
            result.extend([duration(row, 'billi_seconds'), memory(row, 'billi_gib')])
        result.extend([duration(row, 'bf_ultrabubbles_seconds'), memory(row, 'bf_ultrabubbles_gib'),
                       duration(row, 'd_main_seconds'), memory(row, 'd_main_gib')])
    elif label in ('tab:supervisor-comparison', 'tab:app-pangene-comparison'):
        result = [group, dataset(row, scope=('d_main_scope',))]
        result += fields(row, ('d_nontrivial', 'vg_nontrivial', 'common', 'd_only', 'vg_only'))
    elif label in ('tab:supervisor-sizes', 'tab:app-pangene-sizes'):
        result = [dataset(row, scope=('d_main_scope',)), row['length_unit'],
                  count(row, 'nonsnarl_d_nontrivial')]
        if missing(row, 'nonsnarl_d_nontrivial'):
            result += ['-'] * 4
        elif number(row, 'nonsnarl_d_nontrivial') == 0:
            result.append(r'\multicolumn{4}{c}{No qualifying bubbles}')
        else:
            result += fields(row, ('q1', 'median', 'q3', 'maximum'), quartile)
    elif label == 'tab:app-ub-via-d':
        result = [group, dataset(row, scope=('u_via_d_scope',), gbz=True),
                  duration(row, 'u_via_d_seconds'), memory(row, 'u_via_d_gib')]
    elif label in ('tab:threads-main-1-8', 'tab:threads-extra-1-8'):
        result = [dataset(row, short=True, scope=('d_scope_1', 'd_scope_8')), row['format'],
                  seconds(row, 'd_seconds_1'), seconds(row, 'd_seconds_8'), speed(row, 'd_thread_speedup'),
                  seconds(row, 'vg_seconds_1'), seconds(row, 'vg_seconds_8'), speed(row, 'vg_thread_speedup'),
                  speed(row, 'vg_over_d_at_8', bold=True)]
    elif label == 'tab:threads-memory-1-8':
        result = [dataset(row, short=True, scope=('d_scope_1', 'd_scope_8')), row['format']]
        result += [memory(row, key, threads=True) for key in ('d_gib_1', 'd_gib_8', 'vg_gib_1', 'vg_gib_8')]
    elif label == 'tab:app-topology':
        result = [group, dataset(row)]
        keys = (('nodes', 'links', 'components', 'tips') if subtable == 0 else
                ('cut_vertices', 'components_without_tips', 'components_without_cut_vertices',
                 'orientation_conflict_vertices'))
        result += fields(row, keys)
    elif label == 'tab:app-native-counts':
        result = [group, dataset(row, scope=('d_scope_1', 'd_main_scope'))]
        result += fields(row, ('d_all_1', 'd_nontrivial', 'vg_records_all', 'vg_records_nontrivial_native'))
    elif label == 'tab:app-reference-counts':
        result = [group, dataset(row)]
        if subtable == 0:
            result += fields(row, ('vg_ultrabubble_records_all', 'vg_records_all', 'vg_non_ultrabubble_records',
                                   'vg_ultrabubble_records_nontrivial_native'))
        else:
            result += fields(row, ('bf_ultrabubbles_all', 'bf_ultrabubbles_nontrivial'))
            result.append('Failed' if row.get('billi_records') == 'failed' else count(row, 'billi_records'))
    else:
        raise ValueError('Unknown table slot: ' + label)
    return ' & '.join(result) + r' \\'


def render(rows, template, allow_missing=False):
    by_name = {row['dataset']: dict(row, _allow_missing=allow_missing) for row in rows}
    if len(by_name) != len(rows) or not set(by_name) <= set(ALL):
        raise ValueError('Unknown or duplicate dataset in results')
    seen = set()

    def replace(match):
        label, sub = match.group(1), int(match.group(2))
        slot = (label, sub)
        if slot in seen or label not in SLOTS or sub >= len(SLOTS[label]):
            raise ValueError('Invalid table row marker: ' + str(slot))
        seen.add(slot)
        lines = []
        previous = None
        for name in SLOTS[label][sub]:
            if name not in by_name:
                continue
            group = DATASETS[name]['group']
            if previous is not None and group != previous:
                lines.append(r'\midrule')
            lines.append(render_row(label, sub, by_name[name], group_start=group != previous))
            previous = group
        return '\n'.join(lines)

    result = MARKER.sub(replace, template)
    slots = {(label, sub) for label, groups in SLOTS.items() for sub in range(len(groups))}
    if seen != slots or '%% TABLE_ROWS:' in result:
        raise ValueError('Missing table row marker')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tsv', required=True, type=Path)
    parser.add_argument('--template', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--allow-missing', action='store_true')
    args = parser.parse_args()
    with args.tsv.open(newline='') as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    args.output.write_text(render(rows, args.template.read_text(), allow_missing=args.allow_missing))


if __name__ == '__main__':
    main()
