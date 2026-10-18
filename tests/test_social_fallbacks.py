"""Fallbacks preserve selected-post identity, transfer bounds and route isolation."""
import errno
import io
import json
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest

import social_fetch.social_download as download
import social_fetch.social_fallbacks as fallback
import social_fetch.youtube_fallback as youtube
from social_fetch.social_sources import download_link, LABELS

VIDEO = b'0000ftyp' + b'x' * 2048
X_URL = 'https://x.com/NASA/status/12345678/video/2'


def test_every_selected_social_has_an_explicit_alternative():
    assert set(fallback.FALLBACKS) == set(LABELS) - {'youtube'}
    assert all(name != download.PRIMARY_ROUTES[p] for p, (name, _) in fallback.FALLBACKS.items())


def test_outage_uses_clean_attempt_and_records_only_sanitized_route_names(tmp_path, monkeypatch):
    def primary(link, folder):
        (folder / 'raw.mp4').write_bytes(b'stale')
        raise URLError('https://delivery.example/private?token=secret')
    def alternative(link, folder):
        assert not (folder / 'raw.mp4').exists()
        assert link.url == X_URL
        path = folder / 'raw.mp4'
        path.write_bytes(VIDEO)
        return path
    monkeypatch.setattr(download, 'primary_download', primary)
    monkeypatch.setitem(fallback.FALLBACKS, 'x', ('fxtwitter', alternative))
    download.acquire(X_URL, tmp_path)
    receipt = json.loads((tmp_path / 'acquisition.json').read_text())
    assert receipt['route'] == 'fxtwitter'
    assert [a['status'] for a in receipt['route_attempts']] == ['unavailable', 'acquired']
    assert 'secret' not in json.dumps(receipt)
    assert (tmp_path / 'raw.mp4').read_bytes() == VIDEO
    assert not list(tmp_path.glob('attempt-*'))


@pytest.mark.parametrize('error', [ValueError('another post'), OSError(errno.ENOSPC, 'disk full')])
def test_validation_and_local_storage_errors_do_not_switch_provider(tmp_path, monkeypatch, error):
    def primary(*_): raise error
    def alternative(*_): pytest.fail('Unsafe fallback')
    monkeypatch.setattr(download, 'primary_download', primary)
    monkeypatch.setitem(fallback.FALLBACKS, 'x', ('fxtwitter', alternative))
    with pytest.raises(type(error)):
        download.acquire(X_URL, tmp_path)
    assert not (tmp_path / 'acquisition.json').exists()


def test_exhausted_routes_never_receipt_stale_media(tmp_path, monkeypatch):
    (tmp_path / 'raw.mp4').write_bytes(VIDEO)
    def failed(*_): raise URLError('private token')
    monkeypatch.setattr(download, 'primary_download', failed)
    monkeypatch.setitem(fallback.FALLBACKS, 'x', ('fxtwitter', failed))
    with pytest.raises(fallback.ProviderUnavailable, match='All public'):
        download.acquire(X_URL, tmp_path)
    assert not (tmp_path / 'raw.mp4').exists()
    assert not (tmp_path / 'acquisition.json').exists()
    assert len(json.loads((tmp_path / 'route-attempts.json').read_text())) == 2


@pytest.mark.parametrize('platform,url', [
    ('x', 'https://video.twimg.com.evil.test/video.mp4'),
    ('facebook', 'https://www.facebook.com/fake.mp4'),
    ('pinterest', 'https://127.0.0.1/file.mp4'),
    ('reddit', 'http://v.redd.it/file.mp4'),
    ('tiktok', 'https://user:secret@v16.tiktokcdn.com/file.mp4'),
    ('twitch', 'https://arbitrary.cloudfront.net/file.mp4'),
    ('mastodon', 'https://other.social/file.mp4'),
])
def test_fallback_media_hosts_remain_platform_specific(platform, url):
    with pytest.raises(ValueError): fallback.checked_url(platform, url, media=True)


def test_tiktok_observed_native_delivery_does_not_admit_the_whole_website():
    url = 'https://v19-webapp-prime.tiktok.com/video/tos/example.mp4'
    assert download.delivery_url('tiktok', url) == url
    with pytest.raises(ValueError): download.delivery_url('tiktok', 'https://www.tiktok.com/video.mp4')
    with pytest.raises(ValueError): download.delivery_url('tiktok', 'https://evil.tiktok.com/video.mp4')


def test_x_video_selector_preserves_attachment_order_and_post_id(tmp_path, monkeypatch):
    link = download_link(X_URL)
    data = {'code': 200, 'tweet': {'id': '12345678', 'media': {
        'all': [{'type': 'photo'}, {'type': 'video', 'url': 'https://video.twimg.com/second.mp4'}]}}}
    monkeypatch.setattr(fallback, 'document', lambda *a, **k: json.dumps(data))
    monkeypatch.setattr(fallback, 'transfer', lambda l, u, p: u)
    assert fallback.x_download(link, tmp_path).endswith('/second.mp4')
    data['tweet']['id'] = '12345679'
    with pytest.raises(ValueError, match='another post'): fallback.x_download(link, tmp_path)


def test_pinterest_native_metadata_is_bound_to_pin(tmp_path, monkeypatch):
    link = download_link('https://www.pinterest.com/pin/664281013778109217/')
    pin = {'id': link.identity, 'videos': {'video_list': {'v': {'url': 'https://v1.pinimg.com/a.mp4'}}}}
    monkeypatch.setattr(fallback, 'document', lambda *a, **k: json.dumps({'resource_response': {'data': pin}}))
    monkeypatch.setattr(fallback, 'transfer', lambda l, u, p: u)
    assert fallback.pinterest_download(link, tmp_path).endswith('/a.mp4')
    pin['id'] = 'another-pin'
    with pytest.raises(ValueError, match='another post'): fallback.pinterest_download(link, tmp_path)


def test_bluesky_repo_fallback_binds_the_handle_record_and_original_blob(tmp_path, monkeypatch):
    link = download_link('https://bsky.app/profile/bsky.app/post/3l3vgf77uco2g')
    did = 'did:plc:z72i7hdynmk6r22z27h6tvur'
    endpoint = 'https://puffball.us-east.host.bsky.network'
    record = {'uri': f'at://{did}/app.bsky.feed.post/3l3vgf77uco2g', 'value': {'embed': {
        '$type': 'app.bsky.embed.video', 'video': {'mimeType': 'video/mp4', 'size': len(VIDEO),
        'ref': {'$link': 'bafkreih7qpo7ef7hhtm7ehi7paimlieddrn5argpq4eayz6teez2qbsr7m'}}}}}
    monkeypatch.setattr(fallback, 'document', lambda *a, **k: json.dumps({'did': did}))
    def metadata(request, url):
        return {'service': [{'type': 'AtprotoPersonalDataServer', 'serviceEndpoint': endpoint}]} if 'plc.directory' in url else record
    monkeypatch.setattr(download, 'bounded_json', metadata)
    monkeypatch.setattr(download, 'progressive_transfer', lambda r, u, p, **k: (u, k['expected_size']))
    url, size = fallback.bluesky_download(link, tmp_path)
    assert url.startswith(endpoint + '/xrpc/com.atproto.sync.getBlob?') and size == len(VIDEO)
    record['uri'] += 'another'
    with pytest.raises(ValueError, match='another post'): fallback.bluesky_download(link, tmp_path)


def test_instagram_extractor_checks_parent_before_selecting_carousel_video(tmp_path, monkeypatch):
    link = download_link('https://www.instagram.com/p/DeWYHFHIkVC/')
    data = {'id': link.identity, '_type': 'playlist', 'extractor_key': 'Instagram', 'entries': [
        {'id': 'child', 'extractor_key': 'Instagram', 'ext': 'mp4', 'protocol': 'https',
         'url': 'https://cdn.cdninstagram.com/first-video.mp4'}]}
    monkeypatch.setattr(download.shutil, 'which', lambda _: '/usr/bin/yt-dlp')
    def run(command, **kwargs): kwargs['stdout'].write(json.dumps(data))
    monkeypatch.setattr(download.subprocess, 'run', run)
    monkeypatch.setattr(download, 'progressive_transfer', lambda r, u, p: u)
    assert fallback.extractor_download(link, tmp_path).endswith('/first-video.mp4')
    data['id'] = 'another-post'
    with pytest.raises(ValueError, match='another post'): fallback.extractor_download(link, tmp_path)


def test_snapchat_ignores_recommendations_and_selects_the_requested_story(tmp_path, monkeypatch):
    link = download_link('https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPwAAYYWtidGhudGZpAX1TKn0JAX1TKnXJAAAAAA')
    slug = link.url.rsplit('/', 1)[1]
    def story(key, url): return {'story': {'storyId': {'value': key}}, 'metadata': {'videoMetadata': {'contentUrl': url}}}
    data = {'props': {'pageProps': {'spotlightFeed': {'spotlightStories': [
        story('another', 'https://cf-st.sc-cdn.net/wrong.mp4'), story(slug, 'https://cf-st.sc-cdn.net/right.mp4')]}}}}
    monkeypatch.setattr(fallback, 'document', lambda *a, **k: '<script id="__NEXT_DATA__">' + json.dumps(data) + '</script>')
    monkeypatch.setattr(fallback, 'transfer', lambda l, u, p: u)
    assert fallback.snapchat_download(link, tmp_path).endswith('/right.mp4')


def test_linkedin_page_requires_matching_canonical_post(tmp_path, monkeypatch):
    link = download_link('https://www.linkedin.com/feed/update/urn:li:activity:7151241570371948544/')
    html = '<link rel="canonical" href="' + link.url + '"><video data-sources=\'' + json.dumps([
        {'type': 'video/mp4', 'src': 'https://dms.licdn.com/video/0/1704988854139'}]) + "'></video>"
    monkeypatch.setattr(fallback, 'document', lambda *a, **k: html)
    monkeypatch.setattr(fallback, 'transfer', lambda l, u, p: u)
    assert fallback.page_download(link, tmp_path).endswith('/0/1704988854139')
    html = html.replace('7151241570371948544', '7151241570371948545')
    with pytest.raises(ValueError, match='another post'): fallback.page_download(link, tmp_path)


def test_twitch_public_query_checks_slug_before_signed_transfer(tmp_path, monkeypatch):
    link = download_link('https://clips.twitch.tv/FaintLightGullWholeWheat')
    clip = {'slug': 'FaintLightGullWholeWheat', 'playbackAccessToken': {'signature': 'secret', 'value': '{}'},
            'assets': [{'videoQualities': [{'quality': '1080', 'sourceURL': 'https://assets.clips.twitchcdn.net/a.mp4'}]}]}
    monkeypatch.setattr(fallback, 'document', lambda *a, **k: json.dumps({'data': {'clip': clip}}))
    monkeypatch.setattr(fallback, 'transfer', lambda l, u, p: u)
    assert parse_qs(urlsplit(fallback.twitch_download(link, tmp_path)).query)['sig'] == ['secret']
    clip['slug'] = 'another'
    with pytest.raises(ValueError, match='another clip'): fallback.twitch_download(link, tmp_path)


def test_reddit_fallback_refuses_to_discard_split_audio(tmp_path, monkeypatch):
    link = download_link('https://www.reddit.com/r/videos/comments/6rrwyj/')
    video = {'has_audio': True, 'fallback_url': 'https://v.redd.it/example/DASH_720.mp4'}
    post = {'id': link.identity, 'is_video': True, 'secure_media': {'reddit_video': video}}
    monkeypatch.setattr(fallback, 'document', lambda *a, **k: json.dumps([{'data': {'children': [{'data': post}]}}]))
    monkeypatch.setattr(fallback, 'transfer', lambda l, u, p: u)
    with pytest.raises(fallback.ProviderUnavailable, match='split audio'): fallback.reddit_download(link, tmp_path)
    video['has_audio'] = False
    assert fallback.reddit_download(link, tmp_path).endswith('DASH_720.mp4')


def test_mastodon_activitypub_checks_public_audience_and_original_post(tmp_path, monkeypatch):
    link = download_link('https://mastodon.social/@mastodon/116839714185151652')
    post = {'url': link.url, 'type': 'Note', 'to': ['https://www.w3.org/ns/activitystreams#Public'],
            'attachment': [{'mediaType': 'video/mp4', 'url': 'https://files.mastodon.social/a.mp4'}]}
    monkeypatch.setattr(fallback, 'document', lambda *a, **k: json.dumps(post))
    monkeypatch.setattr(fallback, 'transfer', lambda l, u, p: u)
    assert fallback.mastodon_download(link, tmp_path).endswith('/a.mp4')
    post['to'] = []
    with pytest.raises(ValueError, match='nonpublic'): fallback.mastodon_download(link, tmp_path)


def test_cobalt_is_opt_in_and_cannot_redirect_to_an_unrelated_origin(monkeypatch, tmp_path):
    monkeypatch.delenv('SOCIAL_FETCH_COBALT_URL', raising=False)
    assert youtube.endpoint() is None
    monkeypatch.setenv('SOCIAL_FETCH_COBALT_URL', 'http://relay.example')
    with pytest.raises(ValueError, match='HTTPS origin'): youtube.endpoint()
    monkeypatch.setenv('SOCIAL_FETCH_COBALT_URL', 'https://relay.example')
    payload = {'status': 'tunnel', 'filename': 'youtube_jNQXAC9IVRw_720p.mp4', 'url': 'https://evil.test/file.mp4'}
    class Response(io.BytesIO):
        def __init__(self, value): super().__init__(json.dumps(value).encode())
    class Opener:
        def open(self, req, **kwargs):
            body = json.loads(req.data)
            assert body['alwaysProxy'] and body['downloadMode'] == 'auto'
            return Response(payload)
    monkeypatch.setattr(youtube, 'build_opener', lambda *_: Opener())
    with pytest.raises(ValueError, match='delivery origin'):
        youtube.acquire('https://www.youtube.com/watch?v=jNQXAC9IVRw', tmp_path, 'jNQXAC9IVRw', 720)
    payload['filename'] = 'youtube_another-id_720p.mp4'
    with pytest.raises(ValueError, match='selected-video'):
        youtube.acquire('https://www.youtube.com/watch?v=jNQXAC9IVRw', tmp_path, 'jNQXAC9IVRw', 720)


def test_youtube_outage_can_use_configured_independent_relay(monkeypatch, tmp_path):
    import social_fetch.youtube_web as web
    monkeypatch.setenv('SOCIAL_FETCH_COBALT_URL', 'https://relay.example')
    def failed(*a, **k): raise URLError('service outage')
    monkeypatch.setattr(web, 'snapyt_acquire', failed)
    marker = {'route': 'configured_cobalt'}
    monkeypatch.setattr(youtube, 'acquire', lambda *a: marker)
    assert web.acquire('https://youtu.be/jNQXAC9IVRw', tmp_path, 1080, download_only=True) == marker
    def invalid(*a, **k): raise ValueError('Download option does not match the requested video')
    monkeypatch.setattr(web, 'snapyt_acquire', invalid)
    with pytest.raises(ValueError, match='does not match'):
        web.acquire('https://youtu.be/jNQXAC9IVRw', tmp_path, 1080, download_only=True)


def test_configured_cobalt_tunnel_receipts_complete_bytes_and_requires_audio(monkeypatch, tmp_path):
    monkeypatch.setenv('SOCIAL_FETCH_COBALT_URL', 'https://relay.example:443')
    payload = {'status': 'tunnel', 'filename': 'youtube_jNQXAC9IVRw_720p.mp4',
               'url': 'https://relay.example/tunnel?opaque=delivery-token'}
    class Response(io.BytesIO):
        status = 200
        def __init__(self, value):
            super().__init__(value)
            self.headers = {'Content-Length': str(len(value))}
    class Opener:
        def open(self, req, **kwargs):
            if req.data:
                assert json.loads(req.data)['filenameStyle'] == 'classic'
                return Response(json.dumps(payload).encode())
            return Response(VIDEO)
    monkeypatch.setattr(youtube, 'build_opener', lambda *_: Opener())
    url = 'https://www.youtube.com/watch?v=jNQXAC9IVRw'
    saved = youtube.acquire(url, tmp_path, 'jNQXAC9IVRw', 720)
    assert saved['bytes'] == len(VIDEO) and 'delivery-token' not in json.dumps(saved)
    def run(command, **kwargs):
        if str(command[-1]).endswith('.pending.mp4'):
            Path(command[-1]).write_bytes(VIDEO)
    monkeypatch.setattr(download.subprocess, 'run', run)
    monkeypatch.setattr(download.subprocess, 'check_output', lambda *a, **k: json.dumps({
        'streams': [{'codec_type': 'video', 'width': 720, 'height': 1280}],
        'format': {'duration': '20'}}).encode())
    with pytest.raises(ValueError, match='preserve audio'):
        youtube.finalize(url, 'jNQXAC9IVRw', tmp_path)
    assert not (tmp_path / 'jNQXAC9IVRw.receipt.json').exists()
    assert not (tmp_path / 'jNQXAC9IVRw.mp4').exists()
