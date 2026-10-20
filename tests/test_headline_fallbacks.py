"""Selected-media and share-binding regressions for the fallback lane proposal."""
import io
import json
from urllib.error import HTTPError

import pytest

import social_fetch.social_download as download
import social_fetch.social_fallbacks as fallback
from social_fetch.social_sources import download_link, social_link

POST = '7542184870131305759'
FACEBOOK = '10155529876156509'
X_URL = 'https://x.com/buildingisgreen/status/1793226866335076588/video/2'


class Response(io.BytesIO):
    status = 200
    headers = {}


@pytest.mark.parametrize('url', ['https://vm.tiktok.com/ZMnewpost/',
    'https://vt.tiktok.com/ZSnewpost/', 'https://www.tiktok.com/t/ZSnewpost/',
    'https://vm.tiktok.com/1234567890123/', 'https://www.tiktok.com/t/1234567890123/'])
def test_tiktok_share_binds_native_redirect_before_provider(url, monkeypatch):
    calls = []
    class Opener:
        def open(self, req, **kwargs):
            calls.append(req.full_url)
            raise HTTPError(req.full_url, 302, 'redirect',
                {'Location': 'https://www.tiktok.com/@/video/' + POST + '?tracking=removed'}, None)
    monkeypatch.setattr(download, 'build_opener', lambda *_: Opener())
    link = download.resolve_selected_post(download_link(url))
    assert link.identity == POST and link.url == 'https://www.tiktok.com/@/video/' + POST
    assert calls == [url]
    assert social_link('https://www.tiktok.com/@') is None


@pytest.mark.parametrize('target', ['http://www.tiktok.com/@a/video/' + POST,
    'https://www.tiktok.com.evil.test/@a/video/' + POST,
    'https://127.0.0.1/video/' + POST, 'https://www.facebook.com/watch/?v=' + FACEBOOK,
    'https://www.tiktok.com/@a/video/' + POST + '#fragment'])
def test_share_redirect_rejects_escaped_platform_before_following(target, monkeypatch):
    calls = []
    class Opener:
        def open(self, req, **kwargs):
            calls.append(req.full_url)
            raise HTTPError(req.full_url, 302, 'redirect', {'Location': target}, None)
    monkeypatch.setattr(download, 'build_opener', lambda *_: Opener())
    with pytest.raises(ValueError, match='escaped'):
        download.resolve_selected_post(download_link('https://vt.tiktok.com/ZSnewpost/'))
    assert len(calls) == 1


def test_share_redirect_loop_is_bounded(monkeypatch):
    calls = []
    class Opener:
        def open(self, req, **kwargs):
            calls.append(req.full_url)
            raise HTTPError(req.full_url, 302, 'redirect', {'Location': req.full_url}, None)
    monkeypatch.setattr(download, 'build_opener', lambda *_: Opener())
    with pytest.raises(fallback.ProviderUnavailable, match='redirect bound'):
        download.resolve_selected_post(download_link('https://vt.tiktok.com/ZSnewpost/'))
    assert len(calls) == 6


def test_resolved_tiktok_rejects_a_different_provider_post(tmp_path, monkeypatch):
    canonical = download_link('https://www.tiktok.com/@a/video/' + POST)
    monkeypatch.setattr(download, 'resolve_selected_post', lambda _: canonical)
    body = {'code': 0, 'data': {'id': '7252940177100868865', 'play': 'https://www.tikwm.com/file.mp4'}}
    monkeypatch.setattr(download, 'tikwm_request', lambda *a: Response(json.dumps(body).encode()))
    with pytest.raises(ValueError, match='another post'):
        download.tiktok_download(download_link('https://vt.tiktok.com/ZSnewpost/'), tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('original_author', ['', 'stale_author'])
@pytest.mark.parametrize('failure', [None,'post','author'])
def test_tiktok_author_recovery_is_bound_to_the_native_selected_post(monkeypatch, failure, original_author):
    item = {'id':POST,'author':{'uniqueId':'native_author'}}
    if failure == 'post': item['id'] = '7252940177100868865'
    if failure == 'author': item['author']['uniqueId'] = '../../another'
    data = {'__DEFAULT_SCOPE__':{'webapp.video-detail':{'itemInfo':{'itemStruct':item}}}}
    html = '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">' + json.dumps(data) + '</script>'
    class Opener:
        def open(self, req, **kw): return Response(html.encode())
    monkeypatch.setattr(download, 'build_opener', lambda *a: Opener())
    link = download_link('https://www.tiktok.com/@' + original_author + '/video/' + POST)
    if failure:
        with pytest.raises(ValueError): download.tiktok_full_post(link)
    else:
        assert download.tiktok_full_post(link) == download_link('https://www.tiktok.com/@native_author/video/' + POST)


@pytest.mark.parametrize('target', ['https://127.0.0.1/native',
    'https://www.tiktok.com/@other/video/7252940177100868865'])
def test_tiktok_author_lookup_rejects_escaped_redirect_before_request(target, monkeypatch):
    calls = []
    def opener(handler):
        class Opener:
            def open(self, req, **kwargs):
                calls.append(req.full_url)
                return handler.redirect_request(req,None,302,'redirect',{},target)
        return Opener()
    monkeypatch.setattr(download,'build_opener',opener)
    with pytest.raises(ValueError, match='redirected'):
        download.tiktok_full_post(download_link('https://www.tiktok.com/@/video/' + POST))
    assert len(calls) == 1


@pytest.mark.parametrize('original_author', ['', 'stale_author'])
def test_ssstik_retries_only_after_native_author_recovery(tmp_path, monkeypatch, original_author):
    calls = []; recovered = []
    class Opener:
        def open(self, req, **kw):
            calls.append(req)
            if req.data is None: return Response(b"var s_tt = 'public-form-token';")
            if len(calls) == 2: return Response(b'')
            assert b'%40native_author%2Fvideo%2F' in req.data
            return Response(('<a href="https://tikcdn.io/ssstik/' + POST + '">HD</a>').encode())
    def full_post(link):
        recovered.append(link.identity)
        return download_link('https://www.tiktok.com/@native_author/video/' + POST)
    monkeypatch.setattr(fallback, 'build_opener', lambda *a: Opener())
    monkeypatch.setattr(download, 'tiktok_full_post', full_post)
    monkeypatch.setattr(download, 'progressive_transfer', lambda request,url,folder: url)
    assert fallback.ssstik_download(download_link('https://www.tiktok.com/@' + original_author + '/video/' + POST),tmp_path).endswith('/' + POST)
    assert recovered == [POST] and len(calls) == 4


@pytest.mark.parametrize('failure', [None,'post','host','missing'])
def test_ssstik_requires_selected_numeric_media_path_and_platform_host(tmp_path, monkeypatch, failure):
    calls = []
    identity = POST if failure != 'post' else '7252940177100868865'
    host = 'tikcdn.io' if failure != 'host' else 'tikcdn.io.evil.test'
    html = '<a href="https://' + host + '/ssstik/' + identity + '?st=private&amp;e=1">HD</a>'
    if failure == 'missing': html = '<a href="https://tikcdn.io/ssstik/a/music">MP3</a>'
    class Opener:
        def open(self, req, **kwargs):
            calls.append(req)
            if req.data is None: return Response(b"var s_tt = 'public-form-token';")
            assert ('id=https%3A%2F%2Fwww.tiktok.com%2F%40a%2Fvideo%2F'+POST).encode() in req.data
            return Response(html.encode())
    monkeypatch.setattr(fallback, 'build_opener', lambda *a: Opener())
    if failure == 'missing':
        monkeypatch.setattr(download, 'tiktok_full_post', lambda link: link)
    monkeypatch.setattr(download, 'progressive_transfer', lambda request, url, folder: url)
    link = download_link('https://www.tiktok.com/@a/video/' + POST)
    if failure:
        with pytest.raises(ValueError): fallback.ssstik_download(link,tmp_path)
    else:
        assert fallback.ssstik_download(link,tmp_path) == 'https://tikcdn.io/ssstik/' + POST + '?st=private&e=1'
    assert len(calls) == 2
    with pytest.raises(ValueError): fallback.checked_url('tiktok','https://ssstik.io/unbound.mp4',media=True)


@pytest.mark.parametrize('url, expected', [
    ('https://www.facebook.com/share/r/15B1URzika/', 'https://www.facebook.com/reel/1365309657880490'),
    ('https://www.facebook.com/share/v/1GdMNgXLSG/', 'https://www.facebook.com/okgo/videos/1755864954920657/'),
    ('https://www.facebook.com/share/r/123456789/', 'https://www.facebook.com/reel/1365309657880490'),
    ('https://www.facebook.com/share/v/123456789/', 'https://www.facebook.com/okgo/videos/1755864954920657/')])
def test_facebook_share_binds_numeric_native_post(url, expected, monkeypatch):
    class Opener:
        def open(self, req, **kwargs):
            raise HTTPError(req.full_url, 302, 'redirect', {'Location': expected}, None)
    monkeypatch.setattr(download, 'build_opener', lambda *_: Opener())
    resolved = download.resolve_selected_post(download_link(url))
    assert resolved == download_link(expected)
    assert resolved.identity.isdigit()


def facebook_page(video, *, canonical=FACEBOOK, recommendation=None):
    return ('<link rel="canonical" href="https://www.facebook.com/watch/?v=' + canonical + '">'
        '<script type="application/json">' + json.dumps({'selected': video, 'recommended': recommendation}) + '</script>')


@pytest.mark.parametrize('reel_fragment', [False, True])
def test_facebook_structured_video_uses_selected_id_and_browser_request(tmp_path, monkeypatch, reel_fragment):
    selected = {'__typename': 'Video', 'id': FACEBOOK,
                'videoDeliveryLegacyFields': {'id': FACEBOOK, 'browser_native_hd_url': 'https://video.xx.fbcdn.net/selected.mp4'}}
    if reel_fragment: selected.pop('__typename')
    recommendation = {'__typename': 'Video', 'id': '99999999',
                'videoDeliveryLegacyFields': {'browser_native_hd_url': 'https://127.0.0.1/recommendation.mp4'}}
    def document(platform, url, **kwargs):
        assert platform == 'facebook' and 'Chrome/' in kwargs['headers']['User-Agent']
        return facebook_page(selected, recommendation=recommendation)
    monkeypatch.setattr(fallback, 'document', document)
    monkeypatch.setattr(download, 'progressive_transfer', lambda request, url, folder: url)
    assert fallback.page_download(download_link('https://www.facebook.com/watch/?v=' + FACEBOOK),tmp_path).endswith('/selected.mp4')


@pytest.mark.parametrize('failure', ['parent', 'child', 'host'])
def test_facebook_structured_video_rejects_identity_or_host(tmp_path, monkeypatch, failure):
    selected = {'__typename': 'Video', 'id': FACEBOOK,
                'videoDeliveryLegacyFields': {'id': FACEBOOK, 'browser_native_hd_url': 'https://video.xx.fbcdn.net/selected.mp4'}}
    canonical = FACEBOOK
    if failure == 'parent': canonical = '99999999'
    if failure == 'child': selected['videoDeliveryLegacyFields']['id'] = '99999999'
    if failure == 'host': selected['videoDeliveryLegacyFields']['browser_native_hd_url'] = 'https://fbcdn.net.evil.test/selected.mp4'
    monkeypatch.setattr(fallback, 'document', lambda *a, **kw: facebook_page(selected,canonical=canonical))
    monkeypatch.setattr(download, 'progressive_transfer', lambda *a: pytest.fail('Unsafe transfer'))
    with pytest.raises(ValueError):
        fallback.page_download(download_link('https://www.facebook.com/watch/?v=' + FACEBOOK), tmp_path)
    assert not list(tmp_path.iterdir())


def test_facebook_recommendation_cannot_replace_missing_selected_media(tmp_path, monkeypatch):
    recommendation = {'__typename': 'Video', 'id': '99999999',
        'videoDeliveryLegacyFields': {'browser_native_hd_url': 'https://video.xx.fbcdn.net/recommendation.mp4'}}
    monkeypatch.setattr(fallback, 'document', lambda *a, **kw: facebook_page({}, recommendation=recommendation))
    monkeypatch.setattr(download, 'progressive_transfer', lambda *a: pytest.fail('Recommendation transfer'))
    with pytest.raises(fallback.ProviderUnavailable):
        fallback.page_download(download_link('https://www.facebook.com/watch/?v=' + FACEBOOK), tmp_path)


@pytest.mark.parametrize('failure', [None, 'post', 'selector', 'fragment', 'other_platform',
    'host', 'metadata_host_as_media', 'photo', 'missing_identity', 'ambiguous', 'nonprogressive'])
def test_fixupx_preserves_attachment_request_and_validates_selected_page(tmp_path, monkeypatch, failure):
    canonical = X_URL.rsplit('/video/', 1)[0]
    media = 'https://video.twimg.com/second.mp4'
    if failure == 'post': canonical = 'https://x.com/another/status/99999999'
    if failure == 'selector': canonical += '/video/3'
    if failure == 'fragment': canonical += '#another'
    if failure == 'other_platform': canonical = 'https://www.facebook.com/watch/?v=' + FACEBOOK
    if failure == 'host': media = 'https://video.twimg.com.evil.test/second.mp4'
    if failure == 'metadata_host_as_media': media = 'https://fixupx.com/second.mp4'
    if failure == 'nonprogressive': media = 'https://video.twimg.com/second.m3u8'
    html = '' if failure == 'missing_identity' else '<link rel="canonical" href="' + canonical + '">'
    if failure != 'photo': html += '<meta property="og:video" content="' + media + '">'
    if failure == 'ambiguous': html += '<meta property="og:video:secure_url" content="https://video.twimg.com/another.mp4">'
    calls = []
    class Opener:
        def open(self, req, **kwargs):
            calls.append(req.full_url)
            assert req.full_url == X_URL.replace('https://x.com/', 'https://fixupx.com/')
            assert req.get_header('User-agent') == 'Twitterbot/1.0'
            return Response(html.encode())
    transfers = []
    monkeypatch.setattr(fallback, 'build_opener', lambda *_: Opener())
    monkeypatch.setattr(fallback, 'transfer', lambda link, url, folder: transfers.append(url) or url)
    if failure:
        with pytest.raises(ValueError): fallback.fixupx_download(download_link(X_URL), tmp_path)
        assert transfers == []
    else:
        assert fallback.fixupx_download(download_link(X_URL), tmp_path) == media
        assert transfers == [media]
    assert len(calls) == 1


@pytest.mark.parametrize('target', [
    'http://fixupx.com/buildingisgreen/status/1793226866335076588/video/2',
    'https://api.fxtwitter.com/buildingisgreen/status/1793226866335076588/video/2',
    'https://video.twimg.com/second.mp4',
    'https://fixupx.com/buildingisgreen/status/99999999/video/2',
    'https://fixupx.com/buildingisgreen/status/1793226866335076588',
    'https://fixupx.com/buildingisgreen/status/1793226866335076588/video/3'])
def test_fixupx_redirect_cannot_change_host_post_or_attachment(target, tmp_path, monkeypatch):
    calls = []
    def opener(handler):
        class Opener:
            def open(self, req, **kwargs):
                calls.append(req.full_url)
                return handler.redirect_request(req, None, 302, 'redirect', {}, target)
        return Opener()
    monkeypatch.setattr(fallback, 'build_opener', opener)
    monkeypatch.setattr(fallback, 'transfer', lambda *a: pytest.fail('Invalid redirect transferred media'))
    with pytest.raises(ValueError): fallback.fixupx_download(download_link(X_URL), tmp_path)
    assert len(calls) == 1


def test_fixupx_metadata_size_bound_precedes_media_transfer(tmp_path, monkeypatch):
    class Opener:
        def open(self, req, **kwargs): return Response(b' ' * (2 * 1024**2 + 1))
    monkeypatch.setattr(fallback, 'build_opener', lambda *_: Opener())
    monkeypatch.setattr(fallback, 'transfer', lambda *a: pytest.fail('Oversized metadata transferred media'))
    with pytest.raises(ValueError, match='Oversized'):
        fallback.fixupx_download(download_link(X_URL), tmp_path)
