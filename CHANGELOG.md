# Changelog

## 0.4.0 alpha — 2026-10-20

- Add one-command downloads for YouTube, TikTok, Instagram, X, Facebook, Reddit,
  Bluesky, Pinterest, Twitch clips, Snapchat Spotlight, LinkedIn and mastodon.social.
  Each network command waits and exports a receipt-checked MP4 to `-o/--output`
  (default: current directory), with stable filenames and overwrite protection.
- List networks in `--help`, add `--version`, and reject mismatched network URLs
  before downloading. Preserve existing search, download, image, job and resource
  commands and JSON output, including reconnectable waits and failure exit codes.
- Document pipx and pip virtual-environment installation and per-network usage.
  Add offline CLI regressions and dated fresh-install smoke results for every
  network in `docs/SMOKE-RESULTS.md`.

## 0.3.2 alpha — 2026-10-20

- Remove application-only native catalog dispatch, browser poster integration,
  the extra Instagram bulk-download entry point and the obsolete FxTwitter adapter from
  the standalone export. Retain the supported Client/CLI and worker routes.
- Make the default search factory usable without private application modules;
  unsupported native catalog modes now return an explicit error.
- Check that every internal Python import resolves in the installed package.
  Selected X attachment coverage remains on the active FixupX route.
- Shorten the README, put installation and first use first, declare Git and the
  disk-space requirement, and add focused troubleshooting and support links.

## 0.3.1 alpha — 2026-10-20

- Integrate SSSTik selected-post failover, FixupX attachment-preserving embeds and
  Facebook selected progressive playback. Bind TikTok/Facebook shares to native
  posts, recover stale TikTok authors only from the same native video, and export
  the focused regressions with the public package.
- Record 22 fresh integrated-worker downloads, ten working platform alternatives,
  LinkedIn public-page failover and YouTube assigned-relay switching. Preserve the
  unavailable Reddit native-JSON alternative and unconfigured Cobalt limit.
- Integrate read-only Reddit search, bounded current comments, native single-image
  downloads and merged native video with required audio. Image jobs share the
  existing queue, receipt verification and checked export. Preserve Instagram
  comments and linked resources in the shared CLI and Python API.
- Add linked-resource detection and bounded public GitHub, Docs/Drive, file and
  documentation retrieval with readable-text sidecars and integrity receipts.
- Clarify account-sample availability, unknown audio-language identity when relay
  labels are absent, and the external-service boundaries of the MIT client.
- Record a fresh landscape YouTube HD download at its measured 2048 x 872
  dimensions, a fresh Instagram post/account sample, indexed discovery and public
  linked-resource retrieval. Preserve unavailable account/carousel/timeline limits.
- Verify the completed MP4's SHA-256 and selected source against its finalizer
  receipt before marking a worker job ready, including YouTube jobs. Missing
  hashes, wrong-post receipts and same-size corruption fail verification.
- Add regressions for receipt mismatches, interrupted-worker retry and waiting
  queue limits, and include maintained search boundary regressions in the public
  package. Two application-only catalog cases stay in the maintained suite;
  the standalone source scope and experimental route limits are unchanged.
- Record earlier installed-worker failover for six alternatives, a 1080 x 1920
  YouTube Short, headline samples, selected X attachment order and one Pinterest
  discovery/download pair. Retain historical failed samples and the remaining
  mixed Instagram carousel and other unverified format limits.

## 0.3.0 alpha — 2026-10-18

- Add one explicit acquisition alternative for each selectable social source.
  YouTube retains SnapYT relay-server switching and gains an optional connector
  for an operator-owned Cobalt instance; no hosted backend is enrolled by default.
- Isolate route attempts, discard failed partial files, and retain sanitized route
  names/outcomes in acquisition receipts and completed-job JSON.
- Preserve selected-post identity, source-specific CDN/redirect checks and bounded
  progressive MP4 delivery. Validation and local storage errors fail closed.
- Reuse the bounded transfer implementation for TikTok and reject native Reddit
  fallback video that would silently discard a separate audio stream.
- Document measured fallback outcomes and the outstanding-platform audit
  separately from offline regressions and historical primary-route checks.

## 0.2.0 alpha — 2026-10-18

- Add explicitly selected secondary sources: Bluesky, Pinterest video pins,
  Twitch clips, Snapchat Spotlight, public LinkedIn posts and mastodon.social.
  The default social search scope and five headline routes are unchanged.
- Use public native MP4 APIs for Bluesky and mastodon.social; use attributed
  yt-dlp metadata plus validated, bounded HTTPS CDN transfers for the other four.
- Add a bounded mastodon.social account sample, post/author identity checks,
  per-platform delivery/redirect allowlists and incomplete-transfer regressions.
- Expose sanitized failure stages/codes and measured audio presence on new jobs.
- Record six fresh downloads with decoded samples and matching export hashes.
  Five additions also passed useful discovery; Pinterest discovery remains
  partial (image-only indexed candidates). The Mastodon sample is silent gifv.
- Keep exact selected-post URLs/identities relevant when an index omits the ID
  from its title, and require alphanumeric Reddit post identities to match.
- Record Reddit, Vimeo, Dailymotion, Bilibili and Threads limitations separately;
  they are not newly verified acquisition options.

## 0.1.1 — 2026-10-18

- Include the manifest's dotfiles in the source archive and verify the built
  archive in CI, covering the source-distribution development workflow.
- Add a public manifest-refresh command, contribution instructions and a
  reproducible bug-report template.
- Label the release as alpha and clarify the scope of its live verification.
- Acquisition code is unchanged from 0.1.0; its five fresh VM checks still apply.

## 0.1.0 — 2026-10-18

- Standalone JSON CLI and Python client for public social discovery and downloads.
- Public relay adapters for YouTube/Shorts, Instagram and TikTok, plus allowlisted
  yt-dlp extractors for X, Facebook and Reddit.
- Durable jobs, two-worker admission, media receipts and SHA-256 checked MP4 export.
- Per-user data directory, dependency diagnostics and reconnectable CLI waits.
