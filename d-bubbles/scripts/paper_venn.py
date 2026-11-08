"""Stream exact intersections of sorted, nontrivial signed-boundary sets."""
import argparse
import heapq
import json
import os
from pathlib import Path


def bubbles(path):
    previous = None
    with Path(path).open(encoding='utf-8') as stream:
        for row in stream:
            if row.startswith('#') or row == 'x\ty\n':
                continue
            fields = row.rstrip('\n').split('\t')
            if len(fields) != 2 or fields[0] >= fields[1]:
                raise ValueError('Malformed bubble in ' + str(path))
            key = row.rstrip('\n')
            if previous is not None and key <= previous:
                raise ValueError('Bubbles must be sorted without repeats: ' + str(path))
            previous = key
            yield key


def tagged_bubbles(path, bit):
    for key in bubbles(path):
        yield key, bit


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--d', required=True)
    p.add_argument('--vg', required=True)
    p.add_argument('--vg-ultrabubbles', required=True)
    p.add_argument('--billi', required=True)
    p.add_argument('--billi-status', required=True)
    p.add_argument('--physical-summary', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    billi_status = json.loads(Path(args.billi_status).read_text())['status']
    if billi_status not in ('ok', 'failed'):
        raise ValueError('Unrecognized Billi status')
    sources = [(args.d, 1), (args.vg, 2), (args.vg_ultrabubbles, 8)]
    if billi_status == 'ok':
        sources.append((args.billi, 4))
    streams = [tagged_bubbles(path, bit) for path, bit in sources]
    counts = [0] * 16
    last = None
    mask = 0

    def record(bits):
        # Keep ultrabubbles also listed in the filtered vg file.
        if bits & 8 and not bits & 2:
            bits &= ~8
        if bits:
            counts[bits] += 1

    for key, bit in heapq.merge(*streams):
        if key != last:
            if last is not None:
                record(mask)
            last, mask = key, bit
        else:
            mask |= bit
    if last is not None:
        record(mask)
    summary = {}
    with Path(args.physical_summary).open() as stream:
        next(stream)
        for line in stream:
            key, value = line.rstrip('\n').split('\t')
            summary[key] = int(value)
    d = sum(n for bits, n in enumerate(counts) if bits & 1)
    vg = sum(n for bits, n in enumerate(counts) if bits & 2)
    both = sum(n for bits, n in enumerate(counts) if bits & 3 == 3)
    if (d, vg, both) != (summary['nontrivial_d'], summary['nontrivial_vg'],
                         summary['nontrivial_common']):
        raise RuntimeError('Bubble file overlaps differ from the graph comparison')
    with Path(args.output).open('w') as out:
        out.write('d\tvg\tbilli\tultrabubble\tpairs\tbilli_status\n')
        for bits in range(1, 16):
            if billi_status == 'failed' and bits & 4:
                continue
            out.write('\t'.join(str(int(bool(bits & bit))) for bit in (1, 2, 4, 8)))
            out.write('\t%d\t%s\n' % (counts[bits], billi_status))


if __name__ == '__main__':
    main()
