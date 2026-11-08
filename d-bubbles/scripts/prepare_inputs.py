import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import socket



def identity(path):
    stat = path.stat()
    return [stat.st_dev, stat.st_ino, stat.st_mode, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def hashes(path):
    before = identity(path)
    sha = hashlib.sha256()
    md5 = hashlib.md5()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            sha.update(block)
            md5.update(block)
    if identity(path) != before:
        raise RuntimeError('Input changed: ' + str(path))
    return dict(path=str(path.resolve()), identity=before, sha256=sha.hexdigest(), md5=md5.hexdigest())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, action='append', required=True)
    parser.add_argument('--ready', type=Path, required=True)
    args = parser.parse_args()
    args.data.mkdir(parents=True, exist_ok=True)
    items = [item for manifest in args.manifest for item in json.loads(manifest.read_text())['items']]
    names = [item['name'].removesuffix('.gz') for item in items]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate input files')

    inputs = []
    for item in items:
        source = Path(item['path'])
        downloaded = hashes(source)
        checksum = item.get('checksum', '').removeprefix('md5:')
        if downloaded['identity'][3] != item['bytes'] or (checksum and downloaded['md5'] != checksum):
            raise ValueError('Download checksum or size differs: ' + str(source))

        name = item['name'].removesuffix('.gz')
        path = args.data / name
        if item['name'].endswith('.gz'):
            if not path.is_file():
                partial = Path(str(path) + '.new')
                try:
                    with gzip.open(source, 'rb') as stream, partial.open('wb') as output:
                        for block in iter(lambda: stream.read(8 << 20), b''):
                            output.write(block)
                    partial.rename(path)
                except Exception:
                    partial.unlink(missing_ok=True)
                    raise
        elif path.resolve() != source.resolve():
            if not path.exists():
                path.symlink_to(source.resolve())
            elif path.resolve() != source.resolve():
                raise FileExistsError('Input path already exists: ' + str(path))

        result = hashes(path) if path.resolve() != source.resolve() else downloaded
        raw_checksum = item.get('raw_checksum', '').removeprefix('md5:')
        if raw_checksum and (result['md5'] != raw_checksum or result['identity'][3] != item['raw_bytes']):
            raise ValueError('GFA differs from the published checksum: ' + str(path))
        inputs.append(dict(name=name, download=downloaded, input=result, source=item))

    report = dict(checks='PASS', inputs=inputs, host=socket.gethostname(),
                  slurm_job=os.environ.get('SLURM_JOB_ID'))
    (args.data / 'INPUT-ADMISSION.json').write_text(json.dumps(report, indent=2) + '\n')
    args.ready.write_text('done\n')


if __name__ == '__main__':
    main()
