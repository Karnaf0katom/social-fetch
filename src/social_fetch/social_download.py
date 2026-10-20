"""Bounded public social acquisition; media checks run separately through CPU admission.

Instagram reuses SnapInsta; TikTok uses TikWM. Bluesky and selected Mastodon
posts use public metadata APIs and native MP4 delivery. Other selected sources
use attributed, allowlisted yt-dlp extraction. No user login or cookies are used.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from social_fetch.social_sources import download_link, social_link
from social_fetch.social_fallbacks import FALLBACKS, ProviderUnavailable

MAX_BYTES = 512 * 1024**2
PROGRESSIVE_EXTRACTORS = {'instagram': 'Instagram', 'tiktok': 'TikTok',
                        'pinterest': 'Pinterest', 'twitch': 'TwitchClips',
                        'snapchat': 'SnapchatSpotlight', 'linkedin': 'LinkedIn'}
EXTRACTOR_FILTERS = {**PROGRESSIVE_EXTRACTORS, 'twitch': 'twitch:clips'}
DELIVERY_HOSTS = {'instagram': ('cdninstagram.com', 'fbcdn.net'),
                  'tiktok': ('tiktokcdn.com', 'tiktokcdn-us.com', 'tiktokcdn-eu.com',
                             'tiktokv.com', 'byteoversea.com', 'ibytedtos.com',
                             'v19-webapp-prime.tiktok.com'),
                  'pinterest': ('pinimg.com',), 'twitch': ('clips-media-assets2.twitch.tv',
                  'assets.clips.twitchcdn.net', 'd1ndex63qxojbr.cloudfront.net'),
                  'snapchat': ('sc-cdn.net',), 'linkedin': ('licdn.com',)}


def delivery_url(platform, url):
    p = urlsplit(url)
    host = p.hostname or ''
    if (p.scheme != 'https' or p.username or p.password or p.port or p.fragment
            or not any(host == allowed or host.endswith('.' + allowed)
                       for allowed in DELIVERY_HOSTS[platform])):
        raise ValueError('Unexpected ' + platform + ' delivery host')
    return url


def delivery_request(platform, url):
    class Redirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            delivery_url(platform, newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    return build_opener(Redirects()).open(Request(delivery_url(platform, url),
        headers={'User-Agent': 'Mozilla/5.0'}), timeout=30)


def progressive_download(link, folder):
    """Use one attributed extractor for metadata, then validate and stream the MP4."""
    if link.platform == 'tiktok':
        link = resolve_selected_post(link)
    executable = shutil.which('yt-dlp')
    runner = [executable] if executable else [sys.executable, '-m', 'yt_dlp'] if importlib.util.find_spec('yt_dlp') else None
    if not runner:
        raise ProviderUnavailable('Public social extraction is not installed on this server')
    metadata = folder / 'extractor-private.json'
    try:
        with metadata.open('w') as output:
            subprocess.run([*runner, '--ignore-config', '--no-playlist', '--playlist-items', '1',
                '--use-extractors', EXTRACTOR_FILTERS[link.platform], '--skip-download',
                '--dump-single-json', '--socket-timeout', '10', '--retries', '0', '--extractor-retries', '0',
                '--format', 'best[ext=mp4][protocol=https]', link.url], stdout=output,
                check=True, timeout=90, stdin=subprocess.DEVNULL)
        if metadata.stat().st_size > 2 * 1024**2:
            raise ValueError('Oversized extractor metadata')
        data = json.loads(metadata.read_text())
        expected_id = link.url.rsplit('/', 1)[1] if link.platform in {'twitch', 'snapchat'} else link.identity
        actual_id = data.get('display_id') if link.platform == 'twitch' else data.get('id')
        if link.platform == 'instagram' and data.get('_type') == 'playlist':
            if str(actual_id) != expected_id or data.get('extractor_key') != 'Instagram':
                raise ValueError('Extractor returned another post')
            entries = data.get('entries') or []
            if len(entries) > 20:
                raise ValueError('Oversized Instagram carousel')
            data = next((e for e in entries if isinstance(e, dict) and e.get('ext') == 'mp4'
                         and e.get('protocol') == 'https' and e.get('vcodec') != 'none'), {})
            if not data:
                raise ProviderUnavailable('The Instagram post has no progressive video')
            actual_id = expected_id  # Bound above by the selected parent post, not the child media ID.
        if (str(actual_id) != expected_id or data.get('_type', 'video') != 'video'
                or data.get('extractor_key') != PROGRESSIVE_EXTRACTORS[link.platform]):
            raise ValueError('Extractor returned another post')
        if data.get('ext') != 'mp4' or data.get('protocol') != 'https' or data.get('vcodec') == 'none':
            raise ProviderUnavailable('The post has no progressive HTTPS MP4')
        return progressive_transfer(lambda url: delivery_request(link.platform, url), data['url'], folder)
    finally:
        metadata.unlink(missing_ok=True)


def bluesky_url(url):
    p = urlsplit(url)
    host = p.hostname or ''
    if (p.scheme != 'https' or p.username or p.password or p.port or p.fragment
            or not (host in {'public.api.bsky.app', 'plc.directory'}
                    or re.fullmatch(r'[a-z0-9-]+\.[a-z0-9-]+\.host\.bsky\.network', host))):
        raise ValueError('Unexpected Bluesky delivery host')
    return url


class BlueskyRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        bluesky_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def bluesky_request(url):
    return build_opener(BlueskyRedirects()).open(Request(bluesky_url(url),
        headers={'User-Agent': 'social-fetch/alpha'}), timeout=30)


def bounded_json(request, url):
    with request(url) as response:
        raw = response.read(2 * 1024**2 + 1)
    if len(raw) > 2 * 1024**2:
        raise ValueError('Oversized post metadata')
    return json.loads(raw)


def mastodon_url(url):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.username or p.password or p.port or p.fragment
            or p.hostname not in {'mastodon.social', 'files.mastodon.social'}):
        raise ValueError('Unexpected Mastodon instance or delivery host')
    return url


class MastodonRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        mastodon_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def mastodon_request(url):
    return build_opener(MastodonRedirects()).open(Request(mastodon_url(url),
        headers={'User-Agent': 'social-fetch/alpha'}), timeout=30)


def mastodon_download(link, folder):
    from social_fetch.social_sources import social_link
    post_id = link.url.rsplit('/', 1)[1]
    post = bounded_json(mastodon_request, 'https://mastodon.social/api/v1/statuses/' + post_id)
    actual = social_link(post.get('url', ''))
    if (str(post.get('id')) != post_id or not actual or actual.url != link.url
            or post.get('visibility') not in {'public', 'unlisted'} or post.get('reblog')):
        raise ValueError('Mastodon returned another or nonpublic post')
    media = next((m for m in post.get('media_attachments', []) if m.get('type') in {'video', 'gifv'}), None)
    if not media:
        raise ValueError('The Mastodon post has no native video')
    return progressive_transfer(mastodon_request, mastodon_url(media.get('url', '')), folder)


def progressive_transfer(request, url, folder, *, expected_size=None):
    """One complete HTTPS MP4, bounded even without Content-Length. No manifests."""
    target = folder / 'raw.mp4'
    pending = target.with_suffix('.part')
    size, deadline = 0, time.monotonic() + 300
    try:
        with request(url) as response, pending.open('wb') as output:
            if response.status != 200:
                raise ValueError('Expected a complete MP4 response')
            declared = response.headers.get('Content-Length')
            declared = int(declared) if declared is not None else None
            if declared is not None and not 1024 <= declared <= MAX_BYTES:
                raise ValueError('Video exceeds its size bound')
            if expected_size is not None and declared is not None and declared != expected_size:
                raise ProviderUnavailable('Incomplete MP4 transfer')
            for chunk in iter(lambda: response.read(256 * 1024), b''):
                size += len(chunk)
                if size > MAX_BYTES or time.monotonic() > deadline:
                    raise ValueError('Video exceeded its size or time bound')
                output.write(chunk)
        if ((declared is not None and size != declared)
                or (expected_size is not None and size != expected_size)):
            raise ProviderUnavailable('Incomplete MP4 transfer')
        with pending.open('rb') as handle:
            if size < 1024 or b'ftyp' not in handle.read(128):
                raise ValueError('Response is not an MP4')
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
    return target


def bluesky_download(link, folder):
    post_id = link.url.rsplit('/', 1)[1]
    post = bounded_json(bluesky_request, 'https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread?' +
                        urlencode({'uri': f'at://{link.handle}/app.bsky.feed.post/{post_id}',
                                   'depth': 0, 'parentHeight': 0})).get('thread', {}).get('post', {})
    author = post.get('author') or {}
    did = author.get('did', '')
    if (not re.fullmatch(r'did:plc:[a-z2-7]{24}', did)
            or post.get('uri') != f'at://{did}/app.bsky.feed.post/{post_id}'
            or link.handle not in (did, str(author.get('handle', '')).lower())):
        raise ValueError('Bluesky returned another post')
    embed = (post.get('record') or {}).get('embed') or {}
    if embed.get('$type') == 'app.bsky.embed.recordWithMedia':
        embed = embed.get('media') or {}
    # Quoted videos and external links are not the requested author's own media.
    video = embed.get('video') or {}
    cid = (video.get('ref') or {}).get('$link', '')
    size = video.get('size')
    if (embed.get('$type') != 'app.bsky.embed.video' or video.get('mimeType') != 'video/mp4'
            or not re.fullmatch(r'b[a-z2-7]{20,128}', cid)
            or not isinstance(size, int) or not 1024 <= size <= MAX_BYTES):
        raise ValueError('The Bluesky post has no bounded native MP4')
    document = bounded_json(bluesky_request, 'https://plc.directory/' + did)
    endpoint = next((s.get('serviceEndpoint', '') for s in document.get('service', [])
                     if s.get('type') == 'AtprotoPersonalDataServer'), '')
    bluesky_url(endpoint)
    if not re.fullmatch(r'https://[a-z0-9-]+\.[a-z0-9-]+\.host\.bsky\.network', endpoint):
        raise ValueError('Only Bluesky-hosted public storage is supported')
    delivery = endpoint + '/xrpc/com.atproto.sync.getBlob?' + urlencode({'did': did, 'cid': cid})
    return progressive_transfer(bluesky_request, delivery, folder, expected_size=size)


def write_json(path, value):
    pending = path.with_suffix('.tmp')
    pending.write_text(json.dumps(value) + '\n')
    pending.replace(path)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def tikwm_url(url):
    p = urlsplit(url)
    host = p.hostname or ''
    if (p.scheme != 'https' or p.username or p.password or p.port
            or not (host in {'tikwm.com', 'www.tikwm.com'} or host.endswith(
                ('.tikwm.com', '.tiktokcdn.com', '.tiktokcdn-us.com', '.tiktokcdn-eu.com')))):
        raise ValueError('Unexpected TikTok delivery host')
    return url


class TikwmRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        tikwm_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def tikwm_request(url, data=None):
    return build_opener(TikwmRedirects()).open(Request(tikwm_url(url), data=data,
        headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.tikwm.com/',
                 **({'Content-Type': 'application/x-www-form-urlencoded'} if data else {})}), timeout=30)


def resolve_selected_post(link):
    """Bind native TikTok/Facebook share redirects before trusting a provider ID."""
    if link.platform not in {'tiktok', 'facebook'}:
        return link
    def canonical(row):
        path = urlsplit(row.url).path.rstrip('/')
        return row.identity.isdigit() and (
            row.platform == 'facebook' and path == '/watch' or
            row.platform == 'tiktok' and re.fullmatch(r'/@[^/]*/video/\d{10,25}', path))
    if canonical(link):
        return link
    class NoFollow(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = build_opener(NoFollow())
    url = link.url
    for _ in range(6):
        actual = social_link(url)
        if (actual is None or actual.platform != link.platform or actual.kind != 'video'
                or urlsplit(url).fragment):
            raise ValueError('Share redirect escaped its selected platform post')
        if canonical(actual):
            return actual
        try:
            with opener.open(Request(actual.url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15) as response:
                raw = response.read(2 * 1024**2 + 1)
        except HTTPError as error:
            if error.code in {301, 302, 303, 307, 308} and error.headers.get('Location'):
                url = urljoin(actual.url, error.headers['Location'])
                error.close()
                continue
            raise
        if len(raw) > 2 * 1024**2:
            raise ValueError('Oversized selected-post redirect page')
        from social_fetch.social_fallbacks import PostPage
        page = PostPage(raw.decode('utf-8'))
        identities = [social_link(value) for value in page.urls]
        if identities:
            if any(row is None or row.platform != link.platform or row.kind != 'video'
                   or not canonical(row) for row in identities):
                raise ValueError('Share page returned an unexpected post identity')
            if len({row.identity for row in identities}) != 1:
                raise ValueError('Share page returned conflicting post identities')
            return identities[0]
        raise ProviderUnavailable('The public share has no canonical post binding')
    raise ProviderUnavailable('The public share exceeded the redirect bound')


def tiktok_full_post(link):
    """Recover an author only from the selected native video's own metadata."""
    if link.platform != 'tiktok' or not link.identity.isdigit():
        raise ValueError('Unbound TikTok post')
    class Redirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            actual = social_link(newurl)
            if (actual is None or actual.platform != 'tiktok' or actual.kind != 'video'
                    or actual.identity != link.identity or '/video/' not in actual.url
                    or urlsplit(newurl).fragment):
                raise ValueError('TikTok author lookup redirected to another post')
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    with build_opener(Redirects()).open(Request(link.url,
            headers={'User-Agent': 'Mozilla/5.0'}), timeout=15) as response:
        raw = response.read(2 * 1024**2 + 1)
    if len(raw) > 2 * 1024**2:
        raise ValueError('Oversized TikTok author metadata')
    from social_fetch.social_fallbacks import PostPage
    page = PostPage(raw.decode('utf-8'))
    blocks = page.scripts.get('__UNIVERSAL_DATA_FOR_REHYDRATION__') or []
    if len(blocks) != 1:
        raise ProviderUnavailable('The native TikTok post has no author metadata')
    detail = json.loads(blocks[0]).get('__DEFAULT_SCOPE__', {}).get('webapp.video-detail') or {}
    item = (detail.get('itemInfo') or {}).get('itemStruct') or {}
    if not item:
        raise ProviderUnavailable('The native TikTok post is unavailable')
    if str(item.get('id')) != link.identity:
        raise ValueError('TikTok author metadata returned another post')
    author = (item.get('author') or {}).get('uniqueId')
    if not isinstance(author, str) or not re.fullmatch(r'[A-Za-z0-9._]{1,30}', author):
        raise ValueError('Unexpected TikTok author identity')
    return download_link('https://www.tiktok.com/@' + author + '/video/' + link.identity)


def tiktok_download(link, folder):
    link = resolve_selected_post(link)
    data = urlencode({'url': link.url, 'hd': '1'}).encode()
    with tikwm_request('https://www.tikwm.com/api/', data) as response:
        raw = response.read(2 * 1024**2 + 1)
    if len(raw) > 2 * 1024**2:
        raise ValueError('Oversized TikTok response')
    result = json.loads(raw)
    row = result.get('data') or {}
    if result.get('code') != 0 or not re.fullmatch(r'\d{10,25}', str(row.get('id', ''))):
        raise ProviderUnavailable('The public TikTok downloader returned no video')
    if link.identity.isdigit() and str(row['id']) != link.identity:
        raise ValueError('TikTok returned another post')
    delivery = row.get('hdplay') or row.get('play')
    if not isinstance(delivery, str):
        raise ValueError('The TikTok post has no downloadable video')
    if delivery.startswith('/'):
        delivery = 'https://www.tikwm.com' + delivery
    return progressive_transfer(tikwm_request, delivery, folder)


def primary_download(link, folder):
    if link.platform == 'facebook':
        link = resolve_selected_post(link)
    if link.platform == 'instagram':
        from social_fetch.instagram_web import Form, download, page, videos
        rows = videos(Form(page('/process', {'q': link.url, 'scope': 'home', 'lang': 'en'})), link.identity)
        if not rows:
            raise ProviderUnavailable('The Instagram post has no public video')
        # A carousel is one selected post: acquire its first video, never the account.
        (folder / 'source').mkdir(exist_ok=True)
        receipt = download(rows[0], folder)
        target = folder / 'raw.mp4'
        (folder / receipt['file']).replace(target)
    elif link.platform == 'tiktok':
        target = tiktok_download(link, folder)
    elif link.platform == 'reddit':
        from social_fetch.reddit_web import download_video
        target = download_video(link.url, folder)
    elif link.platform == 'bluesky':
        target = bluesky_download(link, folder)
    elif link.platform == 'mastodon':
        target = mastodon_download(link, folder)
    elif link.platform in PROGRESSIVE_EXTRACTORS:
        target = progressive_download(link, folder)
    else:
        executable = shutil.which('yt-dlp')
        runner = [executable] if executable else [sys.executable, '-m', 'yt_dlp'] if importlib.util.find_spec('yt_dlp') else None
        if not runner:
            raise ProviderUnavailable('Public social extraction is not installed on this server')
        # Restrict to progressive HTTPS MP4: no manifest, renderer, whole profile,
        # generic extractor, implicit config/cookies, external downloader or merge.
        target = folder / 'raw.mp4'
        extractor = {'x': 'twitter,twitter:amplify', 'facebook': 'facebook,facebook:reel,FacebookRedirectURL', 'reddit': 'Reddit'}[link.platform]
        command = [*runner, '--ignore-config', '--no-playlist', '--playlist-items', '1',
                   '--force-overwrites',
                   '--use-extractors', extractor, '--no-progress', '--socket-timeout', '15',
                   '--retries', '0', '--extractor-retries', '0', '--fixup', 'never',
                   '--max-filesize', '512M', '--format',
                   'best[ext=mp4][protocol=https]',
                   '--output', str(target), '--print-to-file', 'after_move:%(display_id,id)s', str(folder / 'extracted-id.txt')]
        if link.platform == 'x':
            command.extend(['--extractor-args', 'twitter:api=syndication'])
        command.append(link.url)
        subprocess.run(command, check=True, timeout=600, stdin=subprocess.DEVNULL)
        identities = (folder / 'extracted-id.txt').read_text().splitlines()
        amplify_id = (link.platform == 'x' and identities
                      and re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', identities[-1]))
        expected_id = link.identity.split('-video', 1)[0] if link.platform == 'x' else link.identity
        if (expected_id.isdigit() or link.platform == 'reddit') and (not identities or identities[-1] != expected_id) and not amplify_id:
            raise ValueError('Extractor returned another post')
    if not target.is_file() or not 1024 <= target.stat().st_size <= MAX_BYTES:
        raise ValueError('The post did not produce a bounded MP4')
    return target


PRIMARY_ROUTES = {'instagram': 'snapinsta', 'tiktok': 'tikwm', 'x': 'x_syndication',
    'facebook': 'facebook_extractor', 'reddit': 'reddit_embed_rapidsave',
    'bluesky': 'bluesky_appview', 'mastodon': 'mastodon_rest',
    'pinterest': 'pinterest_extractor', 'twitch': 'twitch_extractor',
    'snapchat': 'snapchat_extractor', 'linkedin': 'linkedin_extractor'}
ROUTE_FAILURES = (URLError, TimeoutError, ConnectionError, subprocess.SubprocessError,
                  ProviderUnavailable, json.JSONDecodeError)


def acquire(url, folder):
    link = download_link(url)
    folder.mkdir(parents=True, exist_ok=True)
    receipt_path = folder / 'acquisition.json'
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_text())
        existing = folder / 'raw.mp4'
        if (previous.get('source_url') == link.url and existing.is_file()
                and existing.stat().st_size == previous.get('bytes') and digest(existing) == previous.get('sha256')):
            return
    # A failed attempt must never lend bytes or an identity to the next route.
    receipt_path.unlink(missing_ok=True)
    target = folder / 'raw.mp4'
    target.unlink(missing_ok=True)
    attempts = []
    fallback_name, fallback = FALLBACKS[link.platform]
    for route, adapter in ((PRIMARY_ROUTES[link.platform], primary_download), (fallback_name, fallback)):
        attempt = folder / ('attempt-' + route)
        if attempt.exists():
            shutil.rmtree(attempt)
        attempt.mkdir()
        try:
            raw = adapter(link, attempt)
            if not raw.is_file() or not 1024 <= raw.stat().st_size <= MAX_BYTES:
                raise ValueError('The post did not produce a bounded MP4')
            with raw.open('rb') as handle:
                if b'ftyp' not in handle.read(128):
                    raise ValueError('The response is not an MP4')
            raw.replace(target)
            attempts.append({'route': route, 'status': 'acquired'})
            write_json(receipt_path, {'source_url': link.url, 'platform': link.platform,
                'bytes': target.stat().st_size, 'sha256': digest(target),
                'route': route, 'route_attempts': attempts,
                **({'audio_required': True} if link.platform == 'reddit'
                   and route == PRIMARY_ROUTES['reddit'] else {})})
            return
        except ROUTE_FAILURES as error:
            # Only stable route names and exception classes cross the API boundary.
            # Validation errors and local storage errors fail closed, without fallback.
            attempts.append({'route': route, 'status': 'unavailable', 'error': type(error).__name__})
            if hasattr(error, 'close'):
                error.close()
        except Exception as error:
            attempts.append({'route': route, 'status': 'rejected' if isinstance(error, ValueError) else 'failed',
                             'error': type(error).__name__})
            raise
        finally:
            shutil.rmtree(attempt, ignore_errors=True)
            write_json(folder / 'route-attempts.json', attempts)
    raise ProviderUnavailable('All public acquisition routes failed: ' +
                              ', '.join(a['route'] for a in attempts))


def finalize(url, folder, video_id):
    link = download_link(url)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', video_id):
        raise ValueError('Invalid output identity')
    receipt = json.loads((folder / 'acquisition.json').read_text())
    raw = folder / 'raw.mp4'
    if (receipt['source_url'] != link.url or raw.stat().st_size != receipt['bytes']
            or digest(raw) != receipt['sha256']):
        raise ValueError('Source does not match its acquisition receipt')
    final = folder / (video_id + '.mp4')
    pending = folder / (video_id + '.pending.mp4')
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                    *(['-protocol_whitelist', 'file,pipe'] if link.platform == 'reddit' else []),
                    '-i', str(raw), '-map', '0:v:0', '-map', '0:a:0?', '-c', 'copy',
                    '-movflags', '+faststart', str(pending)], check=True, timeout=180, stdin=subprocess.DEVNULL)
    metadata = json.loads(subprocess.check_output(['ffprobe', '-v', 'error',
                            *(['-protocol_whitelist', 'file,pipe'] if link.platform == 'reddit' else []), '-show_streams',
                            '-show_format', '-of', 'json', str(pending)], timeout=30, stdin=subprocess.DEVNULL))
    video = next(stream for stream in metadata['streams'] if stream['codec_type'] == 'video')
    duration = float(metadata['format']['duration'])
    if duration <= 0 or int(video['width']) <= 0 or int(video['height']) <= 0:
        raise ValueError('Invalid video metadata')
    has_audio = any(stream['codec_type'] == 'audio' for stream in metadata['streams'])
    if link.platform == 'reddit' and receipt.get('audio_required') is True and not has_audio:
        raise ValueError('Expected Reddit audio stream is missing')
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-nostdin',
                    *(['-protocol_whitelist', 'file,pipe'] if link.platform == 'reddit' else []), '-i', str(pending),
                    '-t', '1', '-f', 'null', '-'], check=True, timeout=60, stdin=subprocess.DEVNULL)
    pending.replace(final)
    write_json(folder / (video_id + '.receipt.json'), {'downloaded': True, 'source_url': link.url,
        'platform': link.platform, 'bytes': final.stat().st_size, 'sha256': digest(final),
        'height': int(video['height']), 'width': int(video['width']), 'duration': duration,
        'audio': has_audio, 'decode_sample_seconds': 1,
        **{k: receipt[k] for k in ('route', 'route_attempts') if k in receipt}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--video-id', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--download-only', action='store_true')
    mode.add_argument('--finalize-only', action='store_true')
    args = parser.parse_args()
    if args.download_only:
        acquire(args.url, args.out)
    else:
        finalize(args.url, args.out, args.video_id)


if __name__ == '__main__':
    main()
