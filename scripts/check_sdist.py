"""Verify every explicit release input was included unchanged in the built sdist."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def check(path):
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        manifests = [m for m in members if m.isfile() and m.name.endswith('/SOURCE-MANIFEST.json')]
        if len(manifests) != 1:
            raise ValueError('Source archive must contain exactly one release manifest.')
        prefix = manifests[0].name.rsplit('/', 1)[0] + '/'
        for member in members:
            parsed = PurePosixPath(member.name)
            if parsed.is_absolute() or '..' in parsed.parts or not (member.isdir() or member.isfile()):
                raise ValueError('Unexpected source archive entry: ' + member.name)
        manifest = json.load(archive.extractfile(manifests[0]))
        if manifest.get('schema') != 'social-fetch.source/v1':
            raise ValueError('Unrecognized source manifest.')
        for name, expected in manifest['files'].items():
            try:
                member = archive.getmember(prefix + name)
            except KeyError:
                raise ValueError('Source archive omitted release input: ' + name) from None
            if not member.isfile() or hashlib.sha256(archive.extractfile(member).read()).hexdigest() != expected:
                raise ValueError('Source archive input differs from its receipt: ' + name)
        actual = {m.name[len(prefix):] for m in members if m.isfile()
                  and m.name.startswith(prefix + 'src/') and m.name.endswith('.py')}
        expected = {name for name in manifest['files'] if name.startswith('src/')}
        if actual != expected:
            raise ValueError('Unexpected or missing Python source in archive.')
    return {'archive': Path(path).name, 'version': manifest['version'],
            'files': len(manifest['files']), 'verified': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', nargs='*', type=Path)
    args = parser.parse_args()
    archives = args.archives or sorted((ROOT / 'dist').glob('*.tar.gz'))
    if not archives:
        parser.error('Build a source archive first, or provide its path.')
    try:
        for archive in archives:
            print(json.dumps(check(archive)))
    except (OSError, ValueError, KeyError, tarfile.TarError) as error:
        parser.exit(1, 'Source archive check failed: ' + str(error) + '\n')
