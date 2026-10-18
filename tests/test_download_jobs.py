import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from social_fetch.download_jobs import DownloadJobs, save

URL = 'https://www.youtube.com/watch?v=VQRLujxTm3c'


def prepared(tmp_path, monkeypatch):
    gate = tmp_path / 'cpu-slot.sh'
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.touch()
    monkeypatch.setattr('social_fetch.download_jobs.CPU_SLOT', gate)
    monkeypatch.setattr('social_fetch.download_jobs.shutil.disk_usage', lambda _: SimpleNamespace(free=64 * 1024**3))
    calls = []
    monkeypatch.setattr('social_fetch.download_jobs.subprocess.Popen', lambda command, **kwargs: calls.append((command, kwargs)) or SimpleNamespace(pid=os.getpid()))
    return DownloadJobs(tmp_path), calls


def test_short_and_watch_requests_share_one_job_and_do_not_spawn_twice(tmp_path, monkeypatch):
    service, calls = prepared(tmp_path, monkeypatch)
    first = service.submit('ours', 'https://www.youtube.com/shorts/VQRLujxTm3c')
    second = service.submit('ours', URL)
    assert first['id'] == second['id'] and len(calls) == 1
    assert first['source_url'] == URL
    assert calls[0][1]['start_new_session'] is True
    assert 'pid' not in first and 'path' not in first
    with pytest.raises(FileNotFoundError):
        service.get('theirs', first['id'])
    with pytest.raises(FileNotFoundError):
        service.get('ours', '../../etc/passwd')
    with pytest.raises(FileNotFoundError):
        service.file('ours', first['id'])


@pytest.mark.parametrize('url', ['http://127.0.0.1/x', 'https://youtube.com.evil.test/watch?v=VQRLujxTm3c', 'https://www.youtube.com/playlist?list=x'])
def test_arbitrary_download_urls_never_start_a_process(tmp_path, monkeypatch, url):
    service, calls = prepared(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        service.submit('ours', url)
    assert not calls


def test_global_admission_limits_workers_and_disk(tmp_path, monkeypatch):
    service, calls = prepared(tmp_path, monkeypatch)
    service.submit('a', URL)
    service.submit('b', URL)
    with pytest.raises(RuntimeError, match='Two downloads'):
        service.submit('c', URL)
    assert len(calls) == 2
    service, calls = prepared(tmp_path / 'empty', monkeypatch)
    monkeypatch.setattr('social_fetch.download_jobs.shutil.disk_usage', lambda _: SimpleNamespace(free=1024))
    with pytest.raises(RuntimeError, match='space'):
        service.submit('a', URL)
    assert not calls


def test_worker_waits_on_same_cpu_job_and_requires_actual_receipt(tmp_path, monkeypatch):
    service, _ = prepared(tmp_path, monkeypatch)
    job = service.submit('ours', URL)
    folder = service.folder('ours', job['id'])
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if '--finalize-only' in command:
            return SimpleNamespace(returncode=75, stderr='queued: job=42 key=assembly', stdout='')
        if 'wait' in command:
            (folder / 'VQRLujxTm3c.mp4').write_bytes(b'mp4')
            save(folder / 'VQRLujxTm3c.receipt.json', {'downloaded': True, 'bytes': 3, 'height': 1080, 'duration': 2})
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr('social_fetch.download_jobs.subprocess.run', run)
    service.work(folder)
    assert len(calls) == 3 and calls[2][1:3] == ['wait', '42']
    assert service.get('ours', job['id'])['status'] == 'ready'
    assert service.file('ours', job['id']).read_bytes() == b'mp4'
    assert service.submit('ours', URL)['status'] == 'ready'


def test_worker_failure_is_not_reported_as_delivery_and_retry_is_explicit(tmp_path, monkeypatch):
    service, calls = prepared(tmp_path, monkeypatch)
    job = service.submit('ours', URL)
    monkeypatch.setattr('social_fetch.download_jobs.subprocess.run', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('secret-service-token')))
    service.work(service.folder('ours', job['id']))
    result = service.get('ours', job['id'])
    assert result['status'] == 'failed' and 'secret-service-token' not in json.dumps(result)
    assert result['failure_stage'] == 'acquisition' and result['error_code'] == 'acquisition_failed'
    service.submit('ours', URL)
    assert len(calls) == 2


@pytest.mark.parametrize('failure', ['timeout', 'assembly', 'verification'])
def test_worker_failures_identify_the_stage_without_exposing_subprocess_output(tmp_path, monkeypatch, failure):
    import subprocess
    service, _ = prepared(tmp_path, monkeypatch)
    job = service.submit('ours', URL)
    def run(command, **kwargs):
        if failure == 'timeout': raise subprocess.TimeoutExpired('secret-service-url', 1)
        return SimpleNamespace(returncode=1 if failure == 'assembly' and '--finalize-only' in command else 0,
                               stderr='secret-service-token', stdout='')
    monkeypatch.setattr('social_fetch.download_jobs.subprocess.run', run)
    service.work(service.folder('ours', job['id']))
    result = service.get('ours', job['id'])
    assert result['status'] == 'failed'
    assert result['failure_stage'] == {'timeout': 'acquisition', 'assembly': 'assembly', 'verification': 'verification'}[failure]
    assert result['error_code'] == ('timeout' if failure == 'timeout' else failure + '_failed')
    assert 'secret-service' not in json.dumps(result)


def test_pending_cpu_wait_never_becomes_failure_or_resubmits_assembly(tmp_path, monkeypatch):
    service, _ = prepared(tmp_path, monkeypatch)
    job = service.submit('ours', URL)
    folder = service.folder('ours', job['id'])
    calls = []
    waits = []
    def run(command, **kwargs):
        calls.append(command)
        if '--finalize-only' in command:
            return SimpleNamespace(returncode=75, stderr='queued: job=42 key=assembly', stdout='')
        if 'wait' in command:
            waits.append(command)
            if len(waits) == 1:
                return SimpleNamespace(returncode=75, stdout='still queued', stderr='')
            (folder / 'VQRLujxTm3c.mp4').write_bytes(b'mp4')
            save(folder / 'VQRLujxTm3c.receipt.json', {'downloaded': True, 'bytes': 3, 'height': 1080, 'duration': 2})
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr('social_fetch.download_jobs.subprocess.run', run)
    service.work(folder)
    assert len(waits) == 2 and all(command[2] == '42' for command in waits)
    assert sum('--finalize-only' in command for command in calls) == 1
    assert service.get('ours', job['id'])['status'] == 'ready'


def test_explicit_repair_resumes_pending_cpu_identity_without_reacquiring_streams(tmp_path, monkeypatch):
    service, launches = prepared(tmp_path, monkeypatch)
    job = service.submit('ours', URL)
    folder = service.folder('ours', job['id'])
    saved = service.read(folder)
    saved.update(status='failed', cpu_job_id='42')
    save(folder / 'job.json', saved)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if 'jobs' in command:
            return SimpleNamespace(returncode=0, stdout=json.dumps({'job': {'status': 'queued'}}))
        assert 'wait' in command and command[2] == '42'
        (folder / 'VQRLujxTm3c.mp4').write_bytes(b'mp4')
        save(folder / 'VQRLujxTm3c.receipt.json', {'downloaded': True, 'bytes': 3, 'height': 1080, 'duration': 2})
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr('social_fetch.download_jobs.subprocess.run', run)
    repaired = service.submit('ours', URL)
    assert repaired['id'] == job['id'] and repaired['created_at'] == job['created_at']
    assert service.read(folder)['cpu_job_id'] == '42' and len(launches) == 2
    service.work(folder)
    assert len(calls) == 2 and service.get('ours', job['id'])['status'] == 'ready'


def test_batch_persists_waiting_jobs_recovers_after_restart_and_never_retries_failure(tmp_path, monkeypatch):
    service, calls = prepared(tmp_path, monkeypatch)
    urls = [f'https://youtube.com/watch?v={value * 11}' for value in 'abcd']
    response = service.batch('ours', [{'url': url, 'title': 'Selected video'} for url in urls] + [{'url': 'http://127.0.0.1/private'}])
    assert len(calls) == 2 and len(response['results']) == 5
    assert 'error' in response['results'][-1]
    jobs = [row['download'] for row in response['results'][:-1]]
    assert [job['status'] for job in jobs] == ['queued', 'queued', 'waiting', 'waiting']
    assert service.batch('ours', [{'url': urls[2]}])['results'][0]['download']['id'] == jobs[2]['id']
    folder = service.folder('ours', jobs[2]['id'])
    waiting = service.read(folder)
    waiting['updated_at'] = 1
    save(folder / 'job.json', waiting)
    assert service.get('ours', jobs[2]['id'])['status'] == 'waiting'
    first = service.folder('ours', jobs[0]['id'])
    failed = service.read(first)
    failed.update(status='failed', message='Retained failure')
    save(first / 'job.json', failed)
    restored = DownloadJobs(tmp_path).list('ours')
    assert len(calls) == 3
    assert {job['status'] for job in restored['downloads']} == {'queued', 'waiting', 'failed'}
    assert not DownloadJobs(tmp_path).list('theirs')['downloads']
    assert len(calls) == 3  # reading never retries the retained failure
    assert service.cancel('ours', jobs[3]['id'])['status'] == 'cancelled'
    assert len(calls) == 3
    with pytest.raises(ValueError, match='waiting'):
        service.cancel('ours', jobs[1]['id'])


def test_waiting_queue_has_disk_backpressure_without_false_failure(tmp_path, monkeypatch):
    service, calls = prepared(tmp_path, monkeypatch)
    monkeypatch.setattr('social_fetch.download_jobs.shutil.disk_usage', lambda _: SimpleNamespace(free=1024))
    result = service.batch('ours', [{'url': URL}])['results'][0]['download']
    assert result['status'] == 'waiting' and 'disk space' in result['message'] and not calls
    assert service.list('ours')['downloads'][0]['status'] == 'waiting'


def test_independent_install_uses_existing_finalizer_without_private_vm_gate(tmp_path, monkeypatch):
    service, _ = prepared(tmp_path, monkeypatch)
    monkeypatch.setattr('social_fetch.download_jobs.CPU_SLOT', tmp_path / 'not-installed/cpu-slot.sh')
    job = service.submit('ours', URL)
    folder = service.folder('ours', job['id'])
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if '--finalize-only' in command:
            (folder / 'VQRLujxTm3c.mp4').write_bytes(b'mp4')
            save(folder / 'VQRLujxTm3c.receipt.json', dict(downloaded=True, bytes=3, height=720, duration=2, sha256='a' * 64))
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr('social_fetch.download_jobs.subprocess.run', run)
    service.work(folder)
    assert len(calls) == 2 and '--download-only' in calls[0] and '--finalize-only' in calls[1]
    assert not any('cpu-slot.sh' in str(part) for command in calls for part in command)
    assert service.get('ours', job['id'])['status'] == 'ready'


def test_youtube_finalizer_retains_a_digest_for_portable_moment_search(tmp_path, monkeypatch):
    import hashlib
    from social_fetch.youtube_web import finalize
    streams = [dict(format_id='133', ext='mp4', bytes=3, track=''), dict(format_id='140', ext='m4a', bytes=3, track='')]
    for stream in streams:
        (tmp_path / f"VQRLujxTm3c.f{stream['format_id']}.{stream['ext']}").write_bytes(b'raw')
    def run(command, **kwargs):
        if command[0] == 'ffmpeg':
            Path(command[-1]).write_bytes(b'final mp4 bytes')
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(stdout=json.dumps({'streams': [
            dict(codec_type='video', codec_name='h264', width=720, height=1280, avg_frame_rate='30/1'),
            dict(codec_type='audio', codec_name='aac'),
        ], 'format': {'duration': '10'}}))
    monkeypatch.setattr('social_fetch.youtube_web.subprocess.run', run)
    receipt = finalize(URL, 'VQRLujxTm3c', tmp_path, streams)
    assert receipt['sha256'] == hashlib.sha256((tmp_path / 'VQRLujxTm3c.mp4').read_bytes()).hexdigest()
