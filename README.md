# social-fetch

**Download a public social video with one command per network.**

```bash
social-fetch youtube 'https://www.youtube.com/watch?v=jNQXAC9IVRw' -o clips
```

Also search public posts, manage saved jobs, or use `from social_fetch import Client`
from Python. The CLI prints JSON for humans and scripts.
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
disk space per active download**. Install the system dependencies on Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y git python3-venv ffmpeg pipx
```

Install the CLI in its own environment with pipx:

```bash
pipx install git+https://github.com/Karnaf0katom/social-fetch
pipx ensurepath
```

Open a new terminal if `social-fetch` is not yet on your PATH. Alternatively, use
pip in a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install git+https://github.com/Karnaf0katom/social-fetch
```

Check the installation and list the networks:

```bash
social-fetch --version
social-fetch doctor
social-fetch --help
```

These commands install from the public GitHub repository, not PyPI. Releases are
on [GitHub](https://github.com/Karnaf0katom/social-fetch/releases), with wheel/source
packages and checksums. `doctor` checks dependencies without testing platform
availability. Version 0.4.0's fresh-install download checks are recorded in
[SMOKE-RESULTS.md](docs/SMOKE-RESULTS.md).

## Download by network

Use one public **video post URL**, not an account or search URL. Each command waits
for the saved job, verifies its SHA-256 during export, and saves an MP4 in `-o`
(`--output`). The directory is created if needed; it defaults to the current
directory. Filenames are `NETWORK-POST_ID.mp4` (some networks use a hashed ID).
Existing files are preserved; choose another directory to export the same post
again. A URL must match the named network.

```bash
social-fetch youtube 'https://www.youtube.com/watch?v=jNQXAC9IVRw' -o clips
social-fetch tiktok 'https://www.tiktok.com/@patroxofficial/video/6742501081818877190' -o clips
social-fetch instagram 'https://www.instagram.com/reel/C_bnaTAO2Ll/' -o clips
social-fetch x 'https://x.com/buildingisgreen/status/1793226866335076588/video/2' -o clips
social-fetch facebook 'https://www.facebook.com/watch/?v=10155529876156509' -o clips
social-fetch reddit 'https://www.reddit.com/r/mercedes_benz/comments/1uwp60q/' -o clips
social-fetch bluesky 'https://bsky.app/profile/bsky.app/post/3l3vgf77uco2g' -o clips
social-fetch pinterest 'https://www.pinterest.com/pin/298856125290563650/' -o clips
social-fetch twitch 'https://clips.twitch.tv/FaintLightGullWholeWheat' -o clips
social-fetch snapchat 'https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPwAAYYWtidGhudGZpAX1TKn0JAX1TKnXJAAAAAA' -o clips
social-fetch linkedin 'https://www.linkedin.com/posts/the-mathworks_2_what-is-mathworks-cloud-center-activity-7151241570371948544-4Gu7/' -o clips
social-fetch mastodon 'https://mastodon.social/@mastodon/116839714185151652' -o clips
```

These public examples can become unavailable. Twitch accepts clips, Snapchat
accepts Spotlight posts, Pinterest requires video pins, and Mastodon is limited
to mastodon.social. Reddit's network command downloads video; use the existing
`image URL --out image.jpg` command for native single images. See the platform
limits below and `social-fetch NETWORK --help` for options.

Commands return nonzero on failure or timeout. `--timeout 900` is the default wait
limit in seconds; timed-out jobs keep running. The JSON includes the job ID for
`status` and `export`. Network commands also accept `--namespace` and `--save`.

Video and audio are copied into MP4 without re-encoding, up to an available 1080p
rendition. Lower source quality is preserved. Audio selection prefers tracks
labeled original and rejects labeled dubbed tracks; an empty label leaves
original-language identity unknown. URL timestamps do not trim the source.

## Existing commands

All previous subcommands and options remain available:

```bash
social-fetch search 'space launch' --source youtube --count 3
social-fetch search 'NASA' --source instagram --accounts --count 3
social-fetch download 'https://www.youtube.com/watch?v=jNQXAC9IVRw' --out clip.mp4
```

`download URL` queues a job and returns immediately. `download --wait` waits;
`download --out clip.mp4` waits and exports to an explicit filename. Search returns
indexed candidates; a result can be unavailable or contain no video. No account
is downloaded in bulk.

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
