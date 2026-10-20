# social-fetch

**Find and download YouTube, Instagram, TikTok, X, Facebook and Reddit videos from a Linux VM.**

**Status: alpha.** The five headline routes and scoped Reddit flow have measured
VM download samples.
The [dated support record](docs/SUPPORT.md) separates each release's fresh checks
from historical samples. Coverage is limited to the measured post types and
delivery formats; external service availability is not guaranteed.

Find public posts and creator accounts, download a selected video, and export a
checked MP4. Use the JSON CLI from an agent or the small Python API from your app.

The maintained source also notices links in post/comment text and can save public
GitHub, Google Docs/Drive, documentation and file resources with readable text and
checksums. Search/account results expose `linked_resources`; `links`, `resource`
and the public Instagram `comments` sample support the
[linked-resource workflow](docs/RESOURCES.md). These features are included in
version 0.3.1; installations of earlier releases need an upgrade.

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

Reddit uses public embeds to bind the selected post to its native media, then
RapidSave to deliver video and audio together. Single images come from Reddit's
native image host. Comment bodies come from current public Reddit embeds;
Arctic Shift supplies only the comment IDs and permalinks used to discover them.

**yt-dlp is used for X and Facebook**, plus metadata
extraction for four explicitly selected secondary sources below. It is an
upstream dependency with attribution. Installing it with this package does not
make it the YouTube acquisition route.

The open-source contribution is our programmable relay adapters, public social
discovery, resumable YouTube transfers, media verification, stream-copy YouTube
assembly, persistent jobs, JSON CLI and Python API. The external relay servers are independently operated;
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
python -m pip install 'git+https://github.com/Karnaf0katom/social-fetch.git@v0.3.1'
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
timestamps do not trim the downloaded source. Selected video and audio are copied
into MP4 without re-encoding, up to an available 1080p rendition. Audio selection
prefers tracks labeled original and excludes tracks labeled dubbed. Some service
responses omit track labels; those downloads do not establish original-language
audio identity. Lower source quality is preserved rather than upscaled.

Account browsing returns a bounded sample and depends on the public viewer or
index. The latest Instagram sample returned three posts; the YouTube account
lookup was unavailable. Account lookup failure does not prevent downloading a
known public post. See [current limits](docs/SUPPORT.md#current-release-limits).

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

## Reddit posts, comments and images

```bash
social-fetch search 'mountain sunrise' --source reddit --count 3
social-fetch comments 'https://www.reddit.com/r/mercedes_benz/comments/1uwp60q/' --count 3
social-fetch download 'https://www.reddit.com/r/mercedes_benz/comments/1uwp60q/' --out reddit-video.mp4
social-fetch image 'https://www.reddit.com/r/itookapicture/comments/1x3kp6y/' --out reddit-image.jpg
```

Comment reading returns a partial sample: 1–20 comments, default 5. Archive ID
discovery can miss recent comments; each returned body is read from a current
public embed. The total remains unknown and replies are not fully expanded.
The same `comments` command retains Instagram's default 50 and maximum 100.

Images use the existing saved-job queue and checked export. The output extension
must match the measured format: JPEG (`.jpg`/`.jpeg`), PNG or WebP. Support is
limited to selected native single-image posts and native video. Galleries,
crossposts and external embeds are excluded. The verified image sample is JPEG;
PNG/WebP follow the checked path but have no live sample. Read-only access needs
no Reddit login; posting, voting and comment writing are not included.

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
`Client.comments(url, count=3)` selects the Reddit or Instagram reader from the
post URL. `Client.download_image(url, wait=True)` queues a native Reddit image;
export its ready job with `Client.export(job['id'], 'reference.jpg')`.
Failed jobs include a sanitized `failure_stage` and `error_code` when available;
new completed social jobs also report whether the measured file contains audio.
Completed social jobs include `route` and `route_attempts`, recording which
adapter supplied the file and which routes were unavailable. These contain stable
route names and exception types, never delivery URLs or provider response text.

## Acquisition fallbacks

An unavailable primary route automatically tries one platform-specific
alternative. Each attempt uses a separate directory; only a completed, bounded
MP4 can be promoted into the source receipt. A post-identity mismatch, forbidden
delivery host, invalid file signature or local disk error stops the job.

| Platform | Primary | Alternative |
| --- | --- | --- |
| YouTube | SnapYT, including assigned relay-server switching | An explicitly configured, operator-owned Cobalt instance |
| Instagram | SnapInsta.lc | Allowlisted Instagram extractor and bounded CDN transfer |
| TikTok | TikWM | SSSTik public form, selected numeric media ID and bounded CDN transfer |
| X | Public syndication through yt-dlp | FixupX selected embed and approved Twitter media CDN |
| Facebook | yt-dlp | Selected public page's progressive video metadata |
| Reddit | Selected public embed plus RapidSave merged MP4 | Selected native-video JSON; only explicitly silent sources |
| Bluesky | Public AppView plus PDS blob | Handle/PLC lookup and the original PDS record/blob |
| Pinterest | yt-dlp metadata | Public pin resource and native MP4 |
| Twitch clips | yt-dlp metadata | Public clip GraphQL and native MP4 |
| Snapchat Spotlight | yt-dlp metadata | Selected story's public page metadata |
| LinkedIn | yt-dlp metadata | Selected post's public video element |
| mastodon.social | Public status REST API | Public ActivityPub Note and native attachment |

These are scoped alternative routes, not an all-platform uptime guarantee.
Platform-native alternatives can share infrastructure with the primary route.
See [support](docs/SUPPORT.md) for the measured live outcomes and remaining blocks.
The integrated source includes the verified TikTok, X and Facebook adapters and
their selected-post/share regressions. LinkedIn's public-page alternative also
completed a fresh installed-worker download on 2026-10-19 after an earlier
unavailable response. See [support](docs/SUPPORT.md) for the exact live samples,
source hashes and remaining limits. Reddit's ordinary merged-media route is
verified separately; its native-JSON alternative remains restricted to explicitly
silent videos and has no fresh working VM sample. YouTube uses its existing
SnapYT relay switching; the optional independent connector remains unverified.

YouTube keeps its existing SnapYT route by default. To enable an independent
fallback, set `SOCIAL_FETCH_COBALT_URL` to the HTTPS origin of your own Cobalt
instance. No hosted instance, login or paid service is selected automatically.
The configured instance must return a same-origin MP4 tunnel whose filename
contains the requested video ID, with video and audio together. Direct
Googlevideo links, pickers and unrelated tunnel hosts are refused. This connector
has offline contract tests; an operator-owned instance was not available for a
fresh live YouTube download in this release.

## Platform scope

| Platform | Search | Acquisition route | Limits |
| --- | --- | --- | --- |
| YouTube / Shorts | Public index | SnapYT public web form | Available MP4 rendition up to 1080p with audio; unlabeled audio has unknown original-language identity |
| Instagram | Public index; bounded profile sample | SnapInsta.lc public web form | Single post/Reel samples verified; mixed carousels can fail identity checks |
| TikTok | Public index | TikWM; SSSTik alternative | Canonical, stale-author and native-bound `vt`/`vm`/`/t/` samples verified; no native feed/profile crawling |
| X | Public index | yt-dlp, public syndication | Progressive HTTPS MP4 only |
| Facebook | Public index | yt-dlp; selected public-page alternative | Watch, Reel, share/v and share/r samples verified; availability remains post dependent |
| Reddit | Public index; bounded current comments | Public embed plus RapidSave; native image host | Native video with audio and single-image posts; partial comment samples |

YouTube, Instagram, TikTok, X and Facebook passed fresh VM download checks for
the initial release. See [support and measured evidence](docs/SUPPORT.md) for dates, current
release checks and known limits. Recognition of a URL or a successful search
does not establish download availability.

## Secondary options

Select these explicitly with `search --source NAME` or `Client.search(source=NAME)`.
They are not added to the default `social` search fan-out. The following five
additions passed discovery and one fresh VM download/export check in the 0.2.0
checks on 18 October 2026; later route outcomes are recorded separately in
[support](docs/SUPPORT.md). Coverage remains narrow.

| Source | Discovery | Acquisition and scope |
| --- | --- | --- |
| `bluesky` | Indexed posts/profiles | Native MP4 via public AppView and Bluesky-hosted PDS; custom storage and quoted/external videos excluded |
| `twitch` | Indexed clips | Public progressive MP4 clips via yt-dlp metadata; VODs, channels and live streams excluded |
| `snapchat` | Indexed Spotlight | Public Spotlight MP4 via yt-dlp metadata; private stories and other formats excluded |
| `linkedin` | Indexed posts | Native public MP4 primary and public-page alternative verified on 2026-10-19; Learning and profiles excluded |
| `mastodon` | Indexed mastodon.social posts; bounded native account sample | Local public/unlisted native MP4 or gifv on mastodon.social only; the measured sample is silent gifv |

`pinterest` is also selectable. The 0.3.1 checks established **one native-video
discovery/download pair**: an installed search result completed a 33.879-second
MP4 with audio and checked export. The known 57.7-second video also passed a
separate installed failover check. Other indexed candidates failed; results are
not prevalidated videos. Use canonical pinterest.com pin links; pin.it share
links, boards and image-only pins are excluded.

```bash
social-fetch search 'Bluesky now has video' --source bluesky
social-fetch search 'EA Play 2016' --source twitch
social-fetch account 'https://mastodon.social/@Mastodon' --count 3
```

All new routes validate source identity, delivery hosts and redirects. New media
transfers are limited to 512 MiB and a five-minute transfer deadline with socket
timeouts; HLS/DASH-only posts are excluded. Native Mastodon account sampling
filters the latest twelve media posts, not a complete timeline or fediverse feed.
Indexed results are candidates: a Pinterest pin, LinkedIn post or other result
can contain an image or text rather than video. Acquisition verifies availability.

Vimeo, Dailymotion, Bilibili and Threads were evaluated but are not new download
options. See [measured results and resume conditions](docs/SUPPORT.md) and the
[sanitized fresh evidence](docs/secondary-live-checks-v0.2.0.json).

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
