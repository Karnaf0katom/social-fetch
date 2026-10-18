"""Durable, tenant-scoped public video acquisition using the existing downloaders.

Workers survive HTTP requests; media assembly goes through the shared CPU owner.
Only recognized public video/post links are accepted, never arbitrary fetch URLs.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from social_fetch.social_sources import download_link

VIDEO_ROOT = Path(__file__).resolve().parents[1]
CPU_SLOT = VIDEO_ROOT.parent.parent / '.agent/bin/cpu-slot.sh'
if not CPU_SLOT.is_file():
    # An exported app on a managed host still honors its installed CPU owner.
    # An independent VM needs neither the monorepo nor this optional command.
    CPU_SLOT = Path(shutil.which('cpu-slot.sh') or CPU_SLOT)
ACTIVE = {'queued', 'downloading', 'assembling'}
PENDING = ACTIVE | {'waiting'}
MAX_WAITING = 50


def save(path, value):
    pending = path.with_suffix('.tmp')
    pending.write_text(json.dumps(value) + '\n')
    pending.replace(path)


class DownloadJobs:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get('FOOTAGE_DOWNLOAD_ROOT', VIDEO_ROOT / 'out/footage-downloads')).resolve()

    @contextmanager
    def lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / '.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def folder(self, namespace, job_id):
        if not re.fullmatch(r'[a-f0-9]{24}', job_id):
            raise FileNotFoundError('Download not found')
        tenant = hashlib.sha256(namespace.encode()).hexdigest()[:24]
        return self.root / tenant / job_id

    def read(self, folder):
        job = json.loads((folder / 'job.json').read_text())
        dead = False
        if job['status'] in ACTIVE and job.get('pid'):
            try:
                os.kill(job['pid'], 0)
                proc = Path(f"/proc/{job['pid']}/stat")
                dead = proc.exists() and proc.read_text().split(') ', 1)[1].startswith('Z ')
            except (ProcessLookupError, PermissionError):
                dead = True
        elif job['status'] in ACTIVE and time.time() - job['updated_at'] > 30:
            dead = True
        if dead:
            job.update(status='failed', message='Download was interrupted. Try again to resume.', updated_at=time.time())
            save(folder / 'job.json', job)
        if job['status'] == 'ready':
            final = folder / (job['video_id'] + '.mp4')
            if not final.is_file() or final.stat().st_size != job.get('bytes'):
                job.update(status='failed', message='The saved MP4 is missing or changed. Try this download again.', updated_at=time.time())
                save(folder / 'job.json', job)
        # Older receipts predate the library. Reuse their measured metadata;
        # listing files never reacquires a source or hashes a large MP4.
        if job['status'] == 'ready' and not job.get('sha256'):
            receipt_path = folder / (job['video_id'] + '.receipt.json')
            if receipt_path.is_file():
                receipt = json.loads(receipt_path.read_text())
                if receipt.get('downloaded') and receipt.get('bytes') == job.get('bytes'):
                    job.update({k: receipt[k] for k in ('sha256', 'width') if k in receipt})
        return job

    def public(self, job):
        return {k: job[k] for k in ('id', 'source_url', 'platform', 'title', 'status', 'message', 'created_at', 'updated_at', 'bytes', 'width', 'height', 'duration', 'sha256') if k in job}

    def _jobs(self):
        rows = []
        for path in self.root.glob('*/*/job.json'):
            try:
                rows.append((path.parent, self.read(path.parent)))
            except (ValueError, KeyError, OSError):
                # One damaged receipt must not hide the rest of the library.
                continue
        return rows

    def _start(self, folder, job):
        job.update(status='queued', message='Download queued', updated_at=time.time())
        save(folder / 'job.json', job)
        try:
            with (folder / 'worker.log').open('a') as log:
                process = subprocess.Popen([sys.executable, '-m', 'social_fetch.download_jobs', '--root', str(self.root),
                                            '--folder', str(folder)], cwd=VIDEO_ROOT,
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            job['pid'] = process.pid
        except OSError:
            job.update(status='failed', message='Could not start the downloader. Try again.')
        save(folder / 'job.json', job)

    def _dispatch(self):
        """Under the shared lock, start only explicitly requested waiting work."""
        rows = self._jobs()
        active = sum(job['status'] in ACTIVE for _, job in rows)
        for folder, job in sorted(rows, key=lambda row: row[1]['created_at']):
            if active >= 2:
                break
            if job['status'] != 'waiting':
                continue
            if shutil.disk_usage(self.root).free < 9 * (active + 1) * 1024**3:
                job.update(message='Waiting for free disk space on this VM', updated_at=time.time())
                save(folder / 'job.json', job)
                break
            self._start(folder, job)
            active += job['status'] in ACTIVE

    def list(self, namespace, count=100):
        if not 1 <= count <= 100:
            raise ValueError('Choose one to 100 downloads')
        tenant = self.folder(namespace, '0' * 24).parent
        with self.lock():
            # Reconnect authorized waiting work after an interrupted worker or
            # server restart. Failed jobs still require an explicit retry.
            self._dispatch()
            rows = [job for folder, job in self._jobs() if folder.parent == tenant]
            rows.sort(key=lambda job: job['created_at'], reverse=True)
            return {'downloads': [self.public(job) for job in rows[:count]], 'total': len(rows)}

    def cancel(self, namespace, job_id):
        with self.lock():
            folder = self.folder(namespace, job_id)
            job = self.read(folder)
            if job['status'] != 'waiting':
                raise ValueError('Only a waiting download can be cancelled')
            job.update(status='cancelled', message='Download cancelled before it started', updated_at=time.time())
            save(folder / 'job.json', job)
            return self.public(job)

    def get(self, namespace, job_id):
        with self.lock():
            return self.public(self.read(self.folder(namespace, job_id)))

    def file(self, namespace, job_id):
        with self.lock():
            folder = self.folder(namespace, job_id)
            job = self.read(folder)
            path = folder / (job['video_id'] + '.mp4')
            if job['status'] != 'ready' or not path.is_file() or path.stat().st_size != job['bytes']:
                raise FileNotFoundError('The completed download is not available')
            return path

    def submit(self, namespace, url, *, queue=False, title=None):
        link = download_link(url)
        normalized = link.url
        identity = normalized if link.platform == 'youtube' else link.platform + ':' + link.identity
        job_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        folder = self.folder(namespace, job_id)
        with self.lock():
            existing = None
            resume_cpu = None
            if (folder / 'job.json').exists():
                existing = self.read(folder)
                normalized = existing['source_url']
                if title and not existing.get('title'):
                    existing['title'] = str(title).strip()[:240]
                    save(folder / 'job.json', existing)
                if existing['status'] in PENDING:
                    return self.public(existing)
                final = folder / (existing['video_id'] + '.mp4')
                if existing['status'] == 'ready' and final.is_file() and final.stat().st_size == existing['bytes']:
                    return self.public(existing)
                if existing.get('cpu_job_id'):
                    result = subprocess.run([str(CPU_SLOT), 'jobs', existing['cpu_job_id'], '--json'],
                                            capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
                    if result.returncode != 0:
                        raise RuntimeError('Could not check the existing assembly job. Try checking again later.')
                    try:
                        state = json.loads(result.stdout)['job']['status']
                    except (ValueError, KeyError, TypeError):
                        raise RuntimeError('The existing assembly status is uncertain. Try checking again later.') from None
                    if state in {'queued', 'running', 'remote', 'held', 'passed'}:
                        resume_cpu = existing['cpu_job_id']
            rows = self._jobs()
            active = sum(job['status'] in ACTIVE for _, job in rows)
            if queue and sum(job['status'] == 'waiting' for _, job in rows) >= MAX_WAITING:
                raise RuntimeError('The VM download queue is full. Wait for a download to finish.')
            if active >= 2 and not queue:
                raise RuntimeError('Two downloads are already running. Try again when one finishes.')
            # Each source can hold two 2-GiB streams plus a merged copy. Reserve
            # peak space for existing workers as well as this new admission.
            if not queue and shutil.disk_usage(self.root).free < 9 * (active + 1) * 1024**3:
                raise RuntimeError('Not enough space for another source download.')
            folder.mkdir(parents=True, exist_ok=True)
            now = time.time()
            job = {'id': job_id, 'video_id': link.identity, 'source_url': normalized, 'platform': link.platform,
                   'status': 'waiting' if queue else 'queued', 'message': 'Waiting for a download slot' if queue else 'Download queued',
                   'created_at': existing['created_at'] if existing else now, 'updated_at': now}
            if resume_cpu:
                job['cpu_job_id'] = resume_cpu
            if title:
                job['title'] = str(title).strip()[:240]
            elif existing and existing.get('title'):
                job['title'] = existing['title']
            save(folder / 'job.json', job)
            if queue:
                self._dispatch()
            else:
                self._start(folder, job)
                if job['status'] == 'failed':
                    raise RuntimeError(job['message'])
            return self.public(self.read(folder))

    def batch(self, namespace, items):
        if not 1 <= len(items) <= 10:
            raise ValueError('Choose one to ten videos per batch')
        results = []
        for item in items:
            try:
                results.append({'url': item['url'], 'download': self.submit(namespace, item['url'], queue=True, title=item.get('title'))})
            except (ValueError, RuntimeError) as exc:
                results.append({'url': item['url'], 'error': str(exc)})
        return {'results': results}

    def work(self, folder):
        def update(**values):
            with self.lock():
                job = json.loads((folder / 'job.json').read_text())
                job.update(updated_at=time.time(), **values)
                save(folder / 'job.json', job)
                return job
        try:
            job = update(pid=os.getpid(), message='Preparing source download')
            platform = job.get('platform', 'youtube')
            command = ([sys.executable, str(VIDEO_ROOT / 'social_fetch/youtube_web.py'), job['source_url'], '--out', str(folder)]
                       if platform == 'youtube' else [sys.executable, '-m', 'social_fetch.social_download',
                       job['source_url'], '--out', str(folder), '--video-id', job['video_id']])
            cpu_job = job.get('cpu_job_id')
            if not cpu_job:
                update(status='downloading', message='Downloading original video and audio' if platform == 'youtube' else 'Downloading selected public post')
                subprocess.run([*command, '--download-only'], cwd=VIDEO_ROOT, check=True, timeout=1800, stdin=subprocess.DEVNULL)
                update(status='assembling', message='Waiting for video assembly and media checks')
                # This checkout must use its shared CPU owner. An independent
                # installation has no private .agent dependency; its two-worker
                # admission above bounds the existing FFmpeg finalizer instead.
                assembly = [str(CPU_SLOT), 'run', '--', *command, '--finalize-only'] if CPU_SLOT.is_file() else [*command, '--finalize-only']
                result = subprocess.run(assembly,
                                        cwd=VIDEO_ROOT, capture_output=True, text=True, timeout=3700, stdin=subprocess.DEVNULL)
                if result.returncode == 75:
                    match = re.search(r'\bjob=(\d+)\b', result.stderr + result.stdout)
                    if not match:
                        raise RuntimeError('Assembly is queued; its job identity is missing')
                    cpu_job = match[1]
                    update(cpu_job_id=cpu_job)
            if cpu_job:
                update(status='assembling', message='Waiting for video assembly and media checks')
                while True:
                    result = subprocess.run([str(CPU_SLOT), 'wait', cpu_job, '--timeout-seconds', '60'],
                                            capture_output=True, text=True, timeout=75, stdin=subprocess.DEVNULL)
                    if result.returncode != 75:
                        break
            if result.returncode:
                raise RuntimeError('Video assembly failed')
            receipt = json.loads((folder / (job['video_id'] + '.receipt.json')).read_text())
            final = folder / (job['video_id'] + '.mp4')
            if (not receipt['downloaded'] or final.stat().st_size != receipt['bytes']
                    or platform != 'youtube' and receipt.get('source_url') != job['source_url']):
                raise RuntimeError('Completed file did not pass its receipt check')
            update(status='ready', message='MP4 ready', **{k: receipt[k] for k in ('bytes', 'height', 'duration', 'width', 'sha256') if k in receipt})
        except Exception:
            # Keep service tokens, subprocess output and host paths out of the public response.
            update(status='failed', message='Public download or media check failed. The post may require login, be unavailable, or have no downloadable video. Open the source or retry.')
        finally:
            with self.lock():
                self._dispatch()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--folder', type=Path, required=True)
    args = parser.parse_args()
    DownloadJobs(args.root).work(args.folder)
