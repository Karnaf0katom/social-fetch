"""Optional YouTube relay fallback using an operator's own Cobalt API instance.

No public instance is selected automatically. The configured instance must proxy
the complete MP4 on its own origin; direct IP-bound Googlevideo links, pickers
and arbitrary redirect destinations are deliberately refused.
"""
import json
import os
import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


def endpoint():
    value = os.environ.get('SOCIAL_FETCH_COBALT_URL', '').rstrip('/')
    if not value:
        return None
    p = urlsplit(value)
    if (p.scheme != 'https' or not p.hostname or p.username or p.password
            or p.port not in (None, 443) or p.path or p.query or p.fragment
            or re.search(r'[\x00-\x20\x7f\\]', value)):
        raise ValueError('SOCIAL_FETCH_COBALT_URL must be an HTTPS origin')
    return value


def acquire(url, out, video_id, height):
    from social_fetch.social_download import progressive_transfer, digest, write_json
    origin = endpoint()
    if not origin:
        raise ValueError('No independent YouTube fallback instance is configured')

    def checked(target):
        if not isinstance(target, str):
            raise ValueError('Unexpected YouTube fallback delivery origin')
        p = urlsplit(target)
        base = urlsplit(origin)
        if (p.scheme != 'https' or (p.hostname, p.port or 443) != (base.hostname, base.port or 443)
                or p.username or p.password or p.fragment
                or re.search(r'[\x00-\x20\x7f\\]', target)):
            raise ValueError('Unexpected YouTube fallback delivery origin')
        return target

    class Redirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            checked(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = build_opener(Redirects())
    body = json.dumps({'url': url, 'videoQuality': str(height), 'youtubeVideoCodec': 'h264',
                       'downloadMode': 'auto', 'filenameStyle': 'classic', 'alwaysProxy': True,
                       'youtubeHLS': False}).encode()
    with opener.open(Request(origin + '/', data=body, headers={
            'Accept': 'application/json', 'Content-Type': 'application/json',
            'User-Agent': 'social-fetch/alpha'}), timeout=30) as response:
        raw = response.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise ValueError('Oversized YouTube fallback metadata')
    data = json.loads(raw)
    filename = data.get('filename') or ''
    if (data.get('status') != 'tunnel' or not filename.endswith('.mp4')
            or not re.search(r'(?<![A-Za-z0-9-])' + re.escape(video_id) + r'(?![A-Za-z0-9-])', filename)):
        raise ValueError('Fallback did not return a selected-video MP4 tunnel')
    target = checked(data.get('url', ''))
    out.mkdir(parents=True, exist_ok=True)
    path = progressive_transfer(lambda u: opener.open(Request(checked(u),
        headers={'User-Agent': 'social-fetch/alpha'}), timeout=30), target, out)
    saved = {'id': video_id, 'source_url': url, 'route': 'configured_cobalt',
             'bytes': path.stat().st_size, 'sha256': digest(path),
             'route_attempts': [{'route': 'snapyt', 'status': 'unavailable'},
                                {'route': 'configured_cobalt', 'status': 'acquired'}]}
    write_json(out / (video_id + '.fallback.json'), saved)
    return saved


def finalize(url, video_id, out):
    from social_fetch.social_download import finalize as finalize_mp4, write_json
    saved = json.loads((out / (video_id + '.fallback.json')).read_text())
    if saved.get('id') != video_id or saved.get('source_url') != url:
        raise ValueError('Saved fallback manifest does not match this source')
    write_json(out / 'acquisition.json', {**saved, 'platform': 'youtube'})
    finalize_mp4(url, out, video_id)
    receipt = json.loads((out / (video_id + '.receipt.json')).read_text())
    if not receipt.get('audio'):
        (out / (video_id + '.mp4')).unlink(missing_ok=True)
        (out / (video_id + '.receipt.json')).unlink(missing_ok=True)
        raise ValueError('YouTube fallback did not preserve audio')
    return receipt
