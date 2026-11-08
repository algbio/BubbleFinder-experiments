#!/usr/bin/env python3
"""Read the tab-separated BB/HP output of Billi v1.2."""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--counts", type=Path, required=True)
    args = parser.parse_args()
    panbubbles = hairpins = 0
    with args.input.open(encoding="utf-8") as stream, args.rows.open("x", encoding="utf-8") as output:
        for line in stream:
            fields = line.rstrip("\n").split("\t")
            if fields[0] not in ("BB", "HP"):
                continue
            if len(fields) < (7 if fields[0] == "BB" else 5):
                raise ValueError("Malformed Billi " + fields[0] + " row")
            if fields[0] == "BB":
                panbubbles += 1
            else:
                hairpins += 1
            output.write(line)
    with args.counts.open("x", encoding="ascii") as output:
        output.write("n_panbubbles\t" + str(panbubbles) + "\nn_hairpins\t" + str(hairpins) + "\n")


if __name__ == "__main__":
    main()
