"""Public social link identities shared by discovery, account browsing and acquisition.

Recognition is not proof that a post contains playable video. Never accepts a
private URL, arbitrary website, login page or whole-account download request.
"""
from dataclasses import dataclass
import hashlib
import re
from urllib.parse import parse_qs, urlsplit

from social_fetch.youtube_web import youtube_url

DEFAULT_SOCIAL = ('youtube', 'instagram', 'tiktok', 'x', 'facebook', 'reddit')
LABELS = {'youtube': 'YouTube', 'instagram': 'Instagram', 'tiktok': 'TikTok',
          'x': 'X', 'facebook': 'Facebook', 'reddit': 'Reddit', 'bluesky': 'Bluesky',
          'pinterest': 'Pinterest', 'twitch': 'Twitch clips', 'snapchat': 'Snapchat Spotlight',
          'linkedin': 'LinkedIn', 'mastodon': 'Mastodon (mastodon.social)'}
DOMAINS = {'youtube': ('youtube.com', 'youtu.be'), 'instagram': ('instagram.com',),
           'tiktok': ('tiktok.com',), 'x': ('x.com', 'twitter.com'),
           'facebook': ('facebook.com',), 'reddit': ('reddit.com',), 'bluesky': ('bsky.app',),
           'pinterest': ('pinterest.com',), 'twitch': ('twitch.tv', 'clips.twitch.tv'),
           'snapchat': ('snapchat.com',), 'linkedin': ('linkedin.com',),
           'mastodon': ('mastodon.social',)}


@dataclass(frozen=True)
class SocialLink:
    platform: str
    url: str
    identity: str
    kind: str
    handle: str = ''


def social_link(value: str) -> SocialLink | None:
    if not isinstance(value, str) or len(value) > 4096 or re.search(r'[\x00-\x20\x7f\\]', value):
        return None
    try:
        p = urlsplit(value)
        if p.scheme not in ('https', 'http') or p.username or p.password or p.port not in (None, 443 if p.scheme == 'https' else 80):
            return None
        host = (p.hostname or '').lower().removeprefix('www.')
        path, q = p.path.rstrip('/'), parse_qs(p.query)
        if host in ('youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'):
            try:
                url = youtube_url(value)
                return SocialLink('youtube', url, parse_qs(urlsplit(url).query)['v'][0], 'video')
            except ValueError:
                match = re.fullmatch(r'/(@[\w.-]{1,100}|(?:channel|c|user)/[\w.-]{1,100})(?:/(?:videos|shorts))?', path)
                if match:
                    account = match[1]
                    return SocialLink('youtube', 'https://www.youtube.com/' + account, account, 'account', account)
        if p.scheme != 'https':
            return None
        if host == 'bsky.app':
            match = re.fullmatch(r'/profile/(did:plc:[a-z2-7]{24}|[A-Za-z0-9][A-Za-z0-9.-]{1,251}\.[A-Za-z]{2,63})(?:/post/([a-z2-7]{13}))?', path)
            if match:
                handle, post = match.groups()
                handle = handle.lower()
                url = 'https://bsky.app/profile/' + handle
                identity = hashlib.sha256((handle + '/' + post).encode()).hexdigest()[:32] if post else handle
                return SocialLink('bluesky', url + ('/post/' + post if post else ''), identity,
                                  'video' if post else 'account', handle)
        if host == 'pinterest.com':
            match = re.fullmatch(r'/pin/(?:[A-Za-z0-9_-]+--)?(\d{8,25})', path)
            if match:
                identity = match[1]
                return SocialLink('pinterest', f'https://www.pinterest.com/pin/{identity}/', identity, 'video')
        if host == 'snapchat.com':
            match = re.fullmatch(r'/spotlight/([A-Za-z0-9_-]{20,150})', path)
            if match:
                slug = match[1]
                identity = slug if len(slug) <= 64 else hashlib.sha256(slug.encode()).hexdigest()[:32]
                return SocialLink('snapchat', 'https://www.snapchat.com/spotlight/' + slug, identity, 'video')
        if host == 'linkedin.com':
            match = re.fullmatch(r'/posts/[A-Za-z0-9_-]+-(\d{10,25})-[A-Za-z0-9_-]{4}', path)
            feed = re.fullmatch(r'/feed/update/urn:li:activity:(\d{10,25})', path)
            if match or feed:
                identity = (match or feed)[1]
                return SocialLink('linkedin', 'https://www.linkedin.com' + path + '/', identity, 'video')
        if host == 'mastodon.social':
            match = re.fullmatch(r'/@([A-Za-z0-9_]{1,30})(?:/(\d{5,25}))?', path)
            if match:
                handle, post = match.groups()
                handle = handle.lower()
                url = 'https://mastodon.social/@' + handle
                identity = hashlib.sha256(('mastodon.social/' + post).encode()).hexdigest()[:32] if post else handle
                return SocialLink('mastodon', url + ('/' + post if post else ''), identity,
                                  'video' if post else 'account', handle)
        if host in ('twitch.tv', 'clips.twitch.tv'):
            slug = ''
            handle = ''
            if host == 'clips.twitch.tv':
                slug = path[1:] if re.fullmatch(r'/[A-Za-z0-9_-]{5,100}', path) else ''
                if path == '/embed' and len(q.get('clip', [])) == 1:
                    slug = q['clip'][0]
            else:
                match = re.fullmatch(r'/([A-Za-z0-9_]{1,25})/clip/([A-Za-z0-9_-]{5,100})', path)
                if match:
                    handle, slug = match.groups()
            if re.fullmatch(r'[A-Za-z0-9_-]{5,100}', slug) and slug.lower() not in {'embed', 'directory', 'settings', 'login'}:
                identity = slug if len(slug) <= 64 else hashlib.sha256(slug.encode()).hexdigest()[:32]
                return SocialLink('twitch', 'https://clips.twitch.tv/' + slug, identity, 'video', handle)
        if host in ('instagram.com', 'm.instagram.com'):
            match = re.fullmatch(r'/(?:p|reel|reels|tv)/([A-Za-z0-9_-]{5,16})', path)
            if match:
                code = match[1]
                return SocialLink('instagram', f'https://www.instagram.com/p/{code}/', code, 'video')
            match = re.fullmatch(r'/([A-Za-z0-9._]{1,30})(?:/reels)?', path)
            if match and match[1].lower() not in {'accounts', 'explore', 'direct', 'stories', 'reels', 'p', 'tv', 'about'}:
                handle = match[1].lower()
                return SocialLink('instagram', f'https://www.instagram.com/{handle}/', handle, 'account', handle)
        if host in ('tiktok.com', 'm.tiktok.com'):
            match = re.fullmatch(r'/@([A-Za-z0-9._]{0,30})(?:/video/(\d{10,25}))?', path)
            if match and (match[1] or match[2]):
                handle, identity = match.groups()
                url = f'https://www.tiktok.com/@{handle}'
                return SocialLink('tiktok', url + ('/video/' + identity if identity else ''), identity or handle.lower(),
                                  'video' if identity else 'account', handle)
            match = re.fullmatch(r'/t/([A-Za-z0-9]{5,30})', path)
            if match:
                return SocialLink('tiktok', f'https://www.tiktok.com/t/{match[1]}/', match[1], 'video')
        if host in ('vm.tiktok.com', 'vt.tiktok.com') and re.fullmatch(r'/[A-Za-z0-9]{5,30}', path):
            return SocialLink('tiktok', f'https://{host}{path}/', path[1:], 'video')
        if host in ('x.com', 'twitter.com', 'mobile.twitter.com'):
            match = re.fullmatch(r'/(?:i(?:/web)?/status|([A-Za-z0-9_]{1,15})/status)/(\d{5,25})(?:/video/([1-4]))?', path)
            if match:
                handle, identity, selected = match.groups()
                suffix = '/video/' + selected if selected and selected != '1' else ''
                key = identity + '-video' + selected if suffix else identity
                return SocialLink('x', f'https://x.com/{handle or "i"}/status/{identity}{suffix}', key, 'video', handle or '')
            match = re.fullmatch(r'/([A-Za-z0-9_]{1,15})(?:/media)?', path)
            if match and match[1].lower() not in {'home', 'search', 'explore', 'login', 'signup', 'settings', 'i', 'intent', 'share'}:
                handle = match[1].lower()
                return SocialLink('x', f'https://x.com/{handle}', handle, 'account', handle)
        if host in ('facebook.com', 'm.facebook.com', 'web.facebook.com'):
            match = re.fullmatch(r'/(?:reel/|[^/]+/videos/(?:[^/]+/)?)(\d{5,25})', path)
            identity = match[1] if match else q.get('v', [''])[0] if path in ('/watch', '/video.php') and len(q.get('v', [])) == 1 else ''
            if re.fullmatch(r'\d{5,25}', identity):
                handle = path.strip('/').split('/')[0] if '/videos/' in path else ''
                return SocialLink('facebook', f'https://www.facebook.com/watch/?v={identity}', identity, 'video', handle)
            match = re.fullmatch(r'/share/[rv]/([A-Za-z0-9]{5,30})', path)
            if match:
                return SocialLink('facebook', f'https://www.facebook.com{path}/', match[1], 'video')
            match = re.fullmatch(r'/([A-Za-z0-9.]{1,100})(?:/(?:videos|reels))?', path)
            if match and match[1].lower() not in {'watch', 'reel', 'reels', 'login', 'help', 'share', 'groups', 'marketplace', 'search', 'gaming', 'events'}:
                handle = match[1]
                return SocialLink('facebook', f'https://www.facebook.com/{handle}', handle.lower(), 'account', handle)
        if host in ('reddit.com', 'old.reddit.com'):
            user_post = re.fullmatch(r'/(?:user|u)/([A-Za-z0-9_-]{3,20})/comments/([a-z0-9]{3,12})(?:/[^/]+)?', path)
            if user_post:
                handle, identity = user_post.groups()
                return SocialLink('reddit', f'https://www.reddit.com/user/{handle}/comments/{identity}/', identity, 'video', handle)
            match = re.fullmatch(r'/r/([A-Za-z0-9_]{2,30})/comments/([a-z0-9]{3,12})(?:/[^/]+)?', path)
            if match:
                community, identity = match.groups()
                return SocialLink('reddit', f'https://www.reddit.com/r/{community}/comments/{identity}/', identity, 'video', community)
            match = re.fullmatch(r'/(?:user|u)/([A-Za-z0-9_-]{3,20})', path)
            if match:
                handle = match[1]
                return SocialLink('reddit', f'https://www.reddit.com/user/{handle}/', handle.lower(), 'account', handle)
    except ValueError:
        pass
    return None


def download_link(value: str) -> SocialLink:
    link = social_link(value)
    if link is None or link.kind != 'video':
        raise ValueError('Use a supported public video post link. Accounts are searched, not downloaded in bulk.')
    return link
