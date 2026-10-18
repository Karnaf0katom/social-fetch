"""Small, persistent social search/download API shared by the standalone CLI."""
from __future__ import annotations

import hashlib
import importlib.util
import math
import os
from pathlib import Path
import shutil
import tempfile
import time

from social_fetch.download_jobs import DownloadJobs, PENDING
from social_fetch.social_accounts import account_search
from social_fetch.web_search import FootageSearch

SOURCES = ('social', 'youtube', 'instagram', 'tiktok', 'x', 'facebook', 'reddit')


def data_directory():
    """Standalone installs never write into their installed Python package."""
    configured = os.environ.get('SOCIAL_FETCH_DATA_DIR') or os.environ.get('FOOTAGE_DOWNLOAD_ROOT')
    if configured:
        return Path(configured).expanduser()
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'social-fetch'


def doctor():
    checks = {'ffmpeg': bool(shutil.which('ffmpeg')), 'ffprobe': bool(shutil.which('ffprobe')),
              'ddgs': importlib.util.find_spec('ddgs') is not None,
              'yt_dlp': importlib.util.find_spec('yt_dlp') is not None or bool(shutil.which('yt-dlp'))}
    return {'status': 'ready' if all(checks.values()) else 'missing_dependencies',
            'checks': checks, 'network_checked': False}


class Client:
    """Linux social discovery and durable download jobs; no web server required.

    Reuse the same data_dir and namespace to observe jobs from another process.
    Downloads return a job immediately unless wait=True. Only ready jobs export.
    """

    def __init__(self, data_dir=None, *, namespace='social-cli'):
        if not isinstance(namespace, str) or not namespace.strip() or len(namespace) > 200:
            raise ValueError('Choose a namespace between 1 and 200 characters.')
        self.namespace = namespace
        self.jobs = DownloadJobs(data_dir if data_dir is not None else data_directory())
        self._search = None

    def _discovery(self):
        if self._search is None:
            self._search = FootageSearch.from_env(include_catalogs=False)
        return self._search

    def search(self, query, *, source='social', accounts=False, page=0, count=12):
        if source not in SOURCES:
            raise ValueError('Choose a supported social platform.')
        return self._discovery().search(query, source=source, intent='accounts' if accounts else 'any',
                                        page=page, count=count, namespace=self.namespace)

    def account(self, url, *, count=5):
        return account_search.browse(url, self._discovery(), count=count, namespace=self.namespace, include_posters=False)

    def download(self, url, *, wait=False, timeout=900):
        self._timeout(timeout)
        job = self.jobs.submit(self.namespace, url)
        return self.wait(job['id'], timeout=timeout) if wait else job

    def status(self, job_id):
        return self.jobs.get(self.namespace, job_id)

    @staticmethod
    def _timeout(timeout):
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 86400:
            raise ValueError('Choose a timeout above zero and at most 86400 seconds.')

    def wait(self, job_id, *, timeout=900):
        self._timeout(timeout)
        deadline = time.monotonic() + timeout
        while True:
            job = self.status(job_id)
            if job['status'] not in PENDING:
                return job
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Download is still pending. Use status with the same data directory and namespace.')
            time.sleep(min(1, remaining))

    def export(self, job_id, out):
        job = self.status(job_id)
        source = self.jobs.file(self.namespace, job_id)
        out = Path(out).expanduser().absolute()
        if out.suffix.lower() != '.mp4':
            raise ValueError('Choose an MP4 output filename.')
        if out.exists() or out.is_symlink():
            raise ValueError('The export destination already exists. Choose another filename.')
        if not job.get('sha256'):
            raise ValueError('The download has no integrity receipt. Download it again before export.')
        out.parent.mkdir(parents=True, exist_ok=True)
        pending = None
        try:
            digest, size = hashlib.sha256(), 0
            with tempfile.NamedTemporaryFile(dir=out.parent, prefix='.social-fetch-', suffix='.part', delete=False) as target:
                pending = Path(target.name)
                with source.open('rb') as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b''):
                        target.write(block)
                        digest.update(block)
                        size += len(block)
            if size != job['bytes'] or digest.hexdigest() != job['sha256']:
                raise ValueError('The saved MP4 does not match its integrity receipt. Download it again.')
            # An exclusive link prevents overwriting a destination created during copying.
            os.link(pending, out)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)
        return {**job, 'exported_to': str(out)}
