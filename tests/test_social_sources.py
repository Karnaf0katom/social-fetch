import json
from types import SimpleNamespace
import pytest

from social_fetch.social_sources import social_link, download_link
from social_fetch.social_accounts import AccountSearch
from social_fetch.web_search import FootageSearch, SearchBatch, SearchUnavailable, candidate
from social_fetch.download_jobs import DownloadJobs


@pytest.mark.parametrize('url,platform,kind', [
    ('https://www.instagram.com/reel/DEXM4VgtQZM/?igsh=x', 'instagram', 'video'),
    ('https://www.instagram.com/NASA/reels/', 'instagram', 'account'),
    ('https://www.tiktok.com/@patroxofficial/video/6742501081818877190', 'tiktok', 'video'),
    ('https://www.tiktok.com/@nasa', 'tiktok', 'account'),
    ('https://vm.tiktok.com/ZMabcdefg/', 'tiktok', 'video'),
    ('https://twitter.com/NASA/status/12345678/video/1', 'x', 'video'),
    ('https://twitter.com/i/web/status/12345678', 'x', 'video'),
    ('https://x.com/NASA', 'x', 'account'),
    ('https://www.facebook.com/nasa/videos/12345678/', 'facebook', 'video'),
    ('https://www.facebook.com/reel/12345678', 'facebook', 'video'),
    ('https://www.facebook.com/NASA', 'facebook', 'account'),
    ('https://www.reddit.com/user/someone/', 'reddit', 'account'),
    ('https://www.reddit.com/r/space/comments/abc123/rocket/', 'reddit', 'video'),
    ('https://www.youtube.com/@NASA/shorts', 'youtube', 'account'),
])
def test_public_post_and_account_recognition(url, platform, kind):
    link = social_link(url)
    assert link.platform == platform and link.kind == kind
    assert 'igsh=' not in link.url
    item = candidate({'url': url, 'title': 'NASA'}, provider='test')
    assert item['kind'] == kind
    if kind == 'account':
        assert item['preview']['kind'] == 'source'
        with pytest.raises(ValueError): download_link(url)


@pytest.mark.parametrize('url', ['http://127.0.0.1/video', 'https://instagram.com.evil.test/reel/ABCDE/',
    'https://user:password@x.com/NASA/status/12345678', 'https://www.instagram.com/accounts/login/',
    'https://shop.tiktok.com/us/k/rocket', 'https://www.facebook.com/search/', 'https://x.com/search',
    'https://www.tiktok.com@127.0.0.1/video/12345678901', 'https://x.com:8080/NASA/status/12345678'])
def test_non_content_and_private_links_never_enable_download(url):
    assert social_link(url) is None
    with pytest.raises(ValueError): download_link(url)


def test_x_media_selector_does_not_silently_download_another_video():
    base = download_link('https://x.com/NASA/status/12345678')
    first = download_link('https://twitter.com/NASA/status/12345678/video/1')
    second = download_link('https://x.com/NASA/status/12345678/video/2')
    assert first.url == base.url and first.identity == base.identity
    assert second.url.endswith('/video/2') and second.identity != base.identity
    with pytest.raises(ValueError): download_link('https://x.com/NASA/status/12345678/photo/2')
    anonymous = download_link('https://twitter.com/i/web/status/12345678')
    assert anonymous.identity == base.identity and not anonymous.handle


class Index:
    name, _key = 'test', 'not-public'
    def __init__(self): self.calls = []
    def search(self, query, category, page, count):
        self.calls.append((query, category, page, count))
        return SearchBatch([
            {'url': 'https://www.instagram.com/nasa/', 'title': 'NASA account'},
            {'url': 'https://www.instagram.com/reel/ABCDE12345/', 'title': 'NASA launch'},
            {'url': 'https://shop.tiktok.com/us/k/nasa', 'title': 'NASA account'},
            {'url': 'https://x.com/NASA', 'title': 'NASA account'},
            {'url': 'https://x.com/NASA/status/12345678', 'title': 'NASA launch'},
            {'url': 'https://x.com/other/status/12345679', 'title': 'NASA launch'},
        ], False)


def test_cross_platform_account_search_is_bounded_and_filters_other_pages():
    index = Index()
    result = FootageSearch(index).search('NASA', source='social', intent='accounts')
    assert len(index.calls) == 6 and all(call[1] == 'page' for call in index.calls)
    assert {row['source'] for row in result['results']} == {'Instagram', 'X'}
    assert all(row['kind'] == 'account' for row in result['results'])
    assert len(result['sources']) == 6
    assert 'not-public' not in json.dumps(result)


def test_account_search_on_default_sources_routes_to_social_and_keeps_video_cache_separate():
    service = FootageSearch(Index())
    result = service.search('NASA', intent='accounts', source='all')
    assert result['source'] == 'social'
    videos = service.search('NASA', source='social')
    assert any(row['kind'] == 'video' for row in videos['results'])
    assert service.search('NASA', intent='accounts', source='all')['cached']


def test_indexed_account_browsing_enforces_actual_handle():
    index = Index()
    result = AccountSearch().browse('https://twitter.com/NASA', FootageSearch(index), count=3)
    assert len(result['results']) == 1
    assert result['results'][0]['url'] == 'https://x.com/NASA/status/12345678'
    assert 'site:x.com/nasa/' in index.calls[0][0]
    assert 'Indexed' in result['warnings'][0]


def test_reddit_community_name_is_not_evidence_of_account_ownership():
    class RedditIndex(Index):
        def search(self, *args):
            return SearchBatch([
                {'url': 'https://www.reddit.com/r/someone/comments/abc123/rocket/', 'title': 'Rocket'},
                {'url': 'https://www.reddit.com/user/someone/comments/def123/rocket/', 'title': 'Rocket'},
            ], False)
    result = AccountSearch().browse('https://www.reddit.com/user/someone/', FootageSearch(RedditIndex()))
    assert len(result['results']) == 1
    assert '/user/someone/comments/' in result['results'][0]['url']


def test_instagram_account_sample_never_returns_expiring_media_or_collection_tokens(monkeypatch):
    def discover(handle, **options):
        assert handle == 'nasa' and options == {'limit': 3, 'max_pages': 2}
        return [{'source_url': 'https://www.instagram.com/p/ABCDE12345/', 'caption': 'Rocket',
                 'media_url': 'https://cdn.example/secret', 'collection': 'secret'}], {'page_bound_reached': True}
    monkeypatch.setattr('social_fetch.instagram_web.discover_profile', discover)
    service = AccountSearch()
    result = service.browse('https://www.instagram.com/nasa/', FootageSearch(Index()), count=3)
    assert len(result['results']) == 1 and 'secret' not in json.dumps(result)
    assert not result['has_more'] and 'sample' in result['warnings'][0]
    assert service.browse('https://www.instagram.com/nasa/', FootageSearch(Index()), count=3)['cached']
    with pytest.raises(ValueError): service.browse('https://instagram.com/nasa/', FootageSearch(Index()), count=100)


def test_public_profile_outage_is_not_an_empty_complete_account(monkeypatch):
    def fail(*a, **k): raise RuntimeError('secret viewer token')
    monkeypatch.setattr('social_fetch.instagram_web.discover_profile', fail)
    with pytest.raises(SearchUnavailable, match='public Instagram') as caught:
        AccountSearch().browse('https://www.instagram.com/nasa/', FootageSearch(Index()))
    assert 'secret' not in str(caught.value)


def test_social_aliases_share_download_jobs_and_accounts_never_launch(tmp_path, monkeypatch):
    import os
    calls = []
    monkeypatch.setattr('social_fetch.download_jobs.shutil.disk_usage', lambda _: SimpleNamespace(free=64 * 1024**3))
    monkeypatch.setattr('social_fetch.download_jobs.subprocess.Popen', lambda *a, **k: calls.append(a) or SimpleNamespace(pid=os.getpid()))
    jobs = DownloadJobs(tmp_path)
    first = jobs.submit('ours', 'https://instagram.com/reel/ABCDE12345/?igsh=tracking')
    assert jobs.submit('ours', 'https://www.instagram.com/p/ABCDE12345/')['id'] == first['id']
    assert first['platform'] == 'instagram' and len(calls) == 1
    with pytest.raises(ValueError): jobs.submit('ours', 'https://www.instagram.com/nasa/')
    assert len(calls) == 1


def test_partial_social_search_survives_a_platform_index_outage():
    class Partial(Index):
        def search(self, query, *args):
            if 'site:tiktok.com' in query: raise SearchUnavailable('Index unavailable')
            return super().search(query, *args)
    service = FootageSearch(Partial())
    result = service.search('NASA', source='social')
    assert result['results'] and result['warnings'] and not result['cached']
    assert any(row['status'] == 'unavailable' for row in result['sources'])
    assert not service.search('NASA', source='social')['cached']


def test_public_social_videos_use_supported_video_backend_and_distinct_web_fallback(monkeypatch):
    import sys
    from importlib.machinery import ModuleSpec
    from social_fetch.web_search import PublicIndex
    calls = []
    class DDGS:
        def __init__(self, **options): pass
        def videos(self, query, **options):
            calls.append(('video', options['backend']))
            raise RuntimeError('private transport diagnostic')
        def text(self, query, **options):
            calls.append(('page', options['backend']))
            return [{'content': 'https://www.tiktok.com/@person/video/6742501081818877190',
                     'title': 'Dance tutorial', 'duration': '0:27'}]
    monkeypatch.setitem(sys.modules, 'ddgs', SimpleNamespace(DDGS=DDGS, __spec__=ModuleSpec('ddgs', None)))
    result = FootageSearch(PublicIndex()).search('dance tutorial', source='tiktok')
    assert len(result['results']) == 1 and result['results'][0]['duration_seconds'] == 27
    assert calls == [('video', 'duckduckgo'), ('page', 'bing')]
    assert 'diagnostic' not in json.dumps(result)


def test_social_search_falls_back_after_irrelevant_results_and_recognizes_exact_handles(monkeypatch):
    import sys
    from importlib.machinery import ModuleSpec
    from social_fetch.web_search import PublicIndex
    calls = []
    class DDGS:
        def __init__(self, **options): pass
        def text(self, query, **options):
            calls.append(options)
            if options['backend'] == 'bing':
                return [{'href': 'https://www.instagram.com/explore/', 'title': 'NASA'},
                        {'href': 'https://example.org/nasa', 'title': 'NASA'}]
            return [{'href': 'https://www.instagram.com/nasa/', 'title': 'Link to instagram.com'}]
    monkeypatch.setitem(sys.modules, 'ddgs', SimpleNamespace(DDGS=DDGS, __spec__=ModuleSpec('ddgs', None)))
    result = FootageSearch(PublicIndex()).search('NASA', source='instagram', intent='accounts', count=1)
    assert len(result['results']) == 1 and result['results'][0]['creator'] == 'nasa'
    assert [call['backend'] for call in calls] == ['bing', 'yahoo']
    assert all(call['max_results'] == 12 for call in calls)


def test_empty_social_discovery_explains_recovery_and_does_not_cache_a_false_success():
    class Empty(Index):
        def search(self, *args): return SearchBatch([], False)
    service = FootageSearch(Empty())
    for _ in range(2):
        result = service.search('unlikely subject', source='instagram')
        assert not result['results'] and not result['cached']
        assert 'paste a post link' in result['warnings'][0]
        assert result['sources'][0]['status'] == 'partial'


def test_instagram_parser_retains_video_poster_for_private_thumbnail_delivery():
    from social_fetch.instagram_web import Form, videos, shortcode_id
    code = 'ABCDE12345'
    form = Form(f'<article data-post-id="{code}"><div data-collection="private">'
                f'<div data-media-type="video" data-media-id="{shortcode_id(code)}_1" '
                'data-media-src="https://instacdn.beubagah.com/video" '
                'data-media-poster="https://instacdn.beubagah.com/poster?token=private"></div></div></article>')
    assert videos(form)[0]['poster_url'].endswith('poster?token=private')
