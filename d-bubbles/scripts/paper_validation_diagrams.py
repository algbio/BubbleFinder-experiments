"""Write available overlaps and mark missing results."""
import argparse
import csv
import json
from pathlib import Path

from paper_tables import ALL, DISPLAY, HPRC


MACROS = r'''
\newcommand{\PaperValidationUnavailable}[3]{%
\begin{minipage}[t]{0.49\linewidth}\centering
\textsf{\textbf{#1}}\par\smallskip
\begin{adjustbox}{max width=\linewidth,max height=40mm}
\begin{tikzpicture}[x=1mm,y=1mm,every node/.style={font=\sffamily\normalsize,inner sep=1pt}]
\path[use as bounding box] (0,0) rectangle (108,30);
\draw[black!35,dashed,rounded corners=2pt] (14,1) rectangle (94,29);
\node[text=black!80] at (54,24) {D-bubbles: #2};
\node[text=black!80] at (54,15) {vg overlap: $-$};
\node[text=black!80] at (54,6) {Billi overlap: #3};
\end{tikzpicture}\end{adjustbox}\end{minipage}%
}
\newcommand{\PaperValidationKnown}[5]{%
\begin{minipage}[t]{0.49\linewidth}\centering
\textsf{\textbf{#1}}\par\smallskip
\begin{adjustbox}{max width=\linewidth,max height=40mm}
\begin{tikzpicture}[x=1mm,y=1mm,every node/.style={font=\sffamily\normalsize,inner sep=1pt}]
\path[use as bounding box] (-54,-24) rectangle (54,20);
\fill[dbcol,opacity=.10] (-16,4) ellipse [x radius=30,y radius=11];
\fill[vgcol,opacity=.10] (16,4) ellipse [x radius=30,y radius=11];
\draw[dbcol,line width=.8pt] (-16,4) ellipse [x radius=30,y radius=11];
\draw[vgcol,line width=.8pt] (16,4) ellipse [x radius=30,y radius=11];
\node[text=dbcol] at (-29,18.5) {D-bubbles};
\node[text=vgcol] at (29,18.5) {snarls (vg)};
\node at (-34,4) {#2}; \node at (0,4) {#3}; \node at (34,4) {#4};
\node[text=pancol] at (0,-16) {Billi overlap: #5};
\end{tikzpicture}\end{adjustbox}\end{minipage}%
}
\newcommand{\PaperValidationThree}[8]{%
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
'''


def name_for(row):
    name = DISPLAY.get(row['dataset'], (row['dataset'], row['dataset']))[0]
    name = name.replace('_', r'\_').replace('%', r'\%')
    if row.get('d_main_scope') == 'partial':
        name += r'$^\dagger$'
    return name


def count(row, key):
    value = row.get(key, '')
    if not value.isdigit():
        raise ValueError('Invalid ' + key + ' for ' + row['dataset'])
    return int(value)


def panel(row, check=None):
    name = name_for(row)
    total = count(row, 'd_nontrivial')
    overlap = (check or {}).get('billi_overlap')
    if overlap:
        atoms = overlap.get('atoms')
        if (overlap.get('status') != 'reused_verified' or not isinstance(atoms, dict) or
                set(atoms) != {str(i) for i in range(1, 8)} or
                not all(isinstance(value, int) and value >= 0 for value in atoms.values())):
            raise ValueError('Invalid prior Billi overlap for ' + row['dataset'])
        if (sum(atoms[str(i)] for i in (1, 3, 5, 7)) != total or
                sum(atoms[str(i)] for i in (2, 3, 6, 7)) != count(row, 'vg_nontrivial') or
                sum(atoms[str(i)] for i in (3, 7)) != count(row, 'common')):
            raise ValueError('Prior Billi overlap disagrees with vg comparison for ' + row['dataset'])
        return (r'\PaperValidationThree{' + name + '}' +
                ''.join('{' + f'{atoms[str(i)]:,}' + '}' for i in (1, 2, 3, 5, 6, 4, 7)))
    billi = 'Failed' if row.get('billi_seconds') == 'failed' else '$-$'
    keys = ('d_only', 'common', 'vg_only', 'vg_nontrivial')
    values = [row.get(key, '') for key in keys]
    if all(value == '-' for value in values):
        return r'\PaperValidationUnavailable{' + name + '}{' + f'{total:,}' + '}{' + billi + '}'
    if not all(value.isdigit() for value in values):
        raise ValueError('Incomplete vg comparison for ' + row['dataset'])
    d_only, common, vg_only, vg_total = map(int, values)
    if d_only + common != total or vg_only + common != vg_total:
        raise ValueError('Inconsistent vg comparison for ' + row['dataset'])
    return (r'\PaperValidationKnown{' + name + '}' +
            ''.join('{' + f'{value:,}' + '}' for value in (d_only, common, vg_only)) +
            '{' + billi + '}')


def render(rows, verification=None):
    by_name = {row['dataset']: row for row in rows}
    if len(by_name) != len(rows):
        raise ValueError('Duplicate dataset in results')
    checks = {row['dataset']: row for row in verification['rows']} if verification else {}
    names = list(by_name)
    groups = [names[i:i + 4] for i in range(0, len(names), 4)]
    parts = ['% Validation only: $-$ means an unavailable overlap.\n', MACROS]
    for number, group in enumerate(groups, 1):
        label = 'fig:overlaps-' + str(number)
        parts.append('\n\\begin{figure}[htbp]\n\\centering\n')
        for index, dataset in enumerate(group):
            parts.append(panel(by_name[dataset], checks.get(dataset)) + '\n')
            if index + 1 < len(group):
                parts.append('\\hfill\n' if index % 2 == 0 else '\\par\\vspace{2mm}\n')
        caption = 'D-bubbles and available overlaps. A dash means a result is missing.'
        if any(by_name[dataset].get('d_main_scope') == 'partial' for dataset in group):
            caption += r' $^\dagger$ D-bubble results cover only regions on tip-to-tip walks.'
        parts.append('\\caption{' + caption + '}\n\\label{' + label + '}\n\\end{figure}\n')
    return ''.join(parts)


def render_four_set(rows):
    row = next((row for row in rows if row['dataset'] == 'hprc-v2.1-mc-chm13'), None)
    if row is None:
        return '% HPRC v2.1 was not selected.\n'
    d = count(row, 'd_nontrivial')
    u = count(row, 'bf_ultrabubbles_nontrivial')
    return (r'''% Validation only: the four-way overlap was not computed.
\begin{figure}[htbp]
\centering
\fbox{\parbox{0.78\linewidth}{\centering
\textbf{HPRC v2.1: four-way comparison}\\[2mm]
Nontrivial d-bubbles: ''' + f'{d:,}' + r'''\\
Nontrivial ultrabubbles: ''' + f'{u:,}' + r'''\\
Overlap with vg and Billi: $-$}}
\caption{Validation only: the four-way overlap is unavailable without the comparator outputs.}
\label{fig:supp-hprc-4set}
\end{figure}
''')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--overlaps', required=True, type=Path)
    parser.add_argument('--four-set', required=True, type=Path)
    args = parser.parse_args()
    with args.results.open(newline='') as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    verification = json.loads(args.report.read_text()) if args.report else None
    overlaps = render(rows, verification)
    four_set = render_four_set(rows)
    args.overlaps.parent.mkdir(parents=True, exist_ok=True)
    args.four_set.parent.mkdir(parents=True, exist_ok=True)
    args.overlaps.write_text(overlaps)
    args.four_set.write_text(four_set)


if __name__ == '__main__':
    main()
