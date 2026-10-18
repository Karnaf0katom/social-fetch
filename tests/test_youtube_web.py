"""Download identity, quality selection, and complete-range acceptance."""
import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest

from social_fetch import youtube_web as web
VIDEO = "SusiqEN2Y4w"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VIDEO}",
    f"https://www.youtube.com/watch?v={VIDEO}&t=205s&list=playlist",
    f"https://youtube.com/shorts/{VIDEO}?si=share-token",
    f"https://www.youtube.com/shorts/{VIDEO}/",
    f"https://m.youtube.com/watch?v={VIDEO}#t=205",
    f"https://youtu.be/{VIDEO}?si=share-token&t=205",
    f"https://www.youtube.com/embed/{VIDEO}",
    f"https://www.youtube.com/live/{VIDEO}",
])
def test_watch_shorts_and_share_links_use_the_same_source(url):
    assert web.youtube_url(url) == f"https://www.youtube.com/watch?v={VIDEO}"


@pytest.mark.parametrize("url", [
    f"https://youtube.com.evil.test/shorts/{VIDEO}",
    f"https://youtube.com@evil.test/shorts/{VIDEO}",
    f"https://user:password@youtube.com/shorts/{VIDEO}",
    f"https://youtube.com:8443/shorts/{VIDEO}",
    f"https://youtu.be/{VIDEO}/another-path",
    f"https://www.youtube.com/watch?v={VIDEO}&v=NiPCDDNEZa0",
    "https://www.youtube.com/playlist?list=PL123456789",
    "https://youtube.com/shorts/too-short",
    f"https://www.you\ntube.com/watch?v={VIDEO}",
])
def test_rejects_non_video_or_ambiguous_input_before_network(url):
    with pytest.raises(ValueError):
        web.youtube_url(url)


def test_shorts_finalize_uses_existing_canonical_manifest(monkeypatch, tmp_path):
    import json
    canonical = f"https://www.youtube.com/watch?v={VIDEO}"
    (tmp_path / f"{VIDEO}.streams.json").write_text(json.dumps({
        "id": VIDEO, "source_url": canonical, "streams": ["saved-streams"],
    }))
    monkeypatch.setattr(web, "finalize", lambda *args: args)
    assert web.acquire(f"https://youtube.com/shorts/{VIDEO}", tmp_path, 1080,
                       finalize_only=True) == (canonical, VIDEO, tmp_path, ["saved-streams"])


def test_direct_worker_script_can_import_its_new_sibling_adapters(tmp_path):
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-I', str(Path(web.__file__)),
        f'https://www.youtube.com/watch?v={VIDEO}', '--out', str(tmp_path), '--finalize-only'],
        cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 1  # No saved streams; the check never needs network access.
    assert 'No module named' not in result.stdout + result.stderr
    assert 'streams.json' in result.stdout


def option(label, kind, ext, tag, video_id=VIDEO):
    return {"data-force": f"https://www.snapyt.app/wp-admin/admin-ajax.php?action=snapyt_force_download&t={video_id}.public-form-token&tg={tag}",
            "data-kind": kind, "data-ext": ext, "data-label": label, "data-bytes": "1000000"}


def test_selects_1080_original_video_and_m4a_without_upscaling():
    rows = [option("360p MP4", "video+audio", "mp4", 18),
            option("1080p MP4", "video-only", "mp4", 137),
            option("2160p MP4", "video-only", "mp4", 400),
            option("720p MP4", "video-only", "mp4", 136),
            option("MP3 320 kbps", "audio-only", "mp3", 251),
            option("M4A Audio", "audio-only", "m4a", 140)]
    assert [s["format_id"] for s in web.select_streams(rows, VIDEO, 1080)] == ["137", "140"]
    assert web.select_streams(rows, VIDEO, 720)[0]["height"] == 720


def test_wrong_video_is_not_silently_downloaded():
    with pytest.raises(ValueError, match="does not match"):
        web.select_streams([option("1080p MP4", "video-only", "mp4", 137, "vTVuB1kgpd4")], VIDEO, 1080)


def test_original_audio_wins_over_auto_dubbed_aac():
    original = {**option("Opus Audio", "audio-only", "opus", "251.3dbe3eb8"), "value": "25"}
    dubbed = {**option("M4A Audio", "audio-only", "m4a", "140.5e1673f8"), "value": "13"}
    rows = [option("1080p MP4", "video-only", "mp4", 137), original, dubbed,
            {"value": "25", "data-track": "en-US|original"},
            {"value": "13", "data-track": "de-DE|dubbed-auto"}]
    audio = web.select_streams(rows, VIDEO, 1080)[1]
    assert audio["format_id"] == "251.3dbe3eb8"
    assert audio["track"] == "en-US|original"
    assert audio["ext"] == "webm"


@pytest.mark.parametrize("url", ["http://www.snapyt.app/", "https://www.snapyt.app.evil.test/",
                               "https://user:pass@www.snapyt.app/", "https://www.snapyt.app:8443/"])
def test_rejects_unexpected_download_destinations(url):
    with pytest.raises(ValueError):
        web.site_url(url)


def test_redirect_is_checked_before_following_it():
    with pytest.raises(ValueError, match="Unexpected"):
        web.ServiceRedirects().redirect_request(Request(web.SITE), None, 302, "redirect", {}, "http://127.0.0.1/")


def test_requires_audio_for_the_source_master():
    with pytest.raises(ValueError, match="both"):
        web.select_streams([option("1080p MP4", "video-only", "mp4", 137)], VIDEO, 1080)


@pytest.mark.parametrize("status,content_range,length", [
    (200, "bytes 10-19/100", "10"), (206, "bytes 0-9/100", "10"),
    (206, "bytes 10-19/200", "10"), (206, "bytes 10-19/100", "9"),
])
def test_rejects_whole_file_wrong_offset_wrong_total_and_truncated_range(status, content_range, length):
    with pytest.raises(ValueError, match="unverified"):
        web.check_range(status, {"Content-Range": content_range, "Content-Length": length}, 10, 19, 100)


def test_verified_range_is_accepted():
    web.check_range(206, {"Content-Range": "bytes 10-19/100", "Content-Length": "10"}, 10, 19, 100)


def test_streaming_uses_the_sites_relay_and_excludes_failed_routes():
    original = option("1080p MP4", "video-only", "mp4", 137)["data-force"]
    query = parse_qs(urlsplit(web.stream_url(original, ["1", "2"])).query)
    assert query["stream"] == ["1"]
    assert query["px"] == ["auto"]
    assert query["tried"] == ["1,2"]
    assert query["t"] == [VIDEO + ".public-form-token"]


def test_keeps_the_public_preview_server_as_a_fallback():
    rows = [option("1080p MP4", "video-only", "mp4", 137), option("M4A", "audio-only", "m4a", 140)]
    page = 'var BIG_MB = 0;\nvar VD_HOSTS = {"single":{"u":"https://s2.snapyt.app/wp-admin/admin-ajax.php","vt":"public-ticket"},"audio":null};\n'
    streams = web.route_streams(page, web.select_streams(rows, VIDEO, 1080))
    assert urlsplit(streams[0]["url"]).hostname == "www.snapyt.app"
    assert urlsplit(streams[0]["alternate_url"]).hostname == "s2.snapyt.app"
    assert parse_qs(urlsplit(streams[0]["alternate_url"]).query)["vt"] == ["public-ticket"]
    assert urlsplit(streams[1]["url"]).hostname == "www.snapyt.app"


def test_one_refused_source_does_not_skip_the_remaining_batch(monkeypatch, tmp_path, capsys):
    urls = [f"https://www.youtube.com/watch?v={video_id}" for video_id in [VIDEO, "vTVuB1kgpd4", "NiPCDDNEZa0"]]
    visited = []
    def acquire(url, *_args, **_kwargs):
        visited.append(url)
        if url == urls[1]:
            raise ValueError("Service refused this source")
    monkeypatch.setattr(web, "acquire", acquire)
    assert web.main([*urls, "--out", str(tmp_path), "--download-only"]) == 1
    assert visited == urls
    assert '"stage": "failed"' in capsys.readouterr().out
