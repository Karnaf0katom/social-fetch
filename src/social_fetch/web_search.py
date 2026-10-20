"""Metadata-only web video discovery. Never fetch, extract or store video bytes.

Search indexes are the discovery owners. Only fixed index endpoints receive server
requests; result pages and player HTML are never fetched or executed here.
"""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import zip_longest
import hashlib
import html
import importlib.util
import ipaddress
import json
import os
import re
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from social_fetch.social_sources import DEFAULT_SOCIAL, DOMAINS, LABELS, social_link


class SearchUnavailable(RuntimeError):
    """Public, credential-free explanation of an index failure."""


class SearchBusy(RuntimeError):
    """The bounded discovery worker is already occupied."""


def public_url(value: Any) -> str | None:
    """Validate references without network I/O. No server request uses these URLs."""
    if not isinstance(value, str) or len(value) > 4096:
        return None
    value = html.unescape(value.strip())
    if value.startswith('//'):
        value = 'https:' + value
    if re.search(r'[\x00-\x20\x7f\\]', value):
        return None
    try:
        parts = urlsplit(value)
        host = (parts.hostname or '').lower().rstrip('.')
        if (parts.scheme not in ('http', 'https') or not host or parts.username
                or parts.password or parts.port not in (None, 80, 443)):
            return None
        if host in ('localhost', 'metadata', 'metadata.google.internal') or host.endswith(
                ('.localhost', '.local', '.internal', '.test', '.invalid')):
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if '.' not in host or not re.fullmatch(r'[a-z0-9.-]+', host):
                return None
        else:
            if not address.is_global:
                return None
        netloc = f'[{host}]' if ':' in host else host
        if parts.port and parts.port != (443 if parts.scheme == 'https' else 80):
            netloc += f':{parts.port}'
        return urlunsplit((parts.scheme, netloc, parts.path or '/', parts.query, ''))
    except ValueError:
        return None


def text(value: Any, limit: int = 800) -> str:
    if not isinstance(value, str):
        return ''
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', '', value))).strip()[:limit]


def duration_seconds(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value) if 0 < value < 604800 else None
    if not isinstance(value, str):
        return None
    if re.fullmatch(r'\d{1,4}:\d{2}(:\d{2})?', value.strip()):
        result = 0
        for segment in value.strip().split(':'):
            result = result * 60 + int(segment)
        return result or None
    match = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', value.strip())
    if match:
        hours, minutes, seconds = (int(v or 0) for v in match.groups())
        return hours * 3600 + minutes * 60 + seconds or None
    return None


def reference(url: str) -> tuple[str, str, dict[str, Any]]:
    """Derive allowlisted official players; never trust index embed_html/embed_url."""
    parts = urlsplit(url)
    host = (parts.hostname or '').removeprefix('www.')
    segments = parts.path.strip('/').split('/')
    query = parse_qs(parts.query)
    video_id = ''
    if host == 'youtu.be':
        video_id = segments[0]
    elif host in ('youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtube-nocookie.com'):
        if segments[0] == 'watch':
            video_id = query.get('v', [''])[0]
        elif len(segments) > 1 and segments[0] in ('embed', 'shorts', 'live'):
            video_id = segments[1]
    if re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        return (f'https://www.youtube.com/watch?v={video_id}', 'YouTube',
                {'kind': 'embed', 'url': f'https://www.youtube-nocookie.com/embed/{video_id}'})
    if host in ('vimeo.com', 'player.vimeo.com'):
        ids = [segment for segment in segments if re.fullmatch(r'\d{5,12}', segment)]
        if ids:
            video_id = ids[-1]
            index = segments.index(video_id)
            video_hash = query.get('h', [''])[0]
            if not video_hash and index + 1 < len(segments):
                video_hash = segments[index + 1]
            suffix = '?h=' + video_hash if re.fullmatch(r'[a-f0-9]{8,16}', video_hash) else ''
            return (f'https://vimeo.com/{video_id}{suffix}', 'Vimeo',
                    {'kind': 'embed', 'url': f'https://player.vimeo.com/video/{video_id}{suffix}'})
    if host == 'dai.ly' or host == 'dailymotion.com':
        video_id = segments[0] if host == 'dai.ly' else (
            segments[1] if len(segments) > 1 and segments[0] == 'video' else '')
        if re.fullmatch(r'[A-Za-z0-9]{5,15}', video_id):
            return (f'https://www.dailymotion.com/video/{video_id}', 'Dailymotion',
                    {'kind': 'embed', 'url': f'https://www.dailymotion.com/embed/video/{video_id}'})
    if host == 'archive.org' and len(segments) == 2 and segments[0] in ('details', 'embed'):
        identifier = segments[1]
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,199}', identifier):
            return (f'https://archive.org/details/{identifier}', 'Internet Archive',
                    {'kind': 'embed', 'url': f'https://archive.org/embed/{identifier}'})
    source = {'youtube.com': 'YouTube', 'm.youtube.com': 'YouTube',
              'music.youtube.com': 'YouTube', 'youtu.be': 'YouTube',
              'vimeo.com': 'Vimeo', 'player.vimeo.com': 'Vimeo',
              'dailymotion.com': 'Dailymotion', 'dai.ly': 'Dailymotion',
              'reddit.com': 'Reddit', 'old.reddit.com': 'Reddit', 'x.com': 'X',
              'twitter.com': 'X', 'tiktok.com': 'TikTok', 'facebook.com': 'Facebook',
              'instagram.com': 'Instagram', 'commons.wikimedia.org': 'Wikimedia Commons',
              'archive.org': 'Internet Archive', 'pexels.com': 'Pexels',
              'mixkit.co': 'Mixkit', 'coverr.co': 'Coverr', 'pixabay.com': 'Pixabay',
              'nowness.com': 'NOWNESS', 'shortoftheweek.com': 'Short of the Week',
              'nfb.ca': 'National Film Board', 'loc.gov': 'Library of Congress',
              'britishpathe.com': 'British Pathé', 'images.nasa.gov': 'NASA Image and Video Library',
              'giphy.com': 'GIPHY', 'tenor.com': 'Tenor'}.get(host, host)
    if (not (host == 'commons.wikimedia.org' and parts.path.startswith('/wiki/'))
            and re.search(r'\.(mp4|webm|m4v|ogv)$', parts.path, re.I)):
        return url, source, {'kind': 'direct', 'url': url}
    # Remove ordinary tracking from page references; retain asset/signed parameters.
    clean_query = [(key, value) for key, values in query.items()
                   if not key.lower().startswith('utm_') and key not in ('fbclid', 'gclid')
                   for value in values]
    canonical = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(clean_query), ''))
    return canonical, source, {'kind': 'source', 'url': None,
                               'reason': 'This source needs its original player. Open the source to watch.'}


def candidate(row: dict[str, Any], *, provider: str, kind: str = 'video') -> dict[str, Any] | None:
    url = public_url(row.get('url') or row.get('link') or row.get('content') or row.get('href'))
    if not url:
        return None
    canonical, source, preview = reference(url)
    social = social_link(url)
    if social:
        canonical, source, kind = social.url, LABELS[social.platform], social.kind
        if preview['kind'] == 'source':
            preview = {'kind': 'source', 'url': None, 'reason':
                       'Open the original account or find its videos below.' if kind == 'account'
                       else 'Open the original post to watch. Video availability is checked when downloading.'}
    thumbnail = row.get('thumbnail') or row.get('imageUrl') or row.get('thumbnailUrl') or row.get('image')
    if isinstance(thumbnail, dict):
        thumbnail = next((image_url for key in ('original', 'src', 'source')
                          if (image_url := public_url(thumbnail.get(key)))), None)
    images = row.get('images')
    if not public_url(thumbnail) and isinstance(images, dict):
        # Indexes already supply card-sized renditions. Avoid the full-size
        # image, and do not let one malformed URL hide valid alternatives.
        thumbnail = next((image_url for key in ('medium', 'large', 'small')
                          if (image_url := public_url(images.get(key)))), None)
    thumbnail = public_url(thumbnail)
    video = row.get('video') if isinstance(row.get('video'), dict) else {}
    publisher = row.get('publisher')
    if isinstance(publisher, dict):
        publisher = publisher.get('name')
    if preview['kind'] != 'source':
        kind = 'video'
    seconds = duration_seconds(video.get('duration') or row.get('duration'))
    if not thumbnail and source == 'YouTube' and preview['kind'] == 'embed':
        thumbnail = f"https://i.ytimg.com/vi/{parse_qs(urlsplit(canonical).query)['v'][0]}/hqdefault.jpg"
    heading = text(row.get('title'), 240)
    if social and kind == 'account' and re.fullmatch(r'(?i)link to (?:www\.)?[a-z0-9.-]+\.[a-z]{2,}', heading):
        heading = f'@{social.handle} on {source}'
    from social_fetch.social_resources import discover_resources
    linked = discover_resources(row, source_url=canonical, limit=20)
    return {
        'id': hashlib.sha256(canonical.encode()).hexdigest()[:24],
        'url': canonical,
        'title': heading or (f'@{social.handle} on {source}' if social and kind == 'account' else f'Video from {source}'),
        'description': text(row.get('description') or row.get('snippet') or row.get('body')),
        'source': source,
        'domain': (urlsplit(canonical).hostname or '').removeprefix('www.'),
        'kind': kind,
        'thumbnail_url': public_url(thumbnail),
        'duration_seconds': seconds,
        'creator': text(video.get('creator') or row.get('channel') or row.get('uploader') or publisher
                        or (social.handle if social else ''), 160),
        'published': text(row.get('page_age') or row.get('date') or row.get('published'), 80),
        'preview': preview,
        'discovered_by': [provider],
        'linked_resources': linked['resources'],
        'resource_notice': linked['notice'] if linked['count'] else None,
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def index_json(url: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bounded fixed-provider JSON, with redirects refused to protect API headers."""
    payload = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=payload, headers={**headers, 'Accept': 'application/json',
                  **({'Content-Type': 'application/json'} if body is not None else {})})
    try:
        with build_opener(_NoRedirect).open(req, timeout=10) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise SearchUnavailable('The search index returned an oversized response.')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError('expected an object')
            return result
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise SearchUnavailable('The search index rejected its server credentials.') from None
        if exc.code == 429:
            raise SearchUnavailable('The search index is rate limited. Try again shortly.') from None
        raise SearchUnavailable('The search index is temporarily unavailable.') from None
    except (URLError, TimeoutError, ValueError, OSError):
        raise SearchUnavailable('The search index could not be reached. Try again shortly.') from None


@dataclass(frozen=True)
class SearchBatch:
    rows: list[dict[str, Any]]
    more: bool
    kind: str | None = None


class BraveIndex:
    name = 'brave'

    def __init__(self, key: str, request: Callable[..., dict[str, Any]] = index_json):
        self._key, self._request = key, request

    def search(self, query: str, category: str, page: int, count: int) -> SearchBatch:
        endpoint = 'videos/search' if category == 'video' else 'web/search'
        size = min(count, 20) if category == 'page' else count
        params = {'q': query, 'count': size, 'offset': page, 'safesearch': 'moderate'}
        data = self._request('https://api.search.brave.com/res/v1/' + endpoint + '?' + urlencode(params),
                             {'X-Subscription-Token': self._key})
        rows = data.get('results', []) if category == 'video' else data.get('web', {}).get('results', [])
        if not isinstance(rows, list):
            raise SearchUnavailable('The search index returned an unreadable result set.')
        return SearchBatch(rows[:size], bool(data.get('query', {}).get('more_results_available', len(rows) >= size)))


class SerperIndex:
    name = 'serper'

    def __init__(self, key: str, request: Callable[..., dict[str, Any]] = index_json):
        self._key, self._request = key, request

    def search(self, query: str, category: str, page: int, count: int) -> SearchBatch:
        endpoint = 'videos' if category == 'video' else 'search'
        data = self._request('https://google.serper.dev/' + endpoint, {'X-API-KEY': self._key},
                             {'q': query, 'num': count, 'page': page + 1})
        rows = data.get('videos' if category == 'video' else 'organic', [])
        if not isinstance(rows, list):
            raise SearchUnavailable('The search index returned an unreadable result set.')
        return SearchBatch(rows[:count], len(rows) >= count)


class PublicIndex:
    """Key-free public web index. Unknown pages stay pages, never verified videos.

    Yahoo and Bing are measured public DDGS backends here. Their web matches can include
    individual videos and publisher hubs. Dedicated Brave/Serper video indexes
    add richer metadata/coverage when configured; no blocked-index retry loop.
    """
    name = 'public'

    def search(self, query: str, category: str, page: int, count: int,
               *, accept: Callable[[dict[str, Any]], bool] | None = None) -> SearchBatch:
        try:
            from ddgs import DDGS
            engine = DDGS(timeout=12)
            effective = query
            # Social coverage is better in Bing; Yahoo remains the established
            # default for general social_fetch. One alternative on index failure,
            # never an unbounded retry or another paid provider.
            social = re.search(r'site:(?:instagram\.com|tiktok\.com|x\.com|twitter\.com|facebook\.com|reddit\.com)', query)
            # DDGS exposes video search through DuckDuckGo. A web lookup is a
            # genuinely different fallback, including when results are unusable.
            attempts = (('video', 'duckduckgo'), ('page', 'bing')) if category == 'video' else tuple(
                ('page', backend) for backend in (('bing', 'yahoo') if social else ('yahoo', 'bing')))
            rows = None
            found_kind = category
            provider_more = False
            for lookup_kind, backend in attempts:
                try:
                    lookup = engine.videos if lookup_kind == 'video' else engine.text
                    response = lookup(effective, backend=backend, page=page + 1,
                                      max_results=count, safesearch='moderate')
                    usable = [row for row in response if isinstance(row, dict) and (not accept or accept(row))]
                    if rows is None or usable:
                        rows, found_kind = usable, lookup_kind
                        provider_more = len(response) >= count
                    if usable:
                        break
                except Exception:
                    continue
            if rows is None:
                raise SearchUnavailable('Public search indexes are unavailable. Try again or connect a search provider.')
            # Some public-index layouts concatenate adjacent result headings.
            # Remove an exact following heading, retaining this result's prefix.
            cleaned = []
            for raw in rows[:count]:
                row = dict(raw)
                title = row.get('title', '')
                if isinstance(title, str):
                    end = len(title)
                    for other in rows:
                        following = other.get('title')
                        if isinstance(following, str) and len(following) > 12:
                            at = title.find(following)
                            if at > 8 and at + len(following) == len(title):
                                end = min(end, at)
                    for suffix in (' - YouTube', ' - IGN', 'Top Stories', 'Also in the news'):
                        at = title.find(suffix)
                        if at > 8:
                            end = min(end, at)
                    row['title'] = title[:end].strip()
                cleaned.append(row)
            return SearchBatch(cleaned, provider_more, kind=found_kind)
        except ImportError:
            raise SearchUnavailable('Web search needs a server connection. Configure an indexed search provider.') from None
        except Exception:
            # DDGS exceptions may contain transport/debug details. Do not expose them.
            raise SearchUnavailable('The free search index is unavailable here. Try again or connect a search provider.') from None


INTENTS = {'any': '', 'footage': 'footage clips', 'official': 'official trailer', 'gameplay': 'gameplay',
           'accounts': ''}

# These are focused queries through the existing index, never scraped provider APIs.
WEB_COLLECTIONS = {
    'creative': ('Creative films', ('vimeo.com', 'nowness.com', 'shortoftheweek.com', 'nfb.ca')),
    'stock': ('Stock libraries', ('mixkit.co', 'coverr.co', 'pexels.com', 'pixabay.com')),
    'culture': ('Memes & culture', ('dailymotion.com', 'reddit.com', 'giphy.com', 'tenor.com')),
    # Domain scopes include individual videos, Shorts and indexed social pages.
    # Acceptance still checks host boundaries and subject relevance below.
    'youtube': ('YouTube & Shorts', ('youtube.com', 'youtu.be')),
    'instagram': ('Instagram', ('instagram.com',)),
    'tiktok': ('TikTok', ('tiktok.com',)),
    'x': ('X / Twitter', DOMAINS['x']),
    'facebook': ('Facebook Reels & videos', DOMAINS['facebook']),
    'reddit': ('Reddit posts', DOMAINS['reddit']),
    'bluesky': ('Bluesky posts', DOMAINS['bluesky']),
    'pinterest': ('Pinterest video pins', DOMAINS['pinterest']),
    'twitch': ('Twitch clips', DOMAINS['twitch']),
    'snapchat': ('Snapchat Spotlight', DOMAINS['snapchat']),
    'linkedin': ('LinkedIn public posts', DOMAINS['linkedin']),
    'mastodon': ('Mastodon · mastodon.social', DOMAINS['mastodon']),
    'social': ('Social media · default platforms', tuple(domain for name in DEFAULT_SOCIAL for domain in DOMAINS[name])),
    'scenes': ('TV & movie clips', ('clip.cafe', 'getyarn.io', 'moviefone.com',
                                  'youtube.com', 'dailymotion.com')),
    'anime': ('Anime clips', ('animethemes.moe', 'youtube.com', 'dailymotion.com')),
}


def search_sites(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Admit at most six domain names, used only as index query restrictions."""
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 6:
        raise ValueError('Choose between one and six websites.')
    domains = set()
    for value in values:
        if not isinstance(value, str) or len(value) > 253:
            raise ValueError('Enter public website domains, such as nyaa.si.')
        domain = value.strip().lower().rstrip('.').removeprefix('www.')
        if (not public_url('https://' + domain + '/')
                or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain)):
            raise ValueError('Enter public website domains, such as nyaa.si.')
        domains.add(domain)
    return tuple(sorted(domains))


def diverse_sources(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lead with supplied files and preserve local ranks while spreading websites."""
    groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for item in items:
        groups.setdefault(item['source'], []).append(item)
    def has_files(group: list[dict[str, Any]]) -> bool:
        return any(item.get('media_url') or (item['preview']['kind'] == 'direct'
                   and item['preview']['url'] == item['url']) for item in group)
    ordered = sorted(groups.values(), key=has_files, reverse=True)
    return [item for rank in zip_longest(*ordered) for item in rank if item is not None]


class UnconfiguredIndex:
    name = 'unconfigured'

    def search(self, *args: Any) -> SearchBatch:
        raise SearchUnavailable('Web search needs a server connection.')


def public_relevance(item: dict[str, Any], query: str) -> int:
    """Public web search can return generic navigation. Require subject evidence.

    This is a title/snippet relevance hint, never verification of footage contents.
    Dedicated API indexes keep their own ranking. No semantic model or media scan.
    """
    selected = social_link(query.strip())
    link = social_link(item['url'])
    if link and ((selected and selected.url == link.url) or query.strip() == link.identity):
        return 5
    content = (item['title'] + ' ' + item['description'] + ' ' + item.get('creator', '')).casefold()
    if re.fullmatch(r'(?:gta\s*(?:6|vi)|grand theft auto\s*(?:6|vi))', query, re.I):
        return 5 if re.search(r'\b(?:gta\s*(?:6|vi)|grand theft auto\s*(?:6|vi))\b', content) else 0
    stop = {'a', 'an', 'the', 'of', 'and', 'or', 'with', 'in', 'on', 'for', 'to', 'video', 'videos'}
    clean_query = re.sub(r'\bsite:\S+', '', query.casefold())
    terms = {word.rstrip('s') if len(word) > 4 else word
             for word in re.findall(r'[^\W_]+', clean_query) if word not in stop}
    # Routing words describe the requested medium, not the subject itself.
    terms -= {'anime', 'opening', 'ending', 'theme', 'clip', 'scene', 'footage', 'quote'}
    if not terms:
        return 1
    words = {word.rstrip('s') if len(word) > 4 else word for word in re.findall(r'[^\W_]+', content)}
    matched = len(terms & words)
    return matched if matched >= min(2, len(terms)) else 0


class FootageSearch:
    """Bounded index lookups, canonical deduplication and a metadata-only LRU."""

    def __init__(self, index: Any, *, clock: Callable[[], float] = time.monotonic,
                 catalogs: dict[str, Any] | None = None):
        self.index, self.clock = index, clock
        self.catalogs = catalogs or {}
        self._cache: OrderedDict[tuple[Any, ...], tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(2)

    @classmethod
    def from_env(cls, *, include_catalogs: bool = False) -> 'FootageSearch':
        catalogs = {}
        if include_catalogs:
            raise ValueError('Native catalogs are outside the standalone social package.')
        choice = os.environ.get('FOOTAGE_SEARCH_PROVIDER', 'auto').strip().lower() or 'auto'
        brave = os.environ.get('BRAVE_SEARCH_API_KEY') or os.environ.get('BRAVE_API_KEY') or ''
        serper = os.environ.get('SERPER_API_KEY') or ''
        if choice == 'brave' or (choice == 'auto' and brave):
            return cls(BraveIndex(brave), catalogs=catalogs)
        if choice == 'serper' or (choice == 'auto' and serper):
            return cls(SerperIndex(serper), catalogs=catalogs)
        if choice not in ('auto', 'public'):
            return cls(UnconfiguredIndex(), catalogs=catalogs)
        return cls(PublicIndex(), catalogs=catalogs)

    def status(self) -> dict[str, Any]:
        configured = (bool(getattr(self.index, '_key', '')) if self.index.name != 'public'
                      else importlib.util.find_spec('ddgs') is not None)
        return {'provider': self.index.name, 'configured': configured, 'downloads_enabled': False,
                'sources': [{'id': 'web', 'label': 'Across the web', 'configured': configured, 'mode': 'indexed'},
                            {'id': 'custom', 'label': 'My websites', 'configured': configured, 'mode': 'indexed'},
                            *[{'id': name, 'label': label, 'configured': configured, 'mode': 'indexed'}
                              for name, (label, _) in WEB_COLLECTIONS.items()],
                            *[{'id': catalog.name, 'label': catalog.label, 'configured': catalog.configured, 'mode': 'native'}
                              for catalog in self.catalogs.values()]],
                'mode': 'indexed' if self.index.name != 'public' else 'public',
                'message': ('Web search needs a server connection.' if not configured else
                            'Public web matches may have limited video metadata and coverage.' if self.index.name == 'public'
                            else 'Search uses an indexed video and web provider.')}

    def inspect(self, url: str) -> dict[str, Any]:
        result = candidate({'url': url}, provider='link', kind='page')
        if result is None:
            raise ValueError('Enter a public HTTP or HTTPS video link.')
        return result

    def search(self, query: str, *, intent: str = 'any', page: int = 0,
               count: int = 24, namespace: str = '', source: str = 'web',
               sites: list[str] | tuple[str, ...] = (),
               selected_sources: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
        """Bounded indexed discovery; native application catalogs are excluded."""
        if selected_sources and source != 'selected':
            raise ValueError('Source selections require Choose sources.')
        if source == 'selected':
            if (not isinstance(selected_sources, (list, tuple)) or not 1 <= len(selected_sources) <= 6
                    or any(not isinstance(name, str) or name not in ('web', 'custom', *WEB_COLLECTIONS, *self.catalogs)
                           for name in selected_sources)):
                raise ValueError('Choose between one and six supported sources.')
            selected_sources = tuple(sorted(set(selected_sources)))
            if ('custom' in selected_sources) != bool(sites):
                raise ValueError('Choose websites when My websites is selected.')
        if intent == 'accounts':
            if source in ('all', 'smart', 'web'):
                source = 'social'
            if (source not in ('social', *DOMAINS, 'selected') or
                    source == 'selected' and any(name not in ('social', *DOMAINS) for name in selected_sources)):
                raise ValueError('Choose a social platform to find accounts.')
        if sites and source not in ('smart', 'custom', 'selected'):
            raise ValueError('Website restrictions require the My websites source.')
        selected_sites = search_sites(sites) if sites else ()
        if source == 'custom' and not selected_sites:
            raise ValueError('Choose between one and six websites.')
        if source == 'web' or source in WEB_COLLECTIONS:
            return self._search_web(query, intent=intent, page=page, count=count, namespace=namespace,
                                    collection=source if source in WEB_COLLECTIONS else '')
        raise ValueError('Choose a supported indexed social source; native catalogs are outside this package.')

    def _search_web(self, query: str, *, intent: str = 'any', page: int = 0,
                    count: int = 24, namespace: str = '', admitted: bool = False,
                    collection: str = '', diversify: bool = False,
                    sites: tuple[str, ...] = ()) -> dict[str, Any]:
        query = ' '.join(query.split())
        if not query or len(query) > 200 or re.search(r'[\x00-\x1f\x7f]', query):
            raise ValueError('Enter a search phrase between 1 and 200 characters.')
        if intent not in INTENTS or not 0 <= page <= 9 or not 1 <= count <= 40:
            raise ValueError('Invalid search options.')
        key = (namespace, query.casefold(), intent, page, count, collection, diversify, sites)
        with self._lock:
            cached = self._cache.get(key)
            if cached and self.clock() - cached[0] < 300:
                self._cache.move_to_end(key)
                return {**cached[1], 'cached': True}
        if not admitted and not self._slots.acquire(blocking=False):
            raise SearchBusy('Search is busy. Try again shortly.')
        try:
            if not self.status()['configured']:
                raise SearchUnavailable('Web search needs a server connection. Configure an indexed search provider.')
            expanded = ('("GTA 6" OR "GTA VI")' if self.index.name != 'public' and re.fullmatch(
                r'(?:gta\s*(?:6|vi)|grand theft auto\s*(?:6|vi))', query, re.I) else query)
            effective = ' '.join(part for part in (expanded, INTENTS[intent]) if part)
            warnings: list[str] = []
            rows: list[dict[str, Any]] = []
            reports: list[dict[str, Any]] = []
            more = False
            # Dedicated indexes have separate video/web coverage. The measured
            # key-free adapter uses one web query, avoiding duplicate rate-limited
            # public requests while classifying individual video links locally.
            kinds = () if collection else ('page',) if self.index.name == 'public' else ('video', 'page')
            requests = [('Video' if kind == 'video' else 'Web', effective if kind == 'video' else effective + ' video', kind, count, ()) for kind in kinds]
            focused = DEFAULT_SOCIAL if collection == 'social' else (collection,) if collection in WEB_COLLECTIONS else ('creative', 'stock') if diversify else ()
            for name in focused:
                label, domains = WEB_COLLECTIONS[name]
                category = 'video' if self.index.name == 'public' and name in DOMAINS and intent != 'accounts' else 'page'
                prefixes = ('tiktok.com/@',) if self.index.name == 'public' and name == 'tiktok' and category == 'page' else domains
                if self.index.name == 'public' and name == 'instagram' and intent != 'accounts':
                    prefixes = ('instagram.com/reel/', 'instagram.com/p/')
                if self.index.name == 'public' and intent != 'accounts':
                    prefixes = {'pinterest': ('pinterest.com/pin/',), 'twitch': ('clips.twitch.tv',),
                                'snapchat': ('snapchat.com/spotlight/',),
                                'linkedin': ('linkedin.com/posts/',)}.get(name, prefixes)
                # Public engines often ignore/garble parenthesized OR scopes.
                # Use a single primary host there; indexed providers retain the
                # full multi-host scope. Result host checks remain authoritative.
                scope = 'site:' + prefixes[0] if self.index.name == 'public' and name in DOMAINS else '(' + ' OR '.join('site:' + domain for domain in prefixes) + ')'
                # Fetch enough raw rows to survive generic headings, unrelated
                # links and profile/post filtering, even for a small gallery.
                size = 12 if name in DOMAINS else min(count, 12)
                requests.append((label, effective + ' ' + scope, category, size, domains))
            for domain in sites:
                requests.append((domain, effective + ' site:' + domain, 'page', min(count, 12), (domain,)))
            def accepted(raw, kind, domains):
                item = candidate(raw, provider=self.index.name, kind=kind)
                if not item or domains and not any(item['domain'] == domain or item['domain'].endswith('.' + domain) for domain in domains):
                    return None
                if intent == 'accounts' and item['kind'] != 'account':
                    return None
                if collection in DOMAINS or collection == 'social':
                    link = social_link(item['url'])
                    if not link or intent != 'accounts' and link.kind != 'video':
                        return None
                return item if (self.index.name != 'public' and not domains or public_relevance(item, query)) else None

            def lookup(phrase, kind, size, domains):
                if isinstance(self.index, PublicIndex) and (collection in DOMAINS or collection == 'social'):
                    return self.index.search(phrase, kind, page, size, accept=lambda raw: bool(accepted(raw, kind, domains)))
                return self.index.search(phrase, kind, page, size)

            with ThreadPoolExecutor(max_workers=min(2 if self.index.name == 'public' else 4, len(requests)), thread_name_prefix='footage-index') as executor:
                jobs = [(label, kind, domains, executor.submit(lookup, phrase, kind, size, domains))
                        for label, phrase, kind, size, domains in requests]
                for label, kind, domains, job in jobs:
                    try:
                        batch = job.result()
                        more = more or batch.more
                        found = 0
                        for raw in batch.rows:
                            if isinstance(raw, dict):
                                item = accepted(raw, batch.kind or kind, domains)
                                if item:
                                    rows.append(item)
                                    found += 1
                        if sites or collection == 'social':
                            reports.append({'id': label, 'label': label, 'status': 'ok',
                                            'result_count': found, 'message': '', 'mode': 'indexed'})
                    except SearchUnavailable as exc:
                        warnings.append(f"{label.capitalize()} search: {exc}")
                        if sites or collection == 'social':
                            reports.append({'id': label, 'label': label, 'status': 'unavailable',
                                            'result_count': 0, 'message': str(exc), 'mode': 'indexed'})
                    except Exception:
                        warnings.append(f"{label.capitalize()} search is temporarily unavailable.")
                        if sites or collection == 'social':
                            reports.append({'id': label, 'label': label, 'status': 'unavailable',
                                            'result_count': 0, 'message': 'Search is temporarily unavailable.', 'mode': 'indexed'})
            if len(warnings) == len(requests):
                raise SearchUnavailable(warnings[0])
            unique: OrderedDict[str, dict[str, Any]] = OrderedDict()
            for item in rows:
                old = unique.get(item['id'])
                if old:
                    for field in ('thumbnail_url', 'duration_seconds', 'creator', 'published', 'description'):
                        if not old[field] and item[field]:
                            old[field] = item[field]
                else:
                    unique[item['id']] = item
            ranked = list(unique.values())
            if self.index.name == 'public':
                ranked.sort(key=lambda item: public_relevance(item, query), reverse=True)
            if diversify or collection:
                ranked = diverse_sources(ranked)
            if collection in DOMAINS or collection == 'social':
                ranked = ranked[:count]
                if not ranked:
                    warnings.append('No matching public accounts were found. Try an exact handle or paste an account link.' if intent == 'accounts' else
                                    'No matching public videos were found. Try another phrase, browse a known account or paste a post link.')
            result = {'query': query, 'effective_query': effective, 'intent': intent, 'page': page,
                      'results': ranked, 'has_more': more and page < 9,
                      'provider': self.index.name, 'warnings': warnings, 'cached': False}
            if sites:
                result.update(source='custom', sites=list(sites), sources=reports)
            elif collection:
                result.update(source=collection, sources=reports if collection == 'social' else [{'id': collection, 'label': WEB_COLLECTIONS[collection][0],
                              'status': 'partial' if warnings else 'ok', 'result_count': len(ranked),
                              'message': '; '.join(warnings), 'mode': 'indexed'}])
            # Cache successful complete responses only; partial failures remain retryable.
            if not warnings:
                with self._lock:
                    self._cache[key] = (self.clock(), result)
                    self._cache.move_to_end(key)
                    while len(self._cache) > 64:
                        self._cache.popitem(last=False)
            return result
        finally:
            if not admitted:
                self._slots.release()
