"""Check the explicit public source manifest without network access."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    root = Path(root)
    manifest = json.loads((root / 'SOURCE-MANIFEST.json').read_text())
    assert manifest['schema'] == 'social-fetch.source/v1'
    for name, expected in manifest['files'].items():
        path = root / name
        assert not path.is_symlink() and path.is_file(), name
        assert path.resolve().is_relative_to(root.resolve()), name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
    actual = {p.relative_to(root).as_posix() for p in (root / 'src').rglob('*.py')}
    recorded = {name for name in manifest['files'] if name.startswith('src/')}
    assert actual == recorded, 'Unexpected or missing Python package source'
    assert not (root / '.env').exists(), 'Environment files are not release inputs'
    return {'schema': manifest['schema'], 'version': manifest['version'],
            'files': len(manifest['files']), 'verified': True}


if __name__ == '__main__':
    print(json.dumps(check()))
