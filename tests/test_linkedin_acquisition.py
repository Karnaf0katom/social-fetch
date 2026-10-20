"""LinkedIn activity binding and native-media delivery regressions."""
import io
import json

import pytest

import social_fetch.social_download as download
import social_fetch.social_fallbacks as fallback
from social_fetch.social_sources import download_link


POST = ('https://www.linkedin.com/posts/the-mathworks_2_what-is-mathworks-cloud-center-'
        'activity-7151241570371948544-4Gu7/')
FEED = 'https://www.linkedin.com/feed/update/urn:li:activity:7151241570371948544/'
MEDIA = 'https://dms.licdn.com/video/0/1704988854139'
VIDEO = b'0000ftyp' + b'x' * 2048


class Response(io.BytesIO):
    status = 200
    headers = {'Content-Length': str(len(VIDEO))}


def test_primary_extensionless_native_mp4_keeps_selected_activity(tmp_path, monkeypatch):
    monkeypatch.setattr(download.shutil, 'which', lambda _: '/usr/bin/yt-dlp')

    def metadata(command, **kwargs):
        assert command[command.index('--use-extractors') + 1] == 'LinkedIn'
        assert command[-1] == POST
        kwargs['stdout'].write(json.dumps({'id': '7151241570371948544',
            'extractor_key': 'LinkedIn', 'ext': 'mp4', 'protocol': 'https', 'url': MEDIA}))

    calls = []

    def media(platform, url):
        calls.append((platform, url))
        return Response(VIDEO)

    monkeypatch.setattr(download.subprocess, 'run', metadata)
    monkeypatch.setattr(download, 'delivery_request', media)
    download.acquire(POST, tmp_path)
    receipt = json.loads((tmp_path / 'acquisition.json').read_text())
    assert calls == [('linkedin', MEDIA)]
    assert receipt['route'] == 'linkedin_extractor'
    assert receipt['source_url'] == POST and receipt['bytes'] == len(VIDEO)
    assert (tmp_path / 'raw.mp4').read_bytes() == VIDEO
    assert not list(tmp_path.glob('attempt-*'))


def test_primary_other_activity_never_downloads_or_tries_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(download.shutil, 'which', lambda _: '/usr/bin/yt-dlp')

    def metadata(command, **kwargs):
        kwargs['stdout'].write(json.dumps({'id': '7151241570371948545',
            'extractor_key': 'LinkedIn', 'ext': 'mp4', 'protocol': 'https', 'url': MEDIA}))

    def forbidden(*args, **kwargs):
        pytest.fail('An unrelated activity must fail before media or fallback requests')

    monkeypatch.setattr(download.subprocess, 'run', metadata)
    monkeypatch.setattr(download, 'delivery_request', forbidden)
    monkeypatch.setitem(fallback.FALLBACKS, 'linkedin', ('linkedin_public_page', forbidden))
    with pytest.raises(ValueError, match='another post'):
        download.acquire(POST, tmp_path)
    assert not (tmp_path / 'acquisition.json').exists()
    assert not (tmp_path / 'raw.mp4').exists()
    assert not list(tmp_path.glob('**/*.part'))


def test_public_page_activity_alias_allows_extensionless_mp4_failover(tmp_path, monkeypatch):
    sources = [{'type': 'video/mp4', 'src': MEDIA, 'data-bitrate': 800},
               {'type': 'application/x-mpegURL', 'src': 'https://dms.licdn.com/playlist.m3u8',
                'data-bitrate': 9000}]
    html = ('<link rel="canonical" href="' + FEED + '"><meta property="og:url" content="' + POST
            + '"><video data-sources=\'' + json.dumps(sources) + "'></video>")
    monkeypatch.setattr(fallback, 'document', lambda *a, **k: html)

    def unavailable(*_):
        raise TimeoutError('Controlled primary availability failure')

    def media(platform, url, **kwargs):
        assert platform == 'linkedin' and url == MEDIA and kwargs == {'media': True}
        return Response(VIDEO)

    monkeypatch.setattr(download, 'primary_download', unavailable)
    monkeypatch.setattr(fallback, 'request', media)
    download.acquire(POST, tmp_path)
    receipt = json.loads((tmp_path / 'acquisition.json').read_text())
    assert receipt['route'] == 'linkedin_public_page'
    assert [a['status'] for a in receipt['route_attempts']] == ['unavailable', 'acquired']
    assert 'Controlled' not in json.dumps(receipt)
    assert (tmp_path / 'raw.mp4').read_bytes() == VIDEO


@pytest.mark.parametrize('identity', ['', '<link rel="canonical" href="' + FEED
    + '"><meta property="og:url" content="' + POST.replace('7151241570371948544', '7151241570371948545') + '">'])
def test_public_media_requires_consistent_selected_post_metadata(tmp_path, monkeypatch, identity):
    html = identity + '<video data-sources=\'' + json.dumps([{'type': 'video/mp4', 'src': MEDIA}]) + "'></video>"
    monkeypatch.setattr(fallback, 'document', lambda *a, **k: html)

    def forbidden(*args, **kwargs):
        pytest.fail('Missing or inconsistent post identity must fail before transfer')

    monkeypatch.setattr(fallback, 'transfer', forbidden)
    with pytest.raises(ValueError):
        fallback.page_download(download_link(POST), tmp_path)


@pytest.mark.parametrize('url', ['https://dms.licdn.com.evil.test/video',
    'https://www.linkedin.com/video', 'http://dms.licdn.com/video',
    'https://user:secret@dms.licdn.com/video', 'https://dms.licdn.com:8443/video',
    'https://127.0.0.1/video'])
def test_linkedin_media_and_redirect_checks_stay_on_approved_cdn(url):
    with pytest.raises(ValueError):
        download.delivery_url('linkedin', url)
    with pytest.raises(ValueError):
        fallback.checked_url('linkedin', url, media=True)
