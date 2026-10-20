"""Small public account samples. Reuses the Instagram viewer and fixed web index."""
from collections import OrderedDict
from contextlib import redirect_stdout
import io
import threading
import time

from social_fetch.social_sources import DOMAINS, LABELS, social_link
from social_fetch.web_search import SearchBusy, SearchUnavailable, candidate


class AccountSearch:
    def __init__(self):
        self._slots = threading.BoundedSemaphore(2)
        self._lock = threading.Lock()
        self._cache = OrderedDict()

    def browse(self, url, search, *, count=5, namespace='', include_posters=True):
        link = social_link(url)
        if not link or link.kind != 'account' or not 1 <= count <= 12:
            raise ValueError('Choose a public account link and a sample of one to twelve posts.')
        key = (namespace, link.url, count, include_posters)
        with self._lock:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < 300:
                self._cache.move_to_end(key)
                return {**cached[1], 'cached': True}
        if not self._slots.acquire(blocking=False):
            raise SearchBusy('Account discovery is busy. Try again shortly.')
        try:
            rows, notes = [], []
            if link.platform == 'mastodon':
                from social_fetch.social_download import bounded_json, mastodon_request
                from urllib.parse import urlencode
                try:
                    account = bounded_json(mastodon_request, 'https://mastodon.social/api/v1/accounts/lookup?' + urlencode({'acct': link.handle}))
                    if str(account.get('acct', '')).lower() != link.handle:
                        raise ValueError('Another account was returned')
                    identity = str(account.get('id', ''))
                    if not identity.isdigit():
                        raise ValueError('Invalid account identity')
                    posts = bounded_json(mastodon_request, 'https://mastodon.social/api/v1/accounts/' + identity +
                        '/statuses?only_media=true&exclude_reblogs=true&limit=12')
                    for post in posts:
                        source = social_link(post.get('url', ''))
                        if (not source or source.kind != 'video' or source.platform != 'mastodon'
                                or source.handle != link.handle or post.get('reblog')
                                or post.get('visibility') not in {'public', 'unlisted'}
                                or not any(m.get('type') in {'video', 'gifv'} for m in post.get('media_attachments', []))):
                            continue
                        item = candidate({'url': source.url, 'title': f'Video from @{link.handle}',
                                          'description': post.get('content', ''),
                                          'uploader': link.handle}, provider='mastodon-public-api')
                        if item:
                            rows.append(item)
                    rows = rows[:count]
                    notes.append('Native video/gifv from the latest twelve media posts on mastodon.social; not a complete account or fediverse index.')
                except Exception:
                    raise SearchUnavailable('The selected public Mastodon account is unavailable.') from None
            elif link.platform == 'instagram':
                from social_fetch.instagram_web import discover_profile
                try:
                    with redirect_stdout(io.StringIO()):
                        posts, receipt = discover_profile(link.handle, limit=count, max_pages=2)
                    for post in posts:
                        item = candidate({'url': post['source_url'], 'title': post.get('caption') or f'Video from @{link.handle}',
                                          'description': post.get('caption', ''), 'uploader': link.handle,
                                          'duration': post.get('source_duration_seconds')}, provider='instagram-viewer')
                        if item:
                            if include_posters and post.get('poster_url'):
                                from social_fetch.posters import register_account_poster
                                item['thumbnail_url'] = register_account_poster(namespace, item['id'], post['poster_url'])
                            rows.append(item)
                    notes.append('A sample of public account videos; this is not a complete account collection.')
                    if receipt.get('page_bound_reached'):
                        notes.append('Stopped after two profile pages; more posts may exist.')
                except Exception:
                    raise SearchUnavailable('The public Instagram viewer could not read this account. Try indexed account search or open its source.') from None
            else:
                # Index lookups only. Post ownership is checked from the URL; an
                # index ignoring site operators cannot mix in another account.
                domains = DOMAINS[link.platform]
                path = link.url.split('/', 3)[3].rstrip('/')
                scope = '(' + ' OR '.join(f'site:{domain}/{path}/' for domain in domains) + ')'
                try:
                    found = search.index.search(link.handle + ' video ' + scope, 'page', 0, 12)
                except Exception:
                    raise SearchUnavailable('Indexed account posts are unavailable. Try again or open the source.') from None
                for raw in found.rows:
                    if not isinstance(raw, dict):
                        continue
                    post = social_link(raw.get('url') or raw.get('link') or raw.get('href') or '')
                    supplied_creator = str(raw.get('channel') or raw.get('uploader') or '').lstrip('@')
                    if link.platform == 'reddit' and post and not post.url.casefold().startswith(link.url.rstrip('/').casefold() + '/comments/'):
                        continue
                    if (post and post.kind == 'video' and post.platform == link.platform
                            and (post.handle.casefold() == link.handle.casefold()
                                 or link.platform == 'youtube' and supplied_creator.casefold() == link.handle.lstrip('@').casefold())):
                        item = candidate(raw, provider=search.index.name, kind='page')
                        if item:
                            rows.append(item)
                rows = rows[:count]
                notes.append('Indexed posts from this account; recent or unindexed posts may be missing.')
            rows = list({item['id']: item for item in rows}.values())[:count]
            result = {'query': link.url, 'effective_query': link.handle, 'intent': 'any', 'page': 0,
                      'source': link.platform, 'provider': 'account', 'results': rows, 'has_more': False,
                      'warnings': notes, 'cached': False,
                      'sources': [{'id': link.platform, 'label': LABELS[link.platform], 'status': 'ok',
                                   'result_count': len(rows), 'message': notes[0]}]}
            with self._lock:
                self._cache[key] = (time.monotonic(), result)
                while len(self._cache) > 64:
                    self._cache.popitem(last=False)
            return result
        finally:
            self._slots.release()


account_search = AccountSearch()
