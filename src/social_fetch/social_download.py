"""Bounded public social acquisition; media checks run separately through CPU admission.

Instagram reuses SnapInsta. TikTok uses the measured TikWM public form. X,
Facebook and Reddit attempt the installed yt-dlp's public, progressive MP4
extractors. No cookies, browser account, config file or paid API is used.
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
        if expected_id.isdigit() and (not identities or identities[-1] != expected_id) and not amplify_id:
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
