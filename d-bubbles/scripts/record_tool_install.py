#!/usr/bin/env python3
"""Record the source version and executable hash after a build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", choices=["billi"], required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args()
    receipt = dict(schema=1, tool=args.tool, commit=args.commit,
                   executable_sha256=hashlib.sha256(args.executable.read_bytes()).hexdigest(), files={})
    target = Path(str(args.executable) + ".toolchain-install.json")
    with target.open("x", encoding="ascii") as output:
        json.dump(receipt, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
