import io
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from social_fetch.social_download import acquire, finalize, tikwm_url, tiktok_download
from social_fetch.social_sources import download_link


class Response(io.BytesIO):
    status = 200
    def __init__(self, data, declared=None):
        super().__init__(data)
        self.headers = {'Content-Length': str(declared if declared is not None else len(data))}


def test_tiktok_transfer_checks_post_identity_and_complete_mp4_before_receipting(tmp_path, monkeypatch):
    link = download_link('https://www.tiktok.com/@person/video/6742501081818877190')
    video = b'0000ftyp' + b'x' * 2048
    calls = []
    def request(url, data=None):
        calls.append(url)
        if '/api/' in url:
            return Response(json.dumps({'code': 0, 'data': {'id': link.identity, 'play': 'https://v16m.tiktokcdn-us.com/video.mp4'}}).encode())
        return Response(video)
    monkeypatch.setattr('social_fetch.social_download.tikwm_request', request)
    acquire(link.url, tmp_path)
    receipt = json.loads((tmp_path / 'acquisition.json').read_text())
    assert receipt['bytes'] == len(video) and receipt['source_url'] == link.url
    assert 'tiktokcdn' not in json.dumps(receipt)
    acquire(link.url, tmp_path)
    assert len(calls) == 2  # Valid source is reused; retry does not reacquire bytes.


def test_mismatched_tiktok_and_incomplete_media_never_become_saved(tmp_path, monkeypatch):
    link = download_link('https://www.tiktok.com/@person/video/6742501081818877190')
    monkeypatch.setattr('social_fetch.social_download.tikwm_request', lambda *a: Response(json.dumps(
        {'code': 0, 'data': {'id': '6742501081818877191', 'play': 'https://www.tikwm.com/video.mp4'}}).encode()))
    with pytest.raises(ValueError, match='another post'): tiktok_download(link, tmp_path)
    def incomplete(url, data=None):
        return Response(json.dumps({'code': 0, 'data': {'id': link.identity, 'play': 'https://www.tikwm.com/video.mp4'}}).encode()) if data else Response(b'ftyp' + b'x' * 1024, declared=9000)
    monkeypatch.setattr('social_fetch.social_download.tikwm_request', incomplete)
    with pytest.raises(ValueError, match='Incomplete'): tiktok_download(link, tmp_path)
    assert not (tmp_path / 'raw.mp4').exists()


@pytest.mark.parametrize('url', ['https://tikwm.com.evil.test/video.mp4', 'http://www.tikwm.com/file',
    'https://127.0.0.1/file', 'https://user:password@v16m.tiktokcdn-us.com/file'])
def test_delivery_redirects_cannot_escape_owned_provider_hosts(url):
    with pytest.raises(ValueError): tikwm_url(url)


def test_generic_extraction_is_one_post_with_no_implicit_browser_or_host_config(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr('social_fetch.social_download.shutil.which', lambda _: '/usr/bin/yt-dlp')
    def run(command, **kwargs):
        commands.append(command)
        (tmp_path / 'raw.mp4').write_bytes(b'ftyp' + b'x' * 1024)
        (tmp_path / 'extracted-id.txt').write_text('12345678\n')
    monkeypatch.setattr('social_fetch.social_download.subprocess.run', run)
    acquire('https://x.com/NASA/status/12345678', tmp_path)
    assert '--ignore-config' in commands[0] and '--no-playlist' in commands[0]
    assert commands[0][commands[0].index('--use-extractors') + 1] == 'twitter,twitter:amplify'
    assert '--cookies-from-browser' not in commands[0] and '--username' not in commands[0]
    assert 'syndication' in ' '.join(commands[0])
    # Twitter's media ID differs from its requested post ID; display_id binds
    # the acquisition to the selected post rather than rejecting every video.
    assert 'after_move:%(display_id,id)s' in commands[0]


def test_venv_module_is_used_when_its_console_script_is_not_on_path(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr('social_fetch.social_download.shutil.which', lambda _: None)
    monkeypatch.setattr('social_fetch.social_download.importlib.util.find_spec', lambda _: object())
    def run(command, **kwargs):
        assert command[:3] == [sys.executable, '-m', 'yt_dlp']
        assert '--ignore-config' in command and '--cookies-from-browser' not in command
        (tmp_path / 'raw.mp4').write_bytes(b'ftyp' + b'x' * 1024)
        (tmp_path / 'extracted-id.txt').write_text('12345678\n')
    monkeypatch.setattr('social_fetch.social_download.subprocess.run', run)
    acquire('https://x.com/NASA/status/12345678', tmp_path)


def test_specific_x_video_keeps_the_selector_and_checks_the_parent_post(tmp_path, monkeypatch):
    monkeypatch.setattr('social_fetch.social_download.shutil.which', lambda _: '/usr/bin/yt-dlp')
    def run(command, **kwargs):
        assert command[-1] == 'https://x.com/NASA/status/12345678/video/2'
        (tmp_path / 'raw.mp4').write_bytes(b'ftyp' + b'x' * 1024)
        (tmp_path / 'extracted-id.txt').write_text('12345678\n')
    monkeypatch.setattr('social_fetch.social_download.subprocess.run', run)
    acquire('https://x.com/NASA/status/12345678/video/2', tmp_path)
    assert json.loads((tmp_path / 'acquisition.json').read_text())['source_url'].endswith('/video/2')


def test_unreceipted_file_from_a_failed_attempt_cannot_be_relabelled_as_another_source(tmp_path, monkeypatch):
    old = b'ftyp' + b'old-video' * 256
    new = b'ftyp' + b'new-video' * 256
    (tmp_path / 'raw.mp4').write_bytes(old)
    monkeypatch.setattr('social_fetch.social_download.shutil.which', lambda _: '/usr/bin/yt-dlp')
    def run(command, **kwargs):
        # Model the extractor's default existing-file behavior. A prior failed
        # identity check may leave bytes without an accepted acquisition receipt.
        if '--force-overwrites' in command: (tmp_path / 'raw.mp4').write_bytes(new)
        (tmp_path / 'extracted-id.txt').write_text('12345678\n')
    monkeypatch.setattr('social_fetch.social_download.subprocess.run', run)
    acquire('https://x.com/NASA/status/12345678', tmp_path)
    assert (tmp_path / 'raw.mp4').read_bytes() == new


def test_checks_require_the_acquired_source_and_a_video_stream(tmp_path, monkeypatch):
    from social_fetch.social_download import digest, write_json
    raw = tmp_path / 'raw.mp4'
    raw.write_bytes(b'ftyp' + b'x' * 1024)
    url = 'https://x.com/NASA/status/12345678'
    write_json(tmp_path / 'acquisition.json', {'source_url': url, 'bytes': raw.stat().st_size, 'sha256': digest(raw)})
    def run(command, **kwargs):
        if str(command[-1]).endswith('.pending.mp4'): Path(command[-1]).write_bytes(raw.read_bytes())
    monkeypatch.setattr('social_fetch.social_download.subprocess.run', run)
    monkeypatch.setattr('social_fetch.social_download.subprocess.check_output', lambda *a, **k: json.dumps(
        {'streams': [{'codec_type': 'video', 'width': 720, 'height': 1280}, {'codec_type': 'audio'}], 'format': {'duration': '27'}}).encode())
    finalize(url, tmp_path, '12345678')
    receipt = json.loads((tmp_path / '12345678.receipt.json').read_text())
    assert receipt['downloaded'] and receipt['audio'] and receipt['decode_sample_seconds'] == 1
    raw.write_bytes(b'corrupted same length'.ljust(raw.stat().st_size, b'x'))
    with pytest.raises(ValueError, match='receipt'): finalize(url, tmp_path, '12345678')
