"""Resource discovery, provenance, real transfer boundaries and agent-facing flows."""
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import time
from urllib.parse import urlencode
import zipfile

import pytest

from social_fetch import social_resources as resources
from social_fetch.client import Client
from social_fetch.social_cli import main
from social_fetch.social_sources import DOMAINS, social_link
from social_fetch.web_search import candidate

POST = 'https://www.instagram.com/p/ABCDE12345/'
REPO = 'https://github.com/example/project'
DOC = 'https://docs.google.com/document/d/public_document_123/edit'
DRIVE = 'https://drive.google.com/file/d/public_file_123/view?resourcekey=shared_key'
POSTS = {
    'youtube': 'https://www.youtube.com/watch?v=jNQXAC9IVRw',
    'instagram': POST,
    'tiktok': 'https://www.tiktok.com/@nasa/video/6742501081818877190',
    'x': 'https://x.com/NASA/status/12345678',
    'facebook': 'https://www.facebook.com/watch/?v=12345678',
    'reddit': 'https://www.reddit.com/r/space/comments/abc123/rocket/',
    'bluesky': 'https://bsky.app/profile/bsky.app/post/3l3vgf77uco2g',
    'pinterest': 'https://www.pinterest.com/pin/664281013778109217/',
    'twitch': 'https://clips.twitch.tv/FaintLightGullWholeWheat',
    'snapchat': 'https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPwAAYYWtidGhudGZpAX1TKn0JAX1TKnXJAAAAAA',
    'linkedin': 'https://www.linkedin.com/posts/the-mathworks_2_what-is-mathworks-cloud-center-activity-7151241570371948544-4Gu7',
    'mastodon': 'https://mastodon.social/@Mastodon/116839714185151652',
}


def test_caption_and_comments_retain_provenance_and_deduplicate_without_network(monkeypatch):
    monkeypatch.setattr(resources, '_read_url', lambda *a, **k: pytest.fail('discovery must stay offline'))
    payload = {'source_url': POST, 'caption': f'Source: [{REPO}]({REPO}?utm_source=social).',
               'comments': [{'id': '7', 'author': 'reader', 'text': f'<a href="{DOC}">Guide</a> and {REPO}.'},
                            {'id': '8', 'text': 'Download: ' + DRIVE}],
               'formats': [{'url': 'https://cdn.example.com/private-token.mp4'}],
               'author_thumbnail': 'https://example.com/private-image'}
    result = resources.discover_resources(payload)
    assert result['count'] == 3 and result['coverage'] == 'supplied_text_only'
    repository = next(item for item in result['resources'] if item['kind'] == 'github_repository')
    assert repository['url'] == REPO and len(repository['occurrences']) == 2
    occurrence = next(item for item in repository['occurrences'] if item.get('comment_id'))
    assert occurrence['comment_id'] == '7' and occurrence['author'] == 'reader' and occurrence['source_url'] == POST
    assert 'private-token' not in json.dumps(result) and 'private-image' not in json.dumps(result)


@pytest.mark.parametrize('platform', DOMAINS)
def test_every_social_result_reports_references_before_description_truncation(platform):
    # The common normalization seam covers every selectable platform, including
    # links supplied through rich-text entities rather than visible text.
    row = {'url': POSTS[platform], 'title': 'Post',
           'description': 'Long caption ' + 'word ' * 180 + f'<a href="{DOC}">read this</a>',
           'entities': {'urls': [{'expanded_url': REPO}]}}
    result = candidate(row, provider='test-' + platform)
    assert len(result['description']) == 800
    assert {item['kind'] for item in result['linked_resources']} == {'google_doc', 'github_repository'}
    assert social_link(row['url']).platform == platform
    assert result['resource_notice'] and result['linked_resources'][0]['occurrences'][0]['source_url'] == social_link(row['url']).url


def test_balanced_markdown_bare_urls_wrappers_and_sheet_tabs():
    wrapped = 'https://l.facebook.com/l.php?' + urlencode({'u': DOC + '?utm_source=fb'})
    result = resources.discover_resources(f'Guide {wrapped}. Code github.com/example/project; '
        '[manual](https://example.com/guide_(new)). '
        'https://docs.google.com/spreadsheets/d/public_sheet_123/edit#gid=123')
    assert result['count'] == 4
    assert any(item['url'] == 'https://example.com/guide_(new)' for item in result['resources'])
    assert any(item['url'].endswith('?gid=123') for item in result['resources'])
    assert any(item['url'] == REPO for item in result['resources'])


def test_signed_parameters_keep_encoding_and_order_and_drive_variants_deduplicate():
    signed = 'https://example.com/file?sig=A%2fb%2B%20&key=1&key=2&utm_source=social'
    assert resources.describe_resource(signed)['url'] == signed.removesuffix('&utm_source=social')
    a = resources.describe_resource(DRIVE)
    b = resources.describe_resource('https://drive.google.com/open?id=public_file_123&resourcekey=shared_key')
    assert a['id'] == b['id']
    assert 'resourcekey=shared_key' in resources._target(a, False)


@pytest.mark.parametrize('value', ['http://127.0.0.1/', 'http://169.254.169.254/',
    'https://localhost/secret', 'https://user:secret@example.com/', 'file:///etc/passwd',
    'https://[broken', 'https://example.com:22/file'])
def test_unsafe_links_are_not_offered_for_download(value):
    assert resources.describe_resource(value) is None


def test_nested_wrapper_cannot_bypass_url_checks_and_limits_are_reported():
    url = 'http://127.0.0.1/secret'
    for _ in range(4):
        url = 'https://www.google.com/url?' + urlencode({'q': url})
    assert resources.describe_resource(url) is None
    report = resources.discover_resources(f'{REPO} {DOC}', limit=1)
    assert report['count'] == 1 and report['truncated']
    report = resources.discover_resources('x' * 1_000_001)
    assert report['truncated']


def serve(monkeypatch, responses):
    calls = []
    def read(url, **kwargs):
        calls.append(url)
        assert url in responses, url
        value = responses[url]
        return value if isinstance(value, tuple) else (200, {'content-type': 'text/plain'}, value)
    monkeypatch.setattr(resources, '_read_url', read)
    return calls


def test_github_readme_is_saved_with_readable_text_and_verifiable_receipt(tmp_path, monkeypatch):
    target = 'https://api.github.com/repos/example/project/readme'
    raw = b'# Project\nUseful material for the agent.\n'
    serve(monkeypatch, {target: (200, {'content-type': 'application/octet-stream'}, raw)})
    client = Client(tmp_path, namespace='research')
    saved = client.resource(REPO)
    assert saved['status'] == 'ready' and saved['scope'] == 'repository_readme'
    assert saved['kind'] == 'github_repository' and saved['text_status'] == 'extracted'
    assert Path(saved['file']).read_bytes() == raw
    assert Path(saved['text_file']).read_text() == raw.decode()
    assert saved['sha256'] == hashlib.sha256(raw).hexdigest()
    assert json.loads(Path(saved['receipt']).read_text()) == saved
    assert saved['trust'] == 'untrusted_source_content'
    another = Client(tmp_path, namespace='other').resource(REPO)
    assert another['file'] != saved['file']


@pytest.mark.parametrize('url,target,kind', [
    (DOC, 'https://docs.google.com/document/d/public_document_123/export?format=txt', 'google_doc'),
    ('https://docs.google.com/spreadsheets/d/public_sheet_123/edit#gid=77',
     'https://docs.google.com/spreadsheets/d/public_sheet_123/export?format=csv&gid=77', 'google_sheet'),
    ('https://docs.google.com/presentation/d/public_slides_123/edit',
     'https://docs.google.com/presentation/d/public_slides_123/export/txt', 'google_slides'),
    (DRIVE, 'https://drive.google.com/uc?export=download&id=public_file_123&resourcekey=shared_key', 'google_drive_file'),
    ('https://github.com/example/project/blob/main/guide.md',
     'https://github.com/example/project/raw/main/guide.md', 'github_file')])
def test_selected_provider_file_is_used_instead_of_the_viewer(tmp_path, monkeypatch, url, target, kind):
    calls = serve(monkeypatch, {target: b'Actual selected file contents'})
    result = Client(tmp_path).resource(url)
    assert result['status'] == 'ready' and result['kind'] == kind
    assert result['text_preview'] == 'Actual selected file contents' and calls == [target]


def test_drive_text_served_as_binary_uses_only_a_safe_filename_hint(tmp_path, monkeypatch):
    target = resources._target(resources.describe_resource(DRIVE), False)
    serve(monkeypatch, {target: (200, {'content-type': 'application/octet-stream',
                                     'content-disposition': 'attachment; filename="../../outside.txt"'}, b'Useful notes\n')})
    result = Client(tmp_path).resource(DRIVE)
    assert result['status'] == 'ready' and result['text_status'] == 'extracted'
    assert result['text_preview'] == 'Useful notes\n'
    assert Path(result['file']).name == result['sha256'] + '.txt'
    assert Path(result['file']).is_relative_to(tmp_path) and not (tmp_path / 'outside.txt').exists()


def test_shortened_link_is_resolved_and_then_uses_github_readme(tmp_path, monkeypatch):
    short = 'https://short.example.com/code'
    target = 'https://api.github.com/repos/example/project/readme'
    calls = serve(monkeypatch, {short: (302, {'location': REPO}, b''),
                               REPO: (200, {'content-type': 'text/html'}, b'<html>Repository</html>'),
                               target: b'# Read the actual README'})
    result = Client(tmp_path).resource(short)
    assert result['kind'] == 'github_repository' and result['scope'] == 'repository_readme'
    assert result['text_preview'] == '# Read the actual README' and calls == [short, REPO, target]
    assert result['url'] == short


def test_pages_produce_readable_text_without_recursively_following_links(tmp_path, monkeypatch):
    page = 'https://example.com/guide'
    raw = f'<html><h1>Useful guide</h1><script>hidden secret</script><p>See <a href="{REPO}">code</a>.</p></html>'.encode()
    calls = serve(monkeypatch, {page: (200, {'content-type': 'text/html'}, raw)})
    result = Client(tmp_path).resources({'comments': [{'id': '1', 'text': page}]}, source_url=POST, download=True)
    saved = result['resources'][0]
    assert result['status'] == 'ready' and result['readable_count'] == 1 and calls == [page]
    assert 'Useful guide' in saved['text_preview'] and 'hidden secret' not in saved['text_preview']
    assert saved['occurrences'][0]['comment_id'] == '1'


def test_saved_search_results_keep_references_that_are_absent_from_visible_snippets(tmp_path, monkeypatch):
    item = candidate({'url': POST, 'description': f'<a href="{DOC}">a guide</a>'}, provider='test')
    assert 'google.com' not in item['description']
    target = 'https://docs.google.com/document/d/public_document_123/export?format=txt'
    serve(monkeypatch, {target: b'The actual guide'})
    result = Client(tmp_path).resources({'results': [item]}, download=True)
    assert result['downloaded_count'] == 1 and result['readable_count'] == 1
    assert result['resources'][0]['occurrences'] == item['linked_resources'][0]['occurrences']


def test_resource_ledger_round_trip_keeps_comment_provenance(tmp_path, monkeypatch):
    first = resources.discover_resources({'source_url': POST, 'comments': [{'id': '7', 'text': DOC}]})
    target = 'https://docs.google.com/document/d/public_document_123/export?format=txt'
    serve(monkeypatch, {target: b'Guide'})
    second = Client(tmp_path).resources(first, download=True)
    assert second['source_url'] == POST
    assert second['resources'][0]['occurrences'] == first['resources'][0]['occurrences']


def test_repository_archive_is_saved_as_code_without_extraction_or_execution(tmp_path, monkeypatch):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('project/run.py', 'raise RuntimeError("must never execute")')
    serve(monkeypatch, {'https://api.github.com/repos/example/project/zipball':
                       (200, {'content-type': 'application/zip'}, archive.getvalue())})
    result = Client(tmp_path).resource(REPO, archive=True)
    assert result['status'] == 'ready' and result['scope'] == 'repository_archive'
    assert result['text_status'] == 'unavailable' and Path(result['file']).suffix == '.zip'
    assert not list(tmp_path.rglob('run.py'))


def test_repository_archive_requires_an_actual_zip(tmp_path, monkeypatch):
    serve(monkeypatch, {'https://api.github.com/repos/example/project/zipball':
                       (200, {'content-type': 'application/zip'}, b'PK\x03\x04invalid')})
    assert Client(tmp_path).resource(REPO, archive=True)['status'] == 'unavailable'
    assert not list(tmp_path.rglob('*.zip'))


@pytest.mark.parametrize('status,state', [(401, 'access_required'), (403, 'access_required'),
    (404, 'not_found'), (429, 'rate_limited'), (500, 'unavailable'), (206, 'unavailable')])
def test_provider_failures_never_create_successful_artifacts(tmp_path, monkeypatch, status, state):
    url = 'https://example.com/file.txt'
    serve(monkeypatch, {url: (status, {}, b'provider error with secret')})
    result = Client(tmp_path).resource(url)
    assert result['status'] == state and 'file' not in result
    assert 'secret' not in json.dumps(result) and not list(tmp_path.rglob('*.receipt.json'))


@pytest.mark.parametrize('url', [DOC, DRIVE])
def test_google_login_and_confirmation_html_are_not_saved_as_documents(tmp_path, monkeypatch, url):
    target = resources._target(resources.describe_resource(url), False)
    serve(monkeypatch, {target: (200, {'content-type': 'text/html'}, b'<html>Sign in to continue</html>')})
    result = Client(tmp_path).resource(url)
    assert result['status'] == 'access_required' and 'file' not in result


@pytest.mark.parametrize('url', ['https://drive.google.com/drive/folders/public_folder_123',
                                'https://github.com/example/project/tree/main/docs'])
def test_folders_require_a_file_selection_before_any_network(tmp_path, monkeypatch, url):
    monkeypatch.setattr(resources, '_read_url', lambda *a, **k: pytest.fail('must not crawl a folder'))
    assert Client(tmp_path).resource(url)['status'] == 'needs_selection'


@pytest.mark.parametrize('location', ['http://127.0.0.1/private', 'https://169.254.169.254/metadata',
                                     'http://example.com/downgrade', 'file:///etc/passwd'])
def test_redirects_cannot_reach_private_or_insecure_destinations(tmp_path, monkeypatch, location):
    url = 'https://example.com/short'
    calls = serve(monkeypatch, {url: (302, {'location': location}, b'')})
    assert Client(tmp_path).resource(url)['status'] == 'blocked' and calls == [url]


def test_public_hostname_with_private_dns_is_refused_before_opening_a_socket(monkeypatch):
    monkeypatch.setattr(resources.socket, 'getaddrinfo', lambda *a, **k: [
        (2, 1, 6, '', ('93.184.216.34', 443)), (2, 1, 6, '', ('127.0.0.1', 443))])
    monkeypatch.setattr(resources.socket, 'socket', lambda *a, **k: pytest.fail('DNS check must come first'))
    with pytest.raises(resources.ResourceError, match='nonpublic'):
        resources._connect('example.com', 443, 1)


def test_https_uses_the_checked_address_and_verifies_the_original_hostname(monkeypatch):
    connections, hosts = [], []
    monkeypatch.setattr(resources.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('93.184.216.34', 443))])
    raw = SimpleNamespace(settimeout=lambda _: None, connect=lambda address: connections.append(address), close=lambda: None)
    monkeypatch.setattr(resources.socket, 'socket', lambda *a, **k: raw)
    conn = resources._HTTPS('example.com', timeout=1)
    conn._context = SimpleNamespace(wrap_socket=lambda sock, server_hostname: hosts.append(server_hostname) or sock)
    conn.connect()
    assert connections == [('93.184.216.34', 443)] and hosts == ['example.com'] and conn.sock is raw


@pytest.mark.parametrize('headers,body,max_bytes', [({'content-length': '99'}, b'a', 10),
    ({}, b'longer than the limit', 5), ({'content-length': '10'}, b'short', 20)])
def test_transfer_enforces_actual_and_declared_size_and_complete_bytes(monkeypatch, headers, body, max_bytes):
    stream = io.BytesIO(body)
    response = SimpleNamespace(status=200, getheaders=lambda: list(headers.items()), read=stream.read)
    fake = SimpleNamespace(request=lambda *a, **k: None, getresponse=lambda: response, close=lambda: None, sock=None)
    monkeypatch.setattr(resources, '_HTTPS', lambda *a, **k: fake)
    with pytest.raises(resources.ResourceError):
        resources._read_url('https://example.com/file', max_bytes=max_bytes, deadline=time.monotonic() + 2)


def test_existing_artifact_corruption_is_not_overwritten(tmp_path, monkeypatch):
    url = 'https://example.com/file.txt'
    serve(monkeypatch, {url: b'original'})
    client = Client(tmp_path)
    first = client.resource(url)
    Path(first['file']).write_bytes(b'modified')
    second = client.resource(url)
    assert second['status'] == 'integrity_error' and Path(first['file']).read_bytes() == b'modified'
    assert not list(tmp_path.rglob('.resource-*'))


def test_missing_pdf_parser_does_not_claim_the_downloaded_binary_was_read(tmp_path, monkeypatch):
    url = 'https://example.com/paper.pdf'
    serve(monkeypatch, {url: (200, {'content-type': 'application/pdf'}, b'%PDF-binary-sample')})
    monkeypatch.setattr(resources.shutil, 'which', lambda _: None)
    result = Client(tmp_path).resource(url)
    assert result['status'] == 'ready' and result['text_status'] == 'unavailable' and 'text_file' not in result


def test_bulk_failures_keep_other_successful_references_and_provenance(tmp_path, monkeypatch):
    good, private = 'https://example.com/guide.txt', 'https://example.com/private.txt'
    serve(monkeypatch, {good: b'Readable', private: (403, {}, b'Private')})
    result = Client(tmp_path).resources(good + ' ' + private, source_url=POST, download=True)
    assert result['status'] == 'partial' and result['downloaded_count'] == 1
    assert [item['status'] for item in result['resources']] == ['ready', 'access_required']
    assert all(item['occurrences'][0]['source_url'] == POST for item in result['resources'])


def test_bulk_download_count_budget_does_not_silently_fetch_every_link(tmp_path, monkeypatch):
    client, called = Client(tmp_path), []
    def saved(url, **kwargs):
        called.append(url)
        return {'url': url, 'status': 'ready', 'bytes': 1, 'text_status': 'unavailable'}
    monkeypatch.setattr(client, 'resource', saved)
    result = client.resources(' '.join(f'https://example.com/{i}.txt' for i in range(21)), limit=30, download=True)
    assert len(called) == 20 and result['resources'][-1]['status'] == 'limit_reached' and result['status'] == 'partial'


def test_bulk_byte_budget_limits_downloads_and_uses_the_remaining_allowance(tmp_path, monkeypatch):
    client, allowances = Client(tmp_path), []
    def saved(url, **kwargs):
        allowances.append(kwargs['max_bytes'])
        return {'url': url, 'status': 'ready', 'bytes': kwargs['max_bytes'], 'text_status': 'unavailable'}
    monkeypatch.setattr(client, 'resource', saved)
    result = client.resources(' '.join(f'https://example.com/{i}.txt' for i in range(3)), download=True)
    assert allowances == [resources.MAX_BYTES, resources.MAX_BYTES]
    assert result['resources'][-1]['status'] == 'limit_reached'


def test_cli_accepts_a_social_json_ledger_and_returns_only_json(tmp_path, capsys):
    path = tmp_path / 'comments.json'
    path.write_text(json.dumps({'source_url': POST, 'comments': [{'id': '2', 'text': REPO}]}))
    assert main(['--data-dir', str(tmp_path), 'links', '--input', str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['resources'][0]['kind'] == 'github_repository'
    assert result['resources'][0]['occurrences'][0]['comment_id'] == '2'


def test_cli_resource_and_bulk_partial_failure_use_meaningful_exit_codes(tmp_path, monkeypatch, capsys):
    serve(monkeypatch, {'https://example.com/good.txt': b'good', 'https://example.com/private': (403, {}, b'')})
    prefix = ['--data-dir', str(tmp_path)]
    assert main([*prefix, 'resource', 'https://example.com/good.txt']) == 0
    assert json.loads(capsys.readouterr().out)['text_status'] == 'extracted'
    assert main([*prefix, 'links', '--text', 'https://example.com/good.txt https://example.com/private', '--download']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'partial'


def test_instagram_caption_and_only_returned_comments_expose_links(tmp_path, monkeypatch):
    from social_fetch import instagram_comments
    monkeypatch.setattr(instagram_comments, '_extract', lambda _: {
        'id': 'ABCDE12345', 'description': REPO, 'comment_count': 3,
        'comments': [{'id': '1', 'text': DOC}, {'id': '2', 'text': DRIVE}]})
    result = Client(tmp_path).comments(POST, count=1)
    assert result['status'] == 'partial' and not result['complete']
    assert {item['kind'] for item in result['linked_resources']} == {'github_repository', 'google_doc'}
    assert result['comments'][0]['linked_resources'][0]['occurrences'][0]['comment_id'] == '1'


@pytest.mark.parametrize('kwargs', [{'max_bytes': 0}, {'max_bytes': True}, {'max_bytes': resources.MAX_BYTES + 1},
    {'timeout': 0}, {'timeout': float('nan')}, {'timeout': float('inf')}, {'timeout': True}])
def test_invalid_download_bounds_stop_before_network(tmp_path, monkeypatch, kwargs):
    monkeypatch.setattr(resources, '_read_url', lambda *a, **k: pytest.fail('must validate first'))
    with pytest.raises(ValueError):
        Client(tmp_path).resource(REPO, **kwargs)
