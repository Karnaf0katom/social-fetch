# social-fetch

**Find public social posts, download a selected video, and export a verified file from a Linux VM.**

Use a JSON CLI from your agent or `from social_fetch import Client` from Python.
YouTube, Instagram, TikTok, X, Facebook and scoped Reddit media have measured VM
downloads. **Status: alpha.** Supported post types and service availability have
[documented limits](docs/SUPPORT.md#current-release-limits).

YouTube, Instagram and TikTok use adapters to independently operated public
relay services. Those routes need no personal login, browser cookies or paid API
key. The relay servers are external dependencies; their server code is outside
this MIT client repository. X/Facebook use attributed yt-dlp routes.

**YouTube's independent fallback requires a full, separately deployed Cobalt
server.** See [YouTube fallback setup](#youtube-fallback-setup) before relying on it.

## Install

Requires **Linux, Python 3.10+, Git, FFmpeg/ffprobe, outbound HTTPS and 9 GiB free
disk space per active download**. On Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y git python3-venv ffmpeg
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'git+https://github.com/Karnaf0katom/social-fetch.git@v0.3.2'
social-fetch doctor
```

Releases are on [GitHub](https://github.com/Karnaf0katom/social-fetch/releases),
with wheel/source packages and checksums. This command does not use PyPI.
`doctor` checks installed dependencies; it does not test platform availability.

## Try it

```bash
social-fetch search 'space launch' --source youtube --count 3
social-fetch search 'NASA' --source instagram --accounts --count 3
social-fetch download 'https://www.youtube.com/watch?v=jNQXAC9IVRw' --out clip.mp4
```

All commands print JSON. `download --out` waits for the saved job, verifies its
SHA-256 while exporting, and refuses to overwrite an existing file. Search
returns indexed candidates; a result can be unavailable or contain no video.
No account is downloaded in bulk.

Video and audio are copied into MP4 without re-encoding, up to an available 1080p
rendition. Lower source quality is preserved. Audio selection prefers tracks
labeled original and rejects labeled dubbed tracks; an empty label leaves
original-language identity unknown. URL timestamps do not trim the source.

## Python API

```python
from social_fetch import Client

client = Client(data_dir="downloads", namespace="research")
matches = client.search("space launch", source="youtube", count=3)
job = client.download("https://www.youtube.com/watch?v=jNQXAC9IVRw", wait=True)
if job["status"] == "ready":
    result = client.export(job["id"], "clip.mp4")
else:
    print(job["message"])
```

`Client.account(url, count=3)` reads a bounded account sample.
`Client.comments(url, count=3)` reads partial Instagram or Reddit comments.
`Client.download_image(url, wait=True)` queues a native Reddit single image.
`Client.resource(url)` saves a linked public resource and readable text when
available. See [linked-resource usage](docs/RESOURCES.md).

## Persistent jobs

Downloads run in detached workers. Save the returned job ID to reconnect:

```bash
social-fetch --data-dir ./downloads download PUBLIC_POST_URL --namespace research
social-fetch --data-dir ./downloads status JOB_ID --namespace research
social-fetch --data-dir ./downloads export JOB_ID --namespace research --out reference.mp4
```

The global `--data-dir` option comes before the command. Data defaults to
`~/.local/share/social-fetch`; `SOCIAL_FETCH_DATA_DIR` or `XDG_DATA_HOME` can change
that location. Reuse both the data directory and namespace to reconnect.
Namespaces group local jobs; they do not authenticate separate OS users.

The queue permits two active downloads. `download --wait --timeout 900` waits
without exporting; a timeout returns the job ID and a nonzero exit code while
the download continues. Reconnect with `status`. Failed jobs can be explicitly
retried by submitting the same URL. Ready jobs are reused after receipt checks.
`Client.wait(id, timeout=900)` raises `TimeoutError` when its observation expires.
Saved media remains until you delete it; manage retention and disk space yourself.

## Platforms and limits

| Source | Measured scope |
| --- | --- |
| `youtube` | Watch, Shorts and share URLs; SnapYT media relay and assigned-server switching. Independent fallback requires a separately deployed Cobalt server; unverified live. |
| `instagram` | Single posts/Reels and bounded account samples through SnapInsta.lc. Mixed carousels remain unverified. |
| `tiktok` | TikWM and SSSTik; canonical and selected `vt`/`vm`/`/t/` share samples. |
| `x` | Public progressive MP4 through yt-dlp or FixupX; selected attachment ordering is preserved. |
| `facebook` | Public Watch, Reel and share samples through yt-dlp or selected page metadata. |
| `reddit` | Native video with audio, native single images and partial current comment samples. |

Additional explicit sources are `bluesky`, `pinterest`, `twitch`, `snapchat`,
`linkedin` and `mastodon`. These are excluded from the default `social` search
fan-out. Their native-media/format limits are in
[the dated support matrix](docs/SUPPORT.md). Mastodon is restricted to
mastodon.social; its measured sample is silent gifv. Twitch supports clips.
Pinterest requires a canonical video pin, rather than a board or pin.it link.
HLS/DASH-only posts are excluded from these progressive-MP4 routes.

Account samples are incomplete and provider dependent. Instagram returned three
posts in the latest launch check; YouTube account browsing was unavailable.
Reddit comments return at most 20 (default 5); Instagram returns at most 100
(default 50). Full comment trees, Reddit galleries, crossposts and external embeds
are excluded. JPEG has a live image sample; PNG/WebP paths have offline checks.
Image export filenames must match the measured format.

```bash
social-fetch account 'https://www.instagram.com/nasacreates/' --count 3
social-fetch comments PUBLIC_REDDIT_OR_INSTAGRAM_POST --count 3
social-fetch image PUBLIC_REDDIT_IMAGE_POST --out reference.jpg
social-fetch links --text 'Resources: https://github.com/Karnaf0katom/social-fetch'
social-fetch resource 'https://github.com/Karnaf0katom/social-fetch/blob/main/README.md'
```

Search uses DDGS public indexes by default. Existing Brave/Serper credentials can
select those providers through `FOOTAGE_SEARCH_PROVIDER=brave|serper` and
`BRAVE_SEARCH_API_KEY` / `SERPER_API_KEY`. The default needs neither.
Sources retain their URLs and attribution; public availability does not itself
grant permission to reuse downloaded media.

## YouTube fallback setup

SnapYT is the default YouTube route. Its assigned-server switching stays within
SnapYT; the independent fallback requires you to deploy and maintain a complete
**Cobalt API server**. Installing social-fetch does not install or start that
server, and no hosted Cobalt instance is supplied or selected automatically.

1. Deploy the backend using [Cobalt's server setup guide](https://github.com/imputnet/cobalt/blob/main/docs/run-an-instance.md), which includes Docker Compose instructions.
2. Serve its API and proxied MP4 downloads from the same HTTPS origin on port 443.
3. Set `SOCIAL_FETCH_COBALT_URL` to your server's HTTPS origin, for example
   `https://cobalt.example.com`, with no path or query string.

The connector requests a proxied MP4 tunnel and rejects direct Googlevideo links
or downloads/redirects to another origin. It has offline checks only and remains
**unverified live**. If SnapYT is unavailable and no compatible Cobalt server is
configured, there is no independent YouTube fallback ready to use.

## Troubleshooting

| Result | What to do |
| --- | --- |
| `doctor` reports missing dependencies | Install the listed Python/system dependency, then run it again. |
| No search matches or account sample unavailable | Try a concrete phrase, exact handle or known public post URL. |
| A download fails | Read its sanitized `failure_stage`/`error_code` and the supported post types. External services or the post may be unavailable. |
| Wait timed out | Observe the existing job with the same data directory and namespace. |
| Export destination exists | Choose a new filename. Existing files are preserved. |
| Insufficient disk space | Free space in the data directory's filesystem before explicitly retrying. |

## Contributing and support

Start with [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests and source-manifest
updates. The [changelog](CHANGELOG.md) records releases;
[SUPPORT.md](docs/SUPPORT.md) separates offline checks, dated live samples and
remaining limits. [Report a bug](https://github.com/Karnaf0katom/social-fetch/issues/new/choose)
with your version, command and sanitized output; keep cookies, delivery tokens
and unreviewed worker logs out of the report.

MIT. See [third-party dependencies and relay services](docs/THIRD_PARTY.md) for
upstream attribution and the boundary between this client and external servers.
