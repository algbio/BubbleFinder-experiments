"""Bind measurements to the campaign's locked external toolchain."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil


EXTERNAL_TOOLS = {'vg', 'billi', 'bubblegun'}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load_lock(path):
    path = Path(path)
    lock = json.loads(path.read_text())
    if not isinstance(lock.get('tools'), dict):
        raise RuntimeError('Tool settings file must list the tools')
    return lock, digest(path)


def commit(pin):
    return pin.get('commit') or pin.get('commit_sha') or pin.get('peeled_commit_sha')


def verify_install(tool, executable, pin):
    """Check the build record before running the command."""
    actual = digest(executable)
    if tool == 'vg' and actual != pin.get('asset_sha256'):
        raise RuntimeError('vg executable differs from the selected version')
    receipt = None
    if tool in {'billi', 'bubblegun'}:
        path = Path(str(executable) + '.toolchain-install.json')
        receipt = json.loads(path.read_text())
        if receipt.get('tool') != tool or receipt.get('commit') != commit(pin):
            raise RuntimeError('Installed tool commit differs from the selected commit')
        if receipt.get('executable_sha256') != actual:
            raise RuntimeError('Executable differs from its build record')
        files = receipt.get('files', {})
        if not isinstance(files, dict):
            raise RuntimeError('Invalid list of installed files')
        if tool == 'bubblegun' and not any(name.endswith('.py') for name in files):
            raise RuntimeError('BubbleGun build record must list its Python files')
        for name, expected in files.items():
            if Path(name).is_absolute() or digest(executable.parent / name) != expected:
                raise RuntimeError('Installed file differs from its build record: ' + name)
    return actual, receipt


def prepare(time_path, command):
    lock_path = os.environ.get('BENCH_TOOLCHAIN_LOCK') or os.environ.get('TOOLCHAIN_LOCK_FILE')
    if not lock_path:
        raise RuntimeError('Set BENCH_TOOLCHAIN_LOCK to the tool settings file')
    lock, lock_sha = load_lock(lock_path)
    argv = shlex.split(command)
    if not argv:
        raise RuntimeError('Empty benchmark command')
    executable_name = os.environ.get('BENCH_TOOLCHAIN_EXE') or argv[0]
    located = shutil.which(executable_name)
    if not located:
        raise RuntimeError('Cannot locate benchmark executable: ' + executable_name)
    # The build record sits next to the launcher, even when it is a symlink.
    executable = Path(located).absolute()
    command_executable = shutil.which(argv[0])
    if not command_executable or Path(command_executable).resolve() != executable.resolve():
        raise RuntimeError('Recorded executable differs from the benchmark command')
    tool = os.environ.get('BENCH_TOOLCHAIN_TOOL') or executable.name.lower()
    pin = lock['tools'].get(tool, {})
    if tool in EXTERNAL_TOOLS and not pin:
        raise RuntimeError('Tool is missing from the settings file: ' + tool)
    actual, install = verify_install(tool, executable, pin)
    graph_sha = os.environ.get('BENCH_GRAPH_SHA256')
    if graph_sha is not None and not re.fullmatch(r'[0-9a-f]{64}', graph_sha):
        raise RuntimeError('Invalid graph checksum in input record')
    out = Path(str(time_path) + '.toolchain.pending.json')
    if Path(str(time_path) + '.toolchain.json').exists():
        raise RuntimeError('Run record already exists. Use a new result directory')
    record = dict(schema=1, state='prepared', toolchain_sha256=lock_sha,
                  tool=tool, tool_pin=pin, executable=str(executable),
                  executable_sha256=actual, install_receipt=install,
                  graph_sha256=graph_sha, command=command,
                  started_utc=datetime.now(timezone.utc).isoformat())
    with out.open('x') as f:
        json.dump(record, f, indent=2)
        f.write('\n')


def finish(time_path, exit_code):
    pending = Path(str(time_path) + '.toolchain.pending.json')
    record = json.loads(pending.read_text())
    actual, install = verify_install(record['tool'], Path(record['executable']), record['tool_pin'])
    if record['executable_sha256'] != actual or record['install_receipt'] != install:
        raise RuntimeError('Tool files changed during the run')
    lock_path = os.environ.get('BENCH_TOOLCHAIN_LOCK') or os.environ.get('TOOLCHAIN_LOCK_FILE')
    _, lock_sha = load_lock(lock_path)
    if lock_sha != record['toolchain_sha256']:
        raise RuntimeError('Tool settings file changed during the run')
    record.update(state='finished', exit_code=int(exit_code), time_sha256=digest(time_path),
                  finished_utc=datetime.now(timezone.utc).isoformat())
    with Path(str(time_path) + '.toolchain.json').open('x') as f:
        json.dump(record, f, indent=2)
        f.write('\n')
    pending.unlink()


def check_command(record, tool, operation, threads, include_trivial):
    command = record.get('command')
    if not isinstance(command, str):
        raise RuntimeError('Measurement has no recorded command')
    try:
        args = shlex.split(command)
    except ValueError as error:
        raise RuntimeError('Invalid recorded benchmark command') from error
    if len(args) < 2 or args[1] != operation:
        raise RuntimeError('Measurement used a different command: ' + str(operation))
    if include_trivial is not None and (('-T' in args) != include_trivial):
        raise RuntimeError('Measurement used a different triviality option')
    if threads is not None:
        flag = '-t' if tool == 'vg' else '-j'
        if (args.count(flag) != 1 or args.index(flag) + 1 == len(args) or
                args[args.index(flag) + 1] != str(threads)):
            raise RuntimeError('Measurement used a different thread count')
    if tool == 'vg':
        if (args.count('-A') != 1 or args.index('-A') + 1 == len(args) or
                args[args.index('-A') + 1] != 'integrated'):
            raise RuntimeError('Measurement used a different vg algorithm')
    if tool == 'billi' and '-w' not in args:
        raise RuntimeError('Measurement used a different Billi mode')


def check_measurement(time_path, tool, lock, lock_sha, artifacts=(),
                      expected_binary_sha256=None, expected_graph_sha256=None,
                      expected_operation=None, expected_threads=None,
                      expected_include_trivial=None):
    """Check archived records without requiring their former tmpfs paths."""
    time_path = Path(time_path)
    if not time_path.exists():
        if any(Path(p).exists() for p in artifacts):
            raise RuntimeError('Tool output has no matching run record: ' + str(time_path))
        return False
    path = Path(str(time_path) + '.toolchain.json')
    if not path.exists():
        raise RuntimeError('Old tool run has no recorded settings: ' + str(time_path))
    record = json.loads(path.read_text())
    pin = lock['tools'].get(tool, {})
    if tool != 'bubblefinder' and not pin:
        raise RuntimeError('Tool is missing from the current settings: ' + tool)
    if (record.get('schema') != 1 or record.get('state') != 'finished'
            or record.get('toolchain_sha256') != lock_sha or record.get('tool') != tool
            or record.get('tool_pin') != pin or record.get('time_sha256') != digest(time_path)):
        raise RuntimeError('Tool run differs from the current settings: ' + str(time_path))
    actual = record.get('executable_sha256')
    if expected_graph_sha256 is not None and record.get('graph_sha256') != expected_graph_sha256:
        raise RuntimeError('Run used a different checked graph: ' + str(time_path))
    if tool == 'bubblefinder' and (not expected_binary_sha256 or actual != expected_binary_sha256):
        raise RuntimeError('Recorded BubbleFinder executable differs from the d-bubble run')
    if tool == 'vg' and actual != pin.get('asset_sha256'):
        raise RuntimeError('Recorded vg executable differs from the locked release')
    if tool in {'billi', 'bubblegun'}:
        install = record.get('install_receipt') or {}
        if (install.get('tool') != tool or install.get('commit') != commit(pin)
                or install.get('executable_sha256') != actual):
            raise RuntimeError('Build record differs from the selected version')
        if tool == 'bubblegun' and not any(name.endswith('.py') for name in install.get('files', {})):
            raise RuntimeError('BubbleGun files have no recorded checksums')
    if expected_operation is not None:
        check_command(record, tool, expected_operation, expected_threads,
                      expected_include_trivial)
    failed = time_path.read_text().startswith('EXIT_CODE=')
    if failed != (record.get('exit_code') != 0):
        raise RuntimeError('Tool exit code differs from its run record')
    if failed:
        for item in artifacts:
            path = Path(item)
            if not path.exists():
                continue
            if path.suffix == '.counts' and path.read_text().strip() == 'status\tfailed':
                continue
            raise RuntimeError('Failed tool run still has a bubble file: ' + str(time_path))
    return not failed


def check_results(results, lock_path):
    lock, lock_sha = load_lock(lock_path)
    results = Path(results)
    # Also check count files that have no timing file.
    suffixes = ('.time', '.snarl_counts', '.pairs', '.counts')
    seen = set()
    pattern = re.compile(r'(.+)\.(vg_gfa(?:_noT)?\.[^.]+|vg_gbz(?:_noT)?|billi|bubblegun)$')
    for path in results.iterdir():
        for suffix in suffixes:
            if not path.name.endswith(suffix):
                continue
            stem = path.name[:-len(suffix)]
            match = pattern.fullmatch(stem)
            if not match or stem in seen:
                continue
            seen.add(stem)
            variant = match.group(2)
            tool = 'vg' if variant.startswith('vg_') else variant
            prefix = results / stem
            artifacts = [Path(str(prefix) + s) for s in ('.snarl_counts', '.pairs', '.counts')]
            check_measurement(Path(str(prefix) + '.time'), tool, lock, lock_sha, artifacts)
    return lock, lock_sha


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action', required=True)
    pre = sub.add_parser('prepare'); pre.add_argument('time', type=Path); pre.add_argument('command')
    end = sub.add_parser('finish'); end.add_argument('time', type=Path); end.add_argument('exit_code', type=int)
    check = sub.add_parser('check-results'); check.add_argument('--results', type=Path, required=True); check.add_argument('--lock', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.time, args.command)
    elif args.action == 'finish': finish(args.time, args.exit_code)
    else: check_results(args.results, args.lock)


if __name__ == '__main__':
    main()
