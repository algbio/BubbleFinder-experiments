"""Explain output differences using independent native snarl tests."""
import argparse
import csv
import json
import os
from pathlib import Path


def bubbles(path):
    last = None
    with Path(path).open() as stream:
        for row in stream:
            key = row.rstrip('\n')
            if last is not None and key <= last:
                raise ValueError('Bubbles must be sorted without repeats: ' + str(path))
            last = key
            yield key


def difference(left, right):
    it = iter(bubbles(right))
    other = next(it, None)
    for key in bubbles(left):
        while other is not None and other < key:
            other = next(it, None)
        if key != other:
            yield key


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--d', required=True)
    p.add_argument('--vg', required=True)
    p.add_argument('--sizes', required=True)
    p.add_argument('--billi-outside')
    p.add_argument('--billi-status')
    p.add_argument('--output', required=True)
    p.add_argument('--report', required=True)
    a = p.parse_args()
    nonsnarls = {}
    with Path(a.sizes).open() as stream:
        for row in csv.DictReader(stream, delimiter='\t'):
            key = row['x'] + '\t' + row['y']
            if key in nonsnarls or row['reason'] not in ('nonseparable', 'nonminimal'):
                raise ValueError('Duplicate or invalid non-snarl classification')
            nonsnarls[key] = row
    counts = {'d_only': 0, 'nonseparable': 0, 'separable_nonminimal': 0, 'snarl': 0}
    with Path(a.output).open('w') as out:
        out.write('x\ty\tclassification\tphysical_nodes\tknown_length\tunknown_nodes\n')
        for key in difference(a.d, a.vg):
            counts['d_only'] += 1
            row = nonsnarls.get(key)
            if row is None:
                counts['snarl'] += 1
                out.write(key + '\tsnarl\t\t\t\n')
            else:
                category = 'nonseparable' if row['reason'] == 'nonseparable' else 'separable_nonminimal'
                counts[category] += 1
                out.write(key + '\t' + category + '\t' + row['physical_nodes'] + '\t' +
                          row['known_length'] + '\t' + row['unknown_nodes'] + '\n')
    if a.billi_outside:
        if not a.billi_status:
            raise ValueError('Billi status is required with the list missing from vg')
        status = json.loads(Path(a.billi_status).read_text())['status']
        if status == 'failed':
            counts['billi_outside_vg'] = 'failed'
        elif status == 'ok':
            with Path(a.billi_outside).open() as stream:
                outside = list(csv.DictReader(stream, delimiter='\t'))
            wanted = {row['x']+'\t'+row['y'] for row in outside}
            if len(wanted) != len(outside):
                raise ValueError('Repeated Billi bubble in the list missing from vg')
            found = {key for key in bubbles(a.d) if key in wanted}
            counts['billi_outside_vg'] = len(outside)
            counts['billi_outside_vg_snarls'] = sum(row['snarl'] == 'yes' for row in outside)
            counts['billi_outside_vg_also_d'] = len(found)
        else:
            raise ValueError('Unrecognized Billi status')
    Path(a.report).write_text(json.dumps(counts, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
