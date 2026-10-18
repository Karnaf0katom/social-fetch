"""Check release inputs, or refresh their hashes after reviewing a source change."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_paths(root, manifest):
    if manifest.get('schema') != 'social-fetch.source/v1' or not isinstance(manifest.get('files'), dict):
        raise ValueError('Unrecognized source manifest.')
    for name in manifest['files']:
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()) or Path(name).is_absolute():
            raise ValueError('Manifest path is outside the source tree: ' + name)
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or symlinked release input: ' + name)
    actual = {p.relative_to(root).as_posix() for p in (root / 'src').rglob('*.py')}
    recorded = {name for name in manifest['files'] if name.startswith('src/')}
    if actual != recorded:
        raise ValueError('Unexpected or missing Python source. Declare new files explicitly with --refresh --add PATH.')
    if (root / '.env').exists():
        raise ValueError('Environment files are not release inputs.')


def check(root=ROOT):
    root = Path(root)
    manifest = json.loads((root / 'SOURCE-MANIFEST.json').read_text())
    validate_paths(root, manifest)
    for name, expected in manifest['files'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Hash changed: ' + name + '. Review the edit, then run scripts/check_release.py --refresh.')
    return {'schema': manifest['schema'], 'version': manifest['version'],
            'files': len(manifest['files']), 'verified': True}


def refresh(root=ROOT, *, add=()):
    root = Path(root)
    manifest = json.loads((root / 'SOURCE-MANIFEST.json').read_text())
    for name in add:
        manifest['files'][name] = ''
    validate_paths(root, manifest)
    manifest['files'] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                         for name in sorted(manifest['files'])}
    (root / 'SOURCE-MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return {**check(root), 'refreshed': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', help='Record reviewed edits to existing release inputs')
    parser.add_argument('--add', action='append', default=[], metavar='PATH', help='Explicitly include a new file with --refresh')
    args = parser.parse_args()
    if args.add and not args.refresh:
        parser.error('--add requires --refresh')
    try:
        print(json.dumps(refresh(add=args.add) if args.refresh else check()))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, 'Source check failed: ' + str(error) + '\n')
