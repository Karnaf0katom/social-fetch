"""Standalone data placement, observation, and receipt-checked export boundaries."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from social_fetch.client import Client, data_directory
from social_fetch.download_jobs import save
from social_fetch.social_cli import main

URL = 'https://www.youtube.com/watch?v=VQRLujxTm3c'


def ready_client(tmp_path, monkeypatch):
    monkeypatch.setattr('social_fetch.download_jobs.shutil.disk_usage', lambda _: SimpleNamespace(free=64 * 1024**3))
    monkeypatch.setattr('social_fetch.download_jobs.subprocess.Popen', lambda *a, **k: SimpleNamespace(pid=os.getpid()))
    client = Client(tmp_path / 'data')
    job = client.download(URL)
    folder = client.jobs.folder(client.namespace, job['id'])
    raw = b'test media bytes'
    (folder / 'VQRLujxTm3c.mp4').write_bytes(raw)
    private = json.loads((folder / 'job.json').read_text())
    save(folder / 'job.json', {**private, 'status': 'ready', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    return client, job, folder


def test_default_data_is_under_user_storage_and_never_the_installed_package(tmp_path, monkeypatch):
    for name in ('SOCIAL_FETCH_DATA_DIR', 'FOOTAGE_DOWNLOAD_ROOT', 'XDG_DATA_HOME'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    assert data_directory() == tmp_path / '.local/share/social-fetch'
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'xdg'))
    assert data_directory() == tmp_path / 'xdg/social-fetch'
    monkeypatch.setenv('SOCIAL_FETCH_DATA_DIR', str(tmp_path / 'custom'))
    assert Client().jobs.root == tmp_path / 'custom'


def test_standalone_search_does_not_load_visual_catalogs_or_require_them(monkeypatch, tmp_path):
    from social_fetch.web_search import FootageSearch
    calls = []
    class Search:
        def search(self, query, **kwargs):
            return {'query': query, **kwargs}
    monkeypatch.setattr(FootageSearch, 'from_env', lambda **kw: calls.append(kw) or Search())
    client = Client(tmp_path)
    assert client.search('space', source='youtube')['source'] == 'youtube'
    assert client.search('space', accounts=True)['intent'] == 'accounts'
    assert calls == [{'include_catalogs': False}]
    with pytest.raises(ValueError):
        client.search('space', source='archive')


def test_account_cli_never_exports_private_player_thumbnail_routes(tmp_path, monkeypatch):
    monkeypatch.setattr('social_fetch.instagram_web.discover_profile', lambda *a, **kw: ([{
        'source_url': 'https://www.instagram.com/p/ABCDE12345/', 'caption': 'Rocket',
        'poster_url': 'https://instacdn.beubagah.com/secret', 'media_url': 'https://instacdn.beubagah.com/secret',
        'collection': 'private-ticket'}], {}))
    result = Client(tmp_path, namespace='standalone-test').account('https://www.instagram.com/standalone_test/')
    assert len(result['results']) == 1
    assert 'secret' not in json.dumps(result) and '/v1/social_fetch/' not in json.dumps(result)


def test_export_rehashes_same_size_corruption_and_refuses_to_overwrite(tmp_path, monkeypatch):
    client, job, folder = ready_client(tmp_path, monkeypatch)
    output = tmp_path / 'clip.mp4'
    assert client.export(job['id'], output)['exported_to'] == str(output)
    with pytest.raises(ValueError, match='already exists'):
        client.export(job['id'], output)
    source = folder / 'VQRLujxTm3c.mp4'
    source.write_bytes(b'x' * source.stat().st_size)
    with pytest.raises(ValueError, match='integrity receipt'):
        client.export(job['id'], tmp_path / 'damaged.mp4')
    assert not (tmp_path / 'damaged.mp4').exists()
    assert not list(tmp_path.glob('.social-fetch-*'))


def test_existing_data_dir_reconnects_and_namespace_remains_isolated(tmp_path, monkeypatch):
    client, job, _ = ready_client(tmp_path, monkeypatch)
    assert Client(client.jobs.root).status(job['id'])['status'] == 'ready'
    with pytest.raises(FileNotFoundError):
        Client(client.jobs.root, namespace='someone-else').status(job['id'])


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), float('inf'), 86401])
def test_invalid_wait_is_refused_before_acquiring_any_source(tmp_path, monkeypatch, timeout):
    client = Client(tmp_path)
    monkeypatch.setattr(client.jobs, 'submit', lambda *a: pytest.fail('must not acquire'))
    with pytest.raises(ValueError, match='timeout'):
        client.download(URL, timeout=timeout)


def test_cli_reports_pending_timeout_with_job_identity_and_nonzero_exit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Client, 'download', lambda *a, **k: {'id': 'a' * 24, 'status': 'queued'})
    monkeypatch.setattr(Client, 'wait', lambda *a, **k: (_ for _ in ()).throw(TimeoutError('Still pending')))
    monkeypatch.setattr(Client, 'status', lambda *a, **k: {'id': 'a' * 24, 'status': 'downloading'})
    assert main(['--data-dir', str(tmp_path), 'download', URL, '--wait']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['id'] == 'a' * 24 and result['timed_out'] and result['status'] == 'downloading'


def test_cli_failed_job_has_nonzero_exit_and_json_only(monkeypatch, capsys):
    monkeypatch.setattr(Client, 'status', lambda *a: {'status': 'failed', 'message': 'Source unavailable'})
    assert main(['status', 'a' * 24]) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'failed'
