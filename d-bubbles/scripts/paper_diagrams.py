"""Write overlap figures from the set counts."""
import argparse
import csv
import json
from pathlib import Path

from paper_tables import DISPLAY


def read(path):
    counts = {i: 0 for i in range(1, 16)}
    status = None
    with Path(path).open() as stream:
        for row in csv.DictReader(stream, delimiter='\t'):
            bits = sum(int(row[k]) * b for k, b in [('d', 1), ('vg', 2),
                       ('billi', 4), ('ultrabubble', 8)])
            counts[bits] = int(row['pairs'])
            if status is not None and status != row['billi_status']:
                raise ValueError('Inconsistent Billi status')
            status = row['billi_status']
    if status not in ('ok', 'failed'):
        raise ValueError('Missing Billi status')
    return counts, status


def marginals(counts):
    return {i: counts[i] + counts[i | 8] for i in range(1, 8)}


def escape(text):
    return text.replace('_', r'\_').replace('%', r'\%')


def small_figure(name, counts, status, partial=False):
    c = marginals(counts)
    name = escape(DISPLAY.get(name, (name, name))[0])
    if partial:
        name += r'$^\dagger$'
    if status == 'failed':
        both = c[3]
        return (r'\PaperFailedVenn{' + name + '}{' + str(c[1]) + '}{' + str(both) + '}{' + str(c[2]) + '}')
    if c[3] == c[5] == c[4] == 0:
        return r'\HNestedVenn{' + name + '}' + ''.join('{' + str(c[i]) + '}' for i in (1, 2, 6, 7))
    if c[3] == c[5] == 0:
        return r'\HThreeVenn{' + name + '}' + ''.join('{' + str(c[i]) + '}' for i in (1, 2, 3, 5, 6, 4, 7))
    return r'\PaperThreeVenn{' + name + '}' + ''.join('{' + str(c[i]) + '}' for i in (1, 2, 3, 5, 6, 4, 7))


THREE = r'''
\newcommand{\PaperThreeVenn}[8]{%
\begin{minipage}[t]{0.49\linewidth}\centering
\textsf{\textbf{#1}}\par\smallskip
\begin{adjustbox}{max width=\linewidth,max height=40mm}
\begin{tikzpicture}[x=1mm,y=1mm,every node/.style={font=\sffamily\footnotesize,inner sep=1pt}]
\path[use as bounding box] (-54,-24) rectangle (54,20);
\fill[dbcol,opacity=.10] (-16,4) ellipse [x radius=30,y radius=11];
\fill[vgcol,opacity=.10] (16,4) ellipse [x radius=30,y radius=11];
\fill[pancol,opacity=.13] (0,-6.5) ellipse [x radius=30,y radius=11];
\draw[dbcol,line width=.8pt] (-16,4) ellipse [x radius=30,y radius=11];
\draw[vgcol,line width=.8pt] (16,4) ellipse [x radius=30,y radius=11];
\draw[pancol,line width=.8pt] (0,-6.5) ellipse [x radius=30,y radius=11];
\node[text=dbcol] at (-29,18.5) {D-bubbles};
\node[text=vgcol] at (29,18.5) {snarls (vg)};
\node[text=pancol] at (0,-21.5) {Billi panbubbles};
\node at (-34,7) {#2}; \node at (34,7) {#3}; \node at (0,11) {#4};
\node at (-21,-5) {#5}; \node at (21,-5) {#6}; \node at (0,-14.2) {#7}; \node at (0,-1) {#8};
\end{tikzpicture}\end{adjustbox}\end{minipage}%
}
\newcommand{\PaperFailedVenn}[4]{%
\begin{minipage}[t]{0.49\linewidth}\centering\textsf{\textbf{#1}}\par\smallskip
\begin{adjustbox}{max width=\linewidth,max height=40mm}
\begin{tikzpicture}[x=1mm,y=1mm,every node/.style={font=\sffamily\footnotesize,inner sep=1pt}]
\path[use as bounding box] (-54,-24) rectangle (54,20);
\fill[dbcol,opacity=.10] (-16,4) ellipse [x radius=30,y radius=11];
\fill[vgcol,opacity=.10] (16,4) ellipse [x radius=30,y radius=11];
\draw[dbcol,line width=.8pt] (-16,4) ellipse [x radius=30,y radius=11];
\draw[vgcol,line width=.8pt] (16,4) ellipse [x radius=30,y radius=11];
\node[text=dbcol] at (-29,18.5) {D-bubbles}; \node[text=vgcol] at (29,18.5) {snarls (vg)};
\node at (-34,4) {#2}; \node at (0,4) {#3}; \node at (34,4) {#4};
\node[text=pancol] at (0,-16) {Billi run failed};
\end{tikzpicture}\end{adjustbox}\end{minipage}%
}
'''


def current(a):
    datasets = a.dataset
    receipts = {}
    for item in a.coverage_receipt:
        name, separator, path = item.partition('=')
        if not separator or not name or not path or name in receipts:
            raise ValueError('Invalid or repeated dataset coverage record')
        receipts[name] = Path(path)
    if receipts and set(receipts) != set(datasets):
        raise ValueError('Coverage records must match the plotted datasets')
    partial = {}
    for name, path in receipts.items():
        receipt = json.loads(path.read_text())
        scope = receipt['coverage']['status']
        if receipt['execution_status'] != 'ok' or scope not in ('full', 'partial'):
            raise ValueError('Missing d-bubble coverage result for ' + name)
        partial[name] = scope == 'partial'
    groups = [datasets[i:i + 4] for i in range(0, len(datasets), 4)]
    with Path(a.output).open('w') as out:
        out.write('% Requires the paper preamble and its HNestedVenn and HThreeVenn macros.\n' + THREE + '\n')
        for i, group in enumerate(groups):
            if not group:
                continue
            out.write('\\begin{figure}[htbp]\n\\centering\n')
            for j, ds in enumerate(group):
                counts, status = read(a.paper / (ds + '.overlaps.tsv'))
                out.write(small_figure(ds, counts, status, partial.get(ds, False)) + '\n')
                if j+1 < len(group):
                    out.write('\\hfill\n' if j % 2 == 0 else '\\par\\vspace{2mm}\n')
            caption = ('Nontrivial d-bubbles, vg snarls and Billi panbubbles. '
                       'Failed Billi runs are shown separately.')
            if any(partial.get(ds, False) for ds in group):
                caption += (r' $^\dagger$ D-bubble results cover only regions '
                            'on tip-to-tip walks.')
            out.write('\\caption{' + caption + '}\n')
            out.write('\\label{' + 'fig:overlaps-' + str(i + 1) + '}\n\\end{figure}\n\n')


def four_set(a):
    ds = 'hprc-v2.1-mc-chm13'
    if ds not in a.dataset:
        return '% HPRC v2.1 was not selected.\n'
    counts, status = read(a.paper / (ds + '.overlaps.tsv'))
    if status == 'failed':
        return ('\\begin{figure}[htbp]\\centering\n'
                '\\fbox{Billi output unavailable for the four set comparison.}\n'
                '\\caption{HPRC v2.1.}\\end{figure}\n')

    parts = [r'\begin{figure}[htbp]\centering',
             r'\begin{adjustbox}{max width=\linewidth}',
             r'\begin{tikzpicture}[x=1mm,y=1mm,every node/.style={font=\sffamily\small}]']
    if not any(value for bits, value in counts.items() if bits not in (1, 2, 6, 7, 15)):
        parts += [
            r'\fill[vgcol,opacity=.10] (65,20) ellipse [x radius=48,y radius=14.5];',
            r'\fill[dbcol,opacity=.10] (119,20) ellipse [x radius=45,y radius=14.5];',
            r'\fill[pancol,opacity=.10] (67,20) ellipse [x radius=41,y radius=11];',
            r'\fill[white] (92,20) ellipse [x radius=12,y radius=6];',
            r'\draw[vgcol,line width=.8pt] (65,20) ellipse [x radius=48,y radius=14.5];',
            r'\draw[dbcol,line width=.8pt] (119,20) ellipse [x radius=45,y radius=14.5];',
            r'\draw[pancol,line width=.8pt] (67,20) ellipse [x radius=41,y radius=11];',
            r'\draw[ubcol,line width=.8pt] (92,20) ellipse [x radius=12,y radius=6];',
            r'\node[text=vgcol] at (65,37) {Snarls (vg)};',
            r'\node[text=dbcol] at (137,37) {D-bubbles};',
            r'\node[text=pancol] at (42,0) {Billi panbubbles};',
            r'\draw[pancol] (42,2)--(67,9);',
            r'\node[text=ubcol] at (92,0) {Ultrabubbles};',
            r'\draw[ubcol] (92,2)--(92,14);',
        ]
        positions = {1: (145, 20), 2: (22, 20), 6: (51, 20), 7: (87.5, 27.8), 15: (92, 20)}
    else:
        # Four ellipse layout from https://github.com/LankyCyril/pyvenn
        ellipses = [('dbcol', .350, .400, 140), ('vgcol', .450, .500, 140),
                    ('pancol', .544, .500, 40), ('ubcol', .644, .400, 40)]
        for color, x, y, angle in ellipses:
            parts.append(f'\\filldraw[{color},fill opacity=.10,line width=.8pt,shift={{({x*140},{y*140})}},rotate={angle}] '
                         '(0,0) ellipse [x radius=50.4,y radius=31.5];')
        positions = {
            1: (.14, .42), 2: (.32, .72), 3: (.23, .59), 4: (.68, .72),
            5: (.29, .30), 6: (.50, .66), 7: (.35, .50), 8: (.85, .42),
            9: (.50, .17), 10: (.71, .30), 11: (.61, .24), 12: (.77, .59),
            13: (.39, .24), 14: (.65, .50), 15: (.50, .38),
        }
        positions = {bits: (x*140, y*140) for bits, (x, y) in positions.items()}
        parts += [r'\node[text=dbcol] at (14,17) {D-bubbles};',
                  r'\node[text=vgcol] at (34,117) {Snarls (vg)};',
                  r'\node[text=pancol] at (104,117) {Billi panbubbles};',
                  r'\node[text=ubcol] at (124,17) {Ultrabubbles};']
    for bits, (x, y) in positions.items():
        parts.append(f'\\node[fill=white,inner sep=1pt] at ({x},{y}) {{{counts[bits]:,}}};')
    parts += [r'\end{tikzpicture}\end{adjustbox}',
              r'\caption{Nontrivial bubbles in HPRC v2.1. Areas are not proportional to counts.}',
              r'\label{fig:supp-hprc-4set}\end{figure}']
    return '\n'.join(parts) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--paper', required=True, type=Path)
    parser.add_argument('--dataset', action='append', required=True)
    parser.add_argument('--coverage-receipt', action='append', default=[])
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--four-set', required=True, type=Path)
    args = parser.parse_args()
    current(args)
    args.four_set.write_text(four_set(args))


if __name__ == '__main__':
    main()
