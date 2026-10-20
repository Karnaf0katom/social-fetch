"""The discovery boundary admits references, not video files or arbitrary HTML."""

import json
from urllib.error import HTTPError

import pytest

from social_fetch.web_search import (
    BraveIndex, FootageSearch, SearchBatch, SearchBusy, SearchUnavailable,
    SerperIndex, candidate, duration_seconds, index_json, public_url,
)


class Index:
    name = 'test'
    _key = 'server-only-key'

    def __init__(self, video=None, pages=None):
        self.video = video or []
        self.pages = pages or []
        self.calls = []

    def search(self, query, category, page, count):
        self.calls.append((query, category, page, count))
        rows = self.video if category == 'video' else self.pages
        if isinstance(rows, Exception):
            raise rows
        return SearchBatch(rows, False)


def test_video_and_web_results_deduplicate_assets_and_preserve_original_sources():
    index = Index([
        {'url': 'https://youtu.be/VQRLujxTm3c?si=tracking', 'title': 'GTA VI trailer',
         'embed_html': '<script>bad()</script>', 'embed_url': 'http://localhost/secret'},
        {'url': 'https://vimeo.com/123456789', 'title': 'City footage', 'duration': '01:30'},
    ], [
        {'url': 'https://www.youtube.com/watch?v=VQRLujxTm3c&utm_source=index',
         'title': 'Duplicate trailer', 'description': 'Original publisher', 'duration': '02:18'},
        {'url': 'https://www.rockstargames.com/VI/media/videos', 'title': 'GTA VI videos'},
        {'url': 'http://169.254.169.254/latest', 'title': 'Do not admit'},
    ])
    result = FootageSearch(index).search('GTA 6', namespace='ours')
    assert len(result['results']) == 3
    video, vimeo, publisher = result['results']
    assert video['url'] == 'https://www.youtube.com/watch?v=VQRLujxTm3c'
    assert video['duration_seconds'] == 138
    assert video['description'] == 'Original publisher'
    assert video['preview'] == {'kind': 'embed', 'url': 'https://www.youtube-nocookie.com/embed/VQRLujxTm3c'}
    assert vimeo['duration_seconds'] == 90
    assert publisher['kind'] == 'page'
    assert publisher['preview']['kind'] == 'source'
    assert {call[1] for call in index.calls} == {'video', 'page'}
    assert len(index.calls) == 2
    assert 'GTA VI' in result['effective_query']
    assert 'server-only-key' not in json.dumps(result)
    assert 'embed_html' not in json.dumps(result)




def test_focused_collections_enforce_host_and_subject_even_when_an_index_ignores_operators():
    index = Index(pages=[
        {'url': 'https://vimeo.com/123456789', 'title': 'City night film'},
        {'url': 'https://www.nowness.com/story/night-city', 'title': 'City at night'},
        {'url': 'https://vimeo.com/987654321', 'title': 'Unrelated animation'},
        {'url': 'https://www.youtube.com/watch?v=VQRLujxTm3c', 'title': 'City at night'},
        {'url': 'https://vimeo.com.attacker.example/film', 'title': 'City at night'},
    ])
    result = FootageSearch(index).search('city night', source='creative')
    assert len(index.calls) == 1 and index.calls[0][1] == 'page'
    assert 'site:vimeo.com' in index.calls[0][0]
    assert [item['source'] for item in result['results']] == ['Vimeo', 'NOWNESS']
    assert result['source'] == 'creative' and result['sources'][0]['id'] == 'creative'




def test_discovery_status_exposes_explicit_scopes_and_preserves_existing_sources():
    service = FootageSearch(Index())
    sources = {row['id']: row for row in service.status()['sources']}
    assert {'web', 'custom', 'creative', 'stock', 'culture',
            'youtube', 'instagram', 'tiktok', 'scenes', 'social', 'x', 'facebook', 'reddit'} <= set(sources)
    assert sources['youtube']['label'] == 'YouTube & Shorts'
    assert sources['scenes']['label'] == 'TV & movie clips'
    assert all(row['configured'] for row in sources.values())


@pytest.mark.parametrize('scope, domains, urls', [
    ('youtube', ('youtube.com', 'youtu.be'), [
        'https://www.youtube.com/watch?v=VQRLujxTm3c',
        'https://m.youtube.com/shorts/QdBZY2fkU-0',
        'https://youtu.be/abcdefghij0',
    ]),
    ('instagram', ('instagram.com',), [
        'https://instagram.com/reel/citynight/',
        'https://www.instagram.com/p/citynight/',
        'https://m.instagram.com/reel/citynight/',
    ]),
    ('tiktok', ('tiktok.com',), [
        'https://www.tiktok.com/@creator/video/6742501081818877190',
        'https://vm.tiktok.com/citynight/',
        'https://tiktok.com/@creator/video/6742501081818877191',
    ]),
    ('scenes', ('clip.cafe', 'getyarn.io', 'moviefone.com', 'youtube.com', 'dailymotion.com'), [
        'https://clip.cafe/movie/city-night/',
        'https://getyarn.io/yarn-clip/city-night',
        'https://www.moviefone.com/movie/city-night/videos/',
        'https://www.youtube.com/watch?v=VQRLujxTm3c',
        'https://www.dailymotion.com/video/x123456',
    ]),
])
def test_explicit_scopes_use_one_bounded_index_query_and_validate_hosts_and_relevance(
        monkeypatch, scope, domains, urls):
    def forbid(*args, **kwargs):
        raise AssertionError('discovery must not fetch result pages or media')
    monkeypatch.setattr('social_fetch.web_search.build_opener', forbid)
    rows = [{'url': url, 'title': 'City night clip'} for url in urls]
    for domain in domains:
        rows.extend([
            {'url': f'https://{domain}.attacker.example/clip', 'title': 'City night clip'},
            {'url': f'https://not{domain}/clip', 'title': 'City night clip'},
            {'url': f'https://{domain}/unrelated', 'title': 'Unrelated cooking tutorial'},
            {'url': f'https://attacker.example/clip?site={domain}', 'title': 'City night clip'},
        ])
    rows.append({'url': 'http://127.0.0.1/clip', 'title': 'City night clip'})
    index = Index(pages=rows)
    result = FootageSearch(index).search('city night', source=scope, page=2, count=40)
    assert len(index.calls) == 1
    phrase, category, page, count = index.calls[0]
    assert phrase == 'city night (' + ' OR '.join('site:' + domain for domain in domains) + ')'
    assert (category, page, count) == ('page', 2, 12)
    assert {item['url'] for item in result['results']} == {
        candidate({'url': url}, provider='test')['url'] for url in urls}
    assert result['source'] == scope
    assert result['sources'][0]['id'] == scope
    assert result['sources'][0]['status'] == 'ok'
    assert result['sources'][0]['result_count'] == len({candidate({'url': url}, provider='test')['url'] for url in urls})
    assert result['warnings'] == []
    if scope == 'youtube':
        assert all(item['source'] == 'YouTube' and item['kind'] == 'video'
                   and item['preview']['kind'] == 'embed' for item in result['results'])


def test_explicit_scope_cache_is_separate_by_scope_and_tenant_and_expires():
    now = [0.0]
    index = Index(pages=[{'url': 'https://www.youtube.com/shorts/VQRLujxTm3c',
                          'title': 'City night clip'}])
    service = FootageSearch(index, clock=lambda: now[0])
    assert not service.search('city night', source='youtube', namespace='ours')['cached']
    assert service.search('city night', source='youtube', namespace='ours')['cached']
    assert not service.search('city night', source='scenes', namespace='ours')['cached']
    assert not service.search('city night', source='youtube', namespace='other')['cached']
    assert len(index.calls) == 3
    now[0] = 301
    assert not service.search('city night', source='youtube', namespace='ours')['cached']
    assert len(index.calls) == 4


@pytest.mark.parametrize('scope', ['youtube', 'instagram', 'tiktok', 'scenes'])
def test_explicit_scopes_preserve_admission_and_release_after_index_failure(scope):
    index = Index(pages=SearchUnavailable('Index unavailable'))
    service = FootageSearch(index)
    assert service._slots.acquire(blocking=False)
    assert service._slots.acquire(blocking=False)
    try:
        with pytest.raises(SearchBusy):
            service.search('city night', source=scope)
        assert not index.calls
    finally:
        service._slots.release()
        service._slots.release()
    with pytest.raises(SearchUnavailable, match='Index unavailable'):
        service.search('city night', source=scope)
    index.pages = [{'url': 'https://clip.cafe/city-night/', 'title': 'City night'}]
    assert not service.search('city night', source=scope)['cached']
    assert len(index.calls) == 2  # Failure remains retryable and releases admission.


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'javascript:alert(1)', 'https://localhost/video.mp4',
    'https://127.0.0.1/a', 'https://[::1]/a', 'https://10.1.1.1/a',
    'https://metadata.google.internal/a', 'https://video.local/a',
    'https://user:password@example.com/a', 'https://example.com:8600/a',
    'https://example.com\\@localhost/a', 'https://example.com/a\nHeader:bad',
])
def test_result_urls_do_not_admit_local_resources_or_credentials(url):
    assert public_url(url) is None
    assert candidate({'url': url}, provider='test') is None


def test_lookalike_hosts_never_receive_official_embeds():
    item = candidate({'url': 'https://youtube.com.attacker.example/watch?v=VQRLujxTm3c',
                      'embed_url': 'https://attacker.example/iframe'}, provider='test')
    assert item['preview']['kind'] == 'source'


def test_youtube_channel_and_playlist_pages_do_not_claim_individual_video_metadata():
    service = FootageSearch(Index())
    for url in ('https://www.youtube.com/@RockstarGames',
                'https://www.youtube.com/playlist?list=PLexample'):
        item = service.inspect(url)
        assert item['source'] == 'YouTube'
        assert item['kind'] == ('account' if '/@' in url else 'page')
        assert item['preview']['kind'] == 'source'
        assert item['thumbnail_url'] is None


def test_public_web_results_keep_subject_matches_and_filter_generic_stock_navigation(monkeypatch):
    from social_fetch.web_search import PublicIndex
    index = PublicIndex()
    monkeypatch.setattr(index, 'search', lambda *args: SearchBatch([
        {'href': 'https://stock.example.com/videos', 'title': 'Free stock video footage'},
        {'href': 'https://www.rockstargames.com/VI/media/videos', 'title': 'Grand Theft Auto VI videos'},
        {'href': 'https://youtu.be/VQRLujxTm3c', 'title': 'GTA VI trailer'},
    ], False, kind='page'))
    service = FootageSearch(index)
    monkeypatch.setattr(service, 'status', lambda: {'configured': True})
    result = service.search('GTA 6')
    assert result['effective_query'] == 'GTA 6'
    assert len(result['results']) == 2
    assert result['results'][0]['kind'] == 'page'
    assert result['results'][1]['kind'] == 'video'


def test_public_adapter_uses_one_query_and_cleans_concatenated_index_headings(monkeypatch):
    import sys
    from importlib.machinery import ModuleSpec
    from types import SimpleNamespace
    from social_fetch.web_search import PublicIndex
    calls = []
    class DDGS:
        def __init__(self, **kwargs):
            pass
        def text(self, query, **kwargs):
            calls.append(query)
            return [
                {'href': 'https://youtu.be/VQRLujxTm3c',
                 'title': 'GTA VI official trailer - YouTubeGTA 6 videos from Rockstar Games'},
                {'href': 'https://www.rockstargames.com/VI/media/videos',
                 'title': 'GTA 6 videos from Rockstar Games'},
            ]
    monkeypatch.setitem(sys.modules, 'ddgs', SimpleNamespace(DDGS=DDGS, __spec__=ModuleSpec('ddgs', None)))
    result = FootageSearch(PublicIndex()).search('GTA 6')
    assert calls == ['GTA 6 video']
    assert result['warnings'] == []
    assert result['results'][0]['title'] == 'GTA VI official trailer'


def test_inspect_is_network_free_and_never_downloads(monkeypatch):
    def forbid(*args, **kwargs):
        raise AssertionError('inspect must not request an index or a media file')
    index = Index()
    monkeypatch.setattr(index, 'search', forbid)
    service = FootageSearch(index)
    item = service.inspect('https://media.example.com/video.mp4?signature=signed')
    assert item['preview'] == {'kind': 'direct', 'url': item['url']}
    assert service.status()['downloads_enabled'] is False
    assert index.calls == []


def test_short_and_watch_urls_share_identity_but_different_assets_do_not():
    urls = ['https://youtube.com/shorts/VQRLujxTm3c',
            'https://youtube.com/watch?v=VQRLujxTm3c&list=anything',
            'https://youtube.com/watch?v=QdBZY2fkU-0']
    items = [candidate({'url': url, 'title': 'Identical title'}, provider='test') for url in urls]
    assert items[0]['id'] == items[1]['id']
    assert items[1]['id'] != items[2]['id']


def test_vimeo_unlisted_hash_is_preserved_in_player_reference():
    item = candidate({'url': 'https://vimeo.com/123456789/abcdef1234'}, provider='test')
    assert item['preview']['url'] == 'https://player.vimeo.com/video/123456789?h=abcdef1234'


def test_partial_failure_returns_useful_results_with_an_explicit_warning():
    service = FootageSearch(Index([{'url': 'https://youtu.be/VQRLujxTm3c'}],
                                 SearchUnavailable('Unavailable right now')))
    result = service.search('trailer')
    assert len(result['results']) == 1
    assert result['warnings'] == ['Web search: Unavailable right now']
    service.search('trailer')
    assert len(service.index.calls) == 4  # Do not cache a temporary partial failure.


def test_total_failure_is_not_reported_as_successful_empty_search():
    service = FootageSearch(Index(SearchUnavailable('No connection'),
                                 RuntimeError('secret-provider-key-in-error')))
    with pytest.raises(SearchUnavailable, match='No connection') as failure:
        service.search('trailer')
    assert 'secret-provider-key' not in str(failure.value)


def test_cache_is_bounded_tenant_scoped_and_expires():
    now = [0.0]
    index = Index([{'url': 'https://youtu.be/VQRLujxTm3c'}])
    service = FootageSearch(index, clock=lambda: now[0])
    assert service.search('trailer', namespace='ours')['cached'] is False
    assert service.search('trailer', namespace='ours')['cached'] is True
    service.search('trailer', namespace='different')
    assert len(index.calls) == 4
    now[0] = 301
    service.search('trailer', namespace='ours')
    assert len(index.calls) == 6


def test_search_admission_refuses_an_already_full_worker_pool():
    service = FootageSearch(Index())
    assert service._slots.acquire(blocking=False)
    assert service._slots.acquire(blocking=False)
    try:
        with pytest.raises(SearchBusy):
            service.search('trailer')
        assert service.index.calls == []
    finally:
        service._slots.release()
        service._slots.release()


def test_brave_and_serper_use_fixed_indexes_and_server_only_credentials():
    calls = []
    def request(url, headers, body=None):
        calls.append((url, headers, body))
        return {'results': [], 'web': {'results': []}, 'organic': [], 'videos': []}
    BraveIndex('private-brave', request).search('GTA VI', 'page', 2, 24)
    SerperIndex('private-serper', request).search('GTA VI', 'video', 2, 24)
    assert calls[0][0].startswith('https://api.search.brave.com/res/v1/web/search?')
    assert 'offset=2' in calls[0][0] and 'count=20' in calls[0][0]
    assert calls[0][1] == {'X-Subscription-Token': 'private-brave'}
    assert calls[1] == ('https://google.serper.dev/videos', {'X-API-KEY': 'private-serper'},
                        {'q': 'GTA VI', 'num': 24, 'page': 3})


def test_authenticated_index_redirects_are_refused_and_error_bodies_not_exposed(monkeypatch):
    class Opener:
        def open(self, request, **kwargs):
            raise HTTPError(request.full_url, 302, 'secret key location', {}, None)
    monkeypatch.setattr('social_fetch.web_search.build_opener', lambda handler: Opener())
    with pytest.raises(SearchUnavailable) as failure:
        index_json('https://api.search.brave.com/res/v1/videos/search', {'X-Subscription-Token': 'private'})
    assert 'secret' not in str(failure.value)


@pytest.mark.parametrize('value, expected', [('02:18', 138), ('PT1H2M3S', 3723),
                                           ('unknown', None), (True, None)])
def test_duration_metadata_is_parsed_without_inventing_missing_values(value, expected):
    assert duration_seconds(value) == expected
