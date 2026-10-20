"""Public samples must retain identity, uncertainty and a small evidence surface."""
import json

import pytest

from social_fetch import instagram_comments as comments

URL = 'https://www.instagram.com/p/DeWh1Y_IdjG/'
CODE = 'DeWh1Y_IdjG'


def test_sample_keeps_reported_total_and_deduplicates_carousel_comments(monkeypatch):
    row = {'id': '123', 'text': 'More tactical control', 'author': 'fan', 'like_count': 5,
           'timestamp': 1791780202, 'author_thumbnail': 'https://private-token.example/secret'}
    monkeypatch.setattr(comments, '_extract', lambda _: {
        'id': CODE, 'comment_count': 43, 'description': 'Caption', 'comments': [row],
        'entries': [{'comments': [row, {'id': '124', 'text': 'Keep player autonomy'}]}],
        'formats': [{'url': 'https://private-token.example/secret'}]})
    result = comments.read_comments(URL, limit=1)
    assert result['status'] == 'partial' and result['reported_total'] == 43
    assert result['fetched_count'] == 2 and result['returned_count'] == 1
    assert result['comments'][0]['id'] == '123'
    assert not result['complete'] and not result['pagination'] and not result['replies_expanded']
    assert 'secret' not in json.dumps(result)


@pytest.mark.parametrize('info', [
    {'id': CODE, 'comment_count': 275, 'comments': []},
    {'id': CODE}, {'status': 'fail', 'message': 'Please try again'},
    {'id': 'WrongPost', 'comment_count': 0, 'comments': []}, None, [],
])
def test_missing_or_failed_comments_never_masquerade_as_zero(monkeypatch, info):
    monkeypatch.setattr(comments, '_extract', lambda _: info)
    result = comments.read_comments(URL)
    assert result['status'] == 'unavailable' and result['reported_total'] != 0
    assert not result['complete'] and result['gaps']


def test_only_explicit_zero_count_is_empty(monkeypatch):
    monkeypatch.setattr(comments, '_extract', lambda _: {'id': CODE, 'comment_count': 0})
    assert comments.read_comments(URL)['status'] == 'empty'


def test_network_failures_are_sanitized(monkeypatch):
    def fail(_):
        raise RuntimeError('temporary-url-secret')
    monkeypatch.setattr(comments, '_extract', fail)
    result = comments.read_comments(URL)
    assert result['status'] == 'unavailable' and result['reported_total'] is None
    assert 'secret' not in json.dumps(result)


@pytest.mark.parametrize('url,limit', [('http://127.0.0.1/', 10), (URL, 0), (URL, 101), (URL, True)])
def test_invalid_input_stops_before_network(monkeypatch, url, limit):
    monkeypatch.setattr(comments, '_extract', lambda _: pytest.fail('unexpected network'))
    with pytest.raises(ValueError):
        comments.read_comments(url, limit=limit)


def test_cli_preserves_existing_evidence_before_network(tmp_path, monkeypatch):
    path = tmp_path / 'comments.json'
    path.write_text('existing')
    monkeypatch.setattr(comments, '_extract', lambda _: pytest.fail('unexpected network'))
    with pytest.raises(SystemExit):
        comments.main([URL, '--out', str(path)])
    assert path.read_text() == 'existing'
