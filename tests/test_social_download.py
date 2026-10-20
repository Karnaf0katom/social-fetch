import io
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from social_fetch.social_download import (acquire, finalize, tikwm_url, tiktok_download,
                                    bluesky_url, progressive_transfer)
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


@pytest.mark.parametrize('url', ['https://puffball.us-east.host.bsky.network.evil.test/file',
    'https://127.0.0.1/file', 'https://user:secret@puffball.us-east.host.bsky.network/file',
    'http://puffball.us-east.host.bsky.network/file', 'https://example.org/xrpc/com.atproto.sync.getBlob'])
def test_bluesky_delivery_rejects_custom_storage_and_spoofed_hosts(url):
    with pytest.raises(ValueError): bluesky_url(url)


def bluesky_fixture():
    did = 'did:plc:z72i7hdynmk6r22z27h6tvur'
    video = b'0000ftyp' + b'x' * 2048
    post = {'uri': f'at://{did}/app.bsky.feed.post/3l3vgf77uco2g',
            'author': {'did': did, 'handle': 'bsky.app'}, 'record': {'embed': {
                '$type': 'app.bsky.embed.video', 'video': {'mimeType': 'video/mp4',
                'size': len(video), 'ref': {'$link': 'bafkreih7qpo7ef7hhtm7ehi7paimlieddrn5argpq4eayz6teez2qbsr7m'}}}}}
    return post, video


@pytest.mark.parametrize('failure', ['identity', 'quote', 'external_storage', 'truncated', None])
def test_bluesky_native_video_is_bound_to_post_and_complete_blob(tmp_path, monkeypatch, failure):
    from social_fetch.social_download import bluesky_download
    post, video = bluesky_fixture()
    if failure == 'identity': post['author']['handle'] = 'other.bsky.social'
    if failure == 'quote':
        post['record']['embed'] = {'$type': 'app.bsky.embed.record', 'record': post['record']['embed']}
    endpoint = 'https://example.org' if failure == 'external_storage' else 'https://puffball.us-east.host.bsky.network'
    calls = []
    def request(url):
        calls.append(url)
        if 'getPostThread' in url: return Response(json.dumps({'thread': {'post': post}}).encode())
        if 'plc.directory' in url:
            return Response(json.dumps({'service': [{'type': 'AtprotoPersonalDataServer', 'serviceEndpoint': endpoint}]}).encode())
        return Response(video[:-1] if failure == 'truncated' else video)
    monkeypatch.setattr('social_fetch.social_download.bluesky_request', request)
    link = download_link('https://bsky.app/profile/bsky.app/post/3l3vgf77uco2g')
    if failure:
        with pytest.raises(ValueError): bluesky_download(link, tmp_path)
        assert not (tmp_path / 'raw.mp4').exists() and not (tmp_path / 'raw.part').exists()
        assert not any('example.org' in url for url in calls)
    else:
        acquire(link.url, tmp_path)
        receipt = json.loads((tmp_path / 'acquisition.json').read_text())
        assert receipt['bytes'] == len(video) and receipt['platform'] == 'bluesky'
        assert 'getBlob' not in json.dumps(receipt)


def test_progressive_video_bound_is_enforced_without_content_length(tmp_path, monkeypatch):
    response = Response(b'0000ftyp' + b'x' * 2048)
    response.headers.clear()
    monkeypatch.setattr('social_fetch.social_download.MAX_BYTES', 1024)
    with pytest.raises(ValueError, match='size or time'):
        progressive_transfer(lambda _: response, 'https://v1.pinimg.com/file', tmp_path)
    assert not (tmp_path / 'raw.mp4').exists() and not (tmp_path / 'raw.part').exists()


@pytest.mark.parametrize('failure', ['identity', 'manifest', 'host', None])
def test_secondary_extractor_cannot_cross_posts_or_escape_progressive_cdn(tmp_path, monkeypatch, failure):
    from social_fetch.social_download import delivery_url
    from social_fetch.social_fallbacks import FALLBACKS, ProviderUnavailable
    def unavailable(*_): raise ProviderUnavailable('Offline alternative unavailable')
    monkeypatch.setitem(FALLBACKS, 'pinterest', ('pinterest_public_api', unavailable))
    monkeypatch.setattr('social_fetch.social_download.shutil.which', lambda _: '/usr/bin/yt-dlp')
    video = b'0000ftyp' + b'x' * 2048
    def run(command, **kwargs):
        assert command[command.index('--use-extractors') + 1] == 'Pinterest'
        data = {'id': '664281013778109217' if failure != 'identity' else '664281013778109218',
                'extractor_key': 'Pinterest', 'ext': 'mp4',
                'protocol': 'm3u8_native' if failure == 'manifest' else 'https',
                'url': 'https://127.0.0.1/file' if failure == 'host' else 'https://v1.pinimg.com/file.mp4'}
        kwargs['stdout'].write(json.dumps(data))
    monkeypatch.setattr('social_fetch.social_download.subprocess.run', run)
    def request(platform, url):
        delivery_url(platform, url)
        return Response(video)
    monkeypatch.setattr('social_fetch.social_download.delivery_request', request)
    if failure:
        with pytest.raises(ValueError): acquire('https://www.pinterest.com/pin/664281013778109217/', tmp_path)
        assert not (tmp_path / 'acquisition.json').exists()
    else:
        acquire('https://www.pinterest.com/pin/664281013778109217/', tmp_path)
        assert (tmp_path / 'raw.mp4').read_bytes() == video
    assert not (tmp_path / 'extractor-private.json').exists()


@pytest.mark.parametrize('failure', ['private', 'identity', 'image', 'host', None])
def test_mastodon_accepts_only_the_selected_public_native_attachment(tmp_path, monkeypatch, failure):
    from social_fetch.social_download import mastodon_url
    url = 'https://mastodon.social/@mastodon/116839714185151652'
    video = b'0000ftyp' + b'x' * 2048
    post = {'id': '116839714185151652', 'url': url, 'visibility': 'public',
            'media_attachments': [{'type': 'gifv', 'url': 'https://files.mastodon.social/file.mp4'}]}
    if failure == 'private': post['visibility'] = 'private'
    if failure == 'identity': post['url'] = url.replace('@mastodon', '@other')
    if failure == 'image': post['media_attachments'][0]['type'] = 'image'
    if failure == 'host': post['media_attachments'][0]['url'] = 'https://127.0.0.1/file.mp4'
    def request(url):
        mastodon_url(url)
        return Response(json.dumps(post).encode()) if '/api/v1/' in url else Response(video)
    monkeypatch.setattr('social_fetch.social_download.mastodon_request', request)
    if failure:
        with pytest.raises(ValueError): acquire(url, tmp_path)
        assert not (tmp_path / 'acquisition.json').exists()
    else:
        acquire(url, tmp_path)
        assert (tmp_path / 'raw.mp4').read_bytes() == video


@pytest.mark.parametrize('platform,url', [
    ('pinterest', 'https://v1.pinimg.com.evil.test/file.mp4'),
    ('twitch', 'https://arbitrary.cloudfront.net/file.mp4'),
    ('snapchat', 'https://sc-cdn.net.evil.test/file.mp4'),
    ('linkedin', 'https://user:password@dms.licdn.com/file.mp4'),
])
def test_secondary_redirects_validate_each_destination(platform, url):
    from social_fetch.social_download import delivery_request
    with pytest.raises(ValueError): delivery_request(platform, url)


def test_generic_extraction_is_one_post_with_no_implicit_browser_or_host_config(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr('social_fetch.social_download.shutil.which', lambda _: '/usr/bin/yt-dlp')
    def run(command, **kwargs):
        commands.append(command)
        target = Path(command[command.index('--output') + 1])
        target.write_bytes(b'ftyp' + b'x' * 1024)
        (target.parent / 'extracted-id.txt').write_text('12345678\n')
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
        target = Path(command[command.index('--output') + 1])
        target.write_bytes(b'ftyp' + b'x' * 1024)
        (target.parent / 'extracted-id.txt').write_text('12345678\n')
    monkeypatch.setattr('social_fetch.social_download.subprocess.run', run)
    acquire('https://x.com/NASA/status/12345678', tmp_path)


def test_specific_x_video_keeps_the_selector_and_checks_the_parent_post(tmp_path, monkeypatch):
    monkeypatch.setattr('social_fetch.social_download.shutil.which', lambda _: '/usr/bin/yt-dlp')
    def run(command, **kwargs):
        assert command[-1] == 'https://x.com/NASA/status/12345678/video/2'
        target = Path(command[command.index('--output') + 1])
        target.write_bytes(b'ftyp' + b'x' * 1024)
        (target.parent / 'extracted-id.txt').write_text('12345678\n')
    monkeypatch.setattr('social_fetch.social_download.subprocess.run', run)
    acquire('https://x.com/NASA/status/12345678/video/2', tmp_path)
    assert json.loads((tmp_path / 'acquisition.json').read_text())['source_url'].endswith('/video/2')


def test_reddit_alphanumeric_post_identity_must_match_before_receipting(tmp_path, monkeypatch):
    def wrong_post(*args):
        return '<div id="canonical-url-updater" value="https://www.reddit.com/r/videos/comments/anotherpost/"></div><shreddit-screenview-data data="{}"></shreddit-screenview-data>'
    monkeypatch.setattr('social_fetch.reddit_web._document', wrong_post)
    with pytest.raises(ValueError, match='another post'):
        acquire('https://www.reddit.com/r/videos/comments/6rrwyj/', tmp_path)
    assert not (tmp_path / 'acquisition.json').exists()


def test_unreceipted_file_from_a_failed_attempt_cannot_be_relabelled_as_another_source(tmp_path, monkeypatch):
    old = b'ftyp' + b'old-video' * 256
    new = b'ftyp' + b'new-video' * 256
    (tmp_path / 'raw.mp4').write_bytes(old)
    monkeypatch.setattr('social_fetch.social_download.shutil.which', lambda _: '/usr/bin/yt-dlp')
    def run(command, **kwargs):
        # Model the extractor's default existing-file behavior. A prior failed
        # identity check may leave bytes without an accepted acquisition receipt.
        target = Path(command[command.index('--output') + 1])
        if '--force-overwrites' in command: target.write_bytes(new)
        (target.parent / 'extracted-id.txt').write_text('12345678\n')
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
