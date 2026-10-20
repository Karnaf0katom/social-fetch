# Support and verification

The code checks identity, expected byte ranges or response length, file signatures
and measured streams. MP4 export verifies the recorded SHA-256. Service responses
and availability can change independently of this source release.

## Current release limits

Version 0.3.1 is an alpha CLI and Python library. The dated checks below record
specific public samples; they do not promise universal platform availability.

- Instagram mixed carousels remain unsupported when the service does not bind
  child media to the requested parent post. Identity checks remain enforced.
- Account browsing is a bounded, provider-dependent sample. Instagram returned
  three posts on 2026-10-20; the YouTube account lookup remained unavailable.
- YouTube audio selection prefers explicitly original tracks and rejects labeled
  dubbed tracks. An empty track label leaves original-language identity unknown.
- The measured mastodon.social sample is silent gifv; video with audio has no
  completed live sample. Other Mastodon instances are outside this release.
- Reddit's normal video-with-audio route is verified. Its legacy native-JSON
  alternative has no working anonymous VM sample. Galleries, crossposts, external
  embeds and complete comment trees are outside the documented Reddit scope.
- The YouTube independent Cobalt connector needs an operator-owned instance and
  remains unverified live. SnapYT relay switching uses the same external service.

The independently operated relay servers are not included in this repository.
The visual Footage interface, additional platforms and PyPI distribution are
separate from this GitHub alpha release.

## Final launch checks — 2026-10-20

The [launch evidence](launch-live-checks-v0.3.1.json) records fresh ordinary
installed-worker downloads in empty data directories. The runtime hashes match
the combined source used for the earlier 22-download integration run.

| Flow | Fresh result |
| --- | --- |
| YouTube landscape HD | 2048 x 872, 888.094 seconds, AV1 video and AAC audio; 188,680,228 finalized bytes, one-second decode and checked export. The service's selected video option was labeled 1080p; these are the measured output dimensions. |
| Instagram post | 720 x 1280, 47.467 seconds, H.264/AAC; 10,329,647 finalized bytes, one-second decode and checked export. |
| Indexed discovery | Three YouTube posts and one Instagram account; results are candidates rather than prevalidated media. |
| Instagram account sample | Three public posts; a sample rather than a complete account inventory. |
| Linked resource | The project's public GitHub README saved with readable text and a matching integrity receipt. |

Both media samples passed namespace isolation, ready-job deduplication,
no-overwrite export, source/receipt hash checks and partial-file cleanup.
The YouTube audio label was empty, leaving original-language identity unknown.
The YouTube account lookup and a Mastodon public-timeline lookup were unavailable.
The mixed Instagram carousel lookup returned no media and establishes no new
carousel support. These metadata failures are preserved alongside successes.

## Integrated fallback checks — 2026-10-19

The [combined-source evidence](integrated-fallback-checks-2026-10-19.json) records
22 successful fresh installed-worker downloads. Eighteen forced-primary cases
completed through ten platform alternatives; three acquisitions used ordinary
primaries. The remaining case injected an initial SnapYT relay HTTP 403 and
completed through the public page's assigned relay. Cobalt was outside this run.

| Alternative | Fresh passing cases |
| --- | --- |
| TikTok SSSTik | Five: canonical, stale author, `vt`, `vm` and native-bound `/t/` |
| X FixupX selected embed | Two: canonical and `/video/2` after a photo |
| Facebook selected public playback | Four: Watch, Reel, share/v and share/r |
| LinkedIn public page | One with native MP4 and audio; the earlier unavailable response remains historical |
| Instagram, Bluesky, Pinterest, Twitch, Snapchat, mastodon.social | One per alternative; Mastodon remains native silent gifv |

Every successful download passed expected audio, one-second decode, checked
export and receipt SHA-256, namespace isolation, ready-job deduplication,
no-overwrite and partial cleanup. Native post observations matched every selected
TikTok/Facebook ID; X transfers matched independently confirmed attachment IDs.
Only primary availability or the initial YouTube relay failure was injected;
alternative responses and media bytes were real.

The combined source passed 479 maintained checks and the clean installation
passed 482 package checks. All 16 installed Python source hashes matched the
export. Identity, forbidden-host and ENOSPC injections stopped before fallback;
same-size corrupt media failed checked export without leaving an output.

The Reddit merged-video primary completed with required audio. Its legacy
native-JSON alternative has no working anonymous VM sample and does not silently
discard separate audio. SnapYT relay switching shares a provider; it does not
establish an independent-provider YouTube fallback. Private/expired posts,
unmeasured formats and universal availability remain outside these sample claims.

## Integrated Reddit checks — 2026-10-19

The [Reddit evidence](reddit-live-checks-2026-10-19.json) records a clean
installation of the combined source, an initially empty data directory and fresh
normal Client/CLI workers. All 479 maintained checks and 482 installed-package
checks passed. All 16 installed Python files matched the exported source; the
portable Footage package also passed its source-isolation check.

| Flow | Fresh installed result |
| --- | --- |
| Search | One indexed Reddit post in the final run; three in the prior integrated run. The empty `mountain sunrise` query is retained in the evidence. |
| Comments | Three current bodies bound to post `1uwp60q`, read from public Reddit embeds after archive ID discovery. |
| Native video | H.264, 1080 x 1920, 52.066667 seconds, AAC stereo; 21,644,453 finalized bytes, one-second decode and checked export. |
| Native image | JPEG, 4500 x 3000, 2,896,146 bytes; one-frame decode and checked export. |

Both exports matched their final receipt SHA-256. Deduplication, namespace
isolation, no-overwrite and image-format extension checks passed. The video's
merged native-media route requires audio before completing its receipt.

Comment coverage is a partial sample of 1–20, default 5. Archive IDs can omit
recent comments; totals are unknown and replies are not fully expanded. Only
native single-image posts and native video are supported. Galleries, crossposts
and external embeds are excluded. JPEG is live-verified; PNG/WebP have checked
format paths without a live sample. No login, posting, comment writing or voting
was added. These changes are included in version 0.3.1; installations of earlier
releases need an upgrade.

## Earlier 0.3.1 alpha candidate checks — 2026-10-18

The [fresh installed-worker evidence](readiness-live-checks-v0.3.1.json) records
an independent installation, per-sample empty data directories, selected source
identities, actual transfers, streams, decoded exports and matching hashes.
Its Python source hashes identify the tested implementation. These earlier
candidate checks are historical and do not identify the final release artifacts.

Six alternatives completed through the ordinary installed CLI and detached
worker after a test-only primary timeout. Alternative requests and media handling
were unmodified. Each completed sample also passed namespace isolation,
deduplication and no-overwrite export checks.

| Alternative | Fresh worker outcome | Audio |
| --- | --- | --- |
| Instagram extractor | 720 x 1280, 47.467 s | Yes |
| Bluesky public repository | 1920 x 1080, 29.737 s | Yes |
| Pinterest native API | 1080 x 1920, 57.700 s | Yes |
| Twitch public GraphQL | 1920 x 1080, 32.099 s | Yes |
| Snapchat public page | 480 x 880, 4.642 s | Yes |
| mastodon.social ActivityPub | 1692 x 1484, 38.850 s | Native silent gifv |
| LinkedIn public page | Unavailable before verified media | Unmeasured |

These results describe the earlier snapshot. LinkedIn, TikTok, X and Facebook
have subsequent candidate/integrated checks; they do not change these recorded
historical outcomes. Reddit was blocked in this earlier run; its current read-only
checks are recorded separately above. The optional independent YouTube connector
still needs an operator-owned instance. No universal availability claim is supported.

| Headline format | Fresh installed result / limit |
| --- | --- |
| YouTube Shorts | 1080 x 1920, 15.209 s, H.264/AAC; decoded and exported. The separate landscape test-video sample failed. |
| Instagram post and Reel | Both completed with audio, decode and checked export. |
| Instagram mixed carousel | Native metadata showed one video and 19 images; the child media ID did not bind to the parent shortcode, so identity checks rejected acquisition. First-video selection is not live-verified for this format. |
| Instagram image-only | Native metadata showed one image; the installed download failed without ready media. |
| TikTok canonical | 540 x 960, 27.467 s, with audio, decode and export. A short-share URL failed in this earlier run; later integrated share samples passed as recorded above. |
| X canonical and `/video/2` | Both completed with audio, decode and export. Syndication metadata confirmed the second attachment was a video after a photo, and the selected media URL matched that attachment. |
| Facebook Watch | 1080 x 1080, 44.331 s, with audio, decode and export. Share/Reel shapes were unverified in this earlier run; later integrated samples passed as recorded above. |

The Shorts relay's audio track label was empty. Audio presence and stream-copy
handling passed; original-language identity was not independently established.
Recognized URL syntax is separate from measured format availability.

Installed search found a new native Pinterest video pin: the selected third
result completed at 720 x 1280, 33.879 s, with audio, decode and a checked export.
Another indexed pin failed. This closes the earlier missing discovery/download
pair for one sample; search results are still not prevalidated videos. Two
indexed Mastodon posts had no native video, so broader audio-video coverage
remains unverified. Fresh YouTube/Instagram account-sample attempts returned
`SearchUnavailable`; prior account samples remain historical.

Primary identity, forbidden-host and ENOSPC injections stopped before fallback.
A CLI observation timeout reconnected to the same real job; an interrupted probe
worker required an explicit retry and completed under its original job ID.
Same-size file corruption failed checked export without a destination or partial
file. Offline regressions cover final receipt identity/hash mismatches,
interrupted-transfer cleanup, worker recovery, storage admission and queue limits.
No host disk was filled and no unrelated worker was terminated.

## 0.3.0 fallback and outstanding-platform checks — 2026-10-18

The fallback registry covers each selectable social source. YouTube's independent
connector requires an explicitly configured operator-owned Cobalt instance;
SnapYT's existing relay-server switching remains the default. No operator-owned
Cobalt instance was available for a fresh live probe. An evaluated Ytultra link
failed direct media transfer with HTTP 403; it was not added as a working backend.

The [fallback evidence](fallback-live-checks-v0.3.0.json) distinguishes direct
adapter acquisitions, finalized/decoded media, export-hash checks, unavailable
routes and the isolated installed-package check. Each network acquisition starts
with empty source storage. Offline outage tests prove that the next route is
selected, stale partial files are discarded, and identity/host/storage failures
stop the job. They do not establish live provider availability.

The separate [outstanding-platform audit](live-coverage-2026-10-18.json) covers
Vimeo, Dailymotion, Threads, Bilibili, Reddit, VK, Douyin, Weibo, Rumble and public
Telegram posts, with explicit limits and resume conditions. Raw route probes
for unequipped platforms are distinct from a supported CLI integration. Existing
Reddit/Bilibili blockers are not repeatedly retried without a changed route.
Broader headline-format gaps remain listed separately; this is not exhaustive
format or platform testing.

<!-- fallback-measurements -->
7 alternatives completed fresh transfers, media finalization, a one-second
decode and a matching file-copy export hash:

| Platform | Measured fallback output | Audio |
| --- | --- | --- |
| bluesky | 1920 x 1080, 29.737 s | Yes |
| instagram | 720 x 1280, 47.467 s | Yes |
| linkedin | 1428 x 720, 161.866 s | Yes |
| mastodon | 1692 x 1484, 38.850 s | No: silent gifv |
| pinterest | 1080 x 1920, 57.700 s | Yes |
| snapchat | 480 x 880, 4.642 s | Yes |
| twitch | 1920 x 1080, 32.099 s | Yes |

TikTok, X and Facebook alternatives were unavailable for the measured posts. Reddit
retains its access block. YouTube's independent connector remains unverified
until an operator-owned instance is configured. These limits do not replace
the earlier primary-route evidence.
<!-- /fallback-measurements -->

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
VK, Douyin, Weibo, Rumble and public Telegram videos were unevaluated for 0.2.0.
The later 0.3.0 audit above records their raw-route results; they remain outside
the integrated CLI source choices. Broader primary-platform format coverage and
fallback relay work are separate from the 0.2.0 measurements.

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
- X/Facebook extraction accepts progressive HTTPS MP4. A post that offers only
  separate DASH/HLS streams can fail. Reddit binds its native video and audio
  streams to the selected post and downloads a merged progressive MP4 through
  RapidSave; raw manifests and arbitrary segment downloads are not supported.
- New secondary MP4 transfers enforce a 512 MiB bound, deadline, response length
  and file signature before finalization. Pinterest pin.it share links, boards,
  Twitch VODs/live streams, Snapchat private stories and LinkedIn Learning are
  excluded. Account URLs never cause bulk downloads.
- This package runs local CLI/worker processes. Its namespaces are organizational;
  it does not expose a network service or implement multi-user authentication.
