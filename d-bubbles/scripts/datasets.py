import csv
from pathlib import Path


with (Path(__file__).resolve().parent.parent / 'config/datasets.tsv').open() as stream:
    DATASETS = {row['dataset']: row for row in csv.DictReader(stream, delimiter='\t')}

GROUPS = ('MC', 'pggb', 'dbg', 'vg', 'Pangene')


def ordered(names):
    return [name for group in GROUPS for name in names if DATASETS[name]['group'] == group]


def length_unit(name):
    return DATASETS.get(name, {}).get('unit', 'bp')
