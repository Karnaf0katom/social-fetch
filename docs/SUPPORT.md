# Support and verification

The code checks identity, expected byte ranges or response length, file signatures
and measured streams. MP4 export verifies the recorded SHA-256. Service responses
and availability can change independently of this source release.

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
- This package runs local CLI/worker processes. Its namespaces are organizational;
  it does not expose a network service or implement multi-user authentication.
