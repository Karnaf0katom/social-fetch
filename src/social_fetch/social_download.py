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
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from social_fetch.social_sources import download_link

MAX_BYTES = 512 * 1024**2
PROGRESSIVE_EXTRACTORS = {'pinterest': 'Pinterest', 'twitch': 'TwitchClips',
                        'snapchat': 'SnapchatSpotlight', 'linkedin': 'LinkedIn'}
EXTRACTOR_FILTERS = {**PROGRESSIVE_EXTRACTORS, 'twitch': 'twitch:clips'}
DELIVERY_HOSTS = {'pinterest': ('pinimg.com',), 'twitch': ('clips-media-assets2.twitch.tv',
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
    executable = shutil.which('yt-dlp')
    runner = [executable] if executable else [sys.executable, '-m', 'yt_dlp'] if importlib.util.find_spec('yt_dlp') else None
    if not runner:
        raise ValueError('Public social extraction is not installed on this server')
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
        if (str(actual_id) != expected_id or data.get('_type', 'video') != 'video'
                or data.get('extractor_key') != PROGRESSIVE_EXTRACTORS[link.platform]):
            raise ValueError('Extractor returned another post')
        if data.get('ext') != 'mp4' or data.get('protocol') != 'https' or data.get('vcodec') == 'none':
            raise ValueError('The post has no progressive HTTPS MP4')
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
                raise ValueError('Incomplete MP4 transfer')
            for chunk in iter(lambda: response.read(256 * 1024), b''):
                size += len(chunk)
                if size > MAX_BYTES or time.monotonic() > deadline:
                    raise ValueError('Video exceeded its size or time bound')
                output.write(chunk)
        if ((declared is not None and size != declared)
                or (expected_size is not None and size != expected_size)):
            raise ValueError('Incomplete MP4 transfer')
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


def tiktok_download(link, folder):
    data = urlencode({'url': link.url, 'hd': '1'}).encode()
    with tikwm_request('https://www.tikwm.com/api/', data) as response:
        raw = response.read(2 * 1024**2 + 1)
    if len(raw) > 2 * 1024**2:
        raise ValueError('Oversized TikTok response')
    result = json.loads(raw)
    row = result.get('data') or {}
    if result.get('code') != 0 or not re.fullmatch(r'\d{10,25}', str(row.get('id', ''))):
        raise ValueError('The public TikTok downloader returned no video')
    if link.identity.isdigit() and str(row['id']) != link.identity:
        raise ValueError('TikTok returned another post')
    delivery = row.get('hdplay') or row.get('play')
    if not isinstance(delivery, str):
        raise ValueError('The TikTok post has no downloadable video')
    if delivery.startswith('/'):
        delivery = 'https://www.tikwm.com' + delivery
    target = folder / 'raw.mp4'
    pending = target.with_suffix('.part')
    size, deadline = 0, time.monotonic() + 300
    with tikwm_request(delivery) as response, pending.open('wb') as output:
        if response.status != 200:
            raise ValueError('Expected a complete TikTok video response')
        expected = response.headers.get('Content-Length')
        if expected and int(expected) > MAX_BYTES:
            raise ValueError('Video exceeds the 512 MiB bound')
        for chunk in iter(lambda: response.read(256 * 1024), b''):
            size += len(chunk)
            if size > MAX_BYTES or time.monotonic() > deadline:
                raise ValueError('Video exceeded its size or time bound')
            output.write(chunk)
    if expected and size != int(expected):
        raise ValueError('Incomplete TikTok transfer')
    with pending.open('rb') as handle:
        if size < 1024 or b'ftyp' not in handle.read(128):
            raise ValueError('TikTok response is not an MP4')
    pending.replace(target)
    return target


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
    if link.platform == 'instagram':
        from social_fetch.instagram_web import Form, download, page, videos
        rows = videos(Form(page('/process', {'q': link.url, 'scope': 'home', 'lang': 'en'})), link.identity)
        if not rows:
            raise ValueError('The Instagram post has no public video')
        # A carousel is one selected post: acquire its first video, never the account.
        (folder / 'source').mkdir(exist_ok=True)
        receipt = download(rows[0], folder)
        target = folder / 'raw.mp4'
        (folder / receipt['file']).replace(target)
    elif link.platform == 'tiktok':
        target = tiktok_download(link, folder)
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
            raise ValueError('Public social extraction is not installed on this server')
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
    write_json(receipt_path, {'source_url': link.url, 'platform': link.platform,
                             'bytes': target.stat().st_size, 'sha256': digest(target)})


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
                    '-i', str(raw), '-map', '0:v:0', '-map', '0:a:0?', '-c', 'copy',
                    '-movflags', '+faststart', str(pending)], check=True, timeout=180, stdin=subprocess.DEVNULL)
    metadata = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                            '-show_format', '-of', 'json', str(pending)], timeout=30, stdin=subprocess.DEVNULL))
    video = next(stream for stream in metadata['streams'] if stream['codec_type'] == 'video')
    duration = float(metadata['format']['duration'])
    if duration <= 0 or int(video['width']) <= 0 or int(video['height']) <= 0:
        raise ValueError('Invalid video metadata')
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-i', str(pending),
                    '-t', '1', '-f', 'null', '-'], check=True, timeout=60, stdin=subprocess.DEVNULL)
    pending.replace(final)
    write_json(folder / (video_id + '.receipt.json'), {'downloaded': True, 'source_url': link.url,
        'platform': link.platform, 'bytes': final.stat().st_size, 'sha256': digest(final),
        'height': int(video['height']), 'width': int(video['width']), 'duration': duration,
        'audio': any(stream['codec_type'] == 'audio' for stream in metadata['streams']), 'decode_sample_seconds': 1})


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
