# Support and verification

The code checks identity, expected byte ranges or response length, file signatures
and measured streams. MP4 export verifies the recorded SHA-256. Service responses
and availability can change independently of this source release.

## 0.2.0 secondary-source VM checks — 2026-10-18

Each row started from an empty data directory on a Linux datacenter VM, completed
acquisition and media finalization, decoded one second and exported with a
matching SHA-256. The five headline routes retain their separate 0.1.0 evidence;
this release does not claim another full set of headline-platform probes.

| Secondary source | Measured output | Audio | Fresh MP4 bytes |
| --- | --- | --- | --- |
| Bluesky | 1920 × 1080, 29.737 s | Yes | 6,688,967 |
| Pinterest | 1080 × 1920, 57.700 s | Yes | 18,403,924 |
| Twitch clip | 1920 × 1080, 32.099 s | Yes | 16,299,421 |
| Snapchat Spotlight | 480 × 880, 4.642 s | Yes | 583,697 |
| LinkedIn public post | 1428 × 720, 161.866 s | Yes | 5,663,647 |
| Mastodon, mastodon.social only | 1692 × 1484, 38.850 s | No: native gifv | 1,287,545 |

The [sanitized evidence](secondary-live-checks-v0.2.0.json) records canonical
source URLs, discovery queries/results, routes and hashes. Indexed search
returned individual post/clip/pin candidates for each source. A native sample
of `@Mastodon` also returned two video/gifv posts among its latest twelve media
posts. This is narrow evidence, not comprehensive availability. An indexed
Pinterest result was image-only and correctly failed acquisition without a
ready file; pin candidates are not prevalidated video search results.
Pinterest's discovery status is **partial**: acquisition passed for a known
native-video pin, but a useful native video was not established among the
measured indexed candidates. It is not in the fully verified discovery/download
list. Exact-pin queries also encountered a public-index failure.

Bluesky uses a public AppView record and PLC directory with a validated
Bluesky-hosted PDS blob. Custom PDS hosts, quoted/external video and HLS-only
delivery are excluded. Mastodon supports only local accounts/posts on the
selected mastodon.social instance and its approved media host, not arbitrary
federated hosts. The measured Mastodon format is silent gifv. Its public
timeline endpoint required authentication; bounded public account discovery
worked without it. Native Bluesky search was blocked; indexed discovery worked.

Pinterest, Twitch clips, Snapchat Spotlight and LinkedIn use platform-specific
yt-dlp metadata extraction, followed by our validated progressive HTTPS MP4
transfer. The VM had yt-dlp 2026.08.19 for these live checks. Metadata recognition
alone is not counted as a download. No new HLS/DASH transfer is enabled.

## Evaluated without a new verified download

| Platform | Discovery | Acquisition outcome | Resume condition |
| --- | --- | --- | --- |
| Reddit | Native-video post indexed | VM session/API access rejected (403/authentication), before inspecting formats | A working public VM route; split audio/manifest support still needs proof |
| Vimeo | Public video indexed | Extractor OAuth failed (401); anonymous config had no progressive MP4 | Working current public route or bounded streaming implementation |
| Dailymotion | Public video indexed | Old sample removed; replacement resolved to HLS only, without acquisition | Validate and bound manifests/segments, then verify completed audio/video |
| Bilibili | Public video indexed | Webpage request rejected (412) | Working datacenter route, followed by split-stream/region checks |
| Threads | Public post indexed | Page readable; selected native video not established | Bind actual media to the public post and complete bounded acquisition |

These are measured limits, not newly supported download choices. No generic
extractor or unrestricted federation fetch was enabled to inflate coverage.
VK, Douyin, Weibo, Rumble and public Telegram videos remain unevaluated for this
release. Broader primary-platform format coverage and fallback relay work also
remain outside these new measurements.

## Prior VM checks — 2026-10-15

These are historical observations from the maintained acquisition owner. Downloaded
media is not distributed with this repository. They are not all-post guarantees or
claims of a fresh network request by every release test.

| Platform | Measured output | Verification |
| --- | --- | --- |
| YouTube | 320 × 240, 19.06 s, AAC, 744,412 bytes | Saved-source reassembly; no fresh network request in the 15 October VM recheck |
| Instagram | 720 × 1280, 47.47 s, audio, 10,329,647 bytes | Download, measured streams and decoded sample |
| TikTok | 540 × 960, 27.47 s, audio, 2,748,534 bytes | Download, measured streams and decoded sample |
| X | 720 × 720, 30.33 s, audio, 3,407,167 bytes | Download, measured streams and decoded sample |
| Facebook | 1080 × 1080, 44.33 s, audio, 12,474,253 bytes | Download, measured streams and decoded sample |
| Reddit | No completed live download receipt | Extractor path only |

The earlier YouTube acquisition also produced complete 1080p sources through
SnapYT while a separate requested video failed across the evaluated routes.
Unavailable videos remain failures.

## Release checks

Release-specific check results are recorded in the GitHub release notes.
The offline suite and package-source manifest are included here for reproduction.
Use `social-fetch doctor` to check an installation before a live download.

## Boundaries

- Linux is required for the persistent worker's file locking and process checks.
- FFmpeg/ffprobe are separate system dependencies. MP4 output copies the supplied
  streams; codec support still depends on your player.
- YouTube/Instagram/TikTok routes use independent public relay services. No
  service-account credentials or user cookies are bundled. Source URLs are sent
  to those services. Direct datacenter access restrictions can still affect other
  platforms and any failed relay.
- Discovery is indexed search or a small account sample. It does not provide a
  complete platform feed, complete account archive or reliable visual scene labels.
- X/Facebook/Reddit extraction accepts progressive HTTPS MP4. A post that offers
  only separate DASH/HLS streams can fail, including Reddit videos with split audio.
- New secondary MP4 transfers enforce a 512 MiB bound, deadline, response length
  and file signature before finalization. Pinterest pin.it share links, boards,
  Twitch VODs/live streams, Snapchat private stories and LinkedIn Learning are
  excluded. Account URLs never cause bulk downloads.
- This package runs local CLI/worker processes. Its namespaces are organizational;
  it does not expose a network service or implement multi-user authentication.
