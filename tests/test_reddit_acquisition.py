"""Reddit acquisition must preserve selected-post, audio and transfer boundaries."""
import io
import json
from html import escape
from urllib.parse import parse_qs, urlencode, urlsplit
import pytest

import social_fetch.social_fallbacks as fallback
import social_fetch.reddit_web as reddit
from social_fetch.social_sources import download_link


SOURCE = 'https://www.reddit.com/r/mercedes_benz/comments/1uwp60q/'
MEDIA = 'https://v.redd.it/selectednative/DASH_720.mp4'
MP4 = b'0000ftyp' + b'x' * 2048


def selected_post(monkeypatch, **changes):
    post = {'id': '1uwp60q', 'is_video': True,
            'secure_media': {'reddit_video': {'has_audio': False, 'fallback_url': MEDIA}}}
    post.update(changes)
    monkeypatch.setattr(fallback, 'document', lambda *a, **k:
                        json.dumps([{'data': {'children': [{'data': post}]}}]))
    return post


@pytest.mark.parametrize('changed_id', ['anotherpost', None, 't3_1uwp60q'])
def test_another_or_ambiguous_post_is_rejected_before_media_request(tmp_path, monkeypatch, changed_id):
    selected_post(monkeypatch, id=changed_id)
    monkeypatch.setattr(fallback, 'transfer', lambda *a: pytest.fail('Unbound media request'))
    with pytest.raises(ValueError, match='another post'):
        fallback.reddit_download(download_link(SOURCE), tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('changes', [
    {'crosspost_parent': 't3_otherpost'},
    {'crosspost_parent_list': [{'id': 'otherpost'}]},
    {'is_video': False},
])
def test_crossposts_and_external_embeds_are_rejected(tmp_path, monkeypatch, changes):
    selected_post(monkeypatch, **changes)
    monkeypatch.setattr(fallback, 'transfer', lambda *a: pytest.fail('Non-native media request'))
    with pytest.raises(fallback.ProviderUnavailable, match='selected native Reddit video'):
        fallback.reddit_download(download_link(SOURCE), tmp_path)


@pytest.mark.parametrize('audio', [True, None, 'missing'])
def test_expected_or_unknown_audio_cannot_be_replaced_by_silent_fallback(tmp_path, monkeypatch, audio):
    video = selected_post(monkeypatch)['secure_media']['reddit_video']
    if audio == 'missing':
        video.pop('has_audio')
    else:
        video['has_audio'] = audio
    monkeypatch.setattr(fallback, 'transfer', lambda *a: pytest.fail('Audio would be discarded'))
    with pytest.raises(fallback.ProviderUnavailable, match='split audio'):
        fallback.reddit_download(download_link(SOURCE), tmp_path)


@pytest.mark.parametrize('url', [
    'https://v.redd.it.evil.example/selectednative/DASH_720.mp4',
    'https://www.reddit.com/selectednative/DASH_720.mp4',
    'https://127.0.0.1/selectednative/DASH_720.mp4',
    'http://v.redd.it/selectednative/DASH_720.mp4',
    'https://user:password@v.redd.it/selectednative/DASH_720.mp4',
    'https://v.redd.it:8443/selectednative/DASH_720.mp4',
    'https://v.redd.it/selectednative/DASH_720.mp4#fragment',
])
def test_reddit_media_redirect_is_checked_before_following(monkeypatch, url):
    class Opener:
        def __init__(self, redirects):
            self.redirects = redirects

        def open(self, request, **kwargs):
            self.redirects.redirect_request(request, None, 302, 'Found', {}, url)
            pytest.fail('Unapproved redirect was followed')

    monkeypatch.setattr(fallback, 'build_opener', lambda redirects: Opener(redirects))
    with pytest.raises(ValueError, match='Unexpected fallback'):
        fallback.request('reddit', MEDIA, media=True)


def test_truncated_reddit_mp4_is_removed_without_a_receipt(tmp_path, monkeypatch):
    selected_post(monkeypatch)

    class Response(io.BytesIO):
        status = 200
        headers = {'Content-Length': str(len(MP4) + 1)}

    monkeypatch.setattr(fallback, 'request', lambda *a, **k: Response(MP4))
    with pytest.raises(fallback.ProviderUnavailable, match='Incomplete MP4'):
        fallback.reddit_download(download_link(SOURCE), tmp_path)
    assert not list(tmp_path.iterdir())


TOKEN = 'doila6xc6adh1'


def embed_page(*, post_id='1uwp60q', player_id='1uwp60q', kind='video',
               media_id=TOKEN, player_media_id=TOKEN, canonical=SOURCE):
    data = {'post': {'id': 't3_' + post_id, 'type': kind,
                     'url': 'https://v.redd.it/' + media_id}}
    return ('<div id="canonical-url-updater" value="' + escape(canonical, quote=True) + '"></div>'
            '<shreddit-screenview-data data="' + escape(json.dumps(data), quote=True) + '"></shreddit-screenview-data>'
            '<shreddit-player post-id="t3_' + player_id + '" src="https://v.redd.it/' + player_media_id + '/HLSPlaylist.m3u8"></shreddit-player>')


def merged_url(**changes):
    values = {'permalink': SOURCE,
              'video_url': 'https://v.redd.it/' + TOKEN + '/CMAF_1080.mp4?source=fallback',
              'audio_url': 'https://v.redd.it/' + TOKEN + '/CMAF_AUDIO_128.mp4'}
    values.update(changes)
    return 'https://sd.rapidsave.com/download.php?' + urlencode(values)


def embedded_route(monkeypatch, *, page=None, delivery=None, declared=None):
    calls = []
    delivery = delivery or merged_url()

    def document(url, validate):
        validate(url)
        calls.append(urlsplit(url).hostname)
        if urlsplit(url).hostname == 'embed.reddit.com':
            return page if page is not None else embed_page()
        return '<a class="downloadbutton" href="' + escape(delivery, quote=True) + '">Download</a>'

    class Response(io.BytesIO):
        status = 200
        headers = {'Content-Length': str(len(MP4) if declared is None else declared)}

    def request(url, validate):
        validate(url)
        calls.append(urlsplit(url).hostname)
        return Response(MP4)

    monkeypatch.setattr(reddit, '_document', document)
    monkeypatch.setattr(reddit, '_request', request)
    return calls


def test_embed_binds_post_player_and_both_native_streams_before_transfer(tmp_path, monkeypatch):
    calls = embedded_route(monkeypatch)
    path = reddit.download_video(SOURCE, tmp_path)
    assert path.read_bytes() == MP4
    assert calls == ['embed.reddit.com', 'rapidsave.com', 'sd.rapidsave.com']


@pytest.mark.parametrize('changes', [
    {'post_id': 'anotherpost'},
    {'canonical': 'https://www.reddit.com/r/videos/comments/anotherpost/'},
    {'player_id': 'anotherpost'},
    {'player_media_id': 'anothernative'},
])
def test_embed_identity_conflicts_stop_before_resolver_or_media(tmp_path, monkeypatch, changes):
    calls = embedded_route(monkeypatch, page=embed_page(**changes))
    with pytest.raises(ValueError):
        reddit.download_video(SOURCE, tmp_path)
    assert calls == ['embed.reddit.com'] and not list(tmp_path.iterdir())


@pytest.mark.parametrize('kind', ['crosspost', 'link', 'text', 'gallery', 'image'])
def test_embed_rejects_crossposts_and_non_video_posts_before_resolving(tmp_path, monkeypatch, kind):
    calls = embedded_route(monkeypatch, page=embed_page(kind=kind))
    with pytest.raises(fallback.ProviderUnavailable, match='selected native'):
        reddit.download_video(SOURCE, tmp_path)
    assert calls == ['embed.reddit.com']


@pytest.mark.parametrize('changes', [
    {'permalink': 'https://www.reddit.com/r/videos/comments/anotherpost/'},
    {'video_url': 'https://v.redd.it/anothernative/CMAF_1080.mp4'},
    {'audio_url': 'https://v.redd.it/anothernative/CMAF_AUDIO_128.mp4'},
    {'video_url': 'https://v.redd.it.evil.example/' + TOKEN + '/CMAF_1080.mp4'},
    {'audio_url': 'https://user:password@v.redd.it/' + TOKEN + '/CMAF_AUDIO_128.mp4'},
    {'audio_url': ''},
    {'audio_url': 'https://v.redd.it/' + TOKEN + '/CMAF_96.mp4'},
    {'video_url': 'https://v.redd.it/' + TOKEN + '/CMAF_1080.mp4?redirect=https://example.test'},
])
def test_resolver_cannot_change_post_video_audio_or_component_hosts(tmp_path, monkeypatch, changes):
    calls = embedded_route(monkeypatch, delivery=merged_url(**changes))
    with pytest.raises(ValueError):
        reddit.download_video(SOURCE, tmp_path)
    assert calls == ['embed.reddit.com', 'rapidsave.com']
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('redirect', [
    'https://sd.rapidsave.com.evil.example/download.php',
    merged_url(video_url='https://v.redd.it/' + TOKEN + '/CMAF_720.mp4'),
    merged_url(audio_url='https://v.redd.it/anothernative/CMAF_AUDIO_128.mp4'),
])
def test_merged_delivery_redirect_must_keep_the_selected_components(tmp_path, monkeypatch, redirect):
    embedded_route(monkeypatch)

    class Opener:
        def __init__(self, handler):
            self.handler = handler

        def open(self, request, **kwargs):
            self.handler.redirect_request(request, None, 302, 'Found', {}, redirect)
            pytest.fail('Changed delivery was followed')

    monkeypatch.setattr(reddit, 'build_opener', lambda handler: Opener(handler))
    monkeypatch.setattr(reddit, '_request', REAL_REDDIT_REQUEST)
    with pytest.raises(ValueError):
        reddit.download_video(SOURCE, tmp_path)
    assert not list(tmp_path.iterdir())


REAL_REDDIT_REQUEST = reddit._request


def test_merged_route_removes_a_truncated_transfer(tmp_path, monkeypatch):
    embedded_route(monkeypatch, declared=len(MP4) + 1)
    with pytest.raises(fallback.ProviderUnavailable, match='Incomplete MP4'):
        reddit.download_video(SOURCE, tmp_path)
    assert not list(tmp_path.iterdir())


def test_reddit_adapter_issues_read_requests_without_account_state(monkeypatch):
    calls = []

    class Opener:
        def open(self, request, **kwargs):
            calls.append((request.get_method(), request.data, request.get_header('Cookie')))
            return io.BytesIO(b'public')

    monkeypatch.setattr(reddit, 'build_opener', lambda handler: Opener())
    with reddit._request('https://embed.reddit.com/r/videos/comments/abc123/',
                         lambda u: reddit._https(u, {'embed.reddit.com'})) as response:
        assert response.read() == b'public'
    assert calls == [('GET', None, None)]


IMAGE_SOURCE = 'https://www.reddit.com/r/itookapicture/comments/1x3kp6y/'
IMAGE_URL = 'https://i.redd.it/hin1y2pvtwuh1.jpeg'
JPEG = b'\xff\xd8\xff' + b'x' * 2048


def image_route(monkeypatch, *, post_id='1x3kp6y', kind='image', url=IMAGE_URL,
                payload=JPEG, declared=None):
    calls = []
    post = {'id': 't3_' + post_id, 'type': kind, 'url': url}
    page = ('<div id="canonical-url-updater" value="' + IMAGE_SOURCE + '"></div>'
            '<shreddit-screenview-data data="' + escape(json.dumps({'post': post}), quote=True) + '"></shreddit-screenview-data>')

    def document(candidate, validate):
        validate(candidate)
        calls.append('metadata')
        return page

    class Response(io.BytesIO):
        status = 200
        headers = {} if declared == 'absent' else {'Content-Length': str(len(payload) if declared is None else declared)}

    def request(candidate, validate):
        validate(candidate)
        calls.append('media')
        return Response(payload)

    monkeypatch.setattr(reddit, '_document', document)
    monkeypatch.setattr(reddit, '_request', request)
    return calls


def image_checks(monkeypatch, *, width=4500, height=3000, codec='mjpeg', container='jpeg_pipe'):
    calls = []
    metadata = {'streams': [{'codec_type': 'video', 'codec_name': codec, 'width': width, 'height': height}],
                'format': {'format_name': container}}
    monkeypatch.setattr(reddit.subprocess, 'check_output', lambda *a, **k: json.dumps(metadata).encode())
    monkeypatch.setattr(reddit.subprocess, 'run', lambda command, **k: calls.append(command))
    return calls


def test_native_image_has_a_checked_receipt_and_safe_cached_source(tmp_path, monkeypatch):
    calls = image_route(monkeypatch)
    raw = reddit.acquire_image(IMAGE_SOURCE, tmp_path)
    assert raw.read_bytes() == JPEG
    assert reddit.acquire_image(IMAGE_SOURCE, tmp_path) == raw
    assert calls == ['metadata', 'media']
    decode = image_checks(monkeypatch)
    reddit.finalize_image(IMAGE_SOURCE, tmp_path, '1x3kp6y')
    receipt = json.loads((tmp_path / '1x3kp6y.receipt.json').read_text())
    assert receipt['downloaded'] is True and receipt['media_kind'] == 'image'
    assert receipt['image_format'] == 'jpeg' and receipt['decode_sample_frames'] == 1
    assert receipt['width'] == 4500 and receipt['height'] == 3000
    assert (tmp_path / '1x3kp6y.image').read_bytes() == JPEG
    assert decode[0][decode[0].index('-protocol_whitelist') + 1] == 'file,pipe'
    assert decode[0][decode[0].index('-frames:v') + 1] == '1'


@pytest.mark.parametrize('changes', [
    {'post_id': 'anotherpost'},
    {'kind': 'crosspost'},
    {'kind': 'gallery'},
    {'url': 'https://i.redd.it.evil.example/hin1y2pvtwuh1.jpeg'},
    {'url': 'https://i.redd.it/hin1y2pvtwuh1.jpeg?redirect=https://example.test'},
])
def test_image_post_and_attachment_binding_are_required_before_transfer(tmp_path, monkeypatch, changes):
    calls = image_route(monkeypatch, **changes)
    with pytest.raises(ValueError):
        reddit.acquire_image(IMAGE_SOURCE, tmp_path)
    assert calls == ['metadata'] and not list(tmp_path.iterdir())


@pytest.mark.parametrize('changes', [
    {'declared': len(JPEG) + 1},
    {'payload': b'0000ftyp' + b'x' * 2048},
    {'payload': b'\x89PNG\r\n\x1a\n' + b'x' * 2048},
])
def test_incomplete_or_mismatched_images_leave_no_receipt(tmp_path, monkeypatch, changes):
    image_route(monkeypatch, **changes)
    with pytest.raises(ValueError):
        reddit.acquire_image(IMAGE_SOURCE, tmp_path)
    assert not list(tmp_path.iterdir())


def test_image_byte_limit_also_applies_without_content_length(tmp_path, monkeypatch):
    image_route(monkeypatch, declared='absent')
    monkeypatch.setattr(reddit, 'MAX_IMAGE_BYTES', 128)
    with pytest.raises(ValueError, match='size or time'):
        reddit.acquire_image(IMAGE_SOURCE, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('changes', [
    {'width': 0}, {'height': 0}, {'width': 100000, 'height': 100000},
    {'codec': 'h264'}, {'container': 'mov,mp4,m4a,3gp,3g2,mj2'},
])
def test_image_dimensions_and_decoder_format_are_verified_before_ready(tmp_path, monkeypatch, changes):
    image_route(monkeypatch)
    reddit.acquire_image(IMAGE_SOURCE, tmp_path)
    decode = image_checks(monkeypatch, **changes)
    with pytest.raises(ValueError):
        reddit.finalize_image(IMAGE_SOURCE, tmp_path, '1x3kp6y')
    assert not decode
    assert not (tmp_path / '1x3kp6y.image').exists()
    assert not (tmp_path / '1x3kp6y.receipt.json').exists()
    assert not (tmp_path / '1x3kp6y.pending.image').exists()


def test_changed_image_bytes_cannot_be_finalized_under_an_old_receipt(tmp_path, monkeypatch):
    image_route(monkeypatch)
    raw = reddit.acquire_image(IMAGE_SOURCE, tmp_path)
    raw.write_bytes(JPEG[:-1] + b'z')
    monkeypatch.setattr(reddit.subprocess, 'check_output', lambda *a, **k: pytest.fail('Unreceipted bytes reached decoder'))
    with pytest.raises(ValueError, match='acquisition receipt'):
        reddit.finalize_image(IMAGE_SOURCE, tmp_path, '1x3kp6y')


def test_metadata_deadline_is_checked_between_available_socket_reads(monkeypatch):
    class Response(io.BytesIO):
        status = 200
        headers = {}
    monkeypatch.setattr(reddit, '_request', lambda *a: Response(b'slow metadata'))
    ticks = iter((0, 0, 61))
    monkeypatch.setattr(reddit.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(ValueError, match='time bound'):
        reddit._document('https://embed.reddit.com/test', lambda _: None)


def comment_page(identifier='abc123', *, post_id='1uwp60q', returned_id=None,
                 text='Current <b>public</b> &amp; readable', canonical=SOURCE,
                 body_id=None, duplicate=False, parent_id=None):
    returned_id = returned_id or identifier
    body_id = body_id or identifier
    data = {'comment': {'id': 't1_' + returned_id, 'post_id': 't3_' + post_id,
                        'type': 'comment', 'created_timestamp': 1700000000000, 'score': 2}}
    if parent_id is not None:
        data['comment']['parent_id'] = parent_id
    body = '<div id="t1_' + body_id + '-post-rtjson-content"><p>' + text + '</p></div>'
    permalink = SOURCE + 'post/' + identifier + '/'
    return ('<div id="canonical-url-updater" value="' + canonical + '"></div>'
            '<shreddit-screenview-data data="' + escape(json.dumps(data), quote=True) + '"></shreddit-screenview-data>'
            '<embed-event-handler id="t1_' + identifier + '" link="' + permalink + '"></embed-event-handler>'
            + body + (body if duplicate else ''))


def comment_route(monkeypatch, *, rows=None, pages=None, outage=False):
    calls = []
    if rows is None:
        rows = [{'id': 'abc123', 'link_id': 't3_1uwp60q',
                 'permalink': '/r/mercedes_benz/comments/1uwp60q/post/abc123/',
                 'body': 'ARCHIVE BODY MUST NEVER BE RETURNED'}]

    def document(url, validate, **kwargs):
        validate(url)
        parsed = urlsplit(url)
        if parsed.hostname == 'arctic-shift.photon-reddit.com':
            calls.append('archive_ids')
            # The live API rejects projections containing permalink.
            if 'permalink' in parse_qs(parsed.query).get('fields', [''])[0].split(','):
                raise fallback.ProviderUnavailable('Unknown selectable field: permalink')
            if outage:
                raise fallback.ProviderUnavailable('Metadata unavailable')
            assert kwargs['max_bytes'] == 2 * 1024**2
            return json.dumps({'data': rows})
        pieces = parsed.path.strip('/').split('/')
        if len(pieces) == 4:
            calls.append('post')
            return embed_page()
        calls.append(pieces[-1])
        assert kwargs['max_bytes'] == 512 * 1024
        return (pages or {}).get(pieces[-1], comment_page(pieces[-1]))

    monkeypatch.setattr(reddit, '_document', document)
    return calls


def test_comment_ids_are_discovered_but_bodies_come_from_current_public_embeds(monkeypatch):
    calls = comment_route(monkeypatch)
    result = reddit.read_comments(SOURCE, limit=5)
    assert result['status'] == 'partial' and result['complete'] is False
    assert result['comments'][0]['text'] == 'Current public & readable'
    assert result['comments'][0]['post_id'] == '1uwp60q'
    assert result['comments'][0]['timestamp'] == 1700000000
    assert result['returned_count'] == 1 and result['reported_total'] is None
    assert 'ARCHIVE BODY' not in json.dumps(result)
    assert calls == ['post', 'archive_ids', 'abc123']


@pytest.mark.parametrize('row', [
    {'id': 'abc123', 'link_id': 't3_anotherpost', 'permalink': '/r/videos/comments/anotherpost/post/abc123/'},
    {'id': 'abc123', 'link_id': 't3_1uwp60q', 'permalink': '/r/videos/comments/anotherpost/post/abc123/'},
    {'id': 'abc123', 'link_id': 't3_1uwp60q', 'permalink': '//evil.example/r/videos/comments/1uwp60q/post/abc123/'},
])
def test_comment_discovery_cannot_cross_post_or_permalink_boundaries(monkeypatch, row):
    calls = comment_route(monkeypatch, rows=[row])
    with pytest.raises(ValueError):
        reddit.read_comments(SOURCE)
    assert calls == ['post', 'archive_ids']


@pytest.mark.parametrize('changes', [
    {'post_id': 'anotherpost'},
    {'returned_id': 'anothercomment'},
    {'canonical': 'https://www.reddit.com/r/videos/comments/anotherpost/'},
    {'duplicate': True},
    {'parent_id': 't3_anotherpost'},
    {'parent_id': 'https://evil.example/'},
])
def test_current_comment_identity_and_body_ambiguity_fail_closed(monkeypatch, changes):
    comment_route(monkeypatch, pages={'abc123': comment_page(**changes)})
    with pytest.raises(ValueError):
        reddit.read_comments(SOURCE)


@pytest.mark.parametrize('body', ['[removed]', '[deleted]'])
def test_removed_current_comment_is_not_replaced_with_its_archive_text(monkeypatch, body):
    comment_route(monkeypatch, pages={'abc123': comment_page(text=body)})
    result = reddit.read_comments(SOURCE)
    assert result['status'] == 'no_exposed_comments'
    assert result['comments'] == [] and result['unavailable_count'] == 1
    assert result['reported_total'] is None and result['complete'] is False


def test_comment_discovery_outage_is_distinct_from_an_empty_sample(monkeypatch):
    comment_route(monkeypatch, outage=True)
    assert reddit.read_comments(SOURCE)['status'] == 'unavailable'
    comment_route(monkeypatch, rows=[])
    result = reddit.read_comments(SOURCE)
    assert result['status'] == 'no_exposed_comments'
    assert result['reported_total'] is None and result['complete'] is False


@pytest.mark.parametrize('limit', [0, 21, True, 1.5])
def test_comment_sample_limits_are_checked_before_network(monkeypatch, limit):
    monkeypatch.setattr(reddit, '_document', lambda *a, **k: pytest.fail('Unbounded comment lookup'))
    with pytest.raises(ValueError, match='between 1 and 20'):
        reddit.read_comments(SOURCE, limit=limit)


def test_comment_body_ignores_scripts_inside_the_selected_text_container(monkeypatch):
    comment_route(monkeypatch, pages={'abc123': comment_page(text='Visible<script>hidden code</script> text')})
    assert reddit.read_comments(SOURCE)['comments'][0]['text'] == 'Visible text'


def test_reddit_primary_requires_audio_before_the_normal_worker_can_receipt(tmp_path, monkeypatch):
    import social_fetch.social_download as download
    from pathlib import Path
    def acquired(value, folder):
        path = folder / 'raw.mp4'
        path.write_bytes(MP4)
        return path
    monkeypatch.setattr(reddit, 'download_video', acquired)
    download.acquire(SOURCE, tmp_path)
    receipt = json.loads((tmp_path / 'acquisition.json').read_text())
    assert receipt['audio_required'] is True and receipt['route'] == 'reddit_embed_rapidsave'
    def remux(command, **kwargs):
        if '-movflags' in command:
            Path(command[-1]).write_bytes(MP4)
        else:
            pytest.fail('A silent source reached completed-file decoding')
    monkeypatch.setattr(download.subprocess, 'run', remux)
    metadata = {'streams': [{'codec_type': 'video', 'width': 1080, 'height': 1920}],
                'format': {'duration': '52'}}
    monkeypatch.setattr(download.subprocess, 'check_output', lambda *a, **k: json.dumps(metadata).encode())
    with pytest.raises(ValueError, match='Expected Reddit audio'):
        download.finalize(SOURCE, tmp_path, '1uwp60q')
    assert not (tmp_path / '1uwp60q.mp4').exists()
    assert not (tmp_path / '1uwp60q.receipt.json').exists()


def queued_image_client(tmp_path, monkeypatch):
    import social_fetch.download_jobs as jobs
    from social_fetch.client import Client
    from types import SimpleNamespace
    monkeypatch.setattr(jobs.DownloadJobs, '_start', lambda *a: None)
    monkeypatch.setattr(jobs.shutil, 'disk_usage', lambda *a: SimpleNamespace(free=100 * 1024**3))
    return Client(tmp_path, namespace='image-owner')


def test_image_and_video_intents_have_distinct_jobs_and_namespace_ownership(tmp_path, monkeypatch):
    from social_fetch.client import Client
    client = queued_image_client(tmp_path, monkeypatch)
    video = client.download(IMAGE_SOURCE)
    image = client.download_image(IMAGE_SOURCE)
    assert video['id'] != image['id'] and image['media_kind'] == 'image'
    assert client.download_image(IMAGE_SOURCE)['id'] == image['id']
    other = Client(tmp_path, namespace='other-owner')
    with pytest.raises(FileNotFoundError):
        other.status(image['id'])


def test_image_export_checks_format_hash_namespace_and_no_overwrite(tmp_path, monkeypatch):
    import hashlib
    import social_fetch.download_jobs as jobs
    from social_fetch.client import Client
    client = queued_image_client(tmp_path / 'data', monkeypatch)
    public = client.download_image(IMAGE_SOURCE)
    folder = client.jobs.folder(client.namespace, public['id'])
    record = json.loads((folder / 'job.json').read_text())
    record.update(status='ready', bytes=len(JPEG), sha256=hashlib.sha256(JPEG).hexdigest(),
                  image_format='jpeg', width=4500, height=3000)
    (folder / (record['video_id'] + '.image')).write_bytes(JPEG)
    jobs.save(folder / 'job.json', record)
    with pytest.raises(ValueError, match='recorded format'):
        client.export(public['id'], tmp_path / 'wrong.png')
    out = tmp_path / 'checked.jpg'
    exported = client.export(public['id'], out)
    assert out.read_bytes() == JPEG and exported['sha256'] == hashlib.sha256(JPEG).hexdigest()
    with pytest.raises(ValueError, match='already exists'):
        client.export(public['id'], out)
    with pytest.raises(FileNotFoundError):
        Client(tmp_path / 'data', namespace='other-owner').export(public['id'], tmp_path / 'leak.jpg')
    (folder / (record['video_id'] + '.image')).write_bytes(JPEG[:-1] + b'z')
    with pytest.raises(ValueError, match='integrity receipt'):
        client.export(public['id'], tmp_path / 'changed.jpg')
    assert not (tmp_path / 'changed.jpg').exists()


def test_image_worker_rejects_a_receipt_for_a_different_media_kind(tmp_path, monkeypatch):
    import hashlib
    import social_fetch.download_jobs as jobs
    from types import SimpleNamespace
    client = queued_image_client(tmp_path, monkeypatch)
    public = client.download_image(IMAGE_SOURCE)
    folder = client.jobs.folder(client.namespace, public['id'])
    record = json.loads((folder / 'job.json').read_text())
    def command(argv, **kwargs):
        if '--finalize-only' in argv:
            (folder / (record['video_id'] + '.image')).write_bytes(JPEG)
            jobs.save(folder / (record['video_id'] + '.receipt.json'), {
                'downloaded': True, 'source_url': IMAGE_SOURCE, 'bytes': len(JPEG),
                'sha256': hashlib.sha256(JPEG).hexdigest(), 'media_kind': 'video',
                'image_format': 'jpeg', 'decode_sample_frames': 1})
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(jobs.subprocess, 'run', command)
    client.jobs.work(folder)
    status = client.status(public['id'])
    assert status['status'] == 'failed' and status['failure_stage'] == 'verification'


def test_comments_cli_reports_unavailable_as_a_failed_read(monkeypatch, capsys):
    import social_fetch.social_cli as cli
    class Client:
        def __init__(self, *a, **k):
            pass
        def comments(self, *a, **k):
            return {'status': 'unavailable', 'comments': [], 'reported_total': None}
    monkeypatch.setattr(cli, 'Client', Client)
    assert cli.main(['comments', SOURCE]) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'unavailable'


@pytest.mark.parametrize('platform,url,count,expected', [
    ('reddit', SOURCE, None, 5),
    ('reddit', SOURCE, 3, 3),
    ('instagram', 'https://www.instagram.com/p/DeWYHFHIkVC/', None, 50),
    ('instagram', 'https://www.instagram.com/p/DeWYHFHIkVC/', 75, 75),
])
def test_shared_comments_command_preserves_each_platform_reader_and_count(
        tmp_path, monkeypatch, capsys, platform, url, count, expected):
    import social_fetch.instagram_comments as instagram
    import social_fetch.social_cli as cli
    calls = []

    def reader(name):
        def read(value, *, limit):
            calls.append((name, value, limit))
            return {'platform': name, 'status': 'partial', 'comments': [{'text': 'Current text'}]}
        return read

    monkeypatch.setattr(reddit, 'read_comments', reader('reddit'))
    monkeypatch.setattr(instagram, 'read_comments', reader('instagram'))
    args = ['--data-dir', str(tmp_path), 'comments', url]
    if count is not None:
        args += ['--count', str(count)]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)['platform'] == platform
    assert calls == [(platform, url, expected)]


def test_shared_comment_reader_enforces_reddit_count_before_network(tmp_path, monkeypatch):
    from social_fetch.client import Client
    monkeypatch.setattr(reddit, '_selected_post', lambda *a, **k: pytest.fail('Unexpected network'))
    with pytest.raises(ValueError, match='between 1 and 20'):
        Client(tmp_path).comments(SOURCE, count=21)


@pytest.mark.parametrize('url', [
    'https://www.youtube.com/watch?v=jNQXAC9IVRw',
    'https://www.instagram.com/creator/',
    'http://127.0.0.1/',
])
def test_shared_comment_reader_rejects_unsupported_sources_before_network(tmp_path, monkeypatch, url):
    from social_fetch.client import Client
    import social_fetch.instagram_comments as instagram
    monkeypatch.setattr(reddit, 'read_comments', lambda *a, **k: pytest.fail('Unexpected Reddit read'))
    monkeypatch.setattr(instagram, 'read_comments', lambda *a, **k: pytest.fail('Unexpected Instagram read'))
    with pytest.raises(ValueError, match='Instagram or Reddit post'):
        Client(tmp_path).comments(url)
