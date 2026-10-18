"""Acquire public YouTube files through SnapYT's public paste-link form.

No login, browser profile, installer, extension, or paid API is used. Download
URLs stay in memory; receipts contain source identity and measured media only.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SITE = "https://www.snapyt.app"
AJAX = SITE + "/wp-admin/admin-ajax.php"


def youtube_url(value):
    """Normalize watch, Shorts and share links without fetching user-supplied URLs.

    Time offsets select a review priority, not a download cut: acquire the source
    master and retain editorial offsets in the production brief.
    """
    value = value.strip()
    if re.search(r"[\x00-\x20\x7f\\]", value):
        raise ValueError("Invalid YouTube URL")
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if (parts.scheme not in {"https", "http"} or parts.username or parts.password
            or parts.port not in (None, 80, 443)):
        raise ValueError("Use a public YouTube watch, Shorts or share URL")
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parts.path == "/watch":
            ids = parse_qs(parts.query).get("v", [])
            video_id = ids[0] if len(ids) == 1 else ""
        else:
            match = re.fullmatch(r"/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})/?", parts.path)
            video_id = match[1] if match else ""
    elif host == "youtu.be":
        video_id = parts.path.removeprefix("/").removesuffix("/")
    else:
        video_id = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Use a public YouTube watch, Shorts or share URL")
    return f"https://www.youtube.com/watch?v={video_id}"


def site_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not re.fullmatch(r"(?:www|s[1-9][0-9]?)\.snapyt\.app", parsed.hostname or "")
            or parsed.port not in (None, 443) or parsed.username or parsed.password):
        raise ValueError("Unexpected download-service URL")
    return url


class ServiceRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        site_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request(url, data=None, **headers):
    site_url(url)
    body = urlencode(data).encode() if data is not None else None
    response = build_opener(ServiceRedirects()).open(Request(url, data=body, headers={
        "User-Agent": "Mozilla/5.0", "Referer": SITE + "/",
        **({"Content-Type": "application/x-www-form-urlencoded"} if body else {}), **headers,
    }), timeout=60)
    try:
        site_url(response.url)
    except BaseException:
        response.close()
        raise
    return response


def text_request(url, data=None):
    with request(url, data) as response:
        body = response.read(2 * 1024 * 1024 + 1)
    if len(body) > 2 * 1024 * 1024:
        raise ValueError("Unexpectedly large service page")
    return body.decode("utf-8")


class Options(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []

    def handle_starttag(self, tag, attrs):
        row = dict(attrs)
        if tag == "option" and ("data-force" in row or "data-track" in row):
            self.rows.append(row)


def select_streams(rows, video_id, height):
    available = []
    tracks = {r["value"]: r.get("data-track", "") for r in rows if "data-track" in r}
    for row in rows:
        if "data-force" not in row:
            continue
        force = site_url(row["data-force"])
        query = parse_qs(urlsplit(force).query)
        if (query.get("action") != ["snapyt_force_download"]
                or not query.get("t", [""])[0].startswith(video_id + ".")):
            raise ValueError("Download option does not match the requested video")
        size = int(row.get("data-bytes") or 0)
        format_id = query.get("tg", [""])[0]
        if not re.fullmatch(r"\d+(?:\.[a-f0-9]{8})?", format_id) or not 1024 <= size <= 2 * 1024**3:
            continue
        match = re.search(r"(\d+)p", row.get("data-label", ""))
        available.append({"url": force, "format_id": format_id, "bytes": size,
                          "height": int(match[1]) if match else 0,
                          "kind": row.get("data-kind"), "ext": row.get("data-ext"),
                          "track": tracks.get(row.get("value"), "")})
    videos = [r for r in available if r["kind"] == "video-only" and r["ext"] == "mp4"
              and 0 < r["height"] <= height]
    audios = [r for r in available if r["kind"] == "audio-only" and r["ext"] in {"m4a", "opus"}
              and "dubbed" not in r["track"]]
    if not videos or not audios:
        raise ValueError("Service did not provide both an MP4 video and non-dubbed audio")
    audio = max(audios, key=lambda r: ("original" in r["track"], r["ext"] == "m4a", r["bytes"]))
    if audio["ext"] == "opus":
        audio = {**audio, "ext": "webm"}
    return [max(videos, key=lambda r: (r["height"], r["bytes"])), audio]


def route_streams(page, streams):
    """Keep the page's assigned server as a fallback to its main download link."""
    hosts_match = re.search(r"var VD_HOSTS\s*=\s*(\{[^\n]+\});", page)
    if not hosts_match:
        return streams
    hosts = json.loads(hosts_match[1])
    saved_match = re.search(r"var VD_MAIN_SAVED\s*=\s*(\{[^\n]+\});", page)
    saved = json.loads(saved_match[1]) if saved_match else {}
    cap_match = re.search(r"var BIG_MB\s*=\s*(\d+)", page)
    cap = int(cap_match[1]) * 1048576 if cap_match and int(cap_match[1]) else 1500000000
    routed = []
    for stream in streams:
        kind = "audio" if stream["kind"] == "audio-only" else "big_file" if stream["bytes"] > cap else "single"
        host = hosts.get(kind)
        parts = urlsplit(stream["url"])
        query = parse_qs(parts.query)
        fmt = int(query.get("fmt", ["-1"])[0])
        keep_main = kind not in saved.get("z", []) and fmt in saved.get("f", [])
        if host and not keep_main:
            target = urlsplit(site_url(host["u"]))
            query["vt"] = [host["vt"]]
            url = urlunsplit(parts._replace(netloc=target.netloc, path=target.path,
                                           query=urlencode(query, doseq=True)))
            stream = {**stream, "alternate_url": url}
        routed.append(stream)
    return routed


def check_range(status, headers, start, end, total):
    expected = f"bytes {start}-{end}/{total}"
    if (status != 206 or headers.get("Content-Range") != expected
            or int(headers.get("Content-Length", -1)) != end - start + 1):
        raise ValueError("Service returned an unverified media range")


def stream_url(url, tried=()):
    parts = urlsplit(site_url(url))
    query = parse_qs(parts.query)
    # These are the public page's buildAttemptUrl parameters. Streaming keeps
    # the service on its own relay instead of redirecting to an IP-bound URL.
    query.update(stream=["1"], busy_ok=["1"], px=["auto"])
    if tried:
        query["tried"] = [",".join(tried)]
    return urlunsplit(parts._replace(query=urlencode(query, doseq=True)))


def media_range(url, start, end):
    tried = []
    for attempt in range(3):
        try:
            return request(stream_url(url, tried), Range=f"bytes={start}-{end}")
        except HTTPError as error:
            route = error.headers.get("X-VD-Route", "")
            error.close()
            if error.code not in {502, 503, 504} or not route.isdigit() or route in tried or attempt == 2:
                raise
            tried.append(route)
            print(json.dumps({"stage": "service_route_retry", "tried_route": route,
                              "http_status": error.code}), flush=True)


def download_stream(stream, path):
    total = stream["bytes"]
    if path.exists():
        if path.stat().st_size != total:
            raise ValueError("Existing completed stream has the wrong size")
        return
    partial = path.with_suffix(path.suffix + ".part")
    last_progress = 0
    while (partial.stat().st_size if partial.exists() else 0) < total:
        start = partial.stat().st_size if partial.exists() else 0
        end = min(start + 32 * 1024**2 - 1, total - 1)
        try:
            response = media_range(stream["url"], start, end)
        except HTTPError as error:
            alternate = stream.pop("alternate_url", None)
            if not alternate or error.code not in {403, 502, 503, 504}:
                raise
            stream["url"] = alternate
            print(json.dumps({"stage": "assigned_service_server", "file": path.name}), flush=True)
            response = media_range(stream["url"], start, end)
        with response:
            check_range(response.status, response.headers, start, end, total)
            remaining = end - start + 1
            with partial.open("ab") as output:
                while remaining:
                    chunk = response.read(min(1024**2, remaining))
                    if not chunk:
                        raise ValueError("Media transfer ended before the promised bytes")
                    if start == 0 and output.tell() == 0:
                        valid = (chunk[4:8] == b"ftyp" if stream["ext"] in {"mp4", "m4a"}
                                 else chunk[:4] in {b"\x1aE\xdf\xa3", b"OggS"})
                        if not valid:
                            raise ValueError("Download is not the requested media container")
                    output.write(chunk)
                    remaining -= len(chunk)
                    if time.monotonic() - last_progress >= 20:
                        last_progress = time.monotonic()
                        print(json.dumps({"stage": "downloading", "file": path.name,
                                          "bytes": output.tell(), "total_bytes": total}), flush=True)
    if partial.stat().st_size != total:
        raise ValueError("Completed transfer has the wrong size")
    partial.replace(path)


def acquire(url, out, height, *, download_only=False, finalize_only=False):
    supplied_url = url
    url = youtube_url(url)
    video_id = parse_qs(urlsplit(url).query)["v"][0]
    if finalize_only:
        saved = json.loads((out / f"{video_id}.streams.json").read_text())
        if saved["id"] != video_id or saved["source_url"] != url:
            raise ValueError("Saved stream manifest does not match this source")
        return finalize(url, video_id, out, saved["streams"])
    nonce_response = json.loads(text_request(AJAX, {"action": "vd_fresh_nonce"}))
    nonce = nonce_response.get("data", {}).get("nonce")
    if not nonce_response.get("success") or not nonce:
        raise ValueError("Could not initialize the public download form")
    lookup = json.loads(text_request(AJAX, {
        "action": "process_video_url", "video_url": url, "security": nonce,
    }))
    redirect = lookup.get("data", {}).get("redirect") if isinstance(lookup.get("data"), dict) else None
    if not lookup.get("success") or not redirect:
        raise ValueError("Download service did not return a preview for this video")
    options = Options()
    page = text_request(site_url(redirect))
    options.feed(page)
    streams = route_streams(page, select_streams(options.rows, video_id, height))
    out.mkdir(parents=True, exist_ok=True)
    for stream in streams:
        path = out / f"{video_id}.f{stream['format_id']}.{stream['ext']}"
        download_stream(stream, path)
    saved = {"id": video_id, "source_url": url, "supplied_url": supplied_url,
             "streams": [{k: s[k] for k in ("format_id", "bytes", "ext", "height", "track")} for s in streams]}
    (out / f"{video_id}.streams.json").write_text(json.dumps(saved, indent=2) + "\n")
    if download_only:
        print(json.dumps({"stage": "streams_saved", **saved}), flush=True)
        return saved
    return finalize(url, video_id, out, saved["streams"])


def finalize(url, video_id, out, streams):
    if len(streams) != 2 or streams[0]["ext"] != "mp4" or streams[1]["ext"] not in {"m4a", "webm"}:
        raise ValueError("Expected one original video and one audio stream")
    paths = []
    for stream in streams:
        if not re.fullmatch(r"\d+(?:\.[a-f0-9]{8})?", stream["format_id"]):
            raise ValueError("Invalid saved stream identity")
        path = out / f"{video_id}.f{stream['format_id']}.{stream['ext']}"
        if path.stat().st_size != stream["bytes"]:
            raise ValueError("Saved source stream is incomplete")
        paths.append(path)
    final = out / f"{video_id}.mp4"
    pending = out / f"{video_id}.merging.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(paths[0]),
                    "-i", str(paths[1]), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
                    "-movflags", "+faststart", str(pending)], check=True, timeout=300)
    probe = json.loads(subprocess.run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(pending),
    ], check=True, capture_output=True, text=True, timeout=30).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    if not any(s["codec_type"] == "audio" for s in probe["streams"]):
        raise ValueError("Merged video has no audio")
    pending.replace(final)
    digest = hashlib.sha256()
    with final.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    receipt = {"id": video_id, "source_url": url, "method": "snapyt_public_form",
               "service": SITE, "browser_used": False, "account_cookies_used": False,
               "downloaded": True, "path": str(final.resolve()), "bytes": final.stat().st_size,
               "sha256": digest.hexdigest(),
               "width": video["width"], "height": video["height"],
               "fps": float(Fraction(video["avg_frame_rate"])),
               "duration": float(probe["format"]["duration"]),
               "video_codec": video["codec_name"],
               "audio_codec": next(s["codec_name"] for s in probe["streams"] if s["codec_type"] == "audio"),
               "streams_reencoded": False,
               "transfers": [{k: s[k] for k in ("format_id", "bytes", "ext", "track")} for s in streams]}
    (out / f"{video_id}.receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+", help="YouTube watch, Shorts or youtu.be links")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--height", type=int, default=1080)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--download-only", action="store_true", help="Network/file IO only; defer merge and checks")
    mode.add_argument("--finalize-only", action="store_true", help="Merge saved streams without network access")
    args = parser.parse_args(argv)
    if not 144 <= args.height <= 2160:
        parser.error("Height must be 144..2160")
    failures = 0
    for url in args.urls:
        try:
            acquire(url, args.out, args.height, download_only=args.download_only, finalize_only=args.finalize_only)
        except Exception as error:
            failures += 1
            print(json.dumps({"stage": "failed", "source_url": url, "error": str(error)}), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
