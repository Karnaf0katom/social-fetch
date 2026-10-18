# social-fetch

**Find and download YouTube, Instagram, TikTok, X and Facebook videos from a Linux VM.**

**Status: alpha.** Five platform routes have passed fresh VM download checks.
Coverage is limited to the post types and delivery formats described below;
external service availability is not guaranteed.

Find public posts and creator accounts, download a selected video, and export a
checked MP4. Use the JSON CLI from an agent or the small Python API from your app.

Direct YouTube and Instagram downloads often fail from datacenter IPs.
social-fetch uses public downloader services for YouTube, Instagram and TikTok;
those services acquire the video and relay it to your VM. These routes need no
personal login, browser cookies, residential proxy subscription or paid API key.
The services receive the public source URL and remain external dependencies.
Access can fail for an individual post or an entire service.

## How the datacenter workaround works

The YouTube route calls our Python HTTP adapter for **SnapYT**. It submits the
public source URL to that service and downloads through its media relay:

```text
Your VM → social-fetch adapter → SnapYT → YouTube
Your VM ← checked video/audio transfers ← SnapYT relay
```

This route does **not** invoke yt-dlp on your VM. SnapYT acquires the source;
your VM receives the relayed media, avoiding the need for YouTube to accept a
direct media-download request from the VM.

Instagram uses our **SnapInsta.lc** adapter, and TikTok uses our **TikWM** adapter.
Those services resolve public posts to media delivered by their service or an
approved CDN. Their own internal download implementations are outside this
project.

**yt-dlp is used for X, Facebook and the unverified Reddit path.** It is an
upstream dependency with attribution. Installing it with this package does not
make it the YouTube acquisition route.

The open-source contribution is our programmable relay adapters, public social
discovery, resumable YouTube transfers, media verification, YouTube assembly with
original audio, persistent jobs, JSON CLI and Python API. The external relay servers are independently operated;
their infrastructure is not included in this repository. This is a working
acquisition route through those services, with the scope and evidence below.

## Install

Requires **Linux, Python 3.10+, FFmpeg/ffprobe, outbound HTTPS and free disk space**.
On Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv ffmpeg
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'git+https://github.com/Karnaf0katom/social-fetch.git@v0.1.1'
social-fetch doctor
```

You can also clone this repository and run `python -m pip install .`.
The package is released on GitHub; the install command above does not use PyPI.
`doctor` checks installed dependencies, without contacting a platform or service.

## Search and download

```bash
# Public indexed posts and profiles. Titles/metadata come from real results.
social-fetch search 'space launch' --source youtube --count 5
social-fetch search 'NASA' --source instagram --accounts
social-fetch account 'https://www.instagram.com/nasacreates/' --count 3

# Replace the URL with a public video you want to acquire.
social-fetch download 'https://www.youtube.com/watch?v=jNQXAC9IVRw' --out clip.mp4
```

`--out` waits for completion, verifies the saved file against its SHA-256 receipt,
and exports it to a new filename. Existing files are never overwritten.
YouTube watch links, Shorts and share links use the same video identity;
timestamps do not trim the downloaded source. Video and original, non-dubbed
audio are copied into MP4 without re-encoding, up to the available 1080p rendition.
Lower source quality is preserved rather than upscaled.

For a long-running acquisition, keep the returned job ID:

```bash
social-fetch download 'https://www.instagram.com/p/DeWYHFHIkVC/' --namespace research
social-fetch status JOB_ID --namespace research
social-fetch export JOB_ID --namespace research --out reference.mp4
```

Downloads run in detached workers and persist across CLI exits. `download --wait`
observes a job without exporting. `--timeout 900` limits the wait; a timeout returns
the job ID and a nonzero exit code while acquisition continues. Status also exits
nonzero for a failed job. Failed downloads can be explicitly retried with the
same URL. Complete, receipt-matching sources are reused where available.
The queue admits at most two active downloads, with a conservative 9 GiB free-disk
requirement per active worker. It never downloads an account in bulk.

All commands print JSON to stdout. Jobs and downloaded media default to
`~/.local/share/social-fetch`. Set `SOCIAL_FETCH_DATA_DIR`, respect `XDG_DATA_HOME`,
or place the global option before the command:

```bash
social-fetch --data-dir ./downloads download PUBLIC_POST_URL --namespace research
social-fetch --data-dir ./downloads status JOB_ID --namespace research
```

Use the same data directory and namespace to reconnect. Namespaces group jobs on
one local machine; they are not an authentication boundary for other OS users.
Manage disk retention yourself; saved media is not deleted automatically.

## Python API

```python
from social_fetch import Client

client = Client(data_dir="downloads", namespace="research")
matches = client.search("space launch", source="youtube", count=5)

job = client.download("https://www.youtube.com/watch?v=jNQXAC9IVRw", wait=True)
if job["status"] == "ready":
    result = client.export(job["id"], "clip.mp4")
else:
    print(job["message"])
```

`Client.search(..., accounts=True)` finds indexed profiles. `Client.account(url)`
reads a bounded sample of posts. `Client.status(id)` reads a saved job and
`Client.wait(id, timeout=900)` waits for it. API wait timeouts raise `TimeoutError`;
download failures return the saved failed job. `Client.export` accepts ready jobs
and checks both byte length and SHA-256 while copying.

## Platform scope

| Platform | Search | Acquisition route | Limits |
| --- | --- | --- | --- |
| YouTube / Shorts | Public index | SnapYT public web form | MP4 video + original audio, available quality up to 1080p |
| Instagram | Public index; bounded profile sample | SnapInsta.lc public web form | Public posts/Reels; first video of a carousel |
| TikTok | Public index | TikWM single-post API | Public video; no native feed/profile crawling |
| X | Public index | yt-dlp, public syndication | Progressive HTTPS MP4 only |
| Facebook | Public index | yt-dlp | Public progressive HTTPS MP4 only |
| Reddit | Public index | yt-dlp | Extractor path present; live download not verified for this release |

YouTube, Instagram, TikTok, X and Facebook passed fresh VM download checks for
the initial release. See [support and measured evidence](docs/SUPPORT.md) for dates, current
release checks and known limits. Recognition of a URL or a successful search
does not establish download availability.

Search uses public web/video indexes through DDGS. Coverage and freshness vary;
empty results and rate limits are surfaced. Optional existing Brave/Serper keys
can select those providers through `FOOTAGE_SEARCH_PROVIDER=brave|serper` and
`BRAVE_SEARCH_API_KEY` / `SERPER_API_KEY`. The default requires neither.
Search results retain source URLs and supplied creator information. A public
post does not by itself establish permission to reuse its media.

## How it fits

social-fetch is the reusable acquisition capability. A separate visual Footage
tool is planned to use it for previewing, inspecting video contents and searching
more sources. This release is usable independently through the CLI and Python.

## Development

```bash
python -m pip install '.[test]'
python scripts/check_release.py
python -m pytest -q
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the edit/test workflow and how to refresh
the explicit source manifest after reviewing a change. CI checks both the source
tree and the contents of the built source archive.

The offline tests cover URL/identity checks, transfer completeness, original-audio
selection, queue admission, namespaces, interrupted workers and checked export.
They do not call public download services. Changes to services can break a route
independently of those tests; report the platform and canonical public source URL
without including cookies, temporary delivery URLs or local worker logs.

MIT. External projects and services retain their own terms; see
[third-party dependencies](docs/THIRD_PARTY.md).
