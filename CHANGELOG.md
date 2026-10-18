# Changelog

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
