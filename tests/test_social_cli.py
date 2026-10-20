"""Per-network commands exercise real waiting/export with offline job fixtures."""
import hashlib
import json
from pathlib import Path

import pytest

from social_fetch import Client, __version__
from social_fetch.download_jobs import save
from social_fetch.social_cli import NETWORKS, main
from social_fetch.social_sources import download_link


SAMPLES = {
    'youtube': 'https://youtu.be/jNQXAC9IVRw',
    'instagram': 'https://www.instagram.com/reel/C_bnaTAO2Ll/',
    'tiktok': 'https://www.tiktok.com/@patroxofficial/video/6742501081818877190',
    'x': 'https://x.com/buildingisgreen/status/1793226866335076588/video/2',
    'facebook': 'https://www.facebook.com/watch/?v=10155529876156509',
    'reddit': 'https://www.reddit.com/r/mercedes_benz/comments/1uwp60q/',
    'bluesky': 'https://bsky.app/profile/bsky.app/post/3l3vgf77uco2g',
    'pinterest': 'https://www.pinterest.com/pin/664281013778109217/',
    'twitch': 'https://clips.twitch.tv/FaintLightGullWholeWheat',
    'snapchat': 'https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPwAAYYWtidGhudGZpAX1TKn0JAX1TKnXJAAAAAA',
    'linkedin': 'https://www.linkedin.com/posts/the-mathworks_2_what-is-mathworks-cloud-center-activity-7151241570371948544-4Gu7/',
    'mastodon': 'https://mastodon.social/@mastodon/116839714185151652',
}
MEDIA = b'offline media fixture'


@pytest.fixture
def downloads(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv('SOCIAL_FETCH_DATA_DIR', str(tmp_path / 'jobs'))

    def ready(client, url, *, image=False):
        link = download_link(url)
        job_id = 'b' * 24
        folder = client.jobs.folder(client.namespace, job_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (link.identity + ('.image' if image else '.mp4'))).write_bytes(MEDIA)
        job = {'id': job_id, 'video_id': link.identity, 'source_url': link.url,
               'platform': link.platform, 'status': 'ready', 'bytes': len(MEDIA),
               'sha256': hashlib.sha256(MEDIA).hexdigest()}
        if image:
            job.update(media_kind='image', image_format='jpeg')
        save(folder / 'job.json', job)
        calls.append((url, image, client.namespace, client.jobs.root))
        return job

    monkeypatch.setattr(Client, 'download', ready)
    monkeypatch.setattr(Client, 'download_image', lambda client, url: ready(client, url, image=True))
    return calls


def test_help_lists_all_networks_and_legacy_commands(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(['--help'])
    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert set(NETWORKS) == set(SAMPLES)
    for command in (*SAMPLES, 'doctor', 'search', 'account', 'comments', 'links',
                    'resource', 'download', 'image', 'status', 'export'):
        assert command in help_text


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(['--version'])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


@pytest.mark.parametrize('network', SAMPLES)
def test_network_download_waits_and_exports_verified_media(network, tmp_path, downloads, capsys):
    url = SAMPLES[network]
    output = tmp_path / 'new output' / 'nested'
    ledger = tmp_path / 'metadata.json'
    data = tmp_path / 'custom jobs'
    assert main(['--data-dir', str(data), network, url, '-o', str(output),
                 '--timeout', '5', '--namespace', 'example', '--save', str(ledger)]) == 0
    result = json.loads(capsys.readouterr().out)
    expected = output / f'{network}-{download_link(url).identity}.mp4'
    assert result['status'] == 'ready'
    assert Path(result['exported_to']) == expected
    assert expected.read_bytes() == MEDIA
    assert result['sha256'] == hashlib.sha256(expected.read_bytes()).hexdigest()
    assert json.loads(ledger.read_text()) == result
    assert downloads == [(url, False, 'example', data)]


def test_default_output_is_current_directory(tmp_path, monkeypatch, downloads, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(['youtube', SAMPLES['youtube']]) == 0
    result = json.loads(capsys.readouterr().out)
    assert Path(result['exported_to']) == tmp_path / 'youtube-jNQXAC9IVRw.mp4'


def test_output_expands_home(tmp_path, monkeypatch, downloads, capsys):
    monkeypatch.setenv('HOME', str(tmp_path))
    assert main(['youtube', SAMPLES['youtube'], '--output', '~/clips']) == 0
    assert Path(json.loads(capsys.readouterr().out)['exported_to']).parent == tmp_path / 'clips'


@pytest.mark.parametrize('url', [SAMPLES['tiktok'], 'https://example.com/video',
                               'https://www.youtube.com/@nasa'])
def test_wrong_network_or_non_post_fails_before_download(url, downloads, capsys):
    assert main(['youtube', url]) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'failed'
    assert downloads == []


@pytest.mark.parametrize('kind', ['existing', 'symlink', 'output-file'])
def test_invalid_output_never_starts_download(kind, tmp_path, downloads, capsys):
    output = tmp_path / 'clips'
    if kind == 'output-file':
        output.write_bytes(b'keep')
    else:
        output.mkdir()
        target = output / 'youtube-jNQXAC9IVRw.mp4'
        if kind == 'existing':
            target.write_bytes(b'keep')
        else:
            target.symlink_to(tmp_path / 'absent')
    assert main(['youtube', SAMPLES['youtube'], '-o', str(output)]) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'failed'
    assert downloads == []
    if kind == 'existing':
        assert target.read_bytes() == b'keep'


@pytest.mark.parametrize('timeout', ['0', '-1', 'nan', 'inf', '86401'])
def test_network_rejects_invalid_timeout_before_download(timeout, downloads, capsys):
    assert main(['youtube', SAMPLES['youtube'], '--timeout', timeout]) == 1
    assert 'timeout' in json.loads(capsys.readouterr().out)['message']
    assert downloads == []


@pytest.mark.parametrize('timed_out', [False, True])
def test_failed_or_timed_out_job_never_exports(timed_out, tmp_path, monkeypatch, downloads, capsys):
    def wait(client, job_id, **kwargs):
        if timed_out:
            raise TimeoutError('Still pending')
        return {'id': job_id, 'status': 'failed', 'message': 'Source unavailable'}

    monkeypatch.setattr(Client, 'wait', wait)
    monkeypatch.setattr(Client, 'status', lambda *a: {'id': 'b' * 24, 'status': 'downloading'})
    output = tmp_path / 'clips'
    assert main(['youtube', SAMPLES['youtube'], '-o', str(output)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == ('downloading' if timed_out else 'failed')
    assert bool(result.get('timed_out')) == timed_out
    assert not output.exists()


@pytest.mark.parametrize('command', ['download', 'image'])
def test_legacy_download_and_image_keep_explicit_output(command, tmp_path, downloads, capsys):
    url = SAMPLES['reddit']
    out = tmp_path / ('legacy.jpg' if command == 'image' else 'legacy.mp4')
    assert main([command, url, '--out', str(out)]) == 0
    assert Path(json.loads(capsys.readouterr().out)['exported_to']) == out
    assert out.read_bytes() == MEDIA
    assert downloads[0][1] == (command == 'image')


def test_legacy_download_remains_nonblocking_by_default(monkeypatch, downloads, capsys):
    monkeypatch.setattr(Client, 'wait', lambda *a, **kw: pytest.fail('must not wait'))
    monkeypatch.setattr(Client, 'export', lambda *a, **kw: pytest.fail('must not export'))
    assert main(['download', SAMPLES['youtube']]) == 0
    assert 'exported_to' not in json.loads(capsys.readouterr().out)
