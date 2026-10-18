"""Exercise the installed public interface outside the source checkout."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from social_fetch import Client, __version__

ROOT = Path(__file__).resolve().parents[1]


def test_public_source_matches_its_manifest():
    spec = importlib.util.spec_from_file_location('check_release', ROOT / 'scripts/check_release.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    assert check.check()['version'] == __version__


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
