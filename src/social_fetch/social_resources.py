"""Discover links in social text and save bounded, public reference material.

Discovery makes no network requests. Retrieval follows only the selected resource;
saved text is source evidence, never agent instructions or executable code.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from email.message import Message
import hashlib
from html import unescape
from html.parser import HTMLParser
import http.client
import io
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.parse import parse_qs, unquote_plus, urlencode, urljoin, urlsplit, urlunsplit
import zipfile

from social_fetch.social_sources import social_link
from social_fetch.web_search import public_url

MAX_BYTES = 20 * 1024**2
MAX_TEXT = 200_000
TEXT_FIELDS = {'title', 'description', 'snippet', 'caption', 'text', 'body', 'content',
               'selftext', 'summary', 'full_text', 'display_text', 'message'}
URL_FIELDS = {'url', 'href', 'uri', 'expanded_url', 'unwound_url', 'expanded', 'external_url'}
CONTAINERS = {'results', 'posts', 'comments', 'replies', 'data', 'record', 'value',
              'entities', 'urls', 'links', 'facets', 'features', 'embed', 'external',
              'attachments', 'card', 'post', 'comment', 'entries', 'items', 'children',
              'linked_resources', 'resources'}
URL_PATTERN = re.compile(r"(?:https?://(?:\[[0-9a-f:.]+\])?|www\.|(?<![\w./])(?:github\.com|docs\.google\.com|drive\.google\.com)/)[^\s<>\"'\[\]\u200b]*", re.I)
TRACKING = {'fbclid', 'gclid', 'igshid', 'igsh', 'si', 'feature'}


def _url(value):
    if not isinstance(value, str):
        return None
    value = unescape(value.strip())
    if value.startswith('www.') or re.match(r'^(github|docs\.google|drive\.google)\.com/', value, re.I):
        value = 'https://' + value
    for _ in range(4):
        try:
            supplied = urlsplit(value)
            tab = parse_qs(supplied.fragment).get('gid', [''])[0]
            if supplied.hostname == 'docs.google.com' and supplied.path.startswith('/spreadsheets/') and tab.isdigit():
                query = parse_qs(supplied.query)
                if 'gid' not in query:
                    value = urlunsplit((*supplied[:3], supplied.query + ('&' if supplied.query else '') + 'gid=' + tab, ''))
        except ValueError:
            return None
        value = public_url(value)
        if not value:
            return None
        parts = urlsplit(value)
        host, query = parts.hostname, parse_qs(parts.query)
        key = None
        if host in {'l.facebook.com', 'lm.facebook.com', 'l.instagram.com'}:
            key = 'u'
        elif host in {'www.youtube.com', 'youtube.com'} and parts.path == '/redirect':
            key = 'q'
        elif host in {'www.google.com', 'google.com'} and parts.path == '/url':
            key = 'url' if 'url' in query else 'q'
        elif host == 'out.reddit.com':
            key = 'url'
        if not key or not query.get(key):
            break
        value = query[key][0]
    value = public_url(value)
    if not value:
        return None
    parts = urlsplit(value)
    # Keep the original encoding/order of signed or provider-specific parameters.
    query = '&'.join(part for part in parts.query.split('&')
                     if (key := unquote_plus(part.split('=', 1)[0]).lower()) not in TRACKING
                     and not key.startswith('utm_'))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ''))


def describe_resource(value):
    """Classify a reference without asserting that it is public or downloadable."""
    # Sheet tabs are meaningful even when supplied in the fragment.
    try:
        fragment = parse_qs(urlsplit(value).fragment) if isinstance(value, str) else {}
    except ValueError:
        return None
    url = _url(value)
    if not url:
        return None
    parts = urlsplit(url)
    host, path = parts.hostname.removeprefix('www.'), parts.path.rstrip('/')
    kind, scope = 'webpage', 'selected_page'
    if host == 'github.com':
        pieces = path.strip('/').split('/')
        if len(pieces) >= 2 and all(re.fullmatch(r'[A-Za-z0-9_.-]+', p) and p not in {'.', '..'} for p in pieces[:2]):
            if len(pieces) == 2:
                kind, scope = 'github_repository', 'repository_readme'
                url = f'https://github.com/{pieces[0]}/{pieces[1].removesuffix(".git")}'
            elif pieces[2] in {'blob', 'raw'} and len(pieces) >= 5:
                kind, scope = 'github_file', 'selected_file'
            elif pieces[2] == 'tree':
                kind, scope = 'github_directory', 'directory_requires_selection'
    elif host == 'raw.githubusercontent.com':
        kind, scope = 'github_file', 'selected_file'
    elif host == 'docs.google.com':
        match = re.match(r'^/(document|spreadsheets|presentation)/(?:u/\d+/)?d/([A-Za-z0-9_-]{10,})(?:/|$)', path)
        if match:
            kind = {'document': 'google_doc', 'spreadsheets': 'google_sheet', 'presentation': 'google_slides'}[match[1]]
            scope = 'selected_tab' if kind == 'google_sheet' else 'selected_document'
            query = parse_qs(parts.query)
            gid = (query.get('gid') or fragment.get('gid') or ['0'])[0]
            url = f'https://docs.google.com/{match[1]}/d/{match[2]}'
            retained = {}
            if kind == 'google_sheet' and gid.isdigit():
                retained['gid'] = gid
            if query.get('resourcekey'):
                retained['resourcekey'] = query['resourcekey'][0]
            if retained:
                url += '?' + urlencode(retained)
    elif host == 'drive.google.com':
        if re.search(r'/folders/[A-Za-z0-9_-]+', path):
            kind, scope = 'google_drive_folder', 'folder_requires_selection'
        elif re.search(r'/file/d/[A-Za-z0-9_-]{10,}', path) or parse_qs(parts.query).get('id'):
            kind, scope = 'google_drive_file', 'selected_file'
            match = re.search(r'/file/d/([A-Za-z0-9_-]{10,})', path)
            query = parse_qs(parts.query)
            identifier = match[1] if match else query.get('id', [''])[0]
            if re.fullmatch(r'[A-Za-z0-9_-]{10,}', identifier):
                url = 'https://drive.google.com/file/d/' + identifier + '/view'
                if query.get('resourcekey'):
                    url += '?' + urlencode({'resourcekey': query['resourcekey'][0]})
    elif social_link(url):
        kind, scope = 'social_post', 'existing_social_reader'
    elif Path(path).suffix.lower() in {'.pdf', '.txt', '.md', '.csv', '.json', '.zip', '.docx', '.xlsx', '.pptx', '.epub'}:
        kind, scope = 'file', 'selected_file'
    return {'id': hashlib.sha256(url.encode()).hexdigest()[:24], 'url': url,
            'kind': kind, 'scope': scope, 'status': 'discovered', 'occurrences': []}


def discover_resources(payload, *, source_url=None, limit=50):
    """Accept raw text or normalized post/comment JSON from any platform.

    Read user-facing fields and explicit link entities, never formats, cookies,
    author thumbnails or arbitrary extractor internals. Keep comment provenance.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('Choose a resource count between 1 and 100.')
    if not isinstance(payload, (str, dict, list)):
        raise ValueError('Supply post/comment text or a JSON object or list.')
    def source_reference(value):
        checked = _url(value)
        social = social_link(checked)
        return social.url if social else checked

    origin = source_reference(source_url) if source_url else None
    if source_url and not origin:
        raise ValueError('Use a public source URL.')
    if origin is None and isinstance(payload, dict):
        origin = source_reference(payload.get('source_url') or payload.get('permalink'))
    found, nodes, characters, truncated = {}, 0, 0, False

    def add(resource, occurrence):
        nonlocal truncated
        if not resource or resource['url'] == occurrence.get('source_url'):
            return
        if resource['id'] not in found and len(found) >= limit:
            truncated = True
            return
        item = found.setdefault(resource['id'], resource)
        if occurrence not in item['occurrences'] and len(item['occurrences']) < 20:
            item['occurrences'].append(occurrence)

    def scan(value, field, context, depth=0):
        nonlocal nodes, characters, truncated
        nodes += 1
        if nodes > 4000 or depth > 12 or characters >= 1_000_000:
            truncated = True
            return
        if isinstance(value, str):
            remaining = 1_000_000 - characters
            if len(value) > remaining:
                truncated = True
            value = value[:remaining]
            characters += len(value)
            for match in URL_PATTERN.finditer(unescape(value)):
                target = match[0].rstrip('.,;!:?')
                for opening, closing in [('(', ')'), ('[', ']'), ('{', '}')]:
                    while target.endswith(closing) and target.count(closing) > target.count(opening):
                        target = target[:-1]
                resource = describe_resource(target)
                add(resource, {**context, 'field': field})
        elif isinstance(value, list):
            for index, item in enumerate(value[:4000]):
                scan(item, f'{field}[{index}]', context, depth + 1)
                if nodes > 4000 or characters >= 1_000_000:
                    break
            if len(value) > 4000:
                truncated = True
        elif isinstance(value, dict):
            context = dict(context)
            # Search normalizes HTML to visible text and truncates snippets. Its
            # already-discovered references must survive a saved-ledger round trip.
            if isinstance(value.get('occurrences'), list) and isinstance(value.get('url'), str):
                resource = describe_resource(value['url'])
                occurrences = value['occurrences'][:20] or [context]
                for occurrence in occurrences:
                    if not isinstance(occurrence, dict):
                        continue
                    clean = {'source_url': source_reference(occurrence.get('source_url')) or context.get('source_url'),
                             'field': str(occurrence.get('field', field))[:1000]}
                    for key in ('comment_id', 'author'):
                        if isinstance(occurrence.get(key), (str, int)):
                            clean[key] = str(occurrence[key])[:200]
                    add(resource, clean)
                return
            candidate = value.get('source_url') or value.get('permalink')
            if not candidate and social_link(value.get('url')):
                candidate = value['url']
            if candidate and (source := source_reference(candidate)):
                context['source_url'] = source
            if ('comments[' in field or 'replies[' in field or field.endswith('.comment')
                    or 'comment_id' in value or 'text' in value and 'id' in value and not candidate):
                identifier = value.get('comment_id', value.get('id'))
                if isinstance(identifier, (str, int)):
                    context['comment_id'] = str(identifier)[:200]
                author = value.get('author')
                if isinstance(author, str):
                    context['author'] = author[:200]
            for key, item in list(value.items())[:200]:
                if key in TEXT_FIELDS | CONTAINERS or key in URL_FIELDS and (depth > 0 or key != 'url'):
                    scan(item, f'{field}.{key}', context, depth + 1)
            if len(value) > 200:
                truncated = True

    scan(payload, '$', {'source_url': origin})
    resources = list(found.values())
    counts = dict(Counter(item['kind'] for item in resources))
    return {'schema': 'social-fetch.resources/v1', 'status': 'discovered',
            'coverage': 'supplied_text_only', 'source_url': origin, 'resources': resources,
            'count': len(resources), 'kinds': counts, 'truncated': truncated,
            'notice': f'Found {len(resources)} linked resources in the available text.',
            'trust': 'untrusted_source_content'}


class ResourceError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _connect(host, port, timeout):
    """Pin the checked public DNS addresses for the actual socket connection."""
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise ResourceError('blocked', 'The resource resolves to a nonpublic network address.')
    # A single pinned address keeps connection attempts bounded. Explicit retry
    # can resolve a different healthy address without relaxing origin validation.
    family, kind, protocol, _, address = addresses[0]
    connection = socket.socket(family, kind, protocol)
    try:
        connection.settimeout(timeout)
        connection.connect(address)
        return connection
    except BaseException:
        connection.close()
        raise


class _HTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = _connect(self.host, self.port, self.timeout)


class _HTTPS(http.client.HTTPSConnection):
    def connect(self):
        raw = _connect(self.host, self.port, self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _read_url(url, *, max_bytes, deadline):
    """No proxy, cookies, ambient credentials, automatic redirects or execution."""
    parts = urlsplit(url)
    connection_type = _HTTPS if parts.scheme == 'https' else _HTTP
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ResourceError('unavailable', 'Resource retrieval timed out.')
    connection = connection_type(parts.hostname, parts.port, timeout=min(10, remaining))
    try:
        path = urlunsplit(('', '', parts.path or '/', parts.query, ''))
        connection.request('GET', path, headers={'User-Agent': 'social-fetch/resources',
                           'Accept': 'application/vnd.github.raw+json' if parts.hostname == 'api.github.com' else '*/*',
                           'Accept-Encoding': 'identity', 'Connection': 'close'})
        response = connection.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        raw = bytearray()
        if 200 <= response.status < 300:
            size = headers.get('content-length')
            if size and (not size.isdigit() or int(size) > max_bytes):
                raise ResourceError('too_large', 'The resource exceeds the download size limit.')
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ResourceError('unavailable', 'Resource retrieval timed out.')
                if connection.sock:
                    connection.sock.settimeout(min(10, remaining))
                block = response.read(min(64 * 1024, max_bytes + 1 - len(raw)))
                if not block:
                    break
                raw.extend(block)
                if len(raw) > max_bytes:
                    raise ResourceError('too_large', 'The resource exceeds the download size limit.')
            if size and len(raw) != int(size):
                raise ResourceError('unavailable', 'The resource transfer was incomplete.')
        return response.status, headers, bytes(raw)
    finally:
        connection.close()


def _download(url, *, max_bytes, deadline):
    for _ in range(6):
        checked = public_url(url)
        if not checked:
            raise ResourceError('blocked', 'The resource or its redirect is not a public HTTP(S) URL.')
        status, headers, raw = _read_url(checked, max_bytes=max_bytes, deadline=deadline)
        if status in {301, 302, 303, 307, 308}:
            target = urljoin(checked, headers.get('location', ''))
            if target == checked or checked.startswith('https:') and not target.startswith('https:'):
                raise ResourceError('blocked', 'The resource returned an invalid or insecure redirect.')
            url = target
            continue
        if status in {401, 403}:
            raise ResourceError('access_required', 'The resource requires access or rejects public downloads.')
        if status == 404:
            raise ResourceError('not_found', 'The linked resource was not found or is private.')
        if status == 429:
            raise ResourceError('rate_limited', 'The resource provider is rate limited; retry later.')
        if status != 200 or headers.get('content-range'):
            raise ResourceError('unavailable', 'The resource provider could not serve this file.')
        if not raw:
            raise ResourceError('unavailable', 'The resource returned an empty response.')
        if headers.get('content-encoding', 'identity').lower() not in {'', 'identity'}:
            raise ResourceError('unavailable', 'The resource ignored the uncompressed transfer request.')
        return raw, headers.get('content-type', 'application/octet-stream'), checked, headers.get('content-disposition', '')
    raise ResourceError('blocked', 'The resource exceeded the redirect limit.')


def _target(resource, archive):
    url, kind = resource['url'], resource['kind']
    parts = urlsplit(url)
    if kind in {'github_repository', 'github_directory'}:
        owner, repo = parts.path.strip('/').split('/')[:2]
        if kind == 'github_directory':
            raise ResourceError('needs_selection', 'Choose a file in this GitHub directory, or use the repository root URL with archive.')
        if archive:
            return f'https://api.github.com/repos/{owner}/{repo}/zipball'
        return f'https://api.github.com/repos/{owner}/{repo}/readme'
    if archive:
        raise ResourceError('unsupported', 'Repository archives require a GitHub repository URL.')
    if kind == 'github_file' and parts.hostname in {'github.com', 'www.github.com'}:
        return 'https://github.com' + parts.path.replace('/blob/', '/raw/', 1)
    if kind in {'google_doc', 'google_sheet', 'google_slides'}:
        base = urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
        if kind == 'google_slides':
            return base + '/export/txt' + ('?' + parts.query if parts.query else '')
        query = {'format': 'csv' if kind == 'google_sheet' else 'txt'}
        if kind == 'google_sheet':
            query['gid'] = parse_qs(parts.query).get('gid', ['0'])[0]
        if parse_qs(parts.query).get('resourcekey'):
            query['resourcekey'] = parse_qs(parts.query)['resourcekey'][0]
        return base + '/export?' + urlencode(query)
    if kind == 'google_drive_file':
        match = re.search(r'/file/d/([A-Za-z0-9_-]{10,})', parts.path)
        query = parse_qs(parts.query)
        identifier = match[1] if match else query.get('id', [''])[0]
        if not re.fullmatch(r'[A-Za-z0-9_-]{10,}', identifier):
            raise ResourceError('unsupported', 'The Drive file link has no usable file ID.')
        params = {'export': 'download', 'id': identifier}
        if query.get('resourcekey'):
            params['resourcekey'] = query['resourcekey'][0]
        return 'https://drive.google.com/uc?' + urlencode(params)
    if kind == 'google_drive_folder':
        raise ResourceError('needs_selection', 'Choose an individual file from the linked Drive folder.')
    if kind == 'social_post':
        raise ResourceError('use_social_reader', 'Use the existing social reader or video download command for this link.')
    return url


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript', 'template'}:
            self.hidden += 1
        if tag in {'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'tr', 'pre'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript', 'template'}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {'p', 'div', 'li', 'h1', 'h2', 'h3', 'tr', 'pre'}:
            self.parts.append('\n')

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def _readable(raw, content_type, url, disposition=''):
    mime = content_type.split(';', 1)[0].strip().lower()
    suffix = Path(urlsplit(url).path).suffix.lower()
    if disposition:
        metadata = Message()
        metadata['Content-Disposition'] = disposition[:4096]
        filename = metadata.get_filename()
        if isinstance(filename, str):
            # Use only a known format hint. Never use the remote filename as a
            # storage path, including traversal paths or RFC 2231 filenames.
            hint = Path(filename.replace('\\', '/')).suffix.lower()
            if hint in {'.txt', '.md', '.csv', '.json', '.rst', '.yaml', '.yml', '.py', '.js', '.ts',
                        '.docx', '.xlsx', '.pptx', '.epub'}:
                suffix = hint
    is_html = mime in {'text/html', 'application/xhtml+xml'} or raw[:256].lstrip().lower().startswith((b'<!doctype html', b'<html'))
    if is_html:
        page = _PageText()
        page.feed(raw.decode('utf-8', errors='replace'))
        value = '\n'.join(re.sub(r'[\t \r]+', ' ', line).strip() for line in ''.join(page.parts).splitlines())
        return re.sub(r'\n{3,}', '\n\n', value).strip(), '.html'
    if raw.startswith(b'%PDF-'):
        return None, '.pdf'
    if raw.startswith(b'PK\x03\x04'):
        return None, suffix if suffix in {'.docx', '.xlsx', '.pptx', '.epub'} else '.zip'
    if (mime.startswith('text/') or mime in {'application/json', 'application/xml', 'application/javascript'}
            or suffix in {'.md', '.txt', '.csv', '.json', '.rst', '.yaml', '.yml', '.py', '.js', '.ts'}):
        if b'\x00' not in raw:
            return raw.decode('utf-8-sig', errors='replace'), suffix if suffix in {'.md', '.txt', '.csv', '.json'} else '.txt'
    extension = mimetypes.guess_extension(mime) or '.bin'
    return None, extension if re.fullmatch(r'\.[a-z0-9]{1,8}', extension) else '.bin'


def _write_once(path, raw):
    """Save immutable bytes; preserve existing files and verify reused content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.resource-', delete=False) as output:
            pending = Path(output.name)
            output.write(raw)
        try:
            os.link(pending, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.stat().st_size != len(raw) or path.read_bytes() != raw:
                raise ResourceError('integrity_error', 'An existing resource file has changed; choose another data directory.') from None
    finally:
        if pending:
            pending.unlink(missing_ok=True)


def fetch_resource(url, root, *, namespace='social-cli', archive=False, max_bytes=MAX_BYTES, timeout=60):
    """Save one public resource with a checksum and optional readable-text sidecar."""
    resource = describe_resource(url)
    if not resource:
        raise ValueError('Use a public HTTP(S) resource URL.')
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_BYTES:
        raise ValueError('Choose a download limit between 1 byte and 20 MiB.')
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 180:
        raise ValueError('Choose a resource timeout above zero and at most 180 seconds.')
    result = {**resource, 'retrieved_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'trust': 'untrusted_source_content', 'text_status': 'unavailable'}
    try:
        deadline = time.monotonic() + timeout
        target = _target(resource, archive)
        raw, content_type, resolved, disposition = _download(target, max_bytes=max_bytes, deadline=deadline)
        # A shortened link can lead to a provider-specific document or repository.
        # Adapt once after resolution; never crawl its outgoing links.
        actual = describe_resource(resolved)
        if (actual and resource['kind'] in {'webpage', 'file'} and actual['kind'] not in {'webpage', 'file'}):
            adapted = _target(actual, archive)
            if adapted != resolved:
                raw, content_type, resolved, disposition = _download(adapted, max_bytes=max_bytes, deadline=deadline)
            result.update(kind=actual['kind'], scope=actual['scope'])
        google = result['kind'] in {'google_doc', 'google_sheet', 'google_slides', 'google_drive_file'}
        if (urlsplit(resolved).hostname in {'accounts.google.com', 'login.microsoftonline.com'}
                or google and ('html' in content_type.lower() or raw[:256].lstrip().lower().startswith((b'<!doctype html', b'<html')))):
            raise ResourceError('access_required', 'Google returned a login, permission or confirmation page instead of the file.')
        text_type = 'text/markdown' if result['kind'] == 'github_repository' and not archive else content_type
        text, suffix = _readable(raw, text_type, resolved, disposition)
        if archive:
            if suffix != '.zip' or not zipfile.is_zipfile(io.BytesIO(raw)):
                raise ResourceError('unavailable', 'GitHub did not return a repository ZIP archive.')
            result['scope'] = 'repository_archive'
        digest = hashlib.sha256(raw).hexdigest()
        tenant = hashlib.sha256(namespace.encode()).hexdigest()[:24]
        folder = Path(root).expanduser().resolve() / 'resources' / tenant / resource['id']
        artifact = folder / (digest + suffix)
        _write_once(artifact, raw)
        if suffix == '.pdf' and shutil.which('pdftotext'):
            # Optional local parser, bounded to 50 pages and a short execution.
            with tempfile.TemporaryDirectory(prefix='social-resource-pdf-') as temporary:
                output = Path(temporary) / 'text.txt'
                try:
                    process = subprocess.run(['pdftotext', '-f', '1', '-l', '50', '-enc', 'UTF-8',
                                              str(artifact), str(output)], stdin=subprocess.DEVNULL,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             timeout=min(15, max(0.1, deadline - time.monotonic())), check=False)
                    if process.returncode == 0 and output.is_file():
                        with output.open('r', errors='replace') as handle:
                            text = handle.read(MAX_TEXT + 1)
                        result['text_coverage'] = 'first_50_pages'
                except (OSError, subprocess.TimeoutExpired):
                    pass
        result.update(status='ready', bytes=len(raw), sha256=digest, file=str(artifact),
                      content_type=content_type.split(';')[0],
                      retrieved_from=urlunsplit((*urlsplit(resolved)[:3], '', '')))
        if text and text.strip():
            readable = text[:MAX_TEXT]
            text_path = folder / (digest + '.readable.txt')
            _write_once(text_path, readable.encode('utf-8'))
            result.update(text_status='extracted', text_file=str(text_path), text_preview=readable[:4000],
                          text_truncated=len(text) > MAX_TEXT, text_characters=len(readable),
                          text_sha256=hashlib.sha256(readable.encode('utf-8')).hexdigest())
        elif text is not None:
            result['text_status'] = 'empty'
        # Separate receipt for each version, never overwrite a previous observation.
        receipt = folder / f'{digest}.{time.time_ns()}.receipt.json'
        result['receipt'] = str(receipt)
        _write_once(receipt, (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())
    except ResourceError as error:
        result.update(status=error.status, message=str(error))
    except (OSError, ValueError, http.client.HTTPException):
        result.update(status='unavailable', message='The public resource could not be retrieved or saved.')
    return result
