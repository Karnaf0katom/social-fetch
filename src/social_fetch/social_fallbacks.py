"""Platform-specific alternatives to the primary public acquisition routes.

Each adapter resolves one selected post, validates its identity and approved
delivery hosts, and transfers a bounded progressive MP4. No generic extractor,
browser cookies, arbitrary federation, or manifest downloader is enabled.
"""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ProviderUnavailable(ValueError):
    """A route is unavailable; another acquisition route may be attempted."""


HOSTS = {
    'instagram': ('instagram.com', 'cdninstagram.com', 'fbcdn.net'),
    'tiktok': ('tiktok.com', 'tiktokcdn.com', 'tiktokcdn-us.com', 'tiktokcdn-eu.com',
               'tiktokv.com', 'byteoversea.com', 'ibytedtos.com', 'v19-webapp-prime.tiktok.com',
               'ssstik.io', 'tikcdn.io'),
    'x': ('api.fxtwitter.com', 'fixupx.com', 'video.twimg.com'),
    'facebook': ('facebook.com', 'www.facebook.com', 'fbcdn.net'),
    'reddit': ('www.reddit.com', 'v.redd.it'),
    'pinterest': ('www.pinterest.com', 'pinimg.com'),
    'twitch': ('gql.twitch.tv', 'clips-media-assets2.twitch.tv',
               'assets.clips.twitchcdn.net', 'd1ndex63qxojbr.cloudfront.net'),
    'snapchat': ('www.snapchat.com', 'sc-cdn.net'),
    'linkedin': ('www.linkedin.com', 'licdn.com'),
    'bluesky': ('bsky.social', 'plc.directory'),
    'mastodon': ('mastodon.social', 'files.mastodon.social'),
}
DELIVERY = {
    'instagram': ('cdninstagram.com', 'fbcdn.net'),
    'tiktok': tuple(h for h in HOSTS['tiktok'][1:] if h != 'ssstik.io'), 'x': ('video.twimg.com',),
    'facebook': ('fbcdn.net',), 'reddit': ('v.redd.it',),
    'pinterest': ('pinimg.com',), 'twitch': HOSTS['twitch'][1:],
    'snapchat': ('sc-cdn.net',), 'linkedin': ('licdn.com',),
    'mastodon': ('files.mastodon.social',),
}


def checked_url(platform, url, *, media=False):
    if not isinstance(url, str) or re.search(r'[\x00-\x20\x7f\\]', url):
        raise ValueError('Unexpected fallback URL')
    p = urlsplit(url)
    hosts = DELIVERY[platform] if media else HOSTS[platform]
    if (p.scheme != 'https' or p.username or p.password or p.port or p.fragment
            or not any(p.hostname == h or (h in DELIVERY.get(platform, ())
                       and (p.hostname or '').endswith('.' + h)) for h in hosts)):
        raise ValueError('Unexpected fallback delivery host')
    return url


def request(platform, url, data=None, *, media=False, headers=None):
    class Redirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, response_headers, newurl):
            checked_url(platform, newurl, media=media)
            return super().redirect_request(req, fp, code, msg, response_headers, newurl)
    body = json.dumps(data).encode() if data is not None else None
    return build_opener(Redirects()).open(Request(checked_url(platform, url, media=media),
        data=body, headers={'User-Agent': 'Mozilla/5.0',
                           **({'Content-Type': 'application/json'} if body else {}),
                           **(headers or {})}), timeout=20)


def document(platform, url, data=None, *, headers=None):
    with request(platform, url, data, headers=headers) as response:
        raw = response.read(6 * 1024**2 + 1)
    if len(raw) > 6 * 1024**2:
        raise ValueError('Oversized fallback metadata')
    return raw.decode('utf-8')


def transfer(link, url, folder):
    from social_fetch.social_download import progressive_transfer
    checked_url(link.platform, url, media=True)
    return progressive_transfer(lambda u: request(link.platform, u, media=True), url, folder)


def same_post(link, url):
    from social_fetch.social_sources import social_link
    actual = social_link(url)
    return actual is not None and actual.platform == link.platform and actual.identity == link.identity


class PostPage(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.urls, self.videos, self.sources, self.scripts = [], [], [], {}
        self.script, self.parts = None, []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'link' and a.get('rel') == 'canonical':
            self.urls.append(a.get('href', ''))
        if tag == 'meta' and a.get('property') == 'og:url':
            self.urls.append(a.get('content', ''))
        if tag == 'meta' and a.get('property') in {'og:video', 'og:video:url', 'og:video:secure_url'}:
            self.videos.append(a.get('content', ''))
        if tag == 'video' and 'data-sources' in a:
            self.sources.extend(json.loads(a['data-sources']))
        if tag == 'script':
            self.script = a.get('id') or a.get('type')
            self.parts = []

    def handle_data(self, data):
        if self.script:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.script:
            self.scripts.setdefault(self.script, []).append(''.join(self.parts))
            self.script = None


def page_download(link, folder):
    if link.platform == 'facebook':
        return facebook_download(link, folder)
    page = PostPage(document(link.platform, link.url))
    if not page.urls:
        raise ProviderUnavailable('The public page has no selected-post identity')
    if not all(same_post(link, url) for url in page.urls):
        raise ValueError('Fallback returned another post')
    if link.platform == 'linkedin':
        sources = [s for s in page.sources if s.get('type') == 'video/mp4']
        urls = [s.get('src', '') for s in sorted(sources,
                key=lambda s: float(s.get('data-bitrate') or 0), reverse=True)]
    else:
        urls = page.videos
    if link.platform != 'linkedin':
        urls = [u for u in urls if urlsplit(u).path.lower().endswith('.mp4')]
    if not urls:
        raise ProviderUnavailable('The public post has no progressive MP4')
    return transfer(link, urls[0], folder)


def facebook_download(link, folder):
    from social_fetch.social_download import progressive_transfer, resolve_selected_post
    link = resolve_selected_post(link)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
               '(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
               'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
               'Accept-Language': 'en-US,en;q=0.5', 'Sec-Fetch-Mode': 'navigate'}
    page = PostPage(document('facebook', link.url, headers=headers))
    if not page.urls:
        raise ProviderUnavailable('The public page has no selected-post identity')
    if not all(same_post(link, url) for url in page.urls):
        raise ValueError('Fallback returned another post')
    urls = []
    for block in page.scripts.get('application/json', []):
        try:
            stack = [json.loads(block)]
        except json.JSONDecodeError:
            continue
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(v for v in node if isinstance(v, (dict, list)))
                continue
            if not isinstance(node, dict):
                continue
            if (str(node.get('id')) == link.identity and (node.get('__typename') == 'Video'
                    or isinstance(node.get('videoDeliveryLegacyFields'), dict))):
                legacy = node.get('videoDeliveryLegacyFields') or node
                if legacy.get('id') is not None and str(legacy['id']) != link.identity:
                    raise ValueError('Facebook media returned another post')
                urls.extend(legacy[key] for key in ('browser_native_hd_url', 'playable_url_quality_hd',
                    'browser_native_sd_url', 'playable_url') if isinstance(legacy.get(key), str) and legacy[key])
                fragment = node.get('videoDeliveryResponseFragment') or {}
                result = fragment.get('videoDeliveryResponseResult') or {}
                for fmt in result.get('progressive_urls') or []:
                    if isinstance(fmt, dict) and isinstance(fmt.get('progressive_url'), str):
                        urls.append(fmt['progressive_url'])
            stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    if not urls:
        urls = [u for u in page.videos if urlsplit(u).path.lower().endswith('.mp4')]
    if not urls:
        raise ProviderUnavailable('The selected Facebook video has no progressive MP4')
    url = checked_url('facebook', urls[0], media=True)
    return progressive_transfer(lambda value: request('facebook', value, media=True,
        headers={'User-Agent': 'facebookexternalhit/1.1'}), url, folder)


def pinterest_download(link, folder):
    options = {'id': link.identity, 'field_set_key': 'detailed'}
    data = json.loads(document('pinterest',
        'https://www.pinterest.com/resource/PinResource/get/?' +
        urlencode({'data': json.dumps({'options': options})}),
        headers={'X-Pinterest-PWS-Handler': 'www/[username].js'}))
    pin = (data.get('resource_response') or {}).get('data') or {}
    if str(pin.get('id')) != link.identity:
        raise ValueError('Pinterest fallback returned another post')
    if (pin.get('embed') or {}).get('src'):
        raise ProviderUnavailable('External Pinterest embeds are not native videos')
    formats = ((pin.get('videos') or {}).get('video_list') or {}).values()
    videos = [v for v in formats if isinstance(v, dict)
              and urlsplit(v.get('url', '')).path.lower().endswith('.mp4')]
    if not videos:
        raise ProviderUnavailable('The Pinterest pin has no progressive MP4')
    video = max(videos, key=lambda v: int(v.get('height') or 0))
    return transfer(link, video['url'], folder)


def snapchat_download(link, folder):
    page = PostPage(document('snapchat', link.url))
    blocks = page.scripts.get('__NEXT_DATA__') or []
    if len(blocks) != 1:
        raise ProviderUnavailable('No public Spotlight metadata')
    props = json.loads(blocks[0]).get('props', {}).get('pageProps', {})
    stories = (props.get('spotlightFeed') or {}).get('spotlightStories') or []
    slug = link.url.rsplit('/', 1)[1]
    selected = [s for s in stories if ((s.get('story') or {}).get('storyId') or {}).get('value') == slug]
    if len(selected) != 1:
        raise ProviderUnavailable('The selected Spotlight video was not returned')
    media = (selected[0].get('metadata') or {}).get('videoMetadata') or {}
    if not media.get('contentUrl'):
        raise ProviderUnavailable('The selected Spotlight post has no native video')
    return transfer(link, media['contentUrl'], folder)


def twitch_download(link, folder):
    slug = link.url.rsplit('/', 1)[1]
    # Twitch's public web-player client ID is not a user credential.
    data = json.loads(document('twitch', 'https://gql.twitch.tv/gql', {
        'query': 'query($slug:ID!){clip(slug:$slug){slug playbackAccessToken(params:{'
                 'platform:"web",playerBackend:"mediaplayer",playerType:"embed"}){signature value} '
                 'assets{videoQualities{quality sourceURL}}}}', 'variables': {'slug': slug}},
        headers={'Client-ID': 'ue6666qo983tsx6so1t0vnawi233wa'}))
    clip = (data.get('data') or {}).get('clip') or {}
    if not clip:
        raise ProviderUnavailable('The public clip route is unavailable')
    if clip.get('slug') != slug:
        raise ValueError('Twitch fallback returned another clip')
    token = clip.get('playbackAccessToken') or {}
    assets = clip.get('assets') or []
    formats = assets[0].get('videoQualities', []) if assets else []
    if not formats or not token.get('signature') or not token.get('value'):
        raise ProviderUnavailable('The public clip has no progressive video')
    video = max(formats, key=lambda f: int(f.get('quality') or 0))
    url = video['sourceURL']
    url += ('&' if urlsplit(url).query else '?') + urlencode({'sig': token['signature'], 'token': token['value']})
    return transfer(link, url, folder)


def fixupx_download(link, folder):
    from social_fetch.social_sources import social_link
    post_id = link.identity.split('-video', 1)[0]
    def selected_url(url):
        checked_url('x', url)
        if urlsplit(url).hostname != 'fixupx.com':
            raise ValueError('Unexpected X embed redirect host')
        actual = social_link(url.replace('https://fixupx.com/', 'https://x.com/', 1))
        if actual is None or actual.kind != 'video' or actual.identity != link.identity:
            raise ValueError('X embed redirected to another post or attachment')
        return url
    class Redirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            selected_url(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    url = selected_url(link.url.replace('https://x.com/', 'https://fixupx.com/', 1))
    with build_opener(Redirects()).open(Request(url, headers={
            'User-Agent': 'Twitterbot/1.0', 'Accept': 'text/html'}), timeout=20) as response:
        raw = response.read(2 * 1024**2 + 1)
    if len(raw) > 2 * 1024**2:
        raise ValueError('Oversized X embed metadata')
    page = PostPage(raw.decode('utf-8'))
    if not page.urls:
        raise ProviderUnavailable('The X embed has no selected-post identity')
    if any(urlsplit(value).fragment for value in page.urls):
        raise ValueError('Unexpected X post identity fragment')
    identities = [social_link(value) for value in page.urls]
    if any(row is None or row.platform != 'x' or row.kind != 'video'
           or row.identity not in {post_id, link.identity} for row in identities):
        raise ValueError('X fallback returned another post')
    urls = [checked_url('x', value, media=True) for value in page.videos]
    if not urls or any(not urlsplit(value).path.lower().endswith('.mp4') for value in urls):
        raise ProviderUnavailable('The selected X attachment has no progressive MP4')
    if len(set(urls)) != 1:
        raise ValueError('The X embed returned ambiguous selected media')
    return transfer(link, urls[0], folder)


def x_download(link, folder):
    post_id = link.identity.split('-video', 1)[0]
    data = json.loads(document('x', 'https://api.fxtwitter.com/status/' + post_id))
    tweet = data.get('tweet') or data.get('status') or {}
    if data.get('code') != 200 or not tweet:
        raise ProviderUnavailable('The public X fallback is unavailable')
    if str(tweet.get('id')) != post_id:
        raise ValueError('X fallback returned another post')
    # Keep photo/video order for /video/N, rather than selecting N from videos only.
    media = tweet.get('media') or {}
    selected = re.search(r'/video/(\d+)$', link.url)
    if selected:
        entries = media.get('all') or []
        index = int(selected[1]) - 1
        if index >= len(entries) or entries[index].get('type') not in {'video', 'gif'}:
            raise ProviderUnavailable('The selected X attachment is not a video')
        video = entries[index]
    else:
        videos = media.get('videos') or []
        if not videos:
            raise ProviderUnavailable('The X post has no native video')
        video = videos[0]
    return transfer(link, video.get('url', ''), folder)


def reddit_download(link, folder):
    listing = json.loads(document('reddit',
        'https://www.reddit.com/comments/' + link.identity + '.json?raw_json=1&limit=1'))
    posts = listing[0].get('data', {}).get('children', []) if isinstance(listing, list) and listing else []
    post = posts[0].get('data', {}) if posts else {}
    if post.get('id') != link.identity:
        raise ValueError('Reddit fallback returned another post')
    if post.get('crosspost_parent') or post.get('crosspost_parent_list') or not post.get('is_video'):
        raise ProviderUnavailable('Only the selected native Reddit video is supported')
    video = (post.get('secure_media') or {}).get('reddit_video') or {}
    if video.get('has_audio') is not False:
        raise ProviderUnavailable('Reddit split audio requires bounded streaming support')
    return transfer(link, video.get('fallback_url', ''), folder)


def mastodon_download(link, folder):
    post = json.loads(document('mastodon', link.url,
        headers={'Accept': 'application/activity+json'}))
    audience = (post.get('to') or []) + (post.get('cc') or [])
    if not same_post(link, post.get('url', '')) or post.get('type') != 'Note':
        raise ValueError('Mastodon fallback returned another post')
    if 'https://www.w3.org/ns/activitystreams#Public' not in audience:
        raise ValueError('Mastodon fallback returned a nonpublic post')
    videos = [a for a in post.get('attachment', []) if a.get('mediaType') == 'video/mp4']
    if not videos:
        raise ProviderUnavailable('The Mastodon post has no native MP4')
    return transfer(link, videos[0].get('url', ''), folder)


def bluesky_download(link, folder):
    from social_fetch.social_download import bluesky_request, bluesky_url, bounded_json, progressive_transfer, MAX_BYTES
    did = link.handle
    if not did.startswith('did:plc:'):
        did = json.loads(document('bluesky', 'https://bsky.social/xrpc/com.atproto.identity.resolveHandle?' +
                         urlencode({'handle': link.handle}))).get('did', '')
    if not re.fullmatch(r'did:plc:[a-z2-7]{24}', did):
        raise ValueError('Unexpected Bluesky fallback identity')
    directory = bounded_json(bluesky_request, 'https://plc.directory/' + did)
    endpoint = next((s.get('serviceEndpoint', '') for s in directory.get('service', [])
                     if s.get('type') == 'AtprotoPersonalDataServer'), '')
    bluesky_url(endpoint)
    if not re.fullmatch(r'https://[a-z0-9-]+\.[a-z0-9-]+\.host\.bsky\.network', endpoint):
        raise ValueError('Only Bluesky-hosted public storage is supported')
    post_id = link.url.rsplit('/', 1)[1]
    post = bounded_json(bluesky_request, endpoint + '/xrpc/com.atproto.repo.getRecord?' +
        urlencode({'repo': did, 'collection': 'app.bsky.feed.post', 'rkey': post_id}))
    if post.get('uri') != f'at://{did}/app.bsky.feed.post/{post_id}':
        raise ValueError('Bluesky fallback returned another post')
    embed = (post.get('value') or {}).get('embed') or {}
    if embed.get('$type') == 'app.bsky.embed.recordWithMedia':
        embed = embed.get('media') or {}
    video = embed.get('video') or {}
    cid = (video.get('ref') or {}).get('$link', '')
    size = video.get('size')
    if (embed.get('$type') != 'app.bsky.embed.video' or video.get('mimeType') != 'video/mp4'
            or not re.fullmatch(r'b[a-z2-7]{20,128}', cid) or not isinstance(size, int)
            or not 1024 <= size <= MAX_BYTES):
        raise ProviderUnavailable('The Bluesky post has no bounded native MP4')
    return progressive_transfer(bluesky_request, endpoint + '/xrpc/com.atproto.sync.getBlob?' +
        urlencode({'did': did, 'cid': cid}), folder, expected_size=size)


def ssstik_download(link, folder):
    from http.cookiejar import CookieJar
    from urllib.request import HTTPCookieProcessor
    from social_fetch.social_download import progressive_transfer, resolve_selected_post, tiktok_full_post
    link = resolve_selected_post(link)
    post_id = link.identity
    ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36')
    class Redirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urlsplit(newurl).hostname != 'ssstik.io':
                raise ValueError('Unexpected TikTok form redirect')
            checked_url('tiktok', newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    opener = build_opener(Redirects(), HTTPCookieProcessor(CookieJar()))
    def form_request(url, data=None):
        headers = {'User-Agent': ua, 'Origin': 'https://ssstik.io',
                   'Referer': 'https://ssstik.io/en', 'HX-Current-URL': 'https://ssstik.io/en',
                   'HX-Request': 'true', 'HX-Target': 'target', 'HX-Trigger': '_gcaptcha_pt'}
        if data is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        with opener.open(Request(checked_url('tiktok', url), data=data, headers=headers), timeout=20) as response:
            raw = response.read(2 * 1024**2 + 1)
        if len(raw) > 2 * 1024**2:
            raise ValueError('Oversized TikTok form response')
        return raw.decode('utf-8')
    urls = []
    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == 'a':
                url = dict(attrs).get('href', '')
                match = re.fullmatch(r'/ssstik/(\d{10,25})', urlsplit(url).path)
                if match:
                    checked_url('tiktok', url, media=True)
                    if urlsplit(url).hostname != 'tikcdn.io' or match[1] != post_id:
                        raise ValueError('TikTok fallback returned another post')
                    urls.append(url)
    for attempt in range(2):
        page = form_request('https://ssstik.io/en')
        token = re.search(r"""(?:s_tt\s*=|tt\s*:)\s*['"]([A-Za-z0-9_=+/-]+)['"]""", page)
        if token is None:
            raise ProviderUnavailable('The public TikTok form is unavailable')
        body = urlencode({'id': link.url, 'locale': 'en', 'tt': token[1]}).encode()
        result = form_request('https://ssstik.io/abc?url=dl', body)
        Links().feed(result)
        if urls:
            break
        if attempt == 0:
            recovered = tiktok_full_post(link)
            if recovered.url == link.url:
                break
            link = recovered
        else:
            break
    if not urls:
        raise ProviderUnavailable('The TikTok form has no selected-post video')
    return progressive_transfer(lambda url: request('tiktok', url, media=True,
        headers={'User-Agent': ua, 'Referer': 'https://ssstik.io/'}), urls[0], folder)


def extractor_download(link, folder):
    from social_fetch.social_download import progressive_download
    return progressive_download(link, folder)


FALLBACKS = {
    'instagram': ('instagram_extractor', extractor_download),
    'tiktok': ('ssstik', ssstik_download),
    'x': ('fixupx', fixupx_download), 'facebook': ('facebook_public_page', page_download),
    'reddit': ('reddit_public_json', reddit_download),
    'pinterest': ('pinterest_public_api', pinterest_download),
    'twitch': ('twitch_public_graphql', twitch_download),
    'snapchat': ('snapchat_public_page', snapchat_download),
    'linkedin': ('linkedin_public_page', page_download),
    'mastodon': ('mastodon_activitypub', mastodon_download),
    'bluesky': ('bluesky_public_repo', bluesky_download),
}
