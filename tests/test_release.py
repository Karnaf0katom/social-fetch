"""Exercise the installed public interface outside the source checkout."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from social_fetch import Client, __version__

ROOT = Path(__file__).resolve().parents[1]


def test_every_internal_import_has_an_installed_owner():
    import social_fetch
    package = Path(social_fetch.__file__).parent
    for path in package.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            targets = []
            if isinstance(node, ast.ImportFrom):
                module = (importlib.util.resolve_name('.' * node.level + (node.module or ''), 'social_fetch')
                          if node.level else node.module or '')
                if module.startswith('social_fetch.'):
                    targets.append(module)
            elif isinstance(node, ast.Import):
                targets.extend(alias.name for alias in node.names if alias.name.startswith('social_fetch.'))
            for target in targets:
                assert importlib.util.find_spec(target) is not None, f'{path.name}:{node.lineno}: {target}'


def test_default_search_factory_needs_no_private_application_catalog(monkeypatch):
    from social_fetch.web_search import FootageSearch
    monkeypatch.setenv('FOOTAGE_SEARCH_PROVIDER', 'public')
    for name in ('BRAVE_SEARCH_API_KEY', 'BRAVE_API_KEY', 'SERPER_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    search = FootageSearch.from_env()
    assert search.index.name == 'public'
    with pytest.raises(ValueError, match='outside'):
        FootageSearch.from_env(include_catalogs=True)


def test_unsupported_native_search_fails_without_a_missing_module():
    from social_fetch.web_search import FootageSearch, PublicIndex
    search = FootageSearch(PublicIndex())
    for source in ('all', 'smart'):
        with pytest.raises(ValueError, match='outside'):
            search.search('space launch', source=source)


def checker():
    spec = importlib.util.spec_from_file_location('check_release', ROOT / 'scripts/check_release.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    return check


def test_public_source_matches_its_manifest():
    assert checker().check()['version'] == __version__


def source_fixture(root):
    path = root / 'src/social_fetch/__init__.py'
    path.parent.mkdir(parents=True)
    path.write_text('original = True\n')
    (root / 'SOURCE-MANIFEST.json').write_text(json.dumps({
        'schema': 'social-fetch.source/v1', 'version': __version__,
        'files': {'src/social_fetch/__init__.py': hashlib.sha256(path.read_bytes()).hexdigest()},
    }))
    return path


def test_contributor_can_refresh_a_reviewed_change_and_verify_it(tmp_path):
    path = source_fixture(tmp_path)
    check = checker()
    assert check.check(tmp_path)['verified']
    path.write_text('reviewed_change = True\n')
    with pytest.raises(ValueError, match='Hash changed'):
        check.check(tmp_path)
    assert check.refresh(tmp_path)['refreshed']
    assert check.check(tmp_path)['verified']


def test_new_source_needs_explicit_declaration_before_refresh(tmp_path):
    source_fixture(tmp_path)
    new = tmp_path / 'src/social_fetch/new.py'
    new.write_text('new_module = True\n')
    check = checker()
    with pytest.raises(ValueError, match='Declare new files explicitly'):
        check.refresh(tmp_path)
    assert check.refresh(tmp_path, add=['src/social_fetch/new.py'])['files'] == 2


def isolated_cli(directory, *args):
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL') if key in os.environ}
    env['HOME'] = str(directory)
    return subprocess.run([sys.executable, '-m', 'social_fetch', *map(str, args)], cwd=directory,
                          env=env, capture_output=True, text=True, timeout=20)


def test_installed_cli_doctor_needs_no_source_path_or_provider_credentials(tmp_path):
    result = isolated_cli(tmp_path, 'doctor')
    assert result.returncode in (0, 1), result.stderr
    data = json.loads(result.stdout)
    assert data['network_checked'] is False
    assert set(data['checks']) == {'ffmpeg', 'ffprobe', 'ddgs', 'yt_dlp'}


def test_installed_cli_reconnects_exports_and_refuses_overwrite_in_another_process(tmp_path):
    data_dir = tmp_path / 'jobs'
    client = Client(data_dir, namespace='release-test')
    job_id, video_id = 'c' * 24, 'VQRLujxTm3c'
    folder = client.jobs.folder(client.namespace, job_id)
    folder.mkdir(parents=True)
    raw = b'test-media-for-cross-process-integrity-check'
    (folder / (video_id + '.mp4')).write_bytes(raw)
    (folder / 'job.json').write_text(json.dumps({
        'id': job_id, 'video_id': video_id, 'source_url': 'https://www.youtube.com/watch?v=' + video_id,
        'platform': 'youtube', 'status': 'ready', 'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(), 'updated_at': time.time(),
    }))
    prefix = ['--data-dir', data_dir]
    status = isolated_cli(tmp_path, *prefix, 'status', job_id, '--namespace', 'release-test')
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)['sha256'] == hashlib.sha256(raw).hexdigest()
    out = tmp_path / 'clip.mp4'
    args = [*prefix, 'export', job_id, '--namespace', 'release-test', '--out', out]
    exported = isolated_cli(tmp_path, *args)
    assert exported.returncode == 0, exported.stderr
    assert out.read_bytes() == raw
    assert isolated_cli(tmp_path, *args).returncode == 1
    wrong = isolated_cli(tmp_path, *prefix, 'status', job_id, '--namespace', 'other')
    assert wrong.returncode == 1
