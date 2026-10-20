"""Read-only, selected-post Reddit metadata and bounded native-media delivery.

The public embed binds a post to its native media. RapidSave supplies the merged
MP4 endpoint; both of its input streams must match that first-party media ID.
No account session, browser state or unrestricted manifest downloader is used.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import URLError

from social_fetch.social_fallbacks import ProviderUnavailable
from social_fetch.social_sources import download_link, social_link

MAX_DOCUMENT = 6 * 1024**2
MAX_IMAGE_BYTES = 20 * 1024**2
MAX_IMAGE_PIXELS = 80_000_000


def _https(url, hosts):
    if (not isinstance(url, str) or len(url) > 8192
            or re.search(r'[\x00-\x20\x7f\\]', url)):
        raise ValueError('Unexpected Reddit URL')
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname not in hosts or p.username or p.password
            or p.port or p.fragment):
        raise ValueError('Unexpected Reddit delivery host')
    return p


def _request(url, validate):
    class Redirects(HTTPRedirectHandler):
        max_redirections = 4
        max_repeats = 2

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            validate(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    validate(url)
    return build_opener(Redirects()).open(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=20)


def _stream(url, validate):
    response = _request(url, validate)

    class Stream:
        status, headers = response.status, response.headers

        def __enter__(self):
            response.__enter__()
            return self

        def __exit__(self, *args):
            return response.__exit__(*args)

        def read(self, size):
            # Return available bytes so the caller checks its deadline between
            # socket reads, including a slow response with no Content-Length.
            return getattr(response, 'read1', response.read)(size)

    return Stream()


def _document(url, validate, *, max_bytes=None, deadline=None):
    cap = MAX_DOCUMENT if max_bytes is None else max_bytes
    if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= MAX_DOCUMENT:
        raise ValueError('Invalid Reddit document bound')
    local_deadline = time.monotonic() + 60
    deadline = min(local_deadline, deadline) if deadline is not None else local_deadline
    size, parts = 0, []
    if time.monotonic() > deadline:
        raise ProviderUnavailable('The Reddit metadata deadline was reached')
    with _stream(url, validate) as response:
        if response.status != 200:
            raise ProviderUnavailable('The public Reddit metadata route is unavailable')
        declared = response.headers.get('Content-Length')
        try:
            declared = int(declared) if declared is not None else None
        except (ValueError, TypeError):
            raise ValueError('Invalid Reddit metadata length') from None
        if declared is not None and not 0 <= declared <= cap:
            raise ValueError('Oversized Reddit metadata')
        for block in iter(lambda: response.read(min(64 * 1024, cap - size + 1)), b''):
            size += len(block)
            if size > cap or time.monotonic() > deadline:
                raise ValueError('Reddit metadata exceeded its size or time bound')
            parts.append(block)
    raw = b''.join(parts)
    if declared is not None and len(raw) != declared:
        raise ProviderUnavailable('Incomplete Reddit metadata')
    return raw.decode('utf-8')


class _Page(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.posts, self.players, self.canonicals, self.downloads = [], [], [], []
        self.comments, self.events, self.bodies = [], [], {}
        self._body, self._depth, self._parts, self._ignored = None, 0, [], 0
        self.feed(text)
        if self._body is not None:
            raise ValueError('Incomplete Reddit comment body')

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'shreddit-screenview-data':
            data = json.loads(a.get('data', '{}'))
            if not isinstance(data, dict):
                raise ValueError('Invalid Reddit post metadata')
            self.posts.append(data.get('post', {}))
            if 'comment' in data:
                self.comments.append(data['comment'])
        if tag == 'shreddit-player':
            self.players.append({key: a.get(key, '') for key in ('src', 'post-id')})
        if tag == 'div' and a.get('id') == 'canonical-url-updater':
            self.canonicals.append(a.get('value', ''))
        if tag == 'a' and 'downloadbutton' in a.get('class', '').split():
            self.downloads.append(a.get('href', ''))
        if tag == 'embed-event-handler':
            self.events.append({'id': a.get('id'), 'link': a.get('link', '')})
        if self._body is not None:
            if tag not in self.VOID:
                self._depth += 1
            if tag in {'script', 'style'}:
                self._ignored += 1
            if tag == 'br':
                self._parts.append('\n')
        elif tag == 'div' and re.fullmatch(r't1_[a-z0-9]{3,12}-post-rtjson-content', a.get('id', '')):
            self._body, self._depth, self._parts, self._ignored = a['id'], 1, [], 0

    def handle_data(self, data):
        if self._body is not None and not self._ignored:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if self._body is None:
            return
        if tag in {'script', 'style'} and self._ignored:
            self._ignored -= 1
        if tag in {'p', 'li', 'blockquote', 'div'}:
            self._parts.append('\n')
        if tag not in self.VOID:
            self._depth -= 1
        if self._depth == 0:
            text = '\n'.join(line.strip() for line in ''.join(self._parts).splitlines() if line.strip())
            self.bodies.setdefault(self._body, []).append(text)
            self._body, self._parts, self._ignored = None, [], 0


def _selected_post(value, *, deadline=None):
    link = download_link(value)
    if link.platform != 'reddit':
        raise ValueError('Use a public Reddit post link')
    url = link.url.replace('https://www.reddit.com/', 'https://embed.reddit.com/', 1)
    options = {'deadline': deadline} if deadline is not None else {}
    page = _Page(_document(url, lambda u: _https(u, {'embed.reddit.com'}), **options))
    if not page.canonicals or len(page.posts) != 1:
        raise ProviderUnavailable('The Reddit embed has no unambiguous selected post')
    for canonical in page.canonicals:
        actual = social_link(canonical)
        if not actual or actual.platform != 'reddit' or actual.identity != link.identity:
            raise ValueError('Reddit returned another post')
    post = page.posts[0]
    if not isinstance(post, dict) or post.get('id') != 't3_' + link.identity:
        raise ValueError('Reddit returned another post')
    return link, post, page


def _native_video(value):
    link, post, page = _selected_post(value)
    crosspost = any(post.get(key) for key in (
        'crosspost_parent', 'crosspost_parent_list', 'crosspost_parent_id',
        'crosspostParentId', 'is_crosspost', 'isCrosspost'))
    if post.get('type') != 'video' or crosspost:
        raise ProviderUnavailable('Only the selected native Reddit video is supported')
    native = _https(post.get('url', ''), {'v.redd.it'})
    token = native.path.strip('/')
    if native.query or not re.fullmatch(r'/[a-z0-9]{5,32}/?', native.path):
        raise ValueError('Unexpected Reddit native media identity')
    if len(page.players) != 1 or page.players[0]['post-id'] != 't3_' + link.identity:
        raise ValueError('The Reddit player belongs to another post')
    player = _https(page.players[0]['src'], {'v.redd.it'})
    if player.path not in {'/' + token + '/HLSPlaylist.m3u8', '/' + token + '/DASHPlaylist.mpd'}:
        raise ValueError('The Reddit player returned another native video')
    return link, token


def _relay_url(link, token, url):
    parsed = _https(url, {'sd.rapidsave.com'})
    values = parse_qs(parsed.query, keep_blank_values=True)
    if (parsed.path != '/download.php' or set(values) != {'permalink', 'video_url', 'audio_url'}
            or any(len(items) != 1 for items in values.values())):
        raise ValueError('Unexpected Reddit merged-video request')
    actual = social_link(values['permalink'][0])
    if not actual or actual.platform != 'reddit' or actual.identity != link.identity:
        raise ValueError('The Reddit downloader returned another post')
    video = _https(values['video_url'][0], {'v.redd.it'})
    audio = _https(values['audio_url'][0], {'v.redd.it'})
    video_path = re.fullmatch('/' + re.escape(token) + r'/(?:CMAF|DASH)_([0-9]{2,4})\.mp4', video.path)
    if not video_path or not 144 <= int(video_path[1]) <= 4320:
        raise ValueError('The Reddit downloader returned another native video')
    if not re.fullmatch('/' + re.escape(token) + r'/(?:CMAF|DASH)_AUDIO_(?:64|128|256)\.mp4', audio.path):
        raise ValueError('The Reddit downloader returned another native audio stream')
    for component in (video, audio):
        query = parse_qs(component.query, keep_blank_values=True)
        if query and (set(query) != {'source'} or len(query['source']) != 1
                      or query['source'][0] not in {'fallback', 'video', 'audio'}):
            raise ValueError('Unexpected Reddit component parameters')
    return values


def download_video(value, folder):
    """Return one complete merged MP4; the worker must verify required audio."""
    from social_fetch.social_download import progressive_transfer

    link, token = _native_video(value)
    url = 'https://rapidsave.com/info?' + urlencode({'url': link.url})

    def metadata_url(candidate):
        parsed = _https(candidate, {'rapidsave.com'})
        if parsed.path != '/info' or parse_qs(parsed.query) != {'url': [link.url]}:
            raise ValueError('Unexpected Reddit resolver redirect')

    page = _Page(_document(url, metadata_url))
    candidates = [item for item in page.downloads if urlsplit(item).scheme]
    if not candidates:
        raise ProviderUnavailable('The Reddit downloader has no complete video with audio')
    if len(candidates) != 1:
        raise ValueError('Ambiguous Reddit merged-video selection')
    delivery = candidates[0]
    selected = _relay_url(link, token, delivery)

    def media_url(candidate):
        if _relay_url(link, token, candidate) != selected:
            raise ValueError('The Reddit delivery redirect changed the selected streams')

    return progressive_transfer(lambda u: _stream(u, media_url), delivery, folder)


def _native_image(value):
    link, post, _ = _selected_post(value)
    if post.get('type') != 'image' or any(post.get(key) for key in (
            'crosspost_parent', 'crosspost_parent_list', 'crosspost_parent_id',
            'crosspostParentId', 'is_crosspost', 'isCrosspost')):
        raise ProviderUnavailable('Use a selected native single-image Reddit post')
    url = post.get('url', '')
    parsed = _https(url, {'i.redd.it'})
    match = re.fullmatch(r'/[a-z0-9]{5,64}\.(jpe?g|png|webp)', parsed.path)
    if not match or parsed.query:
        raise ValueError('Unexpected Reddit native image identity')
    return link, url, 'jpeg' if match[1] in {'jpg', 'jpeg'} else match[1]


def _image_format(header):
    if header.startswith(b'\xff\xd8\xff'):
        return 'jpeg'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return 'webp'
    raise ValueError('Response is not a supported native image')


def acquire_image(value, folder):
    """Save one bounded native image; final media checks belong to the worker."""
    from social_fetch.social_download import digest, write_json

    link = download_link(value)
    if link.platform != 'reddit':
        raise ValueError('Use a public Reddit image post link')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    raw, receipt = folder / 'raw.image', folder / 'acquisition.json'
    if receipt.exists():
        previous = json.loads(receipt.read_text())
        if (previous.get('source_url') == link.url and previous.get('media_kind') == 'image'
                and raw.is_file() and 32 <= raw.stat().st_size <= MAX_IMAGE_BYTES
                and raw.stat().st_size == previous.get('bytes')
                and digest(raw) == previous.get('sha256')):
            return raw
    raw.unlink(missing_ok=True)
    receipt.unlink(missing_ok=True)
    link, url, expected = _native_image(value)

    def delivery(candidate):
        _https(candidate, {'i.redd.it'})
        if candidate != url:
            raise ValueError('The Reddit image redirect changed the selected attachment')

    pending = folder / 'raw.image.part'
    size, deadline = 0, time.monotonic() + 120
    try:
        with _stream(url, delivery) as response, pending.open('wb') as output:
            if response.status != 200:
                raise ValueError('Expected a complete Reddit image response')
            try:
                declared = response.headers.get('Content-Length')
                declared = int(declared) if declared is not None else None
            except (ValueError, TypeError):
                raise ValueError('Invalid Reddit image length') from None
            if declared is not None and not 32 <= declared <= MAX_IMAGE_BYTES:
                raise ValueError('Reddit image exceeds its size bound')
            for block in iter(lambda: response.read(256 * 1024), b''):
                size += len(block)
                if size > MAX_IMAGE_BYTES or time.monotonic() > deadline:
                    raise ValueError('Reddit image exceeded its size or time bound')
                output.write(block)
        if declared is not None and size != declared:
            raise ProviderUnavailable('Incomplete Reddit image transfer')
        with pending.open('rb') as handle:
            if size < 32 or _image_format(handle.read(16)) != expected:
                raise ValueError('Reddit image format does not match its attachment')
        pending.replace(raw)
    finally:
        pending.unlink(missing_ok=True)
    write_json(receipt, {'source_url': link.url, 'platform': 'reddit', 'media_kind': 'image',
                        'image_format': expected, 'bytes': raw.stat().st_size, 'sha256': digest(raw),
                        'route': 'reddit_embed_image',
                        'route_attempts': [{'route': 'reddit_embed_image', 'status': 'acquired'}]})
    return raw


def finalize_image(value, folder, media_id):
    """Decode one image through the existing worker's CPU admission and receipt."""
    from social_fetch.social_download import digest, write_json

    link = download_link(value)
    if link.platform != 'reddit' or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', media_id):
        raise ValueError('Invalid Reddit image output identity')
    folder = Path(folder)
    receipt = json.loads((folder / 'acquisition.json').read_text())
    raw = folder / 'raw.image'
    if (receipt.get('source_url') != link.url or receipt.get('media_kind') != 'image'
            or raw.stat().st_size != receipt.get('bytes') or digest(raw) != receipt.get('sha256')
            or not 32 <= raw.stat().st_size <= MAX_IMAGE_BYTES):
        raise ValueError('Image does not match its acquisition receipt')
    expected = receipt.get('image_format')
    codecs = {'jpeg': 'mjpeg', 'png': 'png', 'webp': 'webp'}
    if expected not in codecs:
        raise ValueError('Unsupported Reddit image format')
    final, pending = folder / (media_id + '.image'), folder / (media_id + '.pending.image')
    try:
        shutil.copyfile(raw, pending)
        data = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
            '-show_streams', '-show_format', '-of', 'json', str(pending)],
            timeout=30, stdin=subprocess.DEVNULL))
        streams = data.get('streams') or []
        if (len(streams) != 1 or streams[0].get('codec_type') != 'video'
                or streams[0].get('codec_name') != codecs[expected]
                or data.get('format', {}).get('format_name') not in {'jpeg_pipe', 'png_pipe', 'webp_pipe', 'image2'}):
            raise ValueError('Native Reddit image metadata does not match its format')
        width, height = int(streams[0].get('width', 0)), int(streams[0].get('height', 0))
        if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
            raise ValueError('Reddit image exceeds its dimension bound')
        subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-nostdin',
                        '-protocol_whitelist', 'file,pipe', '-i', str(pending),
                        '-frames:v', '1', '-f', 'null', '-'],
                       check=True, timeout=60, stdin=subprocess.DEVNULL)
        if pending.stat().st_size != receipt['bytes'] or digest(pending) != receipt['sha256']:
            raise ValueError('Reddit image changed during verification')
        pending.replace(final)
    finally:
        pending.unlink(missing_ok=True)
    write_json(folder / (media_id + '.receipt.json'), {
        'downloaded': True, 'source_url': link.url, 'platform': 'reddit',
        'media_kind': 'image', 'image_format': expected, 'bytes': final.stat().st_size,
        'sha256': digest(final), 'height': height, 'width': width, 'duration': 0,
        'audio': False, 'decode_sample_frames': 1, 'route': receipt['route'],
        'route_attempts': receipt['route_attempts']})


def _comment_link(link, identifier, value):
    parsed = _https(value, {'www.reddit.com', 'reddit.com'})
    pieces = parsed.path.strip('/').split('/')
    if len(pieces) != 6 or pieces[-1] != identifier or any(part in {'.', '..'} for part in pieces):
        raise ValueError('The Reddit comment permalink changed its selected identity')
    actual = social_link('https://www.reddit.com/' + '/'.join(pieces[:4]) + '/')
    if not actual or actual.platform != 'reddit' or actual.identity != link.identity:
        raise ValueError('The Reddit comment belongs to another post')
    return 'https://embed.reddit.com' + parsed.path


def _current_comment(link, identifier, url, *, deadline):
    page = _Page(_document(url, lambda u: _https(u, {'embed.reddit.com'}),
                           max_bytes=512 * 1024, deadline=deadline))
    if len(page.comments) != 1 or not page.canonicals:
        raise ProviderUnavailable('The selected public Reddit comment was not exposed')
    for canonical in page.canonicals:
        actual = social_link(canonical)
        if not actual or actual.platform != 'reddit' or actual.identity != link.identity:
            raise ValueError('The Reddit comment embed belongs to another post')
    comment = page.comments[0]
    if (not isinstance(comment, dict) or comment.get('id') != 't1_' + identifier
            or comment.get('post_id') != 't3_' + link.identity or comment.get('type') != 'comment'):
        raise ValueError('The Reddit embed returned another comment or post')
    events = [event for event in page.events if event['id'] == 't1_' + identifier]
    if len(events) != 1:
        raise ValueError('Ambiguous Reddit comment identity')
    permalink = _comment_link(link, identifier, events[0]['link'])
    bodies = page.bodies.get('t1_' + identifier + '-post-rtjson-content', [])
    if len(bodies) > 1:
        raise ValueError('Ambiguous Reddit comment body')
    if not bodies or not bodies[0] or bodies[0].casefold() in {'[deleted]', '[removed]', 'comment removed by moderator'}:
        raise ProviderUnavailable('The selected public Reddit comment body was not exposed')
    timestamp, score = comment.get('created_timestamp'), comment.get('score')
    parent = comment.get('parent_id')
    if parent is not None and (not isinstance(parent, str) or not re.fullmatch(r't[13]_[a-z0-9]{3,12}', parent)
                               or (parent.startswith('t3_') and parent != 't3_' + link.identity)):
        raise ValueError('The Reddit comment has an unexpected parent identity')
    return {'id': identifier, 'post_id': link.identity, 'text': bodies[0],
            'url': permalink.replace('https://embed.reddit.com/', 'https://www.reddit.com/', 1),
            'parent_id': parent, 'author': None,
            'timestamp': timestamp // 1000 if isinstance(timestamp, int) and not isinstance(timestamp, bool) and timestamp >= 0 else None,
            'score': score if isinstance(score, int) and not isinstance(score, bool) else None}


def read_comments(value, *, limit=5):
    """Read a partial current public sample; archive results supply IDs, not text."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError('Choose a comment count between 1 and 20')
    link = download_link(value)
    if link.platform != 'reddit':
        raise ValueError('Use a public Reddit post link')
    result = {'platform': 'reddit', 'source_url': link.url, 'post_id': link.identity,
              'retrieved_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'status': 'unavailable', 'complete': False, 'reported_total': None,
              'discovery_route': 'arctic_shift_comment_ids', 'body_route': 'reddit_public_comment_embed',
              'current_bodies': True, 'pagination': False, 'replies_expanded': False,
              'discovered_count': 0, 'returned_count': 0, 'comments': [], 'gaps': []}
    deadline = time.monotonic() + 120
    unavailable = (URLError, TimeoutError, ConnectionError, ProviderUnavailable, json.JSONDecodeError, UnicodeError)
    try:
        _selected_post(value, deadline=deadline)
        # permalink is not a selectable API field. Fetch bounded records, using
        # only their identities and permalinks; read bodies from current embeds.
        query = {'link_id': link.identity, 'limit': str(limit)}
        url = 'https://arctic-shift.photon-reddit.com/api/comments/search?' + urlencode(query)

        def discovery_url(candidate):
            parsed = _https(candidate, {'arctic-shift.photon-reddit.com'})
            if parsed.path != '/api/comments/search' or parse_qs(parsed.query) != {key: [value] for key, value in query.items()}:
                raise ValueError('Unexpected Reddit comment discovery redirect')

        response = json.loads(_document(url, discovery_url, max_bytes=2 * 1024**2, deadline=deadline))
    except unavailable:
        result['gaps'] = ['Public post or comment-ID discovery is unavailable; the comment total is unknown.']
        return result
    rows = response.get('data') if isinstance(response, dict) else None
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError('Unexpected or oversized Reddit comment discovery')
    selected = {}
    for row in rows:
        if (not isinstance(row, dict) or row.get('link_id') != 't3_' + link.identity
                or not isinstance(row.get('id'), str) or not re.fullmatch(r'[a-z0-9]{3,12}', row['id'])):
            raise ValueError('Comment discovery returned another post or identity')
        identifier = row['id']
        permalink = row.get('permalink')
        if not isinstance(permalink, str) or not permalink.startswith('/') or permalink.startswith('//'):
            raise ValueError('Invalid Reddit comment discovery permalink')
        selected[identifier] = _comment_link(link, identifier, 'https://www.reddit.com' + permalink)
    result['discovered_count'] = len(selected)
    if not selected:
        result.update(status='no_exposed_comments', gaps=['Bounded discovery exposed no comment IDs; this does not establish zero comments.'])
        return result
    missing, fetched = 0, 0
    for identifier, url in selected.items():
        if time.monotonic() > deadline:
            result['gaps'].append('The bounded comment-read deadline was reached.')
            break
        try:
            comment = _current_comment(link, identifier, url, deadline=deadline)
            fetched += 1
            result['comments'].append(comment)
        except ProviderUnavailable:
            fetched += 1
            missing += 1
        except (URLError, TimeoutError, ConnectionError, json.JSONDecodeError, UnicodeError):
            missing += 1
    result['returned_count'] = len(result['comments'])
    result['unavailable_count'] = missing
    result['status'] = 'partial' if result['comments'] else 'no_exposed_comments' if fetched else 'unavailable'
    result['gaps'].append('Partial sample only: archive IDs may omit recent comments; bodies were read from current public comment embeds.')
    if missing:
        result['gaps'].append('Some discovered comments were not publicly exposed or could not be read.')
    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Bounded native Reddit image worker')
    parser.add_argument('url')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--video-id', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--download-only', action='store_true')
    mode.add_argument('--finalize-only', action='store_true')
    args = parser.parse_args()
    if args.download_only:
        acquire_image(args.url, args.out)
    else:
        finalize_image(args.url, args.out, args.video_id)


if __name__ == '__main__':
    main()
