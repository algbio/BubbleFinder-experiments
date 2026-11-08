import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.request



HPRC = {
    'hprc-v1.1-mc-chm13':
        'https://s3-us-west-2.amazonaws.com/human-pangenomics/pangenomes/freeze/freeze1/minigraph-cactus/hprc-v1.1-mc-chm13/hprc-v1.1-mc-chm13',
    'hprc-v2.0-mc-chm13':
        'https://s3-us-west-2.amazonaws.com/human-pangenomics/pangenomes/scratch/2025_02_28_minigraph_cactus/hprc-v2.0-mc-chm13/hprc-v2.0-mc-chm13',
    'hprc-v2.1-mc-chm13':
        'https://s3-us-west-2.amazonaws.com/human-pangenomics/pangenomes/freeze/release2/minigraph-cactus/v2.1/hprc-v2.1-mc-chm13/hprc-v2.1-mc-chm13',
}

HPRC_FALLBACK = {
    'hprc-v2.0-mc-chm13':
        'https://s3-us-west-2.amazonaws.com/human-pangenomics/pangenomes/freeze/release2/minigraph-cactus/v2.0/hprc-v2.0-mc-chm13/hprc-v2.0-mc-chm13',
}


def hprc_file(dataset, suffix):
    url = HPRC[dataset] + suffix
    try:
        response = urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=60)
    except urllib.error.HTTPError as error:
        if error.code != 404 or dataset not in HPRC_FALLBACK:
            raise
        url = HPRC_FALLBACK[dataset] + suffix
        response = urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=60)
    with response:
        return url, int(response.headers['Content-Length'])


def existing(directories, dataset, extension):
    for directory in directories:
        path = directory / (dataset + extension)
        if path.is_file():
            return path.resolve()
    return None


def fetch(item):
    path = Path(item['path'])
    if item.get('existing'):
        return
    if path.is_file() and path.stat().st_size == item['bytes']:
        return
    if path.exists():
        raise FileExistsError('Wrong file size: ' + str(path))

    partial = Path(str(path) + '.partial')
    subprocess.run(['curl', '-fL', '--retry', '3', '-C', '-', '-o', str(partial), item['url']], check=True)
    if partial.stat().st_size != item['bytes']:
        raise RuntimeError('Incomplete download: ' + str(path))
    partial.rename(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['zenodo', 'hprc'])
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--directory', type=Path, action='append', default=[])
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--stamp', type=Path, required=True)
    parser.add_argument('--dataset', action='append', default=[])
    parser.add_argument('--record', default='19209715')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--gbz', action='store_true')
    args = parser.parse_args()
    if args.jobs < 1 or any(not re.fullmatch('[A-Za-z0-9_.-]+', ds) for ds in args.dataset):
        raise ValueError('Invalid dataset name or download job count')

    args.data.mkdir(parents=True, exist_ok=True)
    directories = [args.data, *args.directory]
    files = None
    items = []
    for ds in args.dataset:
        if (ds in HPRC) != (args.mode == 'hprc'):
            continue
        extensions = ['.gfa', '.gbz'] if ds in HPRC and args.gbz else ['.gfa']
        for extension in extensions:
            raw = existing(directories, ds, extension)
            path = raw or existing(directories, ds, extension + '.gz')
            if path:
                suffix = extension if raw else extension + '.gz'
                items.append(dict(name=ds + suffix, path=str(path), bytes=path.stat().st_size, existing=True))
                continue

            if ds in HPRC:
                suffix = '.gfa.gz' if extension == '.gfa' else extension
                url, size = hprc_file(ds, suffix)
                item = dict(name=ds + suffix, url=url, bytes=size)
            else:
                if files is None:
                    with urllib.request.urlopen('https://zenodo.org/api/records/' + args.record, timeout=60) as response:
                        files = {row['key']: row for row in json.load(response)['files']}
                source = ds + '.gfa'
                suffix = '.gfa.gz' if source + '.gz' in files else '.gfa'
                row = files[ds + suffix]
                raw = files[source]
                url = 'https://zenodo.org/records/' + args.record + '/files/' + ds + suffix + '?download=1'
                item = dict(name=ds + suffix, url=url, bytes=row['size'],
                            checksum=row['checksum'], raw_checksum=raw['checksum'], raw_bytes=raw['size'])
            item['path'] = str((args.data / item['name']).resolve())
            items.append(item)

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(fetch, items))
    args.manifest.write_text(json.dumps({'items': items}, indent=2) + '\n')
    args.stamp.write_text('done\n')


if __name__ == '__main__':
    main()
